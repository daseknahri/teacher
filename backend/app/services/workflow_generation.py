from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from importlib.util import find_spec
from pathlib import Path
import re
from statistics import median
from typing import Any
import unicodedata

import httpx

from .. import config as app_config
from ..models import WorkflowChecklistItemKind, WorkflowUnitType


class NotebookLMGenerationUnavailableError(RuntimeError):
    pass


SUPPORTED_UNIT_PLANNER_PROVIDERS = {"openai", "fallback", "notebooklm"}
SUPPORTED_SESSION_WRITER_PROVIDERS = {"openai", "fallback", "notebooklm"}
SUPPORTED_UNIT_ASSISTANT_PROVIDERS = {"notebooklm"}
NUMBERED_HEADING_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:\s*[-.):]\s*|\s+)(.+)$")
CHAPTER_START_PATTERN = re.compile(r"^\s*(chapter|chapitre|title|titre|lesson|lecon)\b", re.IGNORECASE)
NUMBERED_ROW_START_PATTERN = re.compile(r"(?<!\S)\d+(?:\.\d+)+(?:[)\].:-])?(?:\s+|$)")
SLUG_LIKE_TITLE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$", re.IGNORECASE)
INLINE_ENUMERATION_SPLIT_PATTERN = re.compile(r"(?=(?<!\S)\d+\s*[\).:]\s*)")
NOTEBOOKLM_OUTLINE_BULLET_PATTERN = re.compile(r"^(?P<indent>[ \t]*)(?:[-*•‣▪●○]\s+)?(?P<title>.+?)\s*$")
CHECKLIST_KEYWORD_SPLIT_PATTERN = re.compile(
    r"(?=\b(?:definition|définition|propriete|propriété|proprietes|propriétés|exemple|exemples|remarque|remarques|application|applications|exercice|exercices|theoreme|théorème|methode|méthode)\b)",
    re.IGNORECASE,
)
CHECKLIST_KIND_KEYWORDS: tuple[tuple[str, WorkflowChecklistItemKind], ...] = (
    ("definition", WorkflowChecklistItemKind.DEFINITION),
    ("définition", WorkflowChecklistItemKind.DEFINITION),
    ("propriete", WorkflowChecklistItemKind.PROPERTY),
    ("propriété", WorkflowChecklistItemKind.PROPERTY),
    ("proprietes", WorkflowChecklistItemKind.PROPERTY),
    ("propriétés", WorkflowChecklistItemKind.PROPERTY),
    ("regle", WorkflowChecklistItemKind.PROPERTY),
    ("regles", WorkflowChecklistItemKind.PROPERTY),
    ("remarque", WorkflowChecklistItemKind.PROPERTY),
    ("remarques", WorkflowChecklistItemKind.PROPERTY),
    ("methode", WorkflowChecklistItemKind.PROPERTY),
    ("méthode", WorkflowChecklistItemKind.PROPERTY),
    ("theoreme", WorkflowChecklistItemKind.PROPERTY),
    ("théorème", WorkflowChecklistItemKind.PROPERTY),
    ("exemple", WorkflowChecklistItemKind.EXAMPLE),
    ("exemples", WorkflowChecklistItemKind.EXAMPLE),
    ("application", WorkflowChecklistItemKind.EXERCISE),
    ("applications", WorkflowChecklistItemKind.EXERCISE),
    ("exercice", WorkflowChecklistItemKind.EXERCISE),
    ("exercices", WorkflowChecklistItemKind.EXERCISE),
)
STRUCTURAL_KEYWORD_PREFIXES: tuple[tuple[str, WorkflowChecklistItemKind], ...] = (
    ("activite", WorkflowChecklistItemKind.OTHER),
    ("definition", WorkflowChecklistItemKind.DEFINITION),
    ("propriete", WorkflowChecklistItemKind.PROPERTY),
    ("regle", WorkflowChecklistItemKind.PROPERTY),
    ("remarque", WorkflowChecklistItemKind.PROPERTY),
    ("methode", WorkflowChecklistItemKind.PROPERTY),
    ("theoreme", WorkflowChecklistItemKind.PROPERTY),
    ("exemple", WorkflowChecklistItemKind.EXAMPLE),
    ("application", WorkflowChecklistItemKind.EXERCISE),
    ("exercice", WorkflowChecklistItemKind.EXERCISE),
)
METADATA_NOISE_TERMS: tuple[str, ...] = (
    "professeur",
    "prof",
    "college",
    "annee",
    "seance",
    "math",
    "mathematique",
    "academie",
    "lycee",
    "ecole",
)
RULE_CONTINUATION_PREFIXES: tuple[str, ...] = (
    "on ",
    "il faut ",
    "on garde ",
    "on ecrit ",
    "on effectue ",
    "on ajoute ",
    "on soustrait ",
    "on multiplie ",
    "on divise ",
)
ROMAN_HEADING_PATTERN = re.compile(r"^\s*[IVXLCM]+(?:\s*[-.):/]\s*|\s+).+", re.IGNORECASE)
ALPHA_HEADING_PATTERN = re.compile(r"^\s*[a-z]\s*[-.):/]\s*.+", re.IGNORECASE)
PDF_LAYOUT_LINE_GAP = 2.8
PDF_LAYOUT_HEADING_WORD_LIMIT = 18
PDF_LAYOUT_HEADING_MAX_CHARS = 120
PDF_LAYOUT_MIN_SIZE_DELTA = 1.0


def _resolve_notebooklm_home() -> Path:
    configured = str(app_config.NOTEBOOKLM_HOME or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".notebooklm"


def _resolve_notebooklm_storage_path() -> Path:
    configured_auth_path = str(app_config.NOTEBOOKLM_AUTH_PATH or "").strip()
    if configured_auth_path:
        return Path(configured_auth_path).expanduser()
    profile = app_config.NOTEBOOKLM_PROFILE or "default"
    home_dir = _resolve_notebooklm_home()
    profile_path = home_dir / "profiles" / profile / "storage_state.json"
    legacy_path = home_dir / "storage_state.json"
    if profile == "default" and legacy_path.exists() and not profile_path.exists():
        return legacy_path
    return profile_path


def notebooklm_provider_ready() -> bool:
    if find_spec("notebooklm") is None:
        return False
    storage_path = _resolve_notebooklm_storage_path()
    if not storage_path.exists():
        return False
    try:
        payload = json.loads(storage_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    origins = payload.get("origins") if isinstance(payload, dict) else None
    return isinstance(cookies, list) and isinstance(origins, list)


NOTEBOOKLM_NO_CONTEXT_PATTERNS: tuple[str, ...] = (
    "couldn't find enough context",
    "could not find enough context",
    "not enough context",
    "not enough information",
    "insufficient context",
    "try giving me more specific keywords",
)
TEACHER_META_SECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*objectifs?\b", re.IGNORECASE),
    re.compile(r"^\s*objectifs?\s+d[' ]apprentissage\b", re.IGNORECASE),
    re.compile(r"^\s*comp[ée]tences?\b", re.IGNORECASE),
    re.compile(r"^\s*capacit[ée]s?\b", re.IGNORECASE),
    re.compile(r"^\s*pr[ée]requis\b", re.IGNORECASE),
    re.compile(r"^\s*outils?\s+didactiques\b", re.IGNORECASE),
    re.compile(r"^\s*outils?\s+p[ée]dagogiques\b", re.IGNORECASE),
    re.compile(r"^\s*moyens?\s+didactiques\b", re.IGNORECASE),
    re.compile(r"^\s*ressources?\b", re.IGNORECASE),
    re.compile(r"^\s*supports?\b", re.IGNORECASE),
    re.compile(r"^\s*mat[ée]riel\b", re.IGNORECASE),
    re.compile(r"^\s*modalit[ée]s?\b", re.IGNORECASE),
    re.compile(r"^\s*gestion\s+du\s+temps\b", re.IGNORECASE),
    re.compile(r"^\s*dur[ée]e?\b", re.IGNORECASE),
    re.compile(r"^\s*d[ée]marche\s+p[ée]dagogique\b", re.IGNORECASE),
    re.compile(r"^\s*d[ée]roulement\b", re.IGNORECASE),
)
NOTEBOOKLM_TEMP_NOTEBOOK_TITLES: tuple[str, ...] = (
    "Teacher Progress Smoke Test",
)
NOTEBOOKLM_AUTH_ERROR_PATTERNS: tuple[str, ...] = (
    "sign in",
    "signin",
    "login",
    "log in",
    "unauthorized",
    "forbidden",
    "access denied",
    "cookie",
    "cookies",
    "session expired",
    "storage_state",
    "redirect",
    "google account",
)


def _resolve_notebooklm_health_path() -> Path:
    configured_auth_path = str(app_config.NOTEBOOKLM_AUTH_PATH or "").strip()
    if configured_auth_path:
        return Path(configured_auth_path).expanduser().with_name("health.json")
    profile = app_config.NOTEBOOKLM_PROFILE or "default"
    return _resolve_notebooklm_home() / "profiles" / profile / "health.json"


def _read_notebooklm_health_state() -> dict[str, Any]:
    path = _resolve_notebooklm_health_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_notebooklm_health_state(payload: dict[str, Any]) -> None:
    path = _resolve_notebooklm_health_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _looks_like_notebooklm_auth_error_message(message: str | None) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(pattern in text for pattern in NOTEBOOKLM_AUTH_ERROR_PATTERNS)


def _record_notebooklm_health(
    *,
    source: str,
    ok: bool,
    error_message: str | None = None,
    refresh_required: bool | None = None,
) -> None:
    state = _read_notebooklm_health_state()
    now = datetime.now(UTC).isoformat()
    state["last_event_at"] = now
    state["last_event_source"] = source
    if ok:
        state["last_success_at"] = now
        state["last_success_source"] = source
        state["last_error_at"] = state.get("last_error_at")
        state["refresh_required"] = False if refresh_required is None else bool(refresh_required)
        if "last_error_message" not in state:
            state["last_error_message"] = None
        state["last_error_message"] = state.get("last_error_message")
    else:
        state["last_error_at"] = now
        state["last_error_source"] = source
        state["last_error_message"] = str(error_message or "").strip() or None
        state["refresh_required"] = bool(refresh_required)
    _write_notebooklm_health_state(state)


def note_notebooklm_manual_auth_refresh() -> None:
    state = _read_notebooklm_health_state()
    now = datetime.now(UTC).isoformat()
    state["last_manual_refresh_at"] = now
    state["refresh_required"] = False
    _write_notebooklm_health_state(state)


def note_notebooklm_manual_auth_clear() -> None:
    state = _read_notebooklm_health_state()
    now = datetime.now(UTC).isoformat()
    state["last_manual_clear_at"] = now
    state["refresh_required"] = True
    _write_notebooklm_health_state(state)


def get_notebooklm_runtime_health() -> dict[str, Any]:
    state = _read_notebooklm_health_state()
    refresh_required = bool(state.get("refresh_required"))
    return {
        "refresh_required": refresh_required,
        "last_event_at": state.get("last_event_at"),
        "last_event_source": state.get("last_event_source"),
        "last_success_at": state.get("last_success_at"),
        "last_success_source": state.get("last_success_source"),
        "last_error_at": state.get("last_error_at"),
        "last_error_source": state.get("last_error_source"),
        "last_error_message": state.get("last_error_message"),
        "last_manual_refresh_at": state.get("last_manual_refresh_at"),
        "last_manual_clear_at": state.get("last_manual_clear_at"),
    }


def ensure_notebooklm_generation_ready(*, action_label: str) -> None:
    ready = notebooklm_provider_ready()
    health = get_notebooklm_runtime_health()
    refresh_required = bool(health.get("refresh_required"))
    if refresh_required:
        raise NotebookLMGenerationUnavailableError(
            f"NotebookLM login refresh is required before {action_label}. Use the Owner Panel refresh helper, then run the smoke test again."
        )
    if not ready:
        raise NotebookLMGenerationUnavailableError(
            f"NotebookLM is not ready for {action_label}. Upload or refresh NotebookLM auth from the Owner Panel before continuing."
        )


def _looks_like_notebooklm_no_context(answer: str | None) -> bool:
    text = str(answer or "").strip().lower()
    if not text:
        return True
    return any(pattern in text for pattern in NOTEBOOKLM_NO_CONTEXT_PATTERNS)


async def _ask_notebooklm_with_source_retry(*, opened, notebook_id: str, prompt: str, source_ids: list[str] | None, retries: int = 3) -> Any:
    last_result = None
    for attempt in range(max(1, int(retries))):
        result = await opened.chat.ask(notebook_id, prompt, source_ids=source_ids or None)
        last_result = result
        answer = str(getattr(result, "answer", "") or "").strip()
        if not _looks_like_notebooklm_no_context(answer):
            return result
        if attempt + 1 < max(1, int(retries)):
            await asyncio.sleep(2.0)
    return last_result


async def _safe_delete_notebook_async(notebook_id: str) -> bool:
    notebook_id = str(notebook_id or "").strip()
    if not notebook_id:
        return False
    try:
        await _notebooklm_delete_notebook_async(notebook_id)
        return True
    except Exception:
        return False


def notebooklm_smoke_test() -> dict[str, Any]:
    try:
        return asyncio.run(_notebooklm_smoke_test_async())
    except Exception as exc:
        _record_notebooklm_health(
            source="smoke_test",
            ok=False,
            error_message=f"notebooklm_smoke_runtime_error:{exc.__class__.__name__}",
            refresh_required=_looks_like_notebooklm_auth_error_message(str(exc)),
        )
        return {
            "ok": False,
            "provider": "notebooklm",
            "model": "notebooklm-py" if find_spec("notebooklm") is not None else None,
            "error_message": f"notebooklm_smoke_runtime_error:{exc.__class__.__name__}",
            "answer": None,
            "notebook_id": None,
            "source_ids": [],
        }


async def _notebooklm_smoke_test_async() -> dict[str, Any]:
    client = await _create_notebooklm_client()
    if client is None:
        _record_notebooklm_health(
            source="smoke_test",
            ok=False,
            error_message="notebooklm_client_unavailable",
            refresh_required=False,
        )
        return {
            "ok": False,
            "provider": "notebooklm",
            "model": None,
            "error_message": "notebooklm_client_unavailable",
            "answer": None,
            "notebook_id": None,
            "source_ids": [],
        }

    notebook_id = ""
    source_ids: list[str] = []
    raw_answer = None
    try:
        async with client as opened:
            notebook = await opened.notebooks.create("Teacher Progress Smoke Test")
            notebook_id = str(getattr(notebook, "id", "") or "").strip()
            source = await opened.sources.add_text(
                notebook_id,
                "Smoke Test Source",
                "Code source unique: KAPPA-372\nChapitre 1\nActivite 1\nExercice 1",
                wait=True,
                wait_timeout=120.0,
            )
            source_id = str(getattr(source, "id", "") or "").strip()
            if source_id:
                source_ids = [source_id]
            result = await _ask_notebooklm_with_source_retry(
                opened=opened,
                notebook_id=notebook_id,
                prompt="Quel est le code source unique ? Reponds exactement KAPPA-372",
                source_ids=source_ids,
                retries=3,
            )
            raw_answer = str(getattr(result, "answer", "") or "").strip()
    except Exception as exc:
        _record_notebooklm_health(
            source="smoke_test",
            ok=False,
            error_message=f"notebooklm_smoke_request_failed:{exc.__class__.__name__}:{exc}",
            refresh_required=_looks_like_notebooklm_auth_error_message(str(exc)),
        )
        return {
            "ok": False,
            "provider": "notebooklm",
            "model": "notebooklm-py",
            "error_message": f"notebooklm_smoke_request_failed:{exc.__class__.__name__}",
            "answer": raw_answer,
            "notebook_id": notebook_id or None,
            "source_ids": source_ids,
        }
    finally:
        if notebook_id:
            await _safe_delete_notebook_async(notebook_id)

    smoke_ok = "KAPPA-372" in raw_answer.upper()
    _record_notebooklm_health(
        source="smoke_test",
        ok=smoke_ok,
        error_message=None if smoke_ok else "notebooklm_smoke_unexpected_answer",
        refresh_required=False,
    )
    return {
        "ok": smoke_ok,
        "provider": "notebooklm",
        "model": "notebooklm-py",
        "error_message": None if smoke_ok else "notebooklm_smoke_unexpected_answer",
        "answer": raw_answer,
        "notebook_id": notebook_id or None,
        "source_ids": source_ids,
    }


def notebooklm_cleanup_temp_notebooks() -> dict[str, Any]:
    try:
        return asyncio.run(_notebooklm_cleanup_temp_notebooks_async())
    except Exception as exc:
        return {
            "ok": False,
            "error_message": f"notebooklm_cleanup_runtime_error:{exc.__class__.__name__}",
            "deleted_count": 0,
            "deleted_titles": [],
        }


async def _notebooklm_cleanup_temp_notebooks_async() -> dict[str, Any]:
    client = await _create_notebooklm_client()
    if client is None:
        return {
            "ok": False,
            "error_message": "notebooklm_client_unavailable",
            "deleted_count": 0,
            "deleted_titles": [],
        }

    deleted_titles: list[str] = []
    try:
        async with client as opened:
            notebooks = await opened.notebooks.list()
            for notebook in notebooks or []:
                title = str(getattr(notebook, "title", "") or "").strip()
                notebook_id = str(getattr(notebook, "id", "") or "").strip()
                if title not in NOTEBOOKLM_TEMP_NOTEBOOK_TITLES or not notebook_id:
                    continue
                try:
                    await opened.notebooks.delete(notebook_id)
                    deleted_titles.append(title)
                except Exception:
                    continue
    except Exception as exc:
        return {
            "ok": False,
            "error_message": f"notebooklm_cleanup_request_failed:{exc.__class__.__name__}",
            "deleted_count": len(deleted_titles),
            "deleted_titles": deleted_titles,
        }

    return {
        "ok": True,
        "error_message": None,
        "deleted_count": len(deleted_titles),
        "deleted_titles": deleted_titles,
    }


def generate_unit_checklist_package(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None = None,
    provider: str | None = None,
    document_path: str | None = None,
) -> dict[str, Any]:
    if unit_type == WorkflowUnitType.EXAM:
        return {
            "source": "template",
            "requested_provider": "template",
            "model": None,
            "status": "ready",
            "items": [
                {
                    "title": "Supervision d'examen",
                    "kind": WorkflowChecklistItemKind.SUPERVISION.value,
                    "children": [],
                }
            ],
            "raw_provider_response": None,
            "error_message": None,
        }
    if unit_type == WorkflowUnitType.EXAM_CORRECTION:
        return {
            "source": "template",
            "requested_provider": "template",
            "model": None,
            "status": "ready",
            "items": [
                {
                    "title": "Correction de l'examen",
                    "kind": WorkflowChecklistItemKind.CORRECTION.value,
                    "children": [],
                }
            ],
            "raw_provider_response": None,
            "error_message": None,
        }

    requested_provider = _normalize_provider_name(
        provider or app_config.UNIT_PLANNER_PROVIDER,
        supported=SUPPORTED_UNIT_PLANNER_PROVIDERS,
        default="fallback",
    )
    items: list[dict[str, Any]] | None = None
    unit_map: dict[str, Any] | None = None
    content_blocks: list[dict[str, Any]] | None = None
    raw_provider_response: dict[str, Any] | None = None
    error_message: str | None = None
    actual_provider = requested_provider
    model: str | None = None
    provider_context: dict[str, Any] | None = None
    layout_seed: list[dict[str, Any]] = []
    outline_seed: list[dict[str, Any]] = []
    reference_outline: list[dict[str, Any]] = []
    outline_hint_lines: list[str] = []
    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    openai_shadow_raw: dict[str, Any] | None = None
    openai_shadow_error: str | None = None

    def ensure_reference_outline_context() -> None:
        nonlocal layout_seed, outline_seed, reference_outline, outline_hint_lines
        if reference_outline or outline_hint_lines or layout_seed or outline_seed:
            return
        layout_seed = _build_pdf_layout_outline_seed(unit_type=unit_type, title=title, document_path=document_path)
        outline_seed = _build_outline_seed(unit_type=unit_type, title=title, source_text=source_text)
        reference_outline = _select_reference_outline_seed(
            layout_seed=layout_seed,
            outline_seed=outline_seed,
            unit_type=unit_type,
            unit_title=title,
        )
        outline_hint_lines = _merge_outline_hint_lines(
            _outline_hint_lines(layout_seed),
            _outline_hint_lines(outline_seed),
        )

    status = "ready"

    if requested_provider == "openai":
        ensure_reference_outline_context()
        items, raw_provider_response, error_message = _openai_generate_checklist(
            unit_type=unit_type,
            title=title,
            source_text=source_text,
            session_count=session_count,
            outline_hint_lines=outline_hint_lines,
        )
        if items:
            model = app_config.OPENAI_MODEL
            candidates.append(("openai", items))
    elif requested_provider == "notebooklm":
        items, provider_context, raw_provider_response, error_message = _notebooklm_generate_checklist(
            unit_type=unit_type,
            title=title,
            source_text=source_text,
            session_count=session_count,
            document_path=document_path,
            outline_hint_lines=None,
        )
        response_mode = str((raw_provider_response or {}).get("response_mode") or "").strip().lower()
        if items:
            actual_provider = "notebooklm"
            model = "notebooklm-py"
            normalized_items = _normalize_notebooklm_outline_items(
                items,
                unit_type=unit_type,
                unit_title=title,
            )
            if normalized_items:
                unit_map = _normalize_unit_map_payload(
                    raw_provider_response.get("unit_map") if isinstance(raw_provider_response, dict) else None,
                    fallback_outline=normalized_items,
                    unit_title=title,
                    unit_type=unit_type,
                    source_mode="notebooklm-unit-map",
                )
                selected_outline, unit_map, selected_structure_source = _align_notebooklm_unit_map_with_outline(
                    parsed_outline=normalized_items,
                    unit_map=unit_map,
                    source_text=source_text,
                    unit_type=unit_type,
                    unit_title=title,
                )
                if isinstance(raw_provider_response, dict):
                    raw_provider_response["selected_structure_source"] = selected_structure_source
                    raw_provider_response["unit_map"] = unit_map
                    raw_provider_response["content_blocks"] = _normalize_content_blocks_payload(
                        raw_provider_response.get("content_pack") if isinstance(raw_provider_response.get("content_pack"), dict) else None,
                        unit_map=unit_map,
                        fallback_outline=selected_outline,
                    )
                content_blocks = raw_provider_response.get("content_blocks") if isinstance(raw_provider_response, dict) and isinstance(raw_provider_response.get("content_blocks"), list) else None
                unit_map = _apply_content_blocks_to_unit_map(unit_map, content_blocks)
                content_pack_outline = _build_checklist_from_content_blocks(
                    content_blocks,
                    unit_title=title,
                    unit_type=unit_type,
                    fallback_outline=selected_outline,
                )
                if content_pack_outline:
                    outline_meta_count = _count_teacher_meta_outline_nodes(selected_outline)
                    content_meta_count = _count_teacher_meta_outline_nodes(content_pack_outline)
                    prefer_content_blocks = _content_blocks_have_structured_paths(content_blocks) or content_meta_count < outline_meta_count
                    selected_name, selected_items = _select_best_checklist_candidate(
                        [("outline_response", selected_outline), ("content_blocks", content_pack_outline)],
                        reference_outline=selected_outline,
                        unit_type=unit_type,
                        unit_title=title,
                    )
                    if prefer_content_blocks:
                        selected_outline = content_pack_outline
                        selected_structure_source = "content_blocks"
                    elif selected_name == "content_blocks":
                        selected_outline = selected_items
                        selected_structure_source = "content_blocks"
                if isinstance(raw_provider_response, dict):
                    raw_provider_response["selected_structure_source"] = selected_structure_source
                    raw_provider_response["unit_map"] = unit_map
                items = _copy_jsonable(selected_outline)
                items = _apply_session_numbers(items, session_count=session_count)
                if unit_type in {WorkflowUnitType.CHAPTER, WorkflowUnitType.EXERCISE_SERIES}:
                    items = _ensure_session_coverage_with_exercises(items, session_count=session_count)
                return {
                    "source": actual_provider,
                    "requested_provider": requested_provider,
                    "model": model,
                    "status": "ready",
                    "items": items,
                    "unit_map": unit_map,
                    "content_blocks": content_blocks,
                    "raw_provider_response": raw_provider_response,
                    "error_message": error_message,
                    "provider_context": provider_context,
                }

    ensure_reference_outline_context()
    normalized_candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for source_name, candidate_items in candidates:
        normalized_candidate = _postprocess_checklist_items(candidate_items, unit_type=unit_type, unit_title=title)
        if normalized_candidate:
            normalized_candidates.append((source_name, normalized_candidate))

    selection_pool = list(normalized_candidates)
    if reference_outline:
        selection_pool.append(("reference", reference_outline))

    if selection_pool:
        source_name, items = _select_best_checklist_candidate(
            selection_pool,
            reference_outline=reference_outline,
            unit_type=unit_type,
            unit_title=title,
        )
        if source_name == "reference":
            actual_provider = "fallback"
        elif source_name.startswith("notebooklm"):
            actual_provider = "notebooklm"
        else:
            actual_provider = source_name
        if actual_provider == "openai":
            model = app_config.OPENAI_MODEL
            if requested_provider == "notebooklm" and openai_shadow_raw is not None:
                raw_provider_response = openai_shadow_raw
                error_message = openai_shadow_error
        elif actual_provider == "notebooklm":
            model = "notebooklm-py"
        else:
            model = None
            if requested_provider != "notebooklm":
                raw_provider_response = None
                error_message = None

    if not items:
        actual_provider = "fallback"
        fallback_items = reference_outline or _fallback_generate_checklist(unit_type=unit_type, title=title, source_text=source_text)
        items = fallback_items
    if requested_provider == "notebooklm" and actual_provider != "notebooklm":
        status = "degraded"
    elif error_message:
        status = "degraded"

    items = _apply_session_numbers(items, session_count=session_count)
    if unit_type in {WorkflowUnitType.CHAPTER, WorkflowUnitType.EXERCISE_SERIES}:
        items = _ensure_session_coverage_with_exercises(items, session_count=session_count)
    if actual_provider != "notebooklm":
        unit_map = _normalize_unit_map_payload(
            None,
            fallback_outline=items,
            unit_title=title,
            unit_type=unit_type,
            source_mode=f"{actual_provider}-derived",
        )
    elif unit_map is None:
        unit_map = _normalize_unit_map_payload(
            None,
            fallback_outline=items,
            unit_title=title,
            unit_type=unit_type,
            source_mode=f"{actual_provider}-derived",
        )
    if content_blocks is None:
        content_blocks = _normalize_content_blocks_payload(
            raw_provider_response.get("content_pack") if isinstance(raw_provider_response, dict) and isinstance(raw_provider_response.get("content_pack"), dict) else None,
            unit_map=unit_map,
            fallback_outline=items,
        )
    unit_map = _apply_content_blocks_to_unit_map(unit_map, content_blocks)
    if isinstance(raw_provider_response, dict):
        raw_provider_response["unit_map"] = unit_map
        raw_provider_response["content_blocks"] = content_blocks

    return {
        "source": actual_provider,
        "requested_provider": requested_provider,
        "model": model,
        "status": status,
        "items": items,
        "unit_map": unit_map,
        "content_blocks": content_blocks,
        "raw_provider_response": raw_provider_response,
        "error_message": error_message,
        "provider_context": provider_context,
    }


def generate_session_writeup_package(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    session_number: int | None,
    checked_item_ids: list[int],
    checked_item_titles: list[str],
    note_text: str,
    source_text: str,
    provider: str | None = None,
    document_path: str | None = None,
    provider_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested_provider = _normalize_provider_name(
        provider or app_config.SESSION_WRITER_PROVIDER,
        supported=SUPPORTED_SESSION_WRITER_PROVIDERS,
        default="fallback",
    )

    payload = {
        "requested_provider": requested_provider,
        "session_number": int(session_number) if session_number and session_number > 0 else None,
        "checked_item_ids": [int(value) for value in checked_item_ids],
        "checked_item_titles": [str(value or "").strip() for value in checked_item_titles if str(value or "").strip()],
        "teacher_note": str(note_text or "").strip() or None,
    }

    package: dict[str, Any] | None = None
    if requested_provider == "openai":
        package = _openai_generate_session_writeup(
            unit_title=unit_title,
            unit_type=unit_type,
            session_number=session_number,
            checked_item_ids=checked_item_ids,
            checked_item_titles=checked_item_titles,
            note_text=note_text,
            source_text=source_text,
        )
    elif requested_provider == "notebooklm":
        ensure_notebooklm_generation_ready(action_label="session write-up generation")
        package = _notebooklm_generate_session_writeup(
            unit_title=unit_title,
            unit_type=unit_type,
            session_number=session_number,
            checked_item_ids=checked_item_ids,
            checked_item_titles=checked_item_titles,
            note_text=note_text,
            source_text=source_text,
            document_path=document_path,
            provider_context=provider_context,
        )

    fallback_package = _fallback_session_writeup_package(
        unit_title=unit_title,
        unit_type=unit_type,
        session_number=session_number,
        checked_item_ids=checked_item_ids,
        checked_item_titles=checked_item_titles,
        note_text=note_text,
        source_text=source_text,
    )
    if package is None:
        package = fallback_package
    else:
        package = _merge_writeup_with_fallback(package, fallback_package)

    package["source_payload"] = {
        **payload,
        "provider_used": package.get("provider"),
        "document_path": str(document_path or "").strip() or None,
        "provider_context": provider_context if isinstance(provider_context, dict) else None,
    }
    return package


def generate_unit_assistant_package(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    section_title: str | None,
    section_path: list[str] | None,
    action: str | None,
    teacher_request: str | None,
    source_text: str,
    document_path: str | None,
    provider_context: dict[str, Any] | None,
    unit_map: dict[str, Any] | None,
    content_blocks: list[dict[str, Any]] | None,
    provider: str | None = None,
) -> dict[str, Any]:
    requested_provider = _normalize_provider_name(
        provider or "notebooklm",
        supported=SUPPORTED_UNIT_ASSISTANT_PROVIDERS,
        default="notebooklm",
    )
    ensure_notebooklm_generation_ready(action_label="unit assistant guidance")
    return _notebooklm_generate_unit_assistant(
        unit_title=unit_title,
        unit_type=unit_type,
        section_title=section_title,
        section_path=section_path,
        action=action,
        teacher_request=teacher_request,
        source_text=source_text,
        document_path=document_path,
        provider_context=provider_context,
        unit_map=unit_map,
        content_blocks=content_blocks,
        requested_provider=requested_provider,
    )


def delete_provider_unit_context(*, provider_context: dict[str, Any] | None) -> bool:
    if not isinstance(provider_context, dict):
        return False
    if str(provider_context.get("provider") or "").strip().lower() != "notebooklm":
        return False
    notebook_id = str(provider_context.get("notebook_id") or "").strip()
    if not notebook_id:
        return False
    return _notebooklm_delete_notebook(notebook_id)


def _normalize_provider_name(name: str | None, *, supported: set[str], default: str) -> str:
    normalized = str(name or "").strip().lower()
    if normalized in supported:
        return normalized
    return default


def _build_outline_seed(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
) -> list[dict[str, Any]]:
    base_items = _fallback_generate_checklist(unit_type=unit_type, title=title, source_text=source_text)
    return _postprocess_checklist_items(base_items, unit_type=unit_type, unit_title=title)


def _build_pdf_layout_outline_seed(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    document_path: str | None,
) -> list[dict[str, Any]]:
    path_value = str(document_path or "").strip()
    if not path_value:
        return []
    source = Path(path_value)
    if source.suffix.lower() != ".pdf" or not source.exists():
        return []
    candidate_lines = _extract_pdf_heading_candidate_lines(source, unit_type=unit_type)
    if not candidate_lines:
        return []
    base_items = _fallback_generate_checklist(unit_type=unit_type, title=title, source_text="\n".join(candidate_lines))
    return _postprocess_checklist_items(base_items, unit_type=unit_type, unit_title=title)


def _outline_hint_lines(items: list[dict[str, Any]]) -> list[str]:
    output: list[str] = []

    def walk(nodes: list[dict[str, Any]], depth: int) -> None:
        for node in nodes:
            title = _normalize_outline_title(node.get("title"))
            if not title:
                continue
            kind = str(node.get("kind") or "other").strip().lower() or "other"
            output.append(f"{'  ' * max(0, depth)}- [{kind}] {title}")
            children = node.get("children") if isinstance(node.get("children"), list) else []
            if children:
                walk(children, depth + 1)

    walk(items, 0)
    return output[:60]


def _render_outline_hint_block(outline_hint_lines: list[str] | None) -> str:
    if not outline_hint_lines:
        return "Detected outline: none"
    rows = [str(row).strip() for row in outline_hint_lines if str(row).strip()]
    if not rows:
        return "Detected outline: none"
    return "Detected outline:\n" + "\n".join(rows[:60])


def _merge_outline_hint_lines(*groups: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            value = str(row or "").strip()
            if not value:
                continue
            key = _title_key(value)
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(value)
    return output[:80]


def _prefer_outline_seed(
    *,
    provider_items: list[dict[str, Any]] | None,
    outline_seed: list[dict[str, Any]],
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> list[dict[str, Any]]:
    seed_quality = _score_checklist_quality(outline_seed, unit_type=unit_type, unit_title=unit_title)
    if not provider_items:
        return outline_seed
    provider_quality = _score_checklist_quality(provider_items, unit_type=unit_type, unit_title=unit_title)
    if seed_quality >= provider_quality:
        return outline_seed
    return provider_items


def _select_reference_outline_seed(
    *,
    layout_seed: list[dict[str, Any]],
    outline_seed: list[dict[str, Any]],
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> list[dict[str, Any]]:
    if layout_seed and outline_seed:
        layout_score = _score_checklist_candidate(
            layout_seed,
            reference_outline=outline_seed,
            unit_type=unit_type,
            unit_title=unit_title,
        )
        outline_score = _score_checklist_candidate(
            outline_seed,
            reference_outline=layout_seed,
            unit_type=unit_type,
            unit_title=unit_title,
        )
        return layout_seed if layout_score >= outline_score else outline_seed
    return layout_seed or outline_seed


def _candidate_needs_structural_repair(
    items: list[dict[str, Any]] | None,
    *,
    reference_outline: list[dict[str, Any]],
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> bool:
    if not items:
        return True
    candidate_quality = _score_checklist_quality(items, unit_type=unit_type, unit_title=unit_title)
    baseline_quality = _score_checklist_quality(reference_outline, unit_type=unit_type, unit_title=unit_title)
    candidate_score = _score_checklist_candidate(
        items,
        reference_outline=reference_outline,
        unit_type=unit_type,
        unit_title=unit_title,
    )
    baseline_score = _score_checklist_candidate(
        reference_outline,
        reference_outline=reference_outline,
        unit_type=unit_type,
        unit_title=unit_title,
    )
    coverage = _score_reference_coverage(items, reference_outline)
    reference_titles = _outline_reference_titles(reference_outline)
    minimum_coverage = min(12, max(4, len(reference_titles) * 2))
    if coverage >= minimum_coverage and candidate_quality + 6 >= baseline_quality:
        return False
    return candidate_score + 4 < baseline_score or coverage < minimum_coverage


def _select_best_checklist_candidate(
    candidates: list[tuple[str, list[dict[str, Any]]]],
    *,
    reference_outline: list[dict[str, Any]],
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> tuple[str, list[dict[str, Any]]]:
    best_source = candidates[0][0]
    best_items = candidates[0][1]
    best_score = _score_checklist_candidate(
        best_items,
        reference_outline=reference_outline,
        unit_type=unit_type,
        unit_title=unit_title,
    )
    for source_name, items in candidates[1:]:
        score = _score_checklist_candidate(
            items,
            reference_outline=reference_outline,
            unit_type=unit_type,
            unit_title=unit_title,
        )
        if score > best_score:
            best_source = source_name
            best_items = items
            best_score = score
    return best_source, best_items


def _notebooklm_generate_checklist(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None,
    document_path: str | None,
    outline_hint_lines: list[str] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    try:
        items, provider_context, raw_provider_response, error_message = asyncio.run(
            _notebooklm_generate_checklist_async(
                unit_type=unit_type,
                title=title,
                source_text=source_text,
                session_count=session_count,
                document_path=document_path,
                outline_hint_lines=outline_hint_lines,
            )
        )
        _record_notebooklm_health(
            source="generate_checklist",
            ok=bool(items),
            error_message=error_message,
            refresh_required=_looks_like_notebooklm_auth_error_message(error_message),
        )
        return items, provider_context, raw_provider_response, error_message
    except Exception as exc:
        _record_notebooklm_health(
            source="generate_checklist",
            ok=False,
            error_message=f"notebooklm_runtime_error:{exc.__class__.__name__}:{exc}",
            refresh_required=_looks_like_notebooklm_auth_error_message(str(exc)),
        )
        return None, None, None, f"notebooklm_runtime_error:{exc.__class__.__name__}"


async def _notebooklm_generate_checklist_async(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None,
    document_path: str | None,
    outline_hint_lines: list[str] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    client = await _create_notebooklm_client()
    if client is None:
        return None, None, None, "notebooklm_client_unavailable"

    notebook_id = ""
    notebook_title = f"{app_config.NOTEBOOKLM_NOTEBOOK_PREFIX}{title or 'Unit'}".strip()
    raw_result: dict[str, Any] | None = None
    unit_map_payload: dict[str, Any] | None = None
    content_pack_payload: dict[str, Any] | None = None
    try:
        async with client as opened:
            notebook = await opened.notebooks.create(notebook_title)
            notebook_id = str(notebook.id or "").strip()
            source_ids = await _notebooklm_attach_source(
                client=opened,
                notebook_id=notebook_id,
                unit_title=title,
                source_text=source_text,
                document_path=document_path,
            )
            unit_map_prompt = _build_notebooklm_unit_map_prompt(
                unit_type=unit_type,
                title=title,
            )
            unit_map_result = await _ask_notebooklm_with_source_retry(
                opened=opened,
                notebook_id=notebook_id,
                prompt=unit_map_prompt,
                source_ids=source_ids,
                retries=3,
            )
            unit_map_answer = str(getattr(unit_map_result, "answer", "") or "").strip()
            unit_map_payload = _normalize_unit_map_payload(
                _json_object_from_text(unit_map_answer),
                fallback_outline=None,
                unit_title=title,
                unit_type=unit_type,
                source_mode="notebooklm-unit-map",
            )
            content_pack_prompt = _build_notebooklm_content_pack_prompt(
                unit_type=unit_type,
                title=title,
            )
            content_pack_result = await _ask_notebooklm_with_source_retry(
                opened=opened,
                notebook_id=notebook_id,
                prompt=content_pack_prompt,
                source_ids=source_ids,
                retries=3,
            )
            content_pack_answer = str(getattr(content_pack_result, "answer", "") or "").strip()
            content_pack_payload = _json_object_from_text(content_pack_answer)
            prompt_variants = [
                (
                    "primary",
                    _build_notebooklm_checklist_prompt(
                        unit_type=unit_type,
                        title=title,
                        source_hint="" if str(document_path or "").strip() else source_text,
                        session_count=session_count,
                        outline_hint_lines=outline_hint_lines,
                    ),
                )
            ]
            if unit_type == WorkflowUnitType.CHAPTER:
                prompt_variants.append(("completeness_review", _build_notebooklm_checklist_review_prompt()))

            candidate_rows: list[dict[str, Any]] = []
            for variant_name, prompt in prompt_variants:
                result = await _ask_notebooklm_with_source_retry(
                    opened=opened,
                    notebook_id=notebook_id,
                    prompt=prompt,
                    source_ids=source_ids,
                    retries=3,
                )
                answer = str(getattr(result, "answer", "") or "").strip()
                outline_items = _parse_notebooklm_outline_response(
                    answer,
                    unit_type=unit_type,
                    unit_title=title,
                )
                candidate_rows.append(
                    {
                        "variant": variant_name,
                        "prompt": prompt,
                        "answer": answer,
                        "conversation_id": str(getattr(result, "conversation_id", "") or "").strip() or None,
                        "outline_items": outline_items,
                    }
                )
            raw_result = {
                "notebook_id": notebook_id,
                "source_ids": source_ids,
                "unit_map": unit_map_payload,
                "content_pack": content_pack_payload,
                "responses": [
                    {
                        "variant": "unit_map",
                        "prompt": unit_map_prompt,
                        "answer": unit_map_answer,
                        "conversation_id": str(getattr(unit_map_result, "conversation_id", "") or "").strip() or None,
                    },
                    {
                        "variant": "content_pack",
                        "prompt": content_pack_prompt,
                        "answer": content_pack_answer,
                        "conversation_id": str(getattr(content_pack_result, "conversation_id", "") or "").strip() or None,
                    },
                ] + [
                    {
                        "variant": row["variant"],
                        "prompt": row["prompt"],
                        "answer": row["answer"],
                        "conversation_id": row["conversation_id"],
                    }
                    for row in candidate_rows
                ],
            }
    except Exception as exc:
        provider_context = _build_notebooklm_provider_context(
            notebook_id=notebook_id,
            source_ids=[],
            notebook_title=notebook_title,
        )
        return None, provider_context, raw_result, f"notebooklm_request_failed:{exc.__class__.__name__}"

    provider_context = _build_notebooklm_provider_context(
        notebook_id=notebook_id,
        source_ids=raw_result.get("source_ids") if isinstance(raw_result, dict) else [],
        notebook_title=notebook_title,
    )
    outline_candidates = [
        (str(row.get("variant") or "outline"), row.get("outline_items"))
        for row in (candidate_rows if "candidate_rows" in locals() else [])
        if isinstance(row.get("outline_items"), list) and row.get("outline_items")
    ]
    selected_variant = None
    outline_items = None
    if outline_candidates:
        selected_variant, outline_items = _select_best_notebooklm_outline_candidate(
            outline_candidates,
            source_text=source_text,
            unit_type=unit_type,
            unit_title=title,
        )
        if isinstance(raw_result, dict):
            raw_result["selected_variant"] = selected_variant
    if outline_items:
        unit_map_payload = _normalize_unit_map_payload(
            unit_map_payload,
            fallback_outline=outline_items,
            unit_title=title,
            unit_type=unit_type,
            source_mode="notebooklm-unit-map",
        )
        if isinstance(raw_result, dict):
            raw_result["unit_map"] = unit_map_payload
            raw_result["content_blocks"] = _normalize_content_blocks_payload(
                content_pack_payload,
                unit_map=unit_map_payload,
                fallback_outline=outline_items,
            )
        if isinstance(raw_result, dict):
            raw_result["response_mode"] = "outline"
        return outline_items, provider_context, raw_result, None

    answer = ""
    if "candidate_rows" in locals():
        for row in candidate_rows:
            answer = str(row.get("answer") or "").strip()
            if answer:
                break
    parsed = _json_object_from_text(answer)
    if not isinstance(parsed, dict):
        return None, provider_context, raw_result, "notebooklm_invalid_json"
    items = parsed.get("items")
    if not isinstance(items, list):
        return None, provider_context, raw_result, "notebooklm_missing_items"

    sanitized = _sanitize_items(items)
    if isinstance(raw_result, dict):
        raw_result["unit_map"] = _normalize_unit_map_payload(
            unit_map_payload,
            fallback_outline=sanitized,
            unit_title=title,
            unit_type=unit_type,
            source_mode="notebooklm-unit-map",
        )
        raw_result["content_blocks"] = _normalize_content_blocks_payload(
            content_pack_payload,
            unit_map=raw_result["unit_map"] if isinstance(raw_result.get("unit_map"), dict) else unit_map_payload,
            fallback_outline=sanitized,
        )
        raw_result["response_mode"] = "json"
    if not sanitized:
        return None, provider_context, raw_result, "notebooklm_empty_items"
    return sanitized, provider_context, raw_result, None


def _notebooklm_generate_session_writeup(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    session_number: int | None,
    checked_item_ids: list[int],
    checked_item_titles: list[str],
    note_text: str,
    source_text: str,
    document_path: str | None,
    provider_context: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        result = asyncio.run(
            _notebooklm_generate_session_writeup_async(
                unit_title=unit_title,
                unit_type=unit_type,
                session_number=session_number,
                checked_item_ids=checked_item_ids,
                checked_item_titles=checked_item_titles,
                note_text=note_text,
                source_text=source_text,
                document_path=document_path,
                provider_context=provider_context,
            )
        )
        _record_notebooklm_health(
            source="generate_writeup",
            ok=not bool(result.get("error_message")),
            error_message=str(result.get("error_message") or "").strip() or None,
            refresh_required=_looks_like_notebooklm_auth_error_message(str(result.get("error_message") or "")),
        )
        return result
    except Exception as exc:
        _record_notebooklm_health(
            source="generate_writeup",
            ok=False,
            error_message=f"notebooklm_runtime_error:{exc.__class__.__name__}:{exc}",
            refresh_required=_looks_like_notebooklm_auth_error_message(str(exc)),
        )
        return {
            "provider": "fallback",
            "requested_provider": "notebooklm",
            "model": None,
            "status": "ready",
            "title": None,
            "learning_focus": [],
            "teaching_content": [],
            "practice_items": [],
            "raw_provider_response": None,
            "error_message": f"notebooklm_runtime_error:{exc.__class__.__name__}",
        }


async def _notebooklm_generate_session_writeup_async(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    session_number: int | None,
    checked_item_ids: list[int],
    checked_item_titles: list[str],
    note_text: str,
    source_text: str,
    document_path: str | None,
    provider_context: dict[str, Any] | None,
) -> dict[str, Any]:
    client = await _create_notebooklm_client()
    if client is None:
        return {
            "provider": "fallback",
            "requested_provider": "notebooklm",
            "model": None,
            "status": "ready",
            "title": None,
            "learning_focus": [],
            "teaching_content": [],
            "practice_items": [],
            "raw_provider_response": None,
            "error_message": "notebooklm_client_unavailable",
        }

    notebook_id = str((provider_context or {}).get("notebook_id") or "").strip()
    notebook_title = f"{app_config.NOTEBOOKLM_NOTEBOOK_PREFIX}{unit_title or 'Unit'}".strip()
    created_temporary_notebook = False
    source_ids = [str(value).strip() for value in ((provider_context or {}).get("source_ids") or []) if str(value).strip()]
    raw_result: dict[str, Any] | None = None
    try:
        async with client as opened:
            if not notebook_id:
                notebook = await opened.notebooks.create(notebook_title)
                notebook_id = str(notebook.id or "").strip()
                created_temporary_notebook = True
                source_ids = await _notebooklm_attach_source(
                    client=opened,
                    notebook_id=notebook_id,
                    unit_title=unit_title,
                    source_text=source_text,
                    document_path=document_path,
                )

            prompt = _build_notebooklm_session_writeup_prompt(
                unit_title=unit_title,
                unit_type=unit_type,
                session_number=session_number,
                checked_item_titles=checked_item_titles,
                note_text=note_text,
            )
            result = await _ask_notebooklm_with_source_retry(
                opened=opened,
                notebook_id=notebook_id,
                prompt=prompt,
                source_ids=source_ids,
                retries=3,
            )
            answer = str(getattr(result, "answer", "") or "").strip()
            parsed = _json_object_from_text(answer)
            raw_result = {
                "notebook_id": notebook_id,
                "source_ids": source_ids,
                "answer": answer,
                "conversation_id": str(getattr(result, "conversation_id", "") or "").strip() or None,
            }
    except Exception as exc:
        return {
            "provider": "fallback",
            "requested_provider": "notebooklm",
            "model": None,
            "status": "ready",
            "title": None,
            "learning_focus": [],
            "teaching_content": [],
            "practice_items": [],
            "raw_provider_response": raw_result,
            "error_message": f"notebooklm_request_failed:{exc.__class__.__name__}",
        }
    finally:
        if created_temporary_notebook and notebook_id:
            await _safe_delete_notebook_async(notebook_id)

    if not isinstance(parsed, dict):
        return {
            "provider": "fallback",
            "requested_provider": "notebooklm",
            "model": None,
            "status": "ready",
            "title": None,
            "learning_focus": [],
            "teaching_content": [],
            "practice_items": [],
            "raw_provider_response": raw_result,
            "error_message": "notebooklm_invalid_json",
        }

    normalized = _normalize_writeup_payload(
        title=str(parsed.get("title") or "").strip(),
        learning_focus=parsed.get("learning_focus"),
        teaching_content=parsed.get("teaching_content"),
        practice_items=parsed.get("practice_items"),
        unit_title=unit_title,
        session_number=session_number,
        checked_item_ids=checked_item_ids,
        checked_item_titles=checked_item_titles,
        note_text=note_text,
        provider="notebooklm",
        model="notebooklm-py",
        raw_provider_response=raw_result,
        error_message=None,
    )
    normalized["requested_provider"] = "notebooklm"
    return normalized


def _notebooklm_delete_notebook(notebook_id: str) -> bool:
    try:
        return asyncio.run(_notebooklm_delete_notebook_async(notebook_id))
    except Exception:
        return False


def _normalize_unit_assistant_action(value: Any) -> str:
    action = re.sub(r"[^a-z_]+", "_", str(value or "").strip().lower()).strip("_")
    return action or "explain_section"


def _normalize_unit_assistant_rows(values: Any, *, limit: int = 8) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _normalize_content_block_text(raw, limit=420)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def _find_teacher_playbook_entry(unit_map: dict[str, Any] | None, section_title: str | None, section_path: list[str] | None) -> dict[str, Any] | None:
    rows = unit_map.get("teacher_playbook") if isinstance(unit_map, dict) and isinstance(unit_map.get("teacher_playbook"), list) else []
    if not rows:
        return None
    section_key = _semantic_title_key(section_title)
    path_key = "|".join(_semantic_title_key(row) for row in (section_path or []) if _semantic_title_key(row))
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_section_key = _semantic_title_key(row.get("section_title"))
        row_path_key = "|".join(_semantic_title_key(value) for value in (row.get("section_path") or []) if _semantic_title_key(value))
        if path_key and row_path_key == path_key:
            return row
        if section_key and row_section_key == section_key:
            return row
    return None


def _filter_content_blocks_for_section(
    blocks: list[dict[str, Any]] | None,
    *,
    section_title: str | None,
    section_path: list[str] | None,
) -> list[dict[str, Any]]:
    if not isinstance(blocks, list):
        return []
    title_key = _semantic_title_key(section_title)
    path_key = "|".join(_semantic_title_key(value) for value in (section_path or []) if _semantic_title_key(value))
    matched: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_title_key = _semantic_title_key(block.get("section_title"))
        block_path_key = "|".join(_semantic_title_key(value) for value in (block.get("section_path") or []) if _semantic_title_key(value))
        if path_key and block_path_key == path_key:
            matched.append(block)
        elif title_key and block_title_key == title_key:
            matched.append(block)
    if matched:
        return matched
    return [block for block in blocks if isinstance(block, dict) and not bool(block.get("teacher_only"))][:18]


def _build_notebooklm_unit_assistant_prompt(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    section_title: str | None,
    section_path: list[str] | None,
    action: str,
    teacher_request: str | None,
    playbook_entry: dict[str, Any] | None,
    content_blocks: list[dict[str, Any]],
) -> str:
    section_label = _normalize_outline_title(section_title) or "Toute l'unite"
    path_label = " > ".join(_normalize_outline_title(value) for value in (section_path or []) if _normalize_outline_title(value))
    available_actions = [str(value).strip() for value in ((playbook_entry or {}).get("available_actions") or []) if str(value).strip()]
    suggested_requests = [str(value).strip() for value in ((playbook_entry or {}).get("suggested_requests") or []) if str(value).strip()]
    block_rows = []
    for block in content_blocks[:12]:
        title = _normalize_outline_title(block.get("title"))
        kind = _normalize_content_block_kind(block.get("kind"))
        phase = str(block.get("teaching_phase") or "").strip() or _normalize_content_block_phase(None, kind=kind, title=title)
        material = _normalize_content_block_text(block.get("teaching_material"), limit=260)
        excerpt = _normalize_content_block_text(block.get("source_excerpt"), limit=180)
        if not title:
            continue
        block_rows.append(
            {
                "title": title,
                "kind": kind,
                "teaching_phase": phase,
                "teaching_material": material,
                "source_excerpt": excerpt,
            }
        )
    compact_json = json.dumps(block_rows, ensure_ascii=False, indent=2)
    return "\n".join(
        [
            "Tu es un expert pedagogique qui aide un enseignant a preparer et ajuster son cours a partir d'une unite deja comprise.",
            "Reponds uniquement avec un JSON strict de la forme suivante:",
            "{",
            '  "title": "titre court de la reponse",',
            '  "answer_rows": ["conseil ou contenu 1", "conseil ou contenu 2"],',
            '  "suggested_followups": ["suite utile 1", "suite utile 2"]',
            "}",
            "Contraintes:",
            "- Reponds pour un enseignant, de facon pratique et exploitable en classe.",
            "- Base-toi sur le contexte de l'unite et de la section demandee.",
            "- answer_rows doit contenir 3 a 8 lignes utiles, concretes et courtes.",
            "- suggested_followups doit proposer 2 a 4 suites utiles pour un enseignant.",
            "- Si l'action demande une adaptation de difficulte, produis un resultat utilisable directement en classe.",
            f"Unite: {unit_title or 'Unite'}",
            f"Type d'unite: {unit_type.value if unit_type else 'chapter'}",
            f"Section cible: {section_label}",
            f"Chemin de section: {path_label or '-'}",
            f"Action demandee: {action}",
            f"Demande du professeur: {str(teacher_request or '').strip() or '-'}",
            f"Actions disponibles pour cette section: {', '.join(available_actions) if available_actions else '-'}",
            "Requetes suggerees pour cette section:",
            *(f"- {row}" for row in suggested_requests[:4]),
            "Blocs pedagogiques deja extraits pour cette section:",
            compact_json,
        ]
    )


def _normalize_unit_assistant_payload(
    *,
    parsed: dict[str, Any] | None,
    requested_provider: str,
    action: str,
    section_title: str | None,
    section_path: list[str] | None,
    teacher_request: str | None,
    raw_provider_response: dict[str, Any] | None,
    error_message: str | None,
) -> dict[str, Any]:
    title = _normalize_content_block_text((parsed or {}).get("title"), limit=180) or _normalize_outline_title(section_title) or "Teacher guidance"
    answer_rows = _normalize_unit_assistant_rows((parsed or {}).get("answer_rows"))
    suggested_followups = _normalize_unit_assistant_rows((parsed or {}).get("suggested_followups"), limit=6)
    if not answer_rows and teacher_request:
        answer_rows = [_normalize_content_block_text(teacher_request, limit=220)]
    return {
        "provider": "notebooklm" if not error_message else "fallback",
        "requested_provider": requested_provider,
        "model": "notebooklm-py" if not error_message else None,
        "status": "ready" if not error_message else "degraded",
        "section_title": _normalize_outline_title(section_title) or None,
        "section_path": [_normalize_outline_title(value) for value in (section_path or []) if _normalize_outline_title(value)],
        "action": action,
        "title": title,
        "answer_rows": answer_rows,
        "suggested_followups": suggested_followups,
        "source_payload": {
            "teacher_request": str(teacher_request or "").strip() or None,
            "section_title": _normalize_outline_title(section_title) or None,
            "section_path": [_normalize_outline_title(value) for value in (section_path or []) if _normalize_outline_title(value)],
            "action": action,
        },
        "raw_provider_response": raw_provider_response,
        "error_message": error_message,
    }


def _notebooklm_generate_unit_assistant(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    section_title: str | None,
    section_path: list[str] | None,
    action: str | None,
    teacher_request: str | None,
    source_text: str,
    document_path: str | None,
    provider_context: dict[str, Any] | None,
    unit_map: dict[str, Any] | None,
    content_blocks: list[dict[str, Any]] | None,
    requested_provider: str,
) -> dict[str, Any]:
    try:
        return asyncio.run(
            _notebooklm_generate_unit_assistant_async(
                unit_title=unit_title,
                unit_type=unit_type,
                section_title=section_title,
                section_path=section_path,
                action=action,
                teacher_request=teacher_request,
                source_text=source_text,
                document_path=document_path,
                provider_context=provider_context,
                unit_map=unit_map,
                content_blocks=content_blocks,
                requested_provider=requested_provider,
            )
        )
    except Exception as exc:
        _record_notebooklm_health(
            source="unit_assistant",
            ok=False,
            error_message=f"notebooklm_runtime_error:{exc.__class__.__name__}:{exc}",
            refresh_required=_looks_like_notebooklm_auth_error_message(str(exc)),
        )
        return _normalize_unit_assistant_payload(
            parsed=None,
            requested_provider=requested_provider,
            action=_normalize_unit_assistant_action(action),
            section_title=section_title,
            section_path=section_path,
            teacher_request=teacher_request,
            raw_provider_response=None,
            error_message=f"notebooklm_runtime_error:{exc.__class__.__name__}",
        )


async def _notebooklm_generate_unit_assistant_async(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    section_title: str | None,
    section_path: list[str] | None,
    action: str | None,
    teacher_request: str | None,
    source_text: str,
    document_path: str | None,
    provider_context: dict[str, Any] | None,
    unit_map: dict[str, Any] | None,
    content_blocks: list[dict[str, Any]] | None,
    requested_provider: str,
) -> dict[str, Any]:
    client = await _create_notebooklm_client()
    action_name = _normalize_unit_assistant_action(action)
    if client is None:
        return _normalize_unit_assistant_payload(
            parsed=None,
            requested_provider=requested_provider,
            action=action_name,
            section_title=section_title,
            section_path=section_path,
            teacher_request=teacher_request,
            raw_provider_response=None,
            error_message="notebooklm_client_unavailable",
        )

    playbook_entry = _find_teacher_playbook_entry(unit_map, section_title, section_path)
    normalized_section_path = [
        _normalize_outline_title(value)
        for value in (
            section_path
            or (playbook_entry.get("section_path") if isinstance(playbook_entry, dict) and isinstance(playbook_entry.get("section_path"), list) else [])
        )
        if _normalize_outline_title(value)
    ]
    selected_blocks = _filter_content_blocks_for_section(
        content_blocks,
        section_title=section_title or (playbook_entry.get("section_title") if isinstance(playbook_entry, dict) else None),
        section_path=normalized_section_path or None,
    )
    prompt = _build_notebooklm_unit_assistant_prompt(
        unit_title=unit_title,
        unit_type=unit_type,
        section_title=section_title or (playbook_entry.get("section_title") if isinstance(playbook_entry, dict) else None),
        section_path=normalized_section_path or None,
        action=action_name,
        teacher_request=teacher_request,
        playbook_entry=playbook_entry,
        content_blocks=selected_blocks,
    )

    notebook_id = str((provider_context or {}).get("notebook_id") or "").strip()
    notebook_title = f"{app_config.NOTEBOOKLM_NOTEBOOK_PREFIX}{unit_title or 'Unit'}".strip()
    created_temporary_notebook = False
    source_ids = [str(value).strip() for value in ((provider_context or {}).get("source_ids") or []) if str(value).strip()]
    raw_provider_response: dict[str, Any] | None = None
    try:
        async with client as opened:
            if not notebook_id:
                notebook = await opened.notebooks.create(notebook_title)
                notebook_id = str(getattr(notebook, "id", "") or "").strip()
                created_temporary_notebook = True
                source_ids = await _notebooklm_attach_source(
                    client=opened,
                    notebook_id=notebook_id,
                    unit_title=unit_title,
                    source_text=source_text,
                    document_path=document_path,
                )
            result = await _ask_notebooklm_with_source_retry(
                opened=opened,
                notebook_id=notebook_id,
                prompt=prompt,
                source_ids=source_ids,
                retries=3,
            )
            answer = str(getattr(result, "answer", "") or "").strip()
            parsed = _json_object_from_text(answer)
            raw_provider_response = {
                "notebook_id": notebook_id,
                "source_ids": source_ids,
                "conversation_id": str(getattr(result, "conversation_id", "") or "").strip() or None,
                "prompt": prompt,
                "answer": answer,
            }
    except Exception as exc:
        _record_notebooklm_health(
            source="unit_assistant",
            ok=False,
            error_message=f"notebooklm_request_failed:{exc.__class__.__name__}:{exc}",
            refresh_required=_looks_like_notebooklm_auth_error_message(str(exc)),
        )
        return _normalize_unit_assistant_payload(
            parsed=None,
            requested_provider=requested_provider,
            action=action_name,
            section_title=section_title,
            section_path=normalized_section_path,
            teacher_request=teacher_request,
            raw_provider_response=raw_provider_response,
            error_message=f"notebooklm_request_failed:{exc.__class__.__name__}",
        )
    finally:
        if created_temporary_notebook and notebook_id:
            await _safe_delete_notebook_async(notebook_id)

    _record_notebooklm_health(
        source="unit_assistant",
        ok=True,
        error_message=None,
        refresh_required=False,
    )
    return _normalize_unit_assistant_payload(
        parsed=parsed if isinstance(parsed, dict) else None,
        requested_provider=requested_provider,
        action=action_name,
        section_title=section_title or (playbook_entry.get("section_title") if isinstance(playbook_entry, dict) else None),
        section_path=normalized_section_path,
        teacher_request=teacher_request,
        raw_provider_response=raw_provider_response,
        error_message=None if isinstance(parsed, dict) else "notebooklm_invalid_json",
    )


async def _notebooklm_delete_notebook_async(notebook_id: str) -> bool:
    client = await _create_notebooklm_client()
    if client is None:
        return False
    try:
        async with client as opened:
            await opened.notebooks.delete(notebook_id)
        return True
    except Exception:
        return False


async def _create_notebooklm_client():
    try:
        from notebooklm import NotebookLMClient
    except Exception:
        return None

    kwargs: dict[str, Any] = {
        "timeout": float(app_config.NOTEBOOKLM_TIMEOUT_SECONDS),
    }
    storage_path = _resolve_notebooklm_storage_path()
    if storage_path.exists():
        kwargs["path"] = str(storage_path)
    else:
        auth_path = str(app_config.NOTEBOOKLM_AUTH_PATH or "").strip()
        if auth_path:
            kwargs["path"] = auth_path
    if app_config.NOTEBOOKLM_PROFILE:
        kwargs["profile"] = app_config.NOTEBOOKLM_PROFILE
    keepalive = int(app_config.NOTEBOOKLM_KEEPALIVE_SECONDS or 0)
    if keepalive > 0:
        kwargs["keepalive"] = float(keepalive)
    return await NotebookLMClient.from_storage(**kwargs)


async def _notebooklm_attach_source(
    *,
    client,
    notebook_id: str,
    unit_title: str,
    source_text: str,
    document_path: str | None,
) -> list[str]:
    path_value = str(document_path or "").strip()
    if path_value and Path(path_value).exists():
        source = await client.sources.add_file(notebook_id, path_value, wait=True, wait_timeout=180.0)
        return [str(source.id or "").strip()] if str(source.id or "").strip() else []
    title = str(unit_title or "Unit source").strip() or "Unit source"
    content = str(source_text or "").strip()
    if not content:
        raise ValueError("No unit source available for NotebookLM.")
    source = await client.sources.add_text(notebook_id, title, content, wait=True, wait_timeout=180.0)
    return [str(source.id or "").strip()] if str(source.id or "").strip() else []


def _build_notebooklm_provider_context(*, notebook_id: str, source_ids: list[str] | Any, notebook_title: str) -> dict[str, Any]:
    source_id_rows = [str(value).strip() for value in (source_ids or []) if str(value).strip()]
    return {
        "provider": "notebooklm",
        "notebook_id": str(notebook_id or "").strip() or None,
        "source_ids": source_id_rows,
        "notebook_title": str(notebook_title or "").strip() or None,
    }


def _build_notebooklm_checklist_prompt(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_hint: str,
    session_count: int | None,
    outline_hint_lines: list[str] | None = None,
) -> str:
    del session_count
    prompt_parts = [
        "Lis ce PDF comme un manuel scolaire de mathematiques.",
        "Retourne une liste hierarchique complete du parcours reel fait avec les eleves, dans l'ordre exact du document.",
        "Regles:",
        "- Garde le titre du chapitre comme racine.",
        "- Garde seulement les rubriques que l'enseignant traite avec les eleves: activites, contenu de la lecon, sections, sous-sections, definitions, proprietes, regles, exemples, exercices, evaluation.",
        "- Conserve le texte et le systeme de numerotation visibles dans le document (I, II, 1, 1.1, A, etc.).",
        "- Quand l'ordre pedagogique est implicite ou ambigu, organise la progression comme un enseignant: activites d'amorce, puis notions/lecon, puis definitions/proprietes/regles, puis exemples, puis exercices ou evaluation.",
        "- Dans chaque grande section, essaie de garder une structure exploitable en classe: activite -> contenu/notions -> exemples -> exercices.",
        "- Ne saute aucun titre visible, meme s'il y a plusieurs activites ou plusieurs exercices.",
        "- Si une rubrique contient Activite 1, Activite 2, ... ou Exercice 1, Exercice 2, ..., garde-les tous comme enfants de cette rubrique.",
        "- N'inclus pas dans la checklist les rubriques meta enseignant comme Objectifs d'apprentissage, Competences, Capacites, Prerequis, Outils didactiques, Ressources, Gestion du temps, Demarche pedagogique ou rubriques similaires.",
        "- Ne garde pas les paragraphes de contenu, les calculs detailles, les reponses, ni les sous-exemples A / B / C / D.",
        "- Si un titre est coupe sur deux lignes, reconstitue-le.",
        "- Ignore seulement les metadonnees de couverture (nom du professeur, etablissement, niveau, pagination isolee).",
        "- N'invente pas de nouveaux titres; si le document est ambigu, complete seulement les liens de structure evidents.",
        "Format attendu:",
        "- une ligne par titre",
        "- chaque ligne commence par -",
        "- indentation de deux espaces par niveau",
        "- aucun commentaire avant ou apres la liste",
    ]
    if unit_type == WorkflowUnitType.EXERCISE_SERIES:
        prompt_parts.append("- Pour une serie d'exercices, garde les grandes rubriques et les sous-rubriques visibles.")
    source_block = ""
    trimmed_hint = str(source_hint or "").strip()
    if trimmed_hint:
        source_block = f"\nTexte source de secours si le PDF est indisponible:\n{trimmed_hint}"
    del title
    del outline_hint_lines
    return "\n".join(prompt_parts) + source_block


def _build_notebooklm_checklist_review_prompt() -> str:
    return "\n".join(
        [
            "Relis le meme PDF et corrige la liste precedente pour qu'aucun titre pedagogique visible ne manque.",
            "Je veux la version finale la plus complete et la mieux ordonnee possible pour suivre ce que l'enseignant fait avec les eleves.",
            "Regles:",
            "- Garde le titre du chapitre comme racine.",
            "- Verifie surtout toutes les rubriques Activite 1, Activite 2, ..., Exercice 1, Exercice 2, ..., Definition, Propriete, Regle, Exemple, Evaluation.",
            "- Si l'ordre est ambigu, prefere un deroulement de classe coherent: activites d'amorce, puis notions/lecon, puis definitions/proprietes/regles, puis exemples, puis exercices ou evaluation.",
            "- Exclue les rubriques meta enseignant comme Objectifs d'apprentissage, Competences, Capacites, Prerequis, Outils didactiques, Ressources, Gestion du temps, Demarche pedagogique ou rubriques equivalentes.",
            "- Ne saute aucun titre visible, meme s'il est repetitif ou similaire a un autre.",
            "- Ne garde pas les paragraphes de contenu, les calculs detailles, les reponses, ni les sous-exemples A / B / C / D.",
            "- Si une rubrique est coupee sur plusieurs pages, reconstruis la structure pedagogique complete.",
            "Format attendu:",
            "- une ligne par titre",
            "- chaque ligne commence par -",
            "- indentation de deux espaces par niveau",
            "- aucun commentaire avant ou apres la liste",
        ]
    )


def _build_notebooklm_unit_map_prompt(
    *,
    unit_type: WorkflowUnitType,
    title: str,
) -> str:
    return "\n".join(
        [
            "Lis ce PDF comme une unite pedagogique complete.",
            "Retourne uniquement un JSON strict avec les cles suivantes:",
            "{",
            '  "unit_title": "titre de l\'unite",',
            '  "teaching_goals": ["objectif 1", "objectif 2"],',
            '  "prerequisites": ["prerequis 1"],',
            '  "teacher_resources": ["outil ou support 1"],',
            '  "activity_blocks": ["activite 1", "activite 2"],',
            '  "assessment_blocks": ["evaluation 1"],',
            '  "pedagogy_notes": ["note pedagogique 1"],',
            '  "ordered_outline": [{"title": "...", "kind": "...", "children": [...]}]',
            "}",
            "Contraintes:",
            "- ordered_outline doit garder uniquement le deroulement pedagogique vecu par les eleves, dans l'ordre du document.",
            "- Garde le titre du chapitre comme racine si visible.",
            "- Inclure activites, contenu de la lecon, sections, sous-sections, definitions, proprietes, exemples, exercices et evaluation quand ils sont visibles.",
            "- Si l'ordre pedagogique est flou, recompose-le comme un enseignant: activites d'amorce, puis notions/lecon, puis definitions/proprietes/regles, puis exemples, puis exercices ou evaluation.",
            "- N'inclus pas dans ordered_outline les rubriques meta enseignant comme Objectifs d'apprentissage, Competences, Capacites, Prerequis, Outils didactiques, Ressources, Gestion du temps ou Demarche pedagogique; range-les plutot dans teaching_goals, prerequisites ou teacher_resources.",
            "- teaching_goals doit resumer les objectifs d'apprentissage visibles ou clairement implicites.",
            "- prerequisites doit lister les prerequis visibles ou tres evidents.",
            "- teacher_resources doit lister les outils didactiques ou supports visibles.",
            "- pedagogy_notes doit rester court et utile pour un enseignant.",
            "- Ne retourne aucun commentaire hors JSON.",
            f"Type d'unite: {unit_type.value}",
            f"Titre attendu: {title or 'Unite'}",
        ]
    )


def _build_notebooklm_content_pack_prompt(
    *,
    unit_type: WorkflowUnitType,
    title: str,
) -> str:
    return "\n".join(
        [
            "Lis ce PDF comme une unite pedagogique complete.",
            "Retourne uniquement un JSON strict avec la forme suivante:",
            "{",
            '  "content_blocks": [',
            "    {",
            '      "section_title": "titre de la section ou sous-section pedagogique la plus precise",',
            '      "section_path": ["grande section", "sous-section precise"],',
            '      "kind": "activity|lesson|definition|property|example|exercise|evaluation",',
            '      "teaching_phase": "activity|discovery|content|example|practice|assessment",',
            '      "title": "titre du bloc",',
            '      "source_excerpt": "court extrait fidele du document",',
            '      "teaching_material": "version concise et bien formulee pour enseigner ce bloc",',
            '      "student_visible": true,',
            '      "teacher_only": false,',
            '      "order_index": 1',
            "    }",
            "  ]",
            "}",
            "Contraintes:",
            "- Garde les content_blocks dans l'ordre pedagogique du document.",
            "- section_title et section_path doivent pointer vers la section d'enseignement la plus precise, pas vers des rubriques generiques comme 'Contenu de la lecon' s'il existe un vrai titre pedagogique plus bas.",
            "- Inclure les activites, notions, definitions, proprietes, methodes, exemples, exercices et evaluation visibles ou clairement relies a la progression.",
            "- source_excerpt doit rester court, fidele au document, et sans longues corrections detaillees.",
            "- teaching_material doit etre une formulation propre et exploitable en classe, en 1 a 3 phrases maximum.",
            "- teacher_only = true seulement pour un bloc reserve a l'enseignant; dans ce cas student_visible = false.",
            "- Exclure les rubriques meta enseignant ordinaires comme Objectifs, Prerequis, Outils didactiques, Gestion du temps, sauf si elles apportent une vraie valeur pedagogique et alors marque-les teacher_only.",
            "- Si l'ordre naturel d'une section est ambigu, privilegie: activite -> contenu/notion -> definition/propriete/regle -> exemple -> exercice -> evaluation.",
            "- Ne renvoie aucun commentaire hors JSON.",
            f"Type d'unite: {unit_type.value}",
            f"Titre attendu: {title or 'Unite'}",
        ]
    )


def _parse_notebooklm_outline_response(
    answer: str,
    *,
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> list[dict[str, Any]] | None:
    text = str(answer or "").strip()
    if not text:
        return None
    if text.lstrip().startswith(("{", "[")):
        return None

    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    parsed_any = False

    for depth, title in _extract_notebooklm_outline_lines(text):
        parsed_any = True
        kind = _infer_notebooklm_outline_kind(
            title,
            depth=depth,
            unit_type=unit_type,
            is_first_root=not roots and depth <= 0,
        )
        node: dict[str, Any] = {"title": title, "kind": kind.value, "children": []}
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((depth, node))

    if not parsed_any:
        return None
    normalized = _normalize_notebooklm_outline_items(roots, unit_type=unit_type, unit_title=unit_title)
    return normalized or None


def _normalize_unit_map_payload(
    payload: dict[str, Any] | None,
    *,
    fallback_outline: list[dict[str, Any]] | None,
    unit_title: str,
    unit_type: WorkflowUnitType,
    source_mode: str,
) -> dict[str, Any]:
    payload_outline = payload.get("ordered_outline") if isinstance(payload, dict) and isinstance(payload.get("ordered_outline"), list) else None
    normalized_outline = _normalize_notebooklm_outline_items(
        payload_outline or fallback_outline or [],
        unit_type=unit_type,
        unit_title=unit_title,
    )
    if not normalized_outline:
        normalized_outline = _normalize_notebooklm_outline_items(
            _build_unit_map_outline_candidates(payload),
            unit_type=unit_type,
            unit_title=unit_title,
        )

    normalized = {
        "unit_title": _normalize_outline_title((payload or {}).get("unit_title")) if isinstance(payload, dict) else "",
        "unit_type": unit_type.value,
        "source_mode": str(source_mode or "derived").strip() or "derived",
        "teaching_goals": _normalize_string_list((payload or {}).get("teaching_goals") if isinstance(payload, dict) else None),
        "prerequisites": _normalize_string_list((payload or {}).get("prerequisites") if isinstance(payload, dict) else None),
        "teacher_resources": _normalize_string_list((payload or {}).get("teacher_resources") if isinstance(payload, dict) else None),
        "activity_blocks": _normalize_string_list((payload or {}).get("activity_blocks") if isinstance(payload, dict) else None),
        "assessment_blocks": _normalize_string_list((payload or {}).get("assessment_blocks") if isinstance(payload, dict) else None),
        "pedagogy_notes": _normalize_string_list((payload or {}).get("pedagogy_notes") if isinstance(payload, dict) else None),
        "ordered_outline": normalized_outline,
        "future_actions": [
            "checklist",
            "content_pack",
            "session_writeup",
            "ask_unit",
            "adaptive_practice",
            "teacher_guidance",
            "slide_outline",
        ],
    }
    normalized["unit_title"] = normalized["unit_title"] or _normalize_outline_title(unit_title) or "Unite"

    if not normalized["teaching_goals"]:
        normalized["teaching_goals"] = _extract_unit_map_section_titles(normalized_outline, keywords=("objectif",))
    if not normalized["prerequisites"]:
        normalized["prerequisites"] = _extract_unit_map_section_titles(normalized_outline, keywords=("prerequis",))
    if not normalized["teacher_resources"]:
        normalized["teacher_resources"] = _extract_unit_map_section_titles(normalized_outline, keywords=("outil", "support", "ressource"))
    if not normalized["activity_blocks"]:
        normalized["activity_blocks"] = _extract_unit_map_section_titles(normalized_outline, keywords=("activite",))
    if not normalized["assessment_blocks"]:
        normalized["assessment_blocks"] = _extract_unit_map_section_titles(normalized_outline, keywords=("evaluation", "exercice"))
    if not normalized["pedagogy_notes"]:
        normalized["pedagogy_notes"] = _build_default_pedagogy_notes(
            normalized_outline,
            activity_blocks=normalized["activity_blocks"],
            assessment_blocks=normalized["assessment_blocks"],
        )
    normalized["section_plans"] = _build_unit_section_plans(normalized_outline)
    return normalized


def _align_notebooklm_unit_map_with_outline(
    *,
    parsed_outline: list[dict[str, Any]] | None,
    unit_map: dict[str, Any] | None,
    source_text: str,
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    normalized_map = _normalize_unit_map_payload(
        unit_map,
        fallback_outline=parsed_outline,
        unit_title=unit_title,
        unit_type=unit_type,
        source_mode=str((unit_map or {}).get("source_mode") or "notebooklm-unit-map"),
    )
    map_outline = normalized_map.get("ordered_outline") if isinstance(normalized_map.get("ordered_outline"), list) else []
    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    if parsed_outline:
        candidates.append(("outline_response", parsed_outline))
    if map_outline:
        candidates.append(("unit_map", map_outline))
    if not candidates:
        return [], normalized_map, "none"
    if len(candidates) == 1:
        selected_source, selected_outline = candidates[0]
    elif parsed_outline and map_outline:
        parsed_score = _score_notebooklm_outline_candidate(
            parsed_outline,
            source_text=source_text,
            unit_type=unit_type,
            unit_title=unit_title,
        )
        map_score = _score_notebooklm_outline_candidate(
            map_outline,
            source_text=source_text,
            unit_type=unit_type,
            unit_title=unit_title,
        )
        if map_score + 6 >= parsed_score:
            selected_source, selected_outline = "unit_map", map_outline
        else:
            selected_source, selected_outline = "outline_response", parsed_outline
    else:
        selected_source, selected_outline = _select_best_notebooklm_outline_candidate(
            candidates,
            source_text=source_text,
            unit_type=unit_type,
            unit_title=unit_title,
        )
    normalized_map["ordered_outline"] = _copy_jsonable(selected_outline)
    normalized_map["selected_outline_source"] = selected_source
    return selected_outline, normalized_map, selected_source


def _copy_jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def _build_unit_map_from_items(
    items: list[dict[str, Any]] | None,
    *,
    unit_type: WorkflowUnitType,
    unit_title: str,
    source_mode: str,
) -> dict[str, Any]:
    return _normalize_unit_map_payload(
        None,
        fallback_outline=items,
        unit_title=unit_title,
        unit_type=unit_type,
        source_mode=source_mode,
    )


def _build_unit_map_outline_candidates(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_outline = payload.get("ordered_outline")
    if isinstance(raw_outline, list):
        candidates = _sanitize_items(raw_outline)
        if candidates:
            return candidates
    ordered_titles = payload.get("ordered_titles")
    if not isinstance(ordered_titles, list):
        return []
    candidates: list[dict[str, Any]] = []
    for title in ordered_titles:
        normalized = _normalize_outline_title(title)
        if not normalized:
            continue
        candidates.append({"title": normalized, "kind": WorkflowChecklistItemKind.SECTION.value, "children": []})
    return candidates


def _normalize_string_list(values: Any, *, limit: int = 12) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_outline_title(value)
        if not text:
            continue
        key = _semantic_title_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(text)
        if len(output) >= limit:
            break
    return output


CONTENT_BLOCK_KIND_MAP: dict[str, str] = {
    "activity": "activity",
    "activite": "activity",
    "lesson": "lesson",
    "lecon": "lesson",
    "cours": "lesson",
    "definition": "definition",
    "définition": "definition",
    "property": "property",
    "propriete": "property",
    "propriété": "property",
    "regle": "property",
    "règle": "property",
    "example": "example",
    "exemple": "example",
    "exercise": "exercise",
    "exercice": "exercise",
    "application": "exercise",
    "evaluation": "evaluation",
}

CONTENT_BLOCK_PHASE_MAP: dict[str, str] = {
    "activity": "activity",
    "activite": "activity",
    "discovery": "discovery",
    "decouverte": "discovery",
    "découverte": "discovery",
    "content": "content",
    "lesson": "content",
    "lecon": "content",
    "cours": "content",
    "definition": "content",
    "property": "content",
    "propriete": "content",
    "propriété": "content",
    "regle": "content",
    "règle": "content",
    "example": "example",
    "exemple": "example",
    "practice": "practice",
    "exercise": "practice",
    "exercice": "practice",
    "application": "practice",
    "assessment": "assessment",
    "evaluation": "assessment",
}

GENERIC_SECTION_BUCKET_KEYS: set[str] = {
    "activites",
    "activite",
    "contenu de la lecon",
    "contenu",
    "cours",
    "lecon",
    "evaluation",
    "exercices",
    "exercice",
}


def _normalize_content_block_kind(value: Any) -> str:
    folded = _fold_text_key(value)
    if not folded:
        return "lesson"
    return CONTENT_BLOCK_KIND_MAP.get(folded, CONTENT_BLOCK_KIND_MAP.get(folded.split()[0], "lesson"))


def _normalize_content_block_text(value: Any, *, limit: int) -> str:
    text = _normalize_outline_title(value)
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip(" ;,-")
    if len(text) > limit:
        text = text[:limit].rstrip(" ;,-") + "..."
    return text


def _normalize_content_block_path(value: Any, *, fallback_section_title: str) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    output: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        title = _normalize_content_block_text(item, limit=180)
        if not title:
            continue
        key = _semantic_title_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(title)
    fallback = _normalize_content_block_text(fallback_section_title, limit=180)
    if not output and fallback:
        output = [fallback]
    if len(output) > 1:
        trimmed = list(output)
        while len(trimmed) > 1 and _semantic_title_key(trimmed[0]) in GENERIC_SECTION_BUCKET_KEYS:
            trimmed.pop(0)
        output = trimmed or output
    return output[:6]


def _normalize_content_block_phase(value: Any, *, kind: str, title: str) -> str:
    folded = _fold_text_key(value)
    if folded:
        resolved = CONTENT_BLOCK_PHASE_MAP.get(folded)
        if resolved:
            return resolved
    if kind == "activity" or _is_activity_outline_title(title, kind):
        return "activity"
    if kind == "example":
        return "example"
    if kind in {"exercise", "evaluation"}:
        return "assessment" if kind == "evaluation" else "practice"
    return "content"


def _derive_content_blocks_from_outline(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    def walk(nodes: list[dict[str, Any]], section_title: str | None = None) -> None:
        current_section = section_title
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = _normalize_outline_title(node.get("title"))
            kind = str(node.get("kind") or "").strip().lower()
            children = node.get("children") if isinstance(node.get("children"), list) else []
            if not title or kind == WorkflowChecklistItemKind.CHAPTER.value:
                walk(children, current_section)
                continue
            if kind in {WorkflowChecklistItemKind.SECTION.value, WorkflowChecklistItemKind.SUBSECTION.value}:
                current_section = title
                if children:
                    walk(children, current_section)
                    continue
            if kind != WorkflowChecklistItemKind.CHAPTER.value:
                block_kind = {
                    WorkflowChecklistItemKind.DEFINITION.value: "definition",
                    WorkflowChecklistItemKind.PROPERTY.value: "property",
                    WorkflowChecklistItemKind.EXAMPLE.value: "example",
                    WorkflowChecklistItemKind.EXERCISE.value: "exercise",
                    WorkflowChecklistItemKind.OTHER.value: "activity" if _is_activity_outline_title(title, kind) else "lesson",
                }.get(kind, "lesson")
                blocks.append(
                    {
                        "section_title": current_section or title,
                        "section_path": [current_section or title],
                        "kind": block_kind,
                        "teaching_phase": _normalize_content_block_phase(None, kind=block_kind, title=title),
                        "title": title,
                        "source_excerpt": title,
                        "teaching_material": title,
                        "student_visible": not _is_teacher_meta_outline_title(title),
                        "teacher_only": _is_teacher_meta_outline_title(title),
                        "order_index": len(blocks) + 1,
                    }
                )
            if children:
                walk(children, current_section)

    walk(items)
    return blocks[:240]


def _normalize_content_blocks_payload(
    payload: dict[str, Any] | None,
    *,
    unit_map: dict[str, Any] | None,
    fallback_outline: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    raw_blocks = payload.get("content_blocks") if isinstance(payload, dict) and isinstance(payload.get("content_blocks"), list) else None
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    last_section_title = ""
    for index, row in enumerate(raw_blocks or []):
        if not isinstance(row, dict):
            continue
        title = _normalize_content_block_text(row.get("title"), limit=180)
        section_title = _normalize_content_block_text(row.get("section_title"), limit=180)
        kind = _normalize_content_block_kind(row.get("kind"))
        if not title:
            continue
        if not section_title:
            section_title = last_section_title or title
        section_path = _normalize_content_block_path(row.get("section_path"), fallback_section_title=section_title)
        if section_path:
            section_title = section_path[-1]
        source_excerpt = _normalize_content_block_text(row.get("source_excerpt"), limit=320)
        teaching_material = _normalize_content_block_text(row.get("teaching_material"), limit=520)
        student_visible = bool(row.get("student_visible", True))
        teacher_only = bool(row.get("teacher_only", False))
        if _is_teacher_meta_outline_title(title) or _is_teacher_meta_outline_title(section_title):
            teacher_only = True if row.get("teacher_only") is not False else teacher_only
            student_visible = False if row.get("student_visible") is not True else student_visible
        order_value = row.get("order_index")
        try:
            order_index = int(order_value)
        except Exception:
            order_index = index + 1
        key = (_semantic_title_key(section_title), _semantic_title_key(title), kind)
        if not key[1] or key in seen:
            continue
        seen.add(key)
        block = {
            "section_title": section_title,
            "section_path": section_path,
            "kind": kind,
            "teaching_phase": _normalize_content_block_phase(row.get("teaching_phase"), kind=kind, title=title),
            "title": title,
            "source_excerpt": source_excerpt or title,
            "teaching_material": teaching_material or source_excerpt or title,
            "student_visible": student_visible,
            "teacher_only": teacher_only,
            "order_index": max(1, order_index),
        }
        output.append(block)
        last_section_title = section_title
    if not output:
        output = _derive_content_blocks_from_outline(fallback_outline or (unit_map.get("ordered_outline") if isinstance(unit_map, dict) and isinstance(unit_map.get("ordered_outline"), list) else []))
    output.sort(key=lambda row: (int(row.get("order_index") or 0), _semantic_title_key(row.get("section_title")), _semantic_title_key(row.get("title"))))
    for idx, row in enumerate(output, start=1):
        row["order_index"] = idx
    return output[:240]


def _build_unit_section_plans_from_content_blocks(
    blocks: list[dict[str, Any]] | None,
    *,
    fallback_plans: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(blocks, list) or not blocks:
        return _copy_jsonable(fallback_plans or [])

    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    ordering: list[tuple[int, tuple[str, ...]]] = []

    for raw_block in blocks:
        if not isinstance(raw_block, dict):
            continue
        section_title = _normalize_outline_title(raw_block.get("section_title"))
        section_path = _normalize_content_block_path(raw_block.get("section_path"), fallback_section_title=section_title)
        title = _normalize_outline_title(raw_block.get("title"))
        kind = _normalize_content_block_kind(raw_block.get("kind"))
        if not section_title or not title:
            continue
        if _is_teacher_meta_outline_title(section_title):
            continue
        path_key = tuple(_semantic_title_key(part) for part in section_path if _semantic_title_key(part))
        if not path_key:
            path_key = (_semantic_title_key(section_title),)
        try:
            order_index = int(raw_block.get("order_index") or 0)
        except Exception:
            order_index = 0
        plan = grouped.get(path_key)
        if plan is None:
            plan = {
                "section_title": section_title,
                "section_path": section_path,
                "activity_titles": [],
                "content_titles": [],
                "example_titles": [],
                "exercise_titles": [],
                "delivery_sequence": [],
                "blocks": [],
            }
            grouped[path_key] = plan
            ordering.append((order_index or len(ordering) + 1, path_key))

        student_visible = bool(raw_block.get("student_visible", True))
        teacher_only = bool(raw_block.get("teacher_only", False))
        if teacher_only and not student_visible:
            continue

        source_excerpt = _normalize_content_block_text(raw_block.get("source_excerpt"), limit=320) or title
        teaching_material = _normalize_content_block_text(raw_block.get("teaching_material"), limit=520) or source_excerpt
        compact_block = {
            "title": title,
            "kind": kind,
            "source_excerpt": source_excerpt,
            "teaching_material": teaching_material,
            "student_visible": student_visible,
            "teacher_only": teacher_only,
            "order_index": max(1, order_index or len(plan["blocks"]) + 1),
        }
        plan["blocks"].append(compact_block)
        plan["delivery_sequence"].append(title)
        if kind == "activity":
            plan["activity_titles"].append(title)
        elif kind == "example":
            plan["example_titles"].append(title)
        elif kind in {"exercise", "evaluation"}:
            plan["exercise_titles"].append(title)
        else:
            plan["content_titles"].append(title)

    ordered_titles = [title for _, title in sorted(ordering, key=lambda row: (row[0], " ".join(row[1])))]
    plans: list[dict[str, Any]] = []
    for title in ordered_titles:
        plan = grouped.get(title)
        if not isinstance(plan, dict):
            continue
        plan["blocks"].sort(key=lambda row: (int(row.get("order_index") or 0), _semantic_title_key(row.get("title"))))
        if not plan["delivery_sequence"]:
            continue
        deduped: dict[str, list[str]] = {}
        for key in ("activity_titles", "content_titles", "example_titles", "exercise_titles", "delivery_sequence"):
            seen: set[str] = set()
            items: list[str] = []
            for value in plan.get(key) or []:
                normalized = _normalize_outline_title(value)
                semantic = _semantic_title_key(normalized)
                if not semantic or semantic in seen:
                    continue
                seen.add(semantic)
                items.append(normalized)
            deduped[key] = items
        plan["activity_titles"] = deduped["activity_titles"]
        plan["content_titles"] = deduped["content_titles"]
        plan["example_titles"] = deduped["example_titles"]
        plan["exercise_titles"] = deduped["exercise_titles"]
        plan["delivery_sequence"] = deduped["delivery_sequence"]
        plans.append(plan)
    return plans[:24]


def _content_block_to_checklist_kind(kind: str, *, title: str) -> WorkflowChecklistItemKind:
    if kind == "definition":
        return WorkflowChecklistItemKind.DEFINITION
    if kind == "property":
        return WorkflowChecklistItemKind.PROPERTY
    if kind == "example":
        return WorkflowChecklistItemKind.EXAMPLE
    if kind in {"exercise", "evaluation"}:
        return WorkflowChecklistItemKind.EXERCISE
    if kind == "activity":
        return WorkflowChecklistItemKind.OTHER
    if _is_explicit_topic_outline_title(title):
        return WorkflowChecklistItemKind.SECTION
    return WorkflowChecklistItemKind.OTHER


def _build_checklist_from_content_blocks(
    blocks: list[dict[str, Any]] | None,
    *,
    unit_title: str,
    unit_type: WorkflowUnitType,
    fallback_outline: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(blocks, list) or not blocks:
        return []

    chapter_title = _normalize_outline_title(unit_title) or "Unite"
    if unit_type == WorkflowUnitType.CHAPTER and isinstance(fallback_outline, list) and fallback_outline:
        first = fallback_outline[0] if isinstance(fallback_outline[0], dict) else None
        if isinstance(first, dict):
            first_title = _normalize_outline_title(first.get("title"))
            first_kind = str(first.get("kind") or "").strip().lower()
            if first_title and first_kind == WorkflowChecklistItemKind.CHAPTER.value:
                chapter_title = first_title

    def make_node(title: str, kind: WorkflowChecklistItemKind) -> dict[str, Any]:
        return {"title": title, "kind": kind.value, "children": []}

    root = make_node(chapter_title, WorkflowChecklistItemKind.CHAPTER)
    roots: list[dict[str, Any]] = [root] if unit_type == WorkflowUnitType.CHAPTER else []
    root_children = root["children"] if unit_type == WorkflowUnitType.CHAPTER else roots
    path_index: dict[tuple[str, ...], dict[str, Any]] = {}
    node_child_keys: dict[int, set[str]] = {}

    def register_child(parent_children: list[dict[str, Any]], parent_path: tuple[str, ...], title: str, kind: WorkflowChecklistItemKind) -> dict[str, Any]:
        key = _semantic_title_key(title)
        existing_keys = node_child_keys.setdefault(id(parent_children), set())
        for node in parent_children:
            if _semantic_title_key(node.get("title")) == key:
                return node
        node = make_node(title, kind)
        parent_children.append(node)
        existing_keys.add(key)
        if parent_path:
            path_index[parent_path + (title,)] = node
        return node

    ordered_blocks = sorted(
        [row for row in blocks if isinstance(row, dict)],
        key=lambda row: (int(row.get("order_index") or 0), _semantic_title_key(row.get("section_title")), _semantic_title_key(row.get("title"))),
    )
    for row in ordered_blocks:
        if bool(row.get("teacher_only")) and not bool(row.get("student_visible", True)):
            continue
        title = _normalize_outline_title(row.get("title"))
        kind = _normalize_content_block_kind(row.get("kind"))
        if not title:
            continue
        raw_path = row.get("section_path")
        path_titles = _normalize_content_block_path(raw_path, fallback_section_title=str(row.get("section_title") or ""))
        path_titles = [value for value in path_titles if _semantic_title_key(value) not in GENERIC_SECTION_BUCKET_KEYS or len(path_titles) == 1]

        parent_children = root_children
        parent_path: tuple[str, ...] = ()
        for depth, part in enumerate(path_titles):
            if _semantic_title_key(part) == _semantic_title_key(chapter_title):
                continue
            if _is_teacher_meta_outline_title(part):
                continue
            part_kind = WorkflowChecklistItemKind.SECTION if depth == 0 else WorkflowChecklistItemKind.SUBSECTION
            node = register_child(parent_children, parent_path, part, part_kind)
            parent_children = node["children"]
            parent_path = parent_path + (part,)

        leaf_key = _semantic_title_key(title)
        last_path_key = _semantic_title_key(path_titles[-1]) if path_titles else ""
        if leaf_key and leaf_key == last_path_key and kind in {"lesson", "content"}:
            continue

        leaf_kind = _content_block_to_checklist_kind(kind, title=title)
        register_child(parent_children, parent_path, title, leaf_kind)

    return _sanitize_items(roots)


def _apply_content_blocks_to_unit_map(
    unit_map: dict[str, Any] | None,
    content_blocks: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not isinstance(unit_map, dict):
        return unit_map
    if not isinstance(content_blocks, list) or not content_blocks:
        return unit_map
    updated = _copy_jsonable(unit_map)
    fallback_plans = updated.get("section_plans") if isinstance(updated.get("section_plans"), list) else None
    updated["section_plans"] = _build_unit_section_plans_from_content_blocks(content_blocks, fallback_plans=fallback_plans)
    updated["teacher_playbook"] = _build_teacher_playbook_from_section_plans(updated["section_plans"])
    if not updated.get("activity_blocks"):
        updated["activity_blocks"] = [plan.get("section_title") for plan in updated["section_plans"] if plan.get("activity_titles")]
    if not updated.get("assessment_blocks"):
        updated["assessment_blocks"] = [plan.get("section_title") for plan in updated["section_plans"] if plan.get("exercise_titles")]
    return updated


def _content_blocks_have_structured_paths(blocks: list[dict[str, Any]] | None) -> bool:
    if not isinstance(blocks, list):
        return False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        path = block.get("section_path")
        if isinstance(path, list) and len([row for row in path if _normalize_outline_title(row)]) >= 2:
            return True
    return False


def _extract_unit_map_section_titles(items: list[dict[str, Any]], *, keywords: tuple[str, ...]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for node in _flatten_checklist_nodes(items):
        title = _normalize_outline_title(node.get("title"))
        folded = _fold_text_key(title)
        if not title or not any(keyword in folded for keyword in keywords):
            continue
        key = _semantic_title_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(title)
    return output


def _build_default_pedagogy_notes(
    items: list[dict[str, Any]],
    *,
    activity_blocks: list[str],
    assessment_blocks: list[str],
) -> list[str]:
    notes: list[str] = []
    if activity_blocks:
        notes.append("L'unite s'appuie sur des activites progressives a exploiter en debut ou en cours de seance.")
    if assessment_blocks:
        notes.append("Prevoir un temps de verification des acquis a partir des exercices et rubriques d'evaluation visibles.")
    if _extract_unit_map_section_titles(items, keywords=("propriete", "definition", "regle")):
        notes.append("Les definitions, proprietes et regles doivent etre traitees avant les applications longues.")
    return notes[:4]


def _build_unit_section_plans(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []

    def make_plan(node: dict[str, Any]) -> dict[str, Any] | None:
        title = _normalize_outline_title(node.get("title"))
        kind = str(node.get("kind") or "").strip().lower()
        children = [child for child in (node.get("children") if isinstance(node.get("children"), list) else []) if isinstance(child, dict)]
        if not title or not children:
            return None
        if kind == WorkflowChecklistItemKind.CHAPTER.value:
            return None
        if _is_teacher_meta_outline_title(title) or _is_activity_outline_title(title, kind) or _is_assessment_outline_title(title, kind):
            return None

        activity_titles: list[str] = []
        content_titles: list[str] = []
        example_titles: list[str] = []
        exercise_titles: list[str] = []
        delivery_sequence: list[str] = []

        for child in children:
            child_title = _normalize_outline_title(child.get("title"))
            child_kind = str(child.get("kind") or "").strip().lower()
            if not child_title:
                continue
            delivery_sequence.append(child_title)
            if _is_activity_outline_title(child_title, child_kind):
                activity_titles.append(child_title)
            elif child_kind == WorkflowChecklistItemKind.EXAMPLE.value:
                example_titles.append(child_title)
            elif _is_assessment_outline_title(child_title, child_kind):
                exercise_titles.append(child_title)
            else:
                content_titles.append(child_title)

        if not delivery_sequence:
            return None
        return {
            "section_title": title,
            "activity_titles": activity_titles,
            "content_titles": content_titles,
            "example_titles": example_titles,
            "exercise_titles": exercise_titles,
            "delivery_sequence": delivery_sequence,
        }

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            plan = make_plan(node)
            if plan is not None:
                plans.append(plan)
            children = node.get("children") if isinstance(node.get("children"), list) else []
            walk(children)

    walk(items)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for plan in plans:
        key = "|".join(_semantic_title_key(part) for part in (plan.get("section_path") or []) if _semantic_title_key(part)) or _semantic_title_key(plan.get("section_title"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(plan)
    return deduped[:24]


def _build_teacher_playbook_from_section_plans(
    plans: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not isinstance(plans, list):
        return []
    playbook: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        section_title = _normalize_outline_title(plan.get("section_title"))
        if not section_title:
            continue
        section_path = [
            _normalize_outline_title(value)
            for value in (plan.get("section_path") if isinstance(plan.get("section_path"), list) else [section_title])
            if _normalize_outline_title(value)
        ] or [section_title]
        has_activity = bool(plan.get("activity_titles"))
        has_content = bool(plan.get("content_titles"))
        has_examples = bool(plan.get("example_titles"))
        has_exercises = bool(plan.get("exercise_titles"))
        available_actions = [
            "explain_section",
            "generate_teacher_notes",
            "generate_slides",
        ]
        if has_activity:
            available_actions.append("create_warmup_variant")
        if has_content:
            available_actions.append("simplify_explanation")
        if has_examples:
            available_actions.append("generate_guided_examples")
        if has_content or has_examples or has_exercises:
            available_actions.extend(["generate_easier_practice", "generate_harder_practice"])
        if has_content or has_exercises:
            available_actions.append("generate_quick_quiz")
        if has_exercises:
            available_actions.append("generate_remediation")

        suggested_requests = [
            f"Explique la section '{section_title}' simplement pour la classe.",
        ]
        if has_activity:
            suggested_requests.append(f"Propose une variante plus engageante de l'activite pour '{section_title}'.")
        if has_examples:
            suggested_requests.append(f"Genere deux exemples guides supplementaires pour '{section_title}'.")
        if has_content or has_examples or has_exercises:
            suggested_requests.append(f"Genere trois exercices plus faciles pour '{section_title}' avec reponses courtes.")
            suggested_requests.append(f"Genere trois exercices plus difficiles pour '{section_title}' avec correction resumee.")
        if has_content or has_exercises:
            suggested_requests.append(f"Prepare un mini quiz de sortie pour '{section_title}'.")

        playbook.append(
            {
                "section_title": section_title,
                "section_path": section_path,
                "available_actions": available_actions,
                "suggested_requests": suggested_requests[:6],
                "supports_activity": has_activity,
                "supports_examples": has_examples,
                "supports_exercises": has_exercises,
            }
        )
    return playbook[:24]


def _select_best_notebooklm_outline_candidate(
    candidates: list[tuple[str, list[dict[str, Any]]]],
    *,
    source_text: str,
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> tuple[str, list[dict[str, Any]]]:
    best_name, best_items = candidates[0]
    best_score = _score_notebooklm_outline_candidate(
        best_items,
        source_text=source_text,
        unit_type=unit_type,
        unit_title=unit_title,
    )
    for name, items in candidates[1:]:
        score = _score_notebooklm_outline_candidate(
            items,
            source_text=source_text,
            unit_type=unit_type,
            unit_title=unit_title,
        )
        if score > best_score:
            best_name = name
            best_items = items
            best_score = score
    return best_name, best_items


def _score_notebooklm_outline_candidate(
    items: list[dict[str, Any]],
    *,
    source_text: str,
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> int:
    score = _score_checklist_quality(items, unit_type=unit_type, unit_title=unit_title)
    reference_titles = _extract_notebooklm_reference_titles(source_text)
    candidate_titles = _outline_reference_titles(items)
    for reference in reference_titles:
        if any(_semantic_titles_match(reference, candidate) for candidate in candidate_titles):
            score += 5
        else:
            score -= 2
    score -= _count_notebooklm_outline_noise(items) * 3
    return score


def _extract_notebooklm_reference_titles(source_text: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    allowed_fixed = {
        "objectifs d apprentissage",
        "prerequis",
        "outils didactiques",
        "gestion du temps",
        "activites",
        "contenu de la lecon",
        "evaluation",
    }
    for raw_line in _extract_structural_source_lines(source_text):
        line = _normalize_outline_title(raw_line)
        if not line:
            continue
        folded = _fold_text_key(line)
        include = False
        if folded in allowed_fixed:
            include = True
        elif CHAPTER_START_PATTERN.match(line) or NUMBERED_HEADING_PATTERN.match(line) or ROMAN_HEADING_PATTERN.match(line) or ALPHA_HEADING_PATTERN.match(line):
            include = True
        elif re.match(r"^(activite|exercice|exercise)\s*\d+", folded, flags=re.IGNORECASE):
            include = True
        elif _keyword_kind_from_line(line) is not None and len(line.split()) <= 8:
            include = True
        if not include:
            continue
        key = _semantic_title_key(line)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(key)
    return output


def _count_notebooklm_outline_noise(items: list[dict[str, Any]]) -> int:
    noise = 0
    for node in _flatten_checklist_nodes(items):
        title = _normalize_outline_title(node.get("title"))
        folded = _fold_text_key(title)
        if not title or _is_trivial_outline_fragment(title):
            noise += 1
            continue
        if re.match(r"^\d+\)\s+(?:est|car)$", folded):
            noise += 2
            continue
        if re.fullmatch(r"[a-z]", folded):
            noise += 1
    return noise


def _count_teacher_meta_outline_nodes(items: list[dict[str, Any]]) -> int:
    count = 0
    for node in _flatten_checklist_nodes(items):
        title = _normalize_outline_title(node.get("title"))
        if title and _is_teacher_meta_outline_title(title):
            count += 1
    return count


def _extract_notebooklm_outline_lines(text: str) -> list[tuple[int, str]]:
    output: list[tuple[int, str]] = []
    for raw_line in str(text or "").splitlines():
        line = str(raw_line or "").rstrip()
        if not line:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            continue
        match = NOTEBOOKLM_OUTLINE_BULLET_PATTERN.match(line)
        if not match:
            continue
        indent_text = str(match.group("indent") or "")
        candidate = str(match.group("title") or "").strip()
        had_bullet = bool(re.match(r"^[ \t]*[-*•‣▪●○]\s+", line))
        candidate = _normalize_outline_title(candidate)
        if not candidate:
            continue
        lowered = _fold_text_key(candidate)
        if lowered in {"plan", "outline", "checklist", "liste des titres", "liste des headlines"}:
            continue
        if _is_metadata_noise_line(candidate):
            continue
        indent_width = len(indent_text.expandtabs(2))
        depth = max(0, indent_width // 2)
        output.append((depth, candidate))
    return output


def _infer_notebooklm_outline_kind(
    title: str,
    *,
    depth: int,
    unit_type: WorkflowUnitType,
    is_first_root: bool,
) -> WorkflowChecklistItemKind:
    normalized_title = _normalize_outline_title(title)
    if CHAPTER_START_PATTERN.match(normalized_title):
        return WorkflowChecklistItemKind.CHAPTER
    keyword_kind = _keyword_kind_from_line(normalized_title)
    if keyword_kind is not None:
        return keyword_kind
    if NUMBERED_HEADING_PATTERN.match(normalized_title):
        return _infer_kind_from_text(normalized_title, default=WorkflowChecklistItemKind.SECTION)
    if ROMAN_HEADING_PATTERN.match(normalized_title) or ALPHA_HEADING_PATTERN.match(normalized_title):
        return WorkflowChecklistItemKind.SECTION if depth <= 1 else WorkflowChecklistItemKind.SUBSECTION
    if unit_type == WorkflowUnitType.CHAPTER and is_first_root:
        return WorkflowChecklistItemKind.CHAPTER
    if depth <= 0:
        if unit_type == WorkflowUnitType.EXERCISE_SERIES:
            return WorkflowChecklistItemKind.EXERCISE
        return WorkflowChecklistItemKind.SECTION
    if depth == 1:
        return WorkflowChecklistItemKind.SECTION
    return WorkflowChecklistItemKind.SUBSECTION


def _normalize_notebooklm_outline_items(
    items: list[dict[str, Any]],
    *,
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> list[dict[str, Any]]:
    def walk(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = _normalize_outline_title(node.get("title"))
            if not title or _is_metadata_noise_line(title) or _is_trivial_outline_fragment(title) or _is_teacher_meta_outline_title(title):
                continue
            raw_kind = str(node.get("kind") or WorkflowChecklistItemKind.OTHER.value).strip().lower()
            allowed = {kind.value for kind in WorkflowChecklistItemKind}
            kind = raw_kind if raw_kind in allowed else WorkflowChecklistItemKind.OTHER.value
            children = walk(node.get("children") if isinstance(node.get("children"), list) else [])
            session_number = _normalize_session_number(node.get("session_number"))
            normalized_node: dict[str, Any] = {"title": title, "kind": kind, "children": children}
            if session_number is not None:
                normalized_node["session_number"] = session_number
            output.append(normalized_node)
        return _dedupe_sibling_nodes(output)

    normalized = _resequence_outline_for_teaching_flow(walk(items))
    if unit_type != WorkflowUnitType.CHAPTER or not normalized:
        return normalized
    return _ensure_notebooklm_chapter_root(normalized, unit_title=unit_title)


def _is_teacher_meta_outline_title(title: str) -> bool:
    normalized = _normalize_outline_title(title)
    if not normalized:
        return False
    return any(pattern.match(normalized) for pattern in TEACHER_META_SECTION_PATTERNS)


def _is_activity_outline_title(title: str, kind: str) -> bool:
    folded = _fold_text_key(title)
    return folded.startswith(("activite", "activites"))


def _is_content_outline_title(title: str) -> bool:
    folded = _fold_text_key(title)
    return folded.startswith(("contenu de la lecon", "contenu", "cours", "lecon", "notion", "notions"))


def _is_assessment_outline_title(title: str, kind: str) -> bool:
    folded = _fold_text_key(title)
    if kind == WorkflowChecklistItemKind.EXERCISE.value:
        return True
    return folded.startswith(("evaluation", "exercice", "exercices", "application", "applications"))


def _is_explicit_topic_outline_title(title: str, kind: str) -> bool:
    if kind not in {WorkflowChecklistItemKind.SECTION.value, WorkflowChecklistItemKind.SUBSECTION.value}:
        return False
    raw = str(title or "").strip()
    return bool(
        NUMBERED_HEADING_PATTERN.match(raw)
        or ROMAN_HEADING_PATTERN.match(raw)
        or ALPHA_HEADING_PATTERN.match(raw)
    )


def _outline_teaching_flow_rank(node: dict[str, Any]) -> int:
    title = _normalize_outline_title(node.get("title"))
    kind = str(node.get("kind") or "").strip().lower()
    if not title:
        return 999
    if _is_teacher_meta_outline_title(title):
        return 900
    if _is_activity_outline_title(title, kind):
        return 10
    if _is_content_outline_title(title):
        return 20
    if _is_explicit_topic_outline_title(title, kind):
        return 30
    if kind in {WorkflowChecklistItemKind.SECTION.value, WorkflowChecklistItemKind.SUBSECTION.value}:
        return 35
    if kind in {WorkflowChecklistItemKind.DEFINITION.value, WorkflowChecklistItemKind.PROPERTY.value}:
        return 40
    if kind == WorkflowChecklistItemKind.EXAMPLE.value:
        return 50
    if _is_assessment_outline_title(title, kind):
        return 60
    return 70


def _resequence_outline_for_teaching_flow(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resequenced: list[dict[str, Any]] = []
    for node in items:
        if not isinstance(node, dict):
            continue
        cloned = dict(node)
        children = cloned.get("children") if isinstance(cloned.get("children"), list) else []
        cloned["children"] = _resequence_outline_for_teaching_flow(children)
        resequenced.append(cloned)
    indexed = list(enumerate(resequenced))
    indexed.sort(key=lambda pair: (_outline_teaching_flow_rank(pair[1]), pair[0]))
    return [node for _, node in indexed]


def _ensure_notebooklm_chapter_root(items: list[dict[str, Any]], *, unit_title: str) -> list[dict[str, Any]]:
    if not items:
        return []
    first = dict(items[0])
    if str(first.get("kind") or "").strip().lower() == WorkflowChecklistItemKind.CHAPTER.value:
        if len(items) == 1:
            return [first]
        first["children"] = [
            *(first.get("children") if isinstance(first.get("children"), list) else []),
            *items[1:],
        ]
        return [first]
    if len(items) == 1:
        first["kind"] = WorkflowChecklistItemKind.CHAPTER.value
        return [first]
    if len(str(first.get("title") or "").split()) >= 2:
        first["kind"] = WorkflowChecklistItemKind.CHAPTER.value
        first["children"] = [
            *(first.get("children") if isinstance(first.get("children"), list) else []),
            *items[1:],
        ]
        return [first]
    chapter_title = _normalize_outline_title(unit_title) or "Chapter"
    return [
        {
            "title": chapter_title,
            "kind": WorkflowChecklistItemKind.CHAPTER.value,
            "children": items,
        }
    ]


def _build_notebooklm_session_writeup_prompt(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    session_number: int | None,
    checked_item_titles: list[str],
    note_text: str,
) -> str:
    checked_text = json.dumps([str(value or "").strip() for value in checked_item_titles if str(value or "").strip()], ensure_ascii=False)
    return (
        "A partir des contenus sources de ce notebook, redige uniquement un JSON strict avec les cles "
        "`title`, `learning_focus`, `teaching_content`, `practice_items`.\n"
        "Contraintes:\n"
        "1. Utilise seulement les elements effectivement realises.\n"
        "2. `learning_focus` doit etre une liste breve et claire.\n"
        "3. `teaching_content` doit contenir 1 a 4 paragraphes bien rediges en francais.\n"
        "4. `practice_items` doit contenir des exercices, applications ou renforcements.\n"
        "5. S'il manque du contenu, propose une seance de consolidation par exercices; aucune section ne doit etre vide.\n"
        "6. Ne retourne aucun texte hors JSON.\n"
        f"Unite: {unit_title or 'unite en cours'}\n"
        f"Type d'unite: {unit_type.value if unit_type is not None else 'chapter'}\n"
        f"Numero de seance: {int(session_number) if session_number and session_number > 0 else 'non precise'}\n"
        f"Elements realises: {checked_text}\n"
        f"Note enseignant: {note_text.strip() if note_text.strip() else '(aucune)'}"
    )


def _openai_generate_checklist(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None = None,
    outline_hint_lines: list[str] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, str | None]:
    if not app_config.OPENAI_API_KEY:
        return None, None, "openai_api_key_not_set"

    if unit_type == WorkflowUnitType.CHAPTER:
        task_rules = (
            "Generate a HIERARCHICAL checklist tree for a middle-school math chapter. "
            "Include heading-only nodes using kinds: chapter, section, subsection, property, definition, example. "
            "Use concise titles and preserve source order."
        )
    else:
        task_rules = (
            "Generate a FLAT checklist for an exercise series. "
            "Return each exercise title as a separate item with kind=exercise. "
            "Keep short reminders only."
        )

    system_prompt = (
        "You are an expert middle-school mathematics curriculum planner. "
        "Return STRICT JSON only with this exact schema: "
        "{\"items\": [{\"title\": \"...\", \"kind\": \"...\", \"children\": [...], \"session_number\": 1 }]} . "
        "Allowed kinds: chapter, section, subsection, property, definition, example, exercise, supervision, correction, other. "
        "session_number is optional; if provided it must be an integer >= 1. "
        "Do not include any key other than title, kind, children, session_number."
    )
    session_rule = ""
    if session_count is not None and int(session_count) > 0:
        normalized_count = int(session_count)
        session_rule = (
            f"\nSession split rule: assign each leaf checklist item a session_number between 1 and {normalized_count}. "
            "Preserve source order and keep sequence continuity. "
            "Every session from 1 to requested count must have at least one item. "
            "If source content is insufficient, create short exercise items to fill empty sessions. "
            "Never leave a session empty."
        )
    user_prompt = (
        f"{task_rules}\n"
        f"Unit title: {title}\n"
        f"Unit type: {unit_type.value}\n\n"
        f"Requested session count: {int(session_count) if session_count is not None else 'not provided'}\n"
        f"{session_rule}\n\n"
        "Prefer this extracted structural outline when it matches the PDF. Ignore teacher names, class/year headers, cover metadata, and page furniture.\n"
        f"{_render_outline_hint_block(outline_hint_lines)}\n\n"
        "Source text (may include OCR noise):\n"
        f"{source_text.strip() if source_text.strip() else '(empty)'}"
    )
    payload = {
        "model": app_config.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {app_config.OPENAI_API_KEY}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=app_config.OPENAI_TIMEOUT_SECONDS) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return None, None, "openai_request_failed"

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "\n".join(str(chunk.get("text", "")) for chunk in content if isinstance(chunk, dict))
    parsed = _json_object_from_text(content)
    if not isinstance(parsed, dict):
        return None, data if isinstance(data, dict) else None, "openai_invalid_json"
    items = parsed.get("items")
    if not isinstance(items, list):
        return None, data if isinstance(data, dict) else None, "openai_missing_items"
    sanitized = _sanitize_items(items)
    if not sanitized:
        return None, data if isinstance(data, dict) else None, "openai_empty_items"
    return sanitized, data if isinstance(data, dict) else None, None


def _openai_generate_session_writeup(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    session_number: int | None,
    checked_item_ids: list[int],
    checked_item_titles: list[str],
    note_text: str,
    source_text: str,
) -> dict[str, Any] | None:
    if not app_config.OPENAI_API_KEY:
        return None

    checked_titles = [str(value or "").strip() for value in checked_item_titles if str(value or "").strip()]
    system_prompt = (
        "You are an expert French-speaking middle-school mathematics teacher. "
        "Write a concise but well-structured classroom session summary from checklist items that were actually completed. "
        "Return STRICT JSON only with exactly these keys: title, learning_focus, teaching_content, practice_items. "
        "Rules: "
        "1) Use only the checked checklist items and teacher note; do not invent unrelated topics. "
        "2) learning_focus must be a list of short bullet-style statements. "
        "3) teaching_content must be a list of 1 to 4 well-written teaching paragraphs in French. "
        "4) practice_items must be a list of exercises, reinforcement tasks, or applications. "
        "5) If there is little content, produce an exercise/reinforcement session instead of leaving sections empty. "
        "6) Keep the sequencing coherent for a textbook-style export."
    )
    user_prompt = (
        f"Unite: {unit_title or 'unite en cours'}\n"
        f"Type d'unite: {unit_type.value if unit_type is not None else 'chapter'}\n"
        f"Numero de seance: {int(session_number) if session_number and session_number > 0 else 'non precise'}\n"
        f"Points coches: {json.dumps(checked_titles, ensure_ascii=False)}\n"
        f"Note enseignant: {note_text.strip() if note_text.strip() else '(aucune)'}\n"
        "Source de reference:\n"
        f"{source_text.strip() if source_text.strip() else '(aucun texte source)'}"
    )
    payload = {
        "model": app_config.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {app_config.OPENAI_API_KEY}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=app_config.OPENAI_TIMEOUT_SECONDS) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return None

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "\n".join(str(chunk.get("text", "")) for chunk in content if isinstance(chunk, dict))
    parsed = _json_object_from_text(content)
    if not isinstance(parsed, dict):
        return None

    normalized = _normalize_writeup_payload(
        title=str(parsed.get("title") or "").strip(),
        learning_focus=parsed.get("learning_focus"),
        teaching_content=parsed.get("teaching_content"),
        practice_items=parsed.get("practice_items"),
        unit_title=unit_title,
        session_number=session_number,
        checked_item_ids=checked_item_ids,
        checked_item_titles=checked_item_titles,
        note_text=note_text,
        provider="openai",
        model=app_config.OPENAI_MODEL,
        raw_provider_response=data if isinstance(data, dict) else None,
        error_message=None,
    )
    return normalized


def _fallback_session_writeup_package(
    *,
    unit_title: str,
    unit_type: WorkflowUnitType | None,
    session_number: int | None,
    checked_item_ids: list[int],
    checked_item_titles: list[str],
    note_text: str,
    source_text: str,
) -> dict[str, Any]:
    _ = unit_type
    _ = source_text
    focus_items = _normalize_focus_items(checked_item_titles)
    if not focus_items:
        focus_items = ["Consolidation guidee des acquis par des exercices de renforcement."]

    practice_items = _derive_practice_items(checked_item_titles)
    if not practice_items:
        practice_items = ["Exercices d'application et de revision en lien avec les notions travaillees."]

    title_anchor = _short_heading_from_focus(focus_items[0] if focus_items else (unit_title or "Seance"))
    title = f"Seance {int(session_number)} - {title_anchor}" if session_number and session_number > 0 else title_anchor
    teaching_content = _build_teaching_content(
        focus_items=focus_items,
        unit_title=unit_title,
        note_text=note_text,
    )
    return _normalize_writeup_payload(
        title=title,
        learning_focus=focus_items,
        teaching_content=teaching_content,
        practice_items=practice_items,
        unit_title=unit_title,
        session_number=session_number,
        checked_item_ids=checked_item_ids,
        checked_item_titles=checked_item_titles,
        note_text=note_text,
        provider="fallback",
        model=None,
        raw_provider_response=None,
        error_message=None,
    )


def _merge_writeup_with_fallback(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback)
    merged.update({key: value for key, value in primary.items() if value not in (None, [], "", {})})
    for key in ("learning_focus", "teaching_content", "practice_items"):
        if not merged.get(key):
            merged[key] = list(fallback.get(key) or [])
    if not merged.get("title"):
        merged["title"] = fallback.get("title")
    if not merged.get("provider"):
        merged["provider"] = fallback.get("provider", "fallback")
    if "requested_provider" not in merged:
        merged["requested_provider"] = primary.get("requested_provider") or fallback.get("requested_provider")
    if "error_message" not in merged:
        merged["error_message"] = primary.get("error_message")
    return merged


def _normalize_writeup_payload(
    *,
    title: str,
    learning_focus: Any,
    teaching_content: Any,
    practice_items: Any,
    unit_title: str,
    session_number: int | None,
    checked_item_ids: list[int],
    checked_item_titles: list[str],
    note_text: str,
    provider: str,
    model: str | None,
    raw_provider_response: dict[str, Any] | None,
    error_message: str | None,
) -> dict[str, Any]:
    normalized_focus = _normalize_sentence_list(learning_focus, limit=8)
    if not normalized_focus:
        normalized_focus = _normalize_focus_items(checked_item_titles)
    if not normalized_focus:
        normalized_focus = ["Consolidation guidee des acquis par des exercices de renforcement."]

    normalized_content = _normalize_sentence_list(teaching_content, limit=4)
    if not normalized_content:
        normalized_content = _build_teaching_content(
            focus_items=normalized_focus,
            unit_title=unit_title,
            note_text=note_text,
        )

    normalized_practice = _normalize_sentence_list(practice_items, limit=6)
    if not normalized_practice:
        normalized_practice = _derive_practice_items(checked_item_titles)
    if not normalized_practice:
        normalized_practice = ["Exercices d'application et de revision en lien avec les notions travaillees."]

    title_anchor = _short_heading_from_focus(normalized_focus[0] if normalized_focus else (unit_title or "Seance"))
    normalized_title = str(title or "").strip()
    if not normalized_title:
        normalized_title = f"Seance {int(session_number)} - {title_anchor}" if session_number and session_number > 0 else title_anchor

    return {
        "provider": str(provider or "fallback").strip() or "fallback",
        "model": model,
        "status": "ready",
        "title": normalized_title[:255],
        "checked_item_ids": [int(value) for value in checked_item_ids],
        "checked_item_titles": [str(value or "").strip() for value in checked_item_titles if str(value or "").strip()],
        "learning_focus": normalized_focus,
        "teaching_content": normalized_content,
        "practice_items": normalized_practice,
        "teacher_note_snapshot": str(note_text or "").strip() or None,
        "raw_provider_response": raw_provider_response,
        "error_message": error_message,
    }


def _postprocess_checklist_items(
    items: list[dict[str, Any]],
    *,
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> list[dict[str, Any]]:
    normalized = _normalize_checklist_nodes(
        items,
        unit_type=unit_type,
        unit_title=unit_title,
        ancestor_titles=[unit_title],
    )
    return _collapse_redundant_root(normalized, unit_title=unit_title)


def _normalize_checklist_nodes(
    items: list[dict[str, Any]],
    *,
    unit_type: WorkflowUnitType,
    unit_title: str,
    ancestor_titles: list[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_title = _normalize_outline_title(item.get("title"))
        if not raw_title:
            continue
        raw_kind = str(item.get("kind", WorkflowChecklistItemKind.OTHER.value)).strip().lower()
        kind_values = {kind.value for kind in WorkflowChecklistItemKind}
        kind = WorkflowChecklistItemKind(raw_kind if raw_kind in kind_values else WorkflowChecklistItemKind.OTHER.value)
        kind = _infer_kind_from_text(raw_title, default=kind)
        session_number = _normalize_session_number(item.get("session_number"))
        children_raw = item.get("children") if isinstance(item.get("children"), list) else []
        children = _normalize_checklist_nodes(
            children_raw,
            unit_type=unit_type,
            unit_title=unit_title,
            ancestor_titles=[*ancestor_titles, raw_title],
        )

        if children:
            node_title = _compact_outline_segment(raw_title, default_kind=kind, ancestor_titles=ancestor_titles)
            if not node_title:
                output.extend(children)
                continue
            node = {"title": node_title, "kind": kind.value, "children": children}
            if session_number is not None:
                node["session_number"] = session_number
            output.append(node)
            continue

        verbose_nodes = _explode_verbose_leaf(
            raw_title,
            default_kind=kind,
            session_number=session_number,
            ancestor_titles=ancestor_titles,
        )
        if verbose_nodes:
            output.extend(verbose_nodes)
            continue

        compact_title = _compact_outline_segment(raw_title, default_kind=kind, ancestor_titles=ancestor_titles)
        if not compact_title:
            continue
        node = {"title": compact_title, "kind": kind.value, "children": []}
        if session_number is not None:
            node["session_number"] = session_number
        output.append(node)

    return _dedupe_sibling_nodes(output)


def _collapse_redundant_root(items: list[dict[str, Any]], *, unit_title: str) -> list[dict[str, Any]]:
    current = list(items)
    while len(current) == 1:
        root = current[0]
        children = root.get("children")
        if not isinstance(children, list) or not children:
            break
        title = str(root.get("title") or "").strip()
        kind = str(root.get("kind") or "").strip().lower()
        if _looks_like_slug_title(title) or _titles_equivalent(title, unit_title):
            if _looks_like_slug_title(unit_title) and _titles_equivalent(title, unit_title):
                current = children
                continue
            if kind != WorkflowChecklistItemKind.CHAPTER.value or _looks_like_slug_title(title):
                current = children
                continue
        if len(title) > 110:
            current = children
            continue
        break
    return current


def _explode_verbose_leaf(
    raw_title: str,
    *,
    default_kind: WorkflowChecklistItemKind,
    session_number: int | None,
    ancestor_titles: list[str],
) -> list[dict[str, Any]]:
    segments = _split_verbose_outline_segments(raw_title)
    if len(segments) <= 1 and not _is_verbose_outline(raw_title):
        return []

    output: list[dict[str, Any]] = []
    for segment in segments:
        compact_title = _compact_outline_segment(segment, default_kind=default_kind, ancestor_titles=ancestor_titles)
        if not compact_title:
            continue
        kind = _infer_kind_from_text(segment, default=default_kind)
        node: dict[str, Any] = {"title": compact_title, "kind": kind.value, "children": []}
        if session_number is not None:
            node["session_number"] = session_number
        output.append(node)
    return _dedupe_sibling_nodes(output)


def _split_verbose_outline_segments(text: str) -> list[str]:
    normalized = _normalize_outline_title(text)
    if not normalized:
        return []
    working = re.sub(r"\b(Chapitre|Chapter|Section|Lesson)(\d+)\b", r"\1 \2", normalized, flags=re.IGNORECASE)
    pieces = [working]
    for splitter in (CHECKLIST_KEYWORD_SPLIT_PATTERN, INLINE_ENUMERATION_SPLIT_PATTERN):
        next_pieces: list[str] = []
        for piece in pieces:
            split_rows = [part.strip(" ;,-") for part in splitter.split(piece) if part and part.strip(" ;,-")]
            next_pieces.extend(split_rows or [piece])
        pieces = next_pieces
    output: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if len(piece) > 160 and ":" in piece:
            left, right = piece.split(":", 1)
            left = left.strip()
            right = right.strip()
            if left:
                output.append(left)
            if right:
                output.append(right)
            continue
        output.append(piece)
    return _coalesce_verbose_segments([row for row in output if row])


def _coalesce_verbose_segments(segments: list[str]) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(segments):
        current = str(segments[index] or "").strip()
        if not current:
            index += 1
            continue
        next_value = str(segments[index + 1] or "").strip() if index + 1 < len(segments) else ""
        if current.lower() in {"chapitre", "chapter", "section", "lesson"} and next_value:
            output.append(f"{current} {next_value}".strip())
            index += 2
            continue
        if re.fullmatch(r"\d+\s*[:.]?", current) and next_value:
            output.append(f"{current} {next_value}".strip())
            index += 2
            continue
        output.append(current)
        index += 1
    return output


def _compact_outline_segment(
    text: str,
    *,
    default_kind: WorkflowChecklistItemKind,
    ancestor_titles: list[str],
) -> str:
    value = _normalize_outline_title(text)
    if not value:
        return ""
    match = NUMBERED_HEADING_PATTERN.match(value)
    if match:
        number = match.group(1)
        remainder = _trim_section_heading_phrase(match.group(2))
        remainder_kind = _infer_kind_from_text(match.group(2), default=default_kind)
        if remainder and remainder_kind not in {
            WorkflowChecklistItemKind.SECTION,
            WorkflowChecklistItemKind.SUBSECTION,
            WorkflowChecklistItemKind.CHAPTER,
        } and not _is_generic_kind_label(remainder, remainder_kind):
            keyword_heading = _keyword_heading(match.group(2), kind=remainder_kind, ancestor_titles=ancestor_titles)
            if keyword_heading:
                return keyword_heading
        if remainder:
            return f"{number}) {remainder}"
    chapter_match = re.match(
        r"^\s*(chapitre|chapter)\s*(\d+)?\s*[:.-]?\s*([^.]{3,120}?)(?=(?:\b(?:definition|définition|exemples?|remarques?|applications?|exercices?)\b|$))",
        value,
        re.IGNORECASE,
    )
    if chapter_match:
        label = chapter_match.group(1).capitalize()
        number = str(chapter_match.group(2) or "").strip()
        topic = _trim_heading_phrase(chapter_match.group(3))
        prefix = f"{label} {number}".strip()
        return f"{prefix}: {topic}" if topic else prefix

    kind = _infer_kind_from_text(value, default=default_kind)
    keyword_heading = _keyword_heading(value, kind=kind, ancestor_titles=ancestor_titles)
    if keyword_heading:
        return keyword_heading

    if ":" in value:
        left = _trim_heading_phrase(value.split(":", 1)[0])
        if 2 <= len(left.split()) <= 10 and len(left) <= 90:
            return left

    summary = _trim_heading_phrase(value)
    return summary[:120].rstrip(" -,:;")


def _keyword_heading(text: str, *, kind: WorkflowChecklistItemKind, ancestor_titles: list[str]) -> str:
    lowered = _fold_text_key(text)
    topic_hint = _derive_topic_hint([*ancestor_titles, text])
    label = _keyword_title_label(text, kind=kind)
    if _is_generic_kind_label(text, kind):
        return label
    explicit_tail = ""
    for separator in (":", " - ", "-"):
        if separator in str(text or ""):
            explicit_tail = _trim_heading_phrase(str(text).split(separator, 1)[1])
            break
    if explicit_tail and not _is_metadata_noise_line(explicit_tail):
        return f"{label} - {explicit_tail}" if label else explicit_tail
    if kind == WorkflowChecklistItemKind.DEFINITION:
        return f"{label} - {topic_hint}" if topic_hint else label
    if kind == WorkflowChecklistItemKind.PROPERTY:
        return f"{label} - {topic_hint}" if topic_hint else label
    if kind == WorkflowChecklistItemKind.EXAMPLE:
        return f"{label} - {topic_hint}" if topic_hint else label
    if kind == WorkflowChecklistItemKind.EXERCISE:
        return f"{label} - {topic_hint}" if topic_hint else label
    return ""


def _keyword_title_label(text: str, *, kind: WorkflowChecklistItemKind) -> str:
    lowered = _fold_text_key(text)
    if kind == WorkflowChecklistItemKind.DEFINITION:
        return "Definition"
    if kind == WorkflowChecklistItemKind.PROPERTY:
        if lowered.startswith("remarque") or lowered.startswith("remarques"):
            return "Remarques"
        if lowered.startswith("regle") or lowered.startswith("regles"):
            return "Regle"
        if lowered.startswith("methode"):
            return "Methode"
        if lowered.startswith("theoreme"):
            return "Theoreme"
        return "Propriete"
    if kind == WorkflowChecklistItemKind.EXAMPLE:
        return "Exemples"
    if kind == WorkflowChecklistItemKind.EXERCISE:
        if "application" in lowered or "applications" in lowered:
            return "Applications"
        return "Exercices"
    if kind == WorkflowChecklistItemKind.OTHER:
        return "Activite"
    return ""


def _is_generic_kind_label(text: str, kind: WorkflowChecklistItemKind) -> bool:
    folded = _fold_text_key(text)
    generic_values: dict[WorkflowChecklistItemKind, tuple[str, ...]] = {
        WorkflowChecklistItemKind.DEFINITION: ("definition",),
        WorkflowChecklistItemKind.PROPERTY: ("propriete", "proprietes", "remarque", "remarques", "regle", "regles", "methode", "theoreme"),
        WorkflowChecklistItemKind.EXAMPLE: ("exemple", "exemples"),
        WorkflowChecklistItemKind.EXERCISE: ("exercice", "exercices", "application", "applications"),
        WorkflowChecklistItemKind.OTHER: ("activite", "activites"),
    }
    if folded in generic_values.get(kind, ()):
        return True
    tokens = folded.replace("'", " ").split()
    if not tokens:
        return False
    first = tokens[0]
    if kind == WorkflowChecklistItemKind.EXERCISE and first in {"exercice", "exercices", "application", "applications"} and len(tokens) <= 3:
        return True
    if kind == WorkflowChecklistItemKind.PROPERTY and first in {"propriete", "proprietes", "remarque", "remarques", "regle", "regles", "methode", "theoreme"} and len(tokens) <= 3:
        return True
    return False


def _derive_topic_hint(values: list[str]) -> str:
    for raw in reversed(values):
        value = _normalize_outline_title(raw)
        if not value:
            continue
        if _looks_like_slug_title(value):
            continue
        lowered = _fold_text_key(value)
        if any(keyword in lowered for keyword, _ in CHECKLIST_KIND_KEYWORDS):
            continue
        value = re.sub(r"^\s*(chapitre|chapter|section|lesson)\s*\d*\s*[:.-]?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"^\d+(?:\.\d+)*\s*[\)\].:-]?\s*", "", value)
        value = _trim_heading_phrase(value)
        if value:
            return value
    return ""


def _trim_heading_phrase(text: str) -> str:
    value = _normalize_outline_title(text)
    if not value:
        return ""
    value = re.sub(r"\b(est|sont|peut|peuvent|exprimer|determine|détermine|noter|note|appelle|appelé|appelée)\b.*$", "", value, flags=re.IGNORECASE).strip(" ;,-:")
    value = re.sub(r"^\d+\s*[\).:]\s*", "", value)
    words = value.split()
    if len(words) > 14:
        value = " ".join(words[:14]).strip(" ;,-:")
    return value[:120]


def _trim_section_heading_phrase(text: str) -> str:
    value = _normalize_outline_title(text)
    if not value:
        return ""
    value = re.sub(r"^\d+\s*[\).:]\s*", "", value)
    words = value.split()
    if len(words) > 18:
        value = " ".join(words[:18]).strip(" ;,-:")
    return value[:120].strip(" ;,-:")


def _normalize_outline_title(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"\s*\[\d+(?:\s*[,/-]\s*\d+)*\]\s*$", "", text)
    if _looks_like_slug_title(text):
        text = text.replace("-", " ")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(Chapitre|Chapter|Section|Lesson)(\d+)\b", r"\1 \2", text, flags=re.IGNORECASE)
    text = re.sub(r"\b([A-Za-zÀ-ÿ]+)(\d+)\s*:", r"\1 \2:", text)
    text = re.sub(r"(?i)^\s*\d+\s*(chapitre|chapter)\b", r"\1", text)
    text = re.sub(r"(?<=[A-Za-zÀ-ÿ\)])(\d{1,3})\s*$", "", text).strip()
    return text.strip(" \t\r\n;,-")


def _looks_like_slug_title(text: str) -> bool:
    value = str(text or "").strip()
    return bool(value and SLUG_LIKE_TITLE_PATTERN.match(value))


def _titles_equivalent(left: str, right: str) -> bool:
    return _title_key(left) == _title_key(right)


def _title_key(value: str) -> str:
    text = _fold_text_key(_normalize_outline_title(value))
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _infer_kind_from_text(text: str, *, default: WorkflowChecklistItemKind) -> WorkflowChecklistItemKind:
    lowered = _fold_text_key(text)
    if not lowered:
        return default
    if re.match(r"^\s*(chapter|chapitre)\b", lowered):
        return WorkflowChecklistItemKind.CHAPTER
    match = NUMBERED_HEADING_PATTERN.match(str(text or "").strip())
    if match:
        remainder = str(match.group(2) or "").strip()
        remainder_folded = _fold_text_key(remainder)
        for keyword, kind in CHECKLIST_KIND_KEYWORDS:
            if remainder_folded.startswith(_fold_text_key(keyword)):
                return kind
        depth = max(0, match.group(1).count("."))
        if depth <= 1:
            return WorkflowChecklistItemKind.SECTION
        return WorkflowChecklistItemKind.SUBSECTION
    for keyword, kind in CHECKLIST_KIND_KEYWORDS:
        if keyword in lowered:
            return kind
    return default


def _is_verbose_outline(text: str) -> bool:
    value = _normalize_outline_title(text)
    if not value:
        return False
    if len(value) > 120:
        return True
    if len(re.findall(r"\b(?:definition|définition|propriete|propriété|exemple|exemples|remarque|remarques|application|applications|exercice|exercices)\b", value, flags=re.IGNORECASE)) >= 2:
        return True
    if len(re.findall(r"\d+\s*[\).:]", value)) >= 2:
        return True
    sentence_count = len(re.findall(r"[.;!?]", value))
    return sentence_count >= 2


def _dedupe_sibling_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        title = str(item.get("title") or "").strip()
        kind = str(item.get("kind") or "").strip().lower()
        if not title:
            continue
        key = (_title_key(title), kind)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _sanitize_items(items: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        raw_kind = str(item.get("kind", WorkflowChecklistItemKind.OTHER.value)).strip().lower()
        allowed = {kind.value for kind in WorkflowChecklistItemKind}
        kind = raw_kind if raw_kind in allowed else WorkflowChecklistItemKind.OTHER.value
        children_raw = item.get("children")
        children = _sanitize_items(children_raw if isinstance(children_raw, list) else [])
        session_number = _normalize_session_number(item.get("session_number"))
        node: dict[str, Any] = {"title": title, "kind": kind, "children": children}
        if session_number is not None:
            node["session_number"] = session_number
        output.append(node)
    return output


def _normalize_session_number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(value)
    except Exception:
        return None
    if normalized <= 0:
        return None
    return normalized


def _apply_session_numbers(items: list[dict[str, Any]], session_count: int | None) -> list[dict[str, Any]]:
    normalized_session_count = max(0, int(session_count or 0))
    if normalized_session_count <= 0:
        return items
    leaves = _collect_leaf_nodes(items)
    if not leaves:
        return items
    assigned = 0
    for node in leaves:
        value = _normalize_session_number(node.get("session_number"))
        if value is not None:
            node["session_number"] = min(normalized_session_count, value)
            assigned += 1
    if assigned == len(leaves):
        return items
    for index, node in enumerate(leaves):
        if _normalize_session_number(node.get("session_number")) is not None:
            continue
        bucket = min(normalized_session_count, max(1, int((index * normalized_session_count) / len(leaves)) + 1))
        node["session_number"] = bucket
    return items


def _ensure_session_coverage_with_exercises(items: list[dict[str, Any]], session_count: int | None) -> list[dict[str, Any]]:
    normalized_session_count = max(0, int(session_count or 0))
    if normalized_session_count <= 0:
        return items

    leaves = _collect_leaf_nodes(items)
    by_session: dict[int, int] = {idx: 0 for idx in range(1, normalized_session_count + 1)}
    for node in leaves:
        bucket = _normalize_session_number(node.get("session_number"))
        if bucket is None:
            continue
        normalized_bucket = min(normalized_session_count, bucket)
        node["session_number"] = normalized_bucket
        by_session[normalized_bucket] += 1

    missing_sessions = [idx for idx in range(1, normalized_session_count + 1) if int(by_session.get(idx, 0)) <= 0]
    for session_number in missing_sessions:
        items.append(
            {
                "title": f"Practice exercise - Session {session_number}",
                "kind": WorkflowChecklistItemKind.EXERCISE.value,
                "children": [],
                "session_number": session_number,
            }
        )
    return items


def _collect_leaf_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []
    visited_lists: set[int] = set()

    def walk(nodes: list[dict[str, Any]]) -> None:
        list_id = id(nodes)
        if list_id in visited_lists:
            return
        visited_lists.add(list_id)
        for node in nodes:
            children = node.get("children")
            if isinstance(children, list) and children:
                walk(children)
                continue
            leaves.append(node)

    walk(items)
    return leaves


def _flatten_checklist_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        output.append(item)
        children = item.get("children") if isinstance(item.get("children"), list) else []
        output.extend(_flatten_checklist_nodes(children))
    return output


def _score_checklist_quality(
    items: list[dict[str, Any]] | None,
    *,
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> int:
    flat = _flatten_checklist_nodes(items or [])
    if not flat:
        return -100

    score = min(16, len(flat) * 2)
    roots = [row for row in (items or []) if isinstance(row, dict)]
    if unit_type == WorkflowUnitType.CHAPTER and roots:
        first_kind = str(roots[0].get("kind") or "").strip().lower()
        if first_kind == WorkflowChecklistItemKind.CHAPTER.value:
            score += 6
    for node in flat:
        title = _normalize_outline_title(node.get("title"))
        kind = str(node.get("kind") or "").strip().lower()
        folded = _fold_text_key(title)
        if not title:
            score -= 5
            continue
        if kind in {
            WorkflowChecklistItemKind.SECTION.value,
            WorkflowChecklistItemKind.SUBSECTION.value,
            WorkflowChecklistItemKind.PROPERTY.value,
            WorkflowChecklistItemKind.DEFINITION.value,
            WorkflowChecklistItemKind.EXAMPLE.value,
            WorkflowChecklistItemKind.EXERCISE.value,
        }:
            score += 2
        if len(title) > 95:
            score -= 4
        if _looks_like_slug_title(title):
            score -= 5
        if _is_metadata_noise_line(title):
            score -= 6
        if _is_teacher_meta_outline_title(title):
            score -= 9
        if len(re.findall(r"[.;!?]", title)) >= 2:
            score -= 3
        if folded.startswith(("examples - mathematique", "exemples - mathematique", "exercices - seance", "examples - seance")):
            score -= 6
        if _title_key(title) == _title_key(unit_title):
            score -= 2
    return score


def _score_checklist_candidate(
    items: list[dict[str, Any]] | None,
    *,
    reference_outline: list[dict[str, Any]],
    unit_type: WorkflowUnitType,
    unit_title: str,
) -> int:
    score = _score_checklist_quality(items, unit_type=unit_type, unit_title=unit_title)
    score += _score_reference_coverage(items, reference_outline)
    return score


def _score_reference_coverage(
    items: list[dict[str, Any]] | None,
    reference_outline: list[dict[str, Any]] | None,
) -> int:
    candidate_titles = _outline_reference_titles(items or [])
    reference_titles = _outline_reference_titles(reference_outline or [])
    if not candidate_titles or not reference_titles:
        return 0
    score = 0
    for reference in reference_titles:
        if any(_semantic_titles_match(reference, candidate) for candidate in candidate_titles):
            score += 3
        else:
            score -= 1
    return score


def _outline_reference_titles(items: list[dict[str, Any]]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for node in _flatten_checklist_nodes(items):
        title = _semantic_title_key(node.get("title"))
        if not title or title in seen:
            continue
        seen.add(title)
        output.append(title)
    return output


def _semantic_title_key(value: Any) -> str:
    text = _fold_text_key(_normalize_outline_title(value))
    text = re.sub(
        r"^(?:chapitre|chapter)\s*\d+\s*[:.-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:definition|propriete|regle|remarques?|methode|theoreme|exemples?|exercices?|applications?|activite)\s*[-:]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^\d+(?:\.\d+)*\s*[)\].:/-]?\s*", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


def _semantic_titles_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 6:
        return False
    return shorter in longer


def _fallback_generate_checklist(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
) -> list[dict[str, Any]]:
    lines = _extract_structural_source_lines(source_text)
    if unit_type == WorkflowUnitType.EXERCISE_SERIES:
        exercises = []
        for line in lines:
            low = _fold_text_key(line)
            if "exercise" in low or "exercice" in low or low.startswith("ex "):
                exercises.append(line)
        if not exercises:
            exercises = [f"Exercise {idx}" for idx in range(1, 6)]
        return [{"title": item, "kind": WorkflowChecklistItemKind.EXERCISE.value, "children": []} for item in exercises[:80]]

    root_title = _normalize_outline_title(title) or "Chapter"
    root_node: dict[str, Any] = {
        "title": root_title,
        "kind": WorkflowChecklistItemKind.CHAPTER.value,
        "children": [],
    }
    stack: list[tuple[int, dict[str, Any]]] = [(0, root_node)]
    current_topic_depth = 0

    def append_node(depth: int, node: dict[str, Any]) -> None:
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1] if stack else root_node
        parent["children"].append(node)
        stack.append((depth, node))

    for line in lines:
        if CHAPTER_START_PATTERN.match(line):
            chapter_title = _compact_outline_segment(
                line,
                default_kind=WorkflowChecklistItemKind.CHAPTER,
                ancestor_titles=[title],
            )
            if chapter_title:
                root_node["title"] = chapter_title
            continue

        section_depth = _numbered_heading_depth(line)
        if section_depth is not None:
            kind = _infer_kind_from_text(line, default=WorkflowChecklistItemKind.SECTION)
            node_title, section_children = _split_numbered_heading_children(
                line,
                default_kind=kind,
                root_title=str(root_node["title"]),
            )
            if not node_title or _is_trivial_outline_fragment(node_title):
                continue
            node = {"title": node_title, "kind": kind.value, "children": section_children}
            append_node(section_depth, node)
            current_topic_depth = section_depth
            continue

        keyword_kind = _keyword_kind_from_line(line)
        if keyword_kind is not None:
            node_title = _normalize_keyword_outline_title(
                line,
                kind=keyword_kind,
                current_topic_title=str(stack[-1][1].get("title") or root_node["title"]),
            )
            if not node_title:
                continue
            append_node(max(1, current_topic_depth + 1), {"title": node_title, "kind": keyword_kind.value, "children": []})
            continue

        if current_topic_depth > 0 and _looks_like_rule_continuation(line):
            node_title = _normalize_rule_outline_title(
                line,
                current_topic_title=str(stack[-1][1].get("title") or root_node["title"]),
            )
            if node_title:
                append_node(
                    max(1, current_topic_depth + 1),
                    {"title": node_title, "kind": WorkflowChecklistItemKind.PROPERTY.value, "children": []},
                )

    if not root_node["children"]:
        return [{"title": root_title, "kind": WorkflowChecklistItemKind.CHAPTER.value, "children": []}]
    return [root_node]


def _extract_pdf_heading_candidate_lines(source: Path, *, unit_type: WorkflowUnitType) -> list[str]:
    rows = _extract_pdf_layout_rows(source)
    if not rows:
        return []
    heading_rows = _select_pdf_heading_rows(rows, unit_type=unit_type)
    output: list[str] = []
    seen: set[str] = set()
    for row in heading_rows:
        text = _normalize_outline_title(row.get("text"))
        if not text or _is_metadata_noise_line(text):
            continue
        key = _semantic_title_key(text) or _title_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _extract_pdf_layout_rows(source: Path) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []

    try:
        reader = PdfReader(str(source))
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for page_index, page in enumerate(reader.pages):
        fragments: list[dict[str, Any]] = []

        def visitor(text, cm, tm, font_dict, font_size):
            value = str(text or "")
            if not value.strip():
                return
            fragments.append(
                {
                    "page": page_index + 1,
                    "x": float(tm[4]),
                    "y": round(float(tm[5]), 2),
                    "size": float(font_size or 0.0),
                    "font": str((font_dict or {}).get("/BaseFont") or ""),
                    "text": value,
                }
            )

        try:
            page.extract_text(visitor_text=visitor)
        except Exception:
            continue
        if not fragments:
            continue

        fragments = sorted(fragments, key=lambda row: (-row["y"], row["x"]))
        line_buckets: list[dict[str, Any]] = []
        for fragment in fragments:
            if not line_buckets or abs(float(line_buckets[-1]["y"]) - float(fragment["y"])) > PDF_LAYOUT_LINE_GAP:
                line_buckets.append({"page": fragment["page"], "y": fragment["y"], "parts": []})
            line_buckets[-1]["parts"].append(fragment)

        for bucket in line_buckets:
            parts = sorted(bucket["parts"], key=lambda row: float(row["x"]))
            text = re.sub(r"\s+", " ", "".join(str(part["text"]) for part in parts)).strip()
            if not text:
                continue
            sizes = [float(part["size"]) for part in parts if float(part["size"]) > 0]
            fonts = [str(part["font"]) for part in parts]
            rows.append(
                {
                    "page": int(bucket["page"]),
                    "y": float(bucket["y"]),
                    "x": min(float(part["x"]) for part in parts),
                    "text": text,
                    "max_size": max(sizes) if sizes else 0.0,
                    "avg_size": sum(sizes) / len(sizes) if sizes else 0.0,
                    "bold": any("bold" in font.lower() for font in fonts),
                }
            )
    return rows


def _select_pdf_heading_rows(rows: list[dict[str, Any]], *, unit_type: WorkflowUnitType) -> list[dict[str, Any]]:
    sizes = [float(row.get("max_size") or 0.0) for row in rows if float(row.get("max_size") or 0.0) > 0]
    baseline_size = median(sizes) if sizes else 0.0
    selected: list[dict[str, Any]] = []
    for row in rows:
        text = _normalize_outline_title(row.get("text"))
        if not text or _is_trivial_outline_fragment(text):
            continue
        if _is_metadata_noise_line(text):
            continue
        if _looks_like_body_sentence(text):
            continue
        size = float(row.get("max_size") or row.get("avg_size") or 0.0)
        bold = bool(row.get("bold"))
        short = len(text) <= PDF_LAYOUT_HEADING_MAX_CHARS and len(text.split()) <= PDF_LAYOUT_HEADING_WORD_LIMIT
        numbered = _line_has_structural_marker(text)
        keyword = _keyword_kind_from_line(text) is not None
        prominent = size >= baseline_size + PDF_LAYOUT_MIN_SIZE_DELTA
        uppercase_title = _looks_like_uppercase_title(text)
        if text[:1].islower() and not numbered and not keyword and not (prominent and len(text.split()) <= 4):
            continue
        if unit_type == WorkflowUnitType.EXERCISE_SERIES:
            include = short and (keyword or numbered or prominent or uppercase_title or bold)
        else:
            include = short and (numbered or keyword or prominent or uppercase_title or bold)
        if include:
            selected.append({**row, "text": text})
    return _merge_pdf_heading_rows(selected)


def _merge_pdf_heading_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    index = 0
    while index < len(rows):
        current = dict(rows[index])
        text = str(current.get("text") or "").strip()
        if not text:
            index += 1
            continue
        if CHAPTER_START_PATTERN.match(text) or _looks_like_uppercase_title(text):
            parts = [text]
            next_index = index + 1
            while next_index < len(rows):
                next_row = rows[next_index]
                next_text = str(next_row.get("text") or "").strip()
                if not next_text:
                    next_index += 1
                    continue
                if _line_has_structural_marker(next_text) or _keyword_kind_from_line(next_text) is not None:
                    break
                if int(next_row.get("page") or 0) != int(current.get("page") or 0):
                    break
                if abs(float(next_row.get("x") or 0.0) - float(current.get("x") or 0.0)) > 14:
                    break
                if float(next_row.get("max_size") or 0.0) + 0.3 < float(current.get("max_size") or 0.0):
                    break
                if len(next_text.split()) > PDF_LAYOUT_HEADING_WORD_LIMIT:
                    break
                parts.append(next_text)
                next_index += 1
            if len(parts) > 1:
                merged_title = " ".join(parts).strip()
                separator = ": " if CHAPTER_START_PATTERN.match(text) else " "
                if CHAPTER_START_PATTERN.match(text):
                    chapter_prefix = parts[0]
                    chapter_body = " ".join(parts[1:]).strip(" -:")
                    merged_title = f"{chapter_prefix}{separator}{chapter_body}".strip()
                current["text"] = merged_title
                output.append(current)
                index = next_index
                continue
        output.append(current)
        index += 1
    return output


def _line_has_structural_marker(text: str) -> bool:
    value = str(text or "").strip()
    return bool(
        value
        and (
            CHAPTER_START_PATTERN.match(value)
            or NUMBERED_HEADING_PATTERN.match(value)
            or ROMAN_HEADING_PATTERN.match(value)
            or ALPHA_HEADING_PATTERN.match(value)
        )
    )


def _looks_like_uppercase_title(text: str) -> bool:
    letters = [char for char in str(text or "") if char.isalpha()]
    if len(letters) < 4:
        return False
    uppercase_ratio = sum(1 for char in letters if char.isupper()) / max(1, len(letters))
    return uppercase_ratio >= 0.7 and len(str(text or "").split()) <= 10


def _looks_like_body_sentence(text: str) -> bool:
    value = _normalize_outline_title(text)
    if not value:
        return True
    if _line_has_structural_marker(value) or _keyword_kind_from_line(value) is not None:
        return False
    words = value.split()
    if len(words) > PDF_LAYOUT_HEADING_WORD_LIMIT:
        return True
    if len(re.findall(r"[.;!?]", value)) >= 2:
        return True
    folded = _fold_text_key(value)
    body_starters = (
        "a le ",
        "pour ",
        "soit ",
        "parmi ",
        "dans ",
        "on considere ",
        "la somme ",
        "le quotient ",
        "un nombre ",
        "cette ",
    )
    return any(folded.startswith(prefix) for prefix in body_starters)

def _extract_structural_source_lines(source_text: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in _split_rows(source_text):
        line = _normalize_outline_title(raw)
        if not line:
            continue
        if _is_metadata_noise_line(line):
            continue
        if _is_trivial_outline_fragment(line):
            continue
        key = _title_key(line)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(line)
    return output


def _fold_text_key(value: Any) -> str:
    raw = str(value or "")
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    folded = re.sub(r"\s+", " ", folded).strip().lower()
    return folded


def _numbered_heading_depth(text: str) -> int | None:
    match = NUMBERED_HEADING_PATTERN.match(str(text or "").strip())
    if not match:
        return None
    depth = int(match.group(1).count(".")) + 1
    return max(1, depth)


def _keyword_kind_from_line(text: str) -> WorkflowChecklistItemKind | None:
    folded = _fold_text_key(text)
    for prefix, kind in STRUCTURAL_KEYWORD_PREFIXES:
        if folded.startswith(prefix):
            return kind
    return None


def _is_metadata_noise_line(text: str) -> bool:
    folded = _fold_text_key(text)
    if not folded:
        return True
    if re.match(r"^\d+\s*(chapitre|chapter)\b", folded):
        return True
    if NUMBERED_HEADING_PATTERN.match(str(text or "").strip()) or CHAPTER_START_PATTERN.match(str(text or "").strip()):
        return False
    metadata_hits = sum(1 for token in METADATA_NOISE_TERMS if token in folded)
    if metadata_hits >= 2:
        return True
    if folded.startswith(("exemples -", "exercices -", "example -", "exercise -")) and metadata_hits >= 1:
        return True
    if re.sub(r"[^a-z]+", "", folded) == "":
        return True
    return False


def _is_trivial_outline_fragment(text: str) -> bool:
    folded = _fold_text_key(text)
    if len(re.sub(r"[^a-z]+", "", folded)) < 3:
        return True
    if len(folded) <= 3:
        return True
    if re.fullmatch(r"\d+\s*[/.-]?\s*\d*", folded):
        return True
    return False


def _looks_like_rule_continuation(text: str) -> bool:
    folded = _fold_text_key(text)
    if any(folded.startswith(prefix) for prefix in RULE_CONTINUATION_PREFIXES):
        return True
    if ":" in str(text or "") and len(str(text or "").split()) <= 16:
        return True
    return False


def _normalize_keyword_outline_title(
    text: str,
    *,
    kind: WorkflowChecklistItemKind,
    current_topic_title: str,
) -> str:
    raw = _normalize_outline_title(text)
    if not raw:
        return ""
    exercise_match = re.match(r"^\s*(exercice|exercise|application)\s*(\d+)\b", raw, re.IGNORECASE)
    if kind == WorkflowChecklistItemKind.EXERCISE and exercise_match:
        label = "Applications" if _fold_text_key(exercise_match.group(1)).startswith("application") else "Exercice"
        return f"{label} {exercise_match.group(2)}"
    if kind == WorkflowChecklistItemKind.OTHER and _fold_text_key(raw).startswith("activite"):
        return _compact_outline_segment(raw, default_kind=WorkflowChecklistItemKind.SECTION, ancestor_titles=[current_topic_title])
    label = _keyword_title_label(raw, kind=kind)
    if ":" in raw:
        _, remainder = raw.split(":", 1)
    elif " - " in raw:
        _, remainder = raw.split(" - ", 1)
    elif "-" in raw:
        _, remainder = raw.split("-", 1)
    else:
        remainder = raw
    remainder = _trim_heading_phrase(remainder)
    if not remainder or _is_metadata_noise_line(remainder):
        topic_hint = _trim_heading_phrase(current_topic_title)
        remainder = topic_hint
    if not remainder:
        return ""
    return f"{label} - {remainder}"


def _normalize_rule_outline_title(text: str, *, current_topic_title: str) -> str:
    remainder = _trim_heading_phrase(text)
    if not remainder or _is_metadata_noise_line(remainder):
        remainder = _trim_heading_phrase(current_topic_title)
    if not remainder:
        return ""
    return f"Propriete - {remainder}"


def _split_numbered_heading_children(
    text: str,
    *,
    default_kind: WorkflowChecklistItemKind,
    root_title: str,
) -> tuple[str, list[dict[str, Any]]]:
    raw = _normalize_outline_title(text)
    if not raw:
        return "", []
    if ":" not in raw:
        return (
            _compact_outline_segment(raw, default_kind=default_kind, ancestor_titles=[root_title]),
            [],
        )
    left, right = raw.split(":", 1)
    left_title = _compact_outline_segment(left, default_kind=default_kind, ancestor_titles=[root_title])
    right_title = _trim_heading_phrase(right)
    if not left_title:
        left_title = _compact_outline_segment(raw, default_kind=default_kind, ancestor_titles=[root_title])
    if not right_title or _is_metadata_noise_line(right_title):
        return left_title, []
    child = {
        "title": f"Propriete - {right_title}",
        "kind": WorkflowChecklistItemKind.PROPERTY.value,
        "children": [],
    }
    return left_title, [child]


def _json_object_from_text(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = text[start : end + 1]
        try:
            return json.loads(chunk)
        except Exception:
            return None
    return None


def _split_rows(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    output: list[str] = []
    lines = [
        re.sub(r"\s+", " ", segment).strip(" ;,-")
        for segment in re.split(r"[\r\n]+", raw)
        if str(segment or "").strip()
    ]
    for line in lines:
        matches = list(NUMBERED_ROW_START_PATTERN.finditer(line))
        if len(matches) > 1 and int(matches[0].start()) == 0:
            for idx, match in enumerate(matches):
                start = int(match.start())
                end = int(matches[idx + 1].start()) if idx + 1 < len(matches) else len(line)
                chunk = line[start:end].strip(" ;,-")
                if chunk:
                    output.append(chunk)
            continue
        output.append(line)
    deduped: list[str] = []
    seen: set[str] = set()
    for row in output:
        text = str(row or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _normalize_focus_items(checked_titles: list[str]) -> list[str]:
    output: list[str] = []
    for raw in checked_titles:
        rows = _split_rows(raw)
        candidates = rows if rows else [str(raw or "").strip()]
        for candidate in candidates:
            cleaned = _clean_sentence(candidate)
            if cleaned and cleaned not in output:
                output.append(cleaned)
            if len(output) >= 8:
                return output
    return output


def _derive_practice_items(checked_titles: list[str]) -> list[str]:
    output: list[str] = []
    for raw in checked_titles:
        rows = _split_rows(raw)
        candidates = rows if rows else [str(raw or "").strip()]
        for candidate in candidates:
            normalized = str(candidate or "").lower()
            if "exercice" not in normalized and "exercise" not in normalized and "application" not in normalized:
                continue
            cleaned = _clean_sentence(candidate)
            if cleaned and cleaned not in output:
                output.append(cleaned)
            if len(output) >= 6:
                return output
    return output


def _normalize_sentence_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        raw_items = _split_rows(value)
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            if isinstance(item, str):
                rows = _split_rows(item)
                raw_items.extend(rows if rows else [item])
    else:
        raw_items = []

    output: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = _clean_sentence(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output


def _clean_sentence(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^[\-\u2022]+\s*", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*\s*[\)\].:-]?\s*", "", value)
    value = " ".join(value.split()).strip(" ;,-")
    if not value:
        return ""
    value = value[0].upper() + value[1:]
    if value[-1] not in ".!?":
        value = f"{value}."
    return value


def _short_heading_from_focus(text: str) -> str:
    value = _clean_sentence(text).rstrip(".")
    return value or "Contenus de seance"


def _build_teaching_content(*, focus_items: list[str], unit_title: str, note_text: str) -> list[str]:
    anchors = [str(item or "").strip().rstrip(".") for item in focus_items if str(item or "").strip()]
    if note_text:
        return [_clean_sentence(note_text)]
    if len(anchors) >= 2:
        return [
            _clean_sentence(
                f"Cette seance a ete consacree a {anchors[0].lower()} puis a {anchors[1].lower()} dans la progression de l'unite {unit_title or 'en cours'}"
            ),
            "Les apprentissages ont ete consolides par des explications guidees, des exemples progressifs et des exercices d'application."
        ]
    if anchors:
        return [
            _clean_sentence(
                f"Cette seance a developpe {anchors[0].lower()} a travers une demarche guidee et des situations d'application"
            ),
            "La classe a poursuivi la consolidation des acquis par des exercices progressifs et une reprise des notions essentielles."
        ]
    return [
        "Cette seance a ete consacree a la consolidation des acquis precedents par des activites de rappel et des exercices structures."
    ]
