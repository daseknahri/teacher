from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any

import httpx

from .. import config as app_config
from ..models import WorkflowChecklistItemKind, WorkflowUnitType


SUPPORTED_UNIT_PLANNER_PROVIDERS = {"openai", "fallback", "notebooklm"}
SUPPORTED_SESSION_WRITER_PROVIDERS = {"openai", "fallback", "notebooklm"}
NUMBERED_HEADING_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:\s*[-.):]\s*|\s+)(.+)$")
CHAPTER_START_PATTERN = re.compile(r"^\s*(chapter|chapitre|title|titre|lesson|lecon)\b", re.IGNORECASE)
NUMBERED_ROW_START_PATTERN = re.compile(r"(?<!\S)\d+(?:\.\d+)+(?:[)\].:-])?(?:\s+|$)")
SLUG_LIKE_TITLE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$", re.IGNORECASE)
INLINE_ENUMERATION_SPLIT_PATTERN = re.compile(r"(?=(?<!\S)\d+\s*[\).:]\s*)")
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
    ("exemple", WorkflowChecklistItemKind.EXAMPLE),
    ("exemples", WorkflowChecklistItemKind.EXAMPLE),
    ("application", WorkflowChecklistItemKind.EXERCISE),
    ("applications", WorkflowChecklistItemKind.EXERCISE),
    ("exercice", WorkflowChecklistItemKind.EXERCISE),
    ("exercices", WorkflowChecklistItemKind.EXERCISE),
)


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
    raw_provider_response: dict[str, Any] | None = None
    error_message: str | None = None
    actual_provider = requested_provider
    model: str | None = None
    provider_context: dict[str, Any] | None = None

    if requested_provider == "openai":
        items, raw_provider_response, error_message = _openai_generate_checklist(
            unit_type=unit_type,
            title=title,
            source_text=source_text,
            session_count=session_count,
        )
        if items:
            model = app_config.OPENAI_MODEL
    elif requested_provider == "notebooklm":
        items, provider_context, raw_provider_response, error_message = _notebooklm_generate_checklist(
            unit_type=unit_type,
            title=title,
            source_text=source_text,
            session_count=session_count,
            document_path=document_path,
        )
        if items:
            actual_provider = "notebooklm"
            model = "notebooklm-py"

    if not items:
        actual_provider = "fallback"
        fallback_items = _fallback_generate_checklist(unit_type=unit_type, title=title, source_text=source_text)
        items = fallback_items

    items = _postprocess_checklist_items(items, unit_type=unit_type, unit_title=title)
    items = _apply_session_numbers(items, session_count=session_count)
    if unit_type in {WorkflowUnitType.CHAPTER, WorkflowUnitType.EXERCISE_SERIES}:
        items = _ensure_session_coverage_with_exercises(items, session_count=session_count)

    return {
        "source": actual_provider,
        "requested_provider": requested_provider,
        "model": model,
        "status": "ready",
        "items": items,
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


def _notebooklm_generate_checklist(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None,
    document_path: str | None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    try:
        return asyncio.run(
            _notebooklm_generate_checklist_async(
                unit_type=unit_type,
                title=title,
                source_text=source_text,
                session_count=session_count,
                document_path=document_path,
            )
        )
    except Exception as exc:
        return None, None, None, f"notebooklm_runtime_error:{exc.__class__.__name__}"


async def _notebooklm_generate_checklist_async(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None,
    document_path: str | None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    client = await _create_notebooklm_client()
    if client is None:
        return None, None, None, "notebooklm_client_unavailable"

    notebook_id = ""
    notebook_title = f"{app_config.NOTEBOOKLM_NOTEBOOK_PREFIX}{title or 'Unit'}".strip()
    raw_result: dict[str, Any] | None = None
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
            prompt = _build_notebooklm_checklist_prompt(
                unit_type=unit_type,
                title=title,
                source_hint="" if str(document_path or "").strip() else source_text,
                session_count=session_count,
            )
            result = await opened.chat.ask(notebook_id, prompt, source_ids=source_ids or None)
            answer = str(getattr(result, "answer", "") or "").strip()
            parsed = _json_object_from_text(answer)
            raw_result = {
                "notebook_id": notebook_id,
                "source_ids": source_ids,
                "answer": answer,
                "conversation_id": str(getattr(result, "conversation_id", "") or "").strip() or None,
            }
    except Exception as exc:
        provider_context = _build_notebooklm_provider_context(
            notebook_id=notebook_id,
            source_ids=[],
            notebook_title=notebook_title,
        )
        return None, provider_context, raw_result, f"notebooklm_request_failed:{exc.__class__.__name__}"

    if not isinstance(parsed, dict):
        provider_context = _build_notebooklm_provider_context(
            notebook_id=notebook_id,
            source_ids=raw_result.get("source_ids") if isinstance(raw_result, dict) else [],
            notebook_title=notebook_title,
        )
        return None, provider_context, raw_result, "notebooklm_invalid_json"
    items = parsed.get("items")
    if not isinstance(items, list):
        provider_context = _build_notebooklm_provider_context(
            notebook_id=notebook_id,
            source_ids=raw_result.get("source_ids") if isinstance(raw_result, dict) else [],
            notebook_title=notebook_title,
        )
        return None, provider_context, raw_result, "notebooklm_missing_items"

    sanitized = _sanitize_items(items)
    provider_context = _build_notebooklm_provider_context(
        notebook_id=notebook_id,
        source_ids=raw_result.get("source_ids") if isinstance(raw_result, dict) else [],
        notebook_title=notebook_title,
    )
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
        return asyncio.run(
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
            result = await opened.chat.ask(notebook_id, prompt, source_ids=source_ids or None)
            answer = str(getattr(result, "answer", "") or "").strip()
            parsed = _json_object_from_text(answer)
            raw_result = {
                "notebook_id": notebook_id,
                "source_ids": source_ids,
                "answer": answer,
                "conversation_id": str(getattr(result, "conversation_id", "") or "").strip() or None,
            }
            if created_temporary_notebook and notebook_id:
                await opened.notebooks.delete(notebook_id)
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
) -> str:
    task_rules = (
        "Lis cette unite pedagogique et retourne uniquement un JSON strict avec la cle `items`. "
        "Chaque element doit respecter exactement ce schema: "
        "{\"title\":\"...\",\"kind\":\"chapter|section|subsection|property|definition|example|exercise|supervision|correction|other\",\"children\":[...],\"session_number\":1}. "
        "Utilise uniquement ces cles. "
        "Le checklist doit contenir uniquement des titres pedagogiques courts, jamais des paragraphes complets, definitions redigees, exemples developpes ou exercices detailles."
    )
    if unit_type == WorkflowUnitType.EXERCISE_SERIES:
        specialization = (
            " L'unite est une serie d'exercices: cree surtout des elements `exercise`, courts, distincts et ordonnes."
        )
    else:
        specialization = (
            " L'unite est un chapitre: construis une hierarchie claire et concise (chapitre, sections, sous-sections, proprietes, definitions, exemples). "
            "Utilise les vrais titres du document. Si le PDF melange titre et contenu, reduis chaque item a un intitulé bref de type manuel scolaire."
        )
    session_rule = ""
    if session_count is not None and int(session_count) > 0:
        session_rule = (
            f" Attribue a chaque element terminal un `session_number` entre 1 et {int(session_count)}. "
            "Respecte l'ordre du document. Toutes les seances doivent recevoir du contenu. "
            "Si le contenu est trop court, ajoute des exercices de consolidation dans les dernieres seances."
        )
    formatting_rules = (
        " Regles de qualite: "
        "1) chaque `title` doit etre court, idealement moins de 90 caracteres; "
        "2) ne jamais inclure plusieurs notions dans un seul item; "
        "3) si une ligne contient Definition, Exemple, Remarque, Application ou Exercice, separe-les en items differents; "
        "4) preserve strictement l'ordre pedagogique du PDF; "
        "5) ne retourne aucun texte hors JSON."
    )
    source_block = ""
    trimmed_hint = str(source_hint or "").strip()
    if trimmed_hint:
        source_block = f"\nIndice textuel de secours si utile:\n{trimmed_hint}"
    return (
        f"{task_rules}{specialization}{session_rule}{formatting_rules}\n"
        f"Titre de l'unite: {title}\n"
        f"Type: {unit_type.value}\n"
        "Ne retourne aucun texte hors JSON."
        f"{source_block}"
    )


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
        if _looks_like_slug_title(title) or _titles_equivalent(title, unit_title):
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
    return [row for row in output if row]


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
        remainder = _trim_heading_phrase(match.group(2))
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
    lowered = text.lower()
    topic_hint = _derive_topic_hint([*ancestor_titles, text])
    if kind == WorkflowChecklistItemKind.DEFINITION:
        return f"Definition - {topic_hint}" if topic_hint else "Definition"
    if kind == WorkflowChecklistItemKind.PROPERTY:
        return f"Propriete - {topic_hint}" if topic_hint else "Propriete"
    if kind == WorkflowChecklistItemKind.EXAMPLE:
        return f"Exemples - {topic_hint}" if topic_hint else "Exemples"
    if kind == WorkflowChecklistItemKind.EXERCISE:
        if "application" in lowered or "applications" in lowered:
            return f"Applications - {topic_hint}" if topic_hint else "Applications"
        return f"Exercices - {topic_hint}" if topic_hint else "Exercices"
    return ""


def _derive_topic_hint(values: list[str]) -> str:
    for raw in reversed(values):
        value = _normalize_outline_title(raw)
        if not value:
            continue
        if _looks_like_slug_title(value):
            continue
        lowered = value.lower()
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


def _normalize_outline_title(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _looks_like_slug_title(text):
        text = text.replace("-", " ")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(Chapitre|Chapter|Section|Lesson)(\d+)\b", r"\1 \2", text, flags=re.IGNORECASE)
    text = re.sub(r"\b([A-Za-zÀ-ÿ]+)(\d+)\s*:", r"\1 \2:", text)
    return text.strip(" \t\r\n;,-")


def _looks_like_slug_title(text: str) -> bool:
    value = str(text or "").strip()
    return bool(value and SLUG_LIKE_TITLE_PATTERN.match(value))


def _titles_equivalent(left: str, right: str) -> bool:
    return _title_key(left) == _title_key(right)


def _title_key(value: str) -> str:
    text = _normalize_outline_title(value).lower()
    text = re.sub(r"[^a-z0-9à-ÿ]+", "", text)
    return text


def _infer_kind_from_text(text: str, *, default: WorkflowChecklistItemKind) -> WorkflowChecklistItemKind:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return default
    if re.match(r"^\s*(chapter|chapitre)\b", lowered):
        return WorkflowChecklistItemKind.CHAPTER
    match = NUMBERED_HEADING_PATTERN.match(str(text or "").strip())
    if match:
        depth = max(0, match.group(1).count("."))
        if depth <= 0:
            return WorkflowChecklistItemKind.SECTION
        if depth == 1:
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


def _fallback_generate_checklist(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
) -> list[dict[str, Any]]:
    lines = [line.strip() for line in (source_text or "").splitlines() if line.strip()]
    if unit_type == WorkflowUnitType.EXERCISE_SERIES:
        exercises = []
        for line in lines:
            low = line.lower()
            if "exercise" in low or "exercice" in low or "ex " in low:
                exercises.append(line)
        if not exercises:
            exercises = [f"Exercise {idx}" for idx in range(1, 6)]
        return [{"title": item, "kind": WorkflowChecklistItemKind.EXERCISE.value, "children": []} for item in exercises[:80]]

    nodes: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []

    def append_node(depth: int, node: dict[str, Any]) -> None:
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            nodes.append(node)
        stack.append((depth, node))

    chapter_found = False
    for line in lines:
        if CHAPTER_START_PATTERN.match(line):
            node = {"title": line, "kind": WorkflowChecklistItemKind.CHAPTER.value, "children": []}
            append_node(0, node)
            chapter_found = True
            continue
        match = NUMBERED_HEADING_PATTERN.match(line)
        if match:
            number = match.group(1)
            depth = max(0, number.count("."))
            if depth == 0:
                kind = WorkflowChecklistItemKind.SECTION.value
            elif depth == 1:
                kind = WorkflowChecklistItemKind.SUBSECTION.value
            else:
                kind = WorkflowChecklistItemKind.OTHER.value
            node = {"title": line, "kind": kind, "children": []}
            append_node(depth + 1, node)
            continue
        lower = line.lower()
        if "definition" in lower:
            kind = WorkflowChecklistItemKind.DEFINITION.value
        elif "property" in lower or "propriete" in lower:
            kind = WorkflowChecklistItemKind.PROPERTY.value
        elif "example" in lower or "exemple" in lower:
            kind = WorkflowChecklistItemKind.EXAMPLE.value
        else:
            continue
        node = {"title": line, "kind": kind, "children": []}
        append_node(3, node)

    if not nodes:
        default_chapter_title = title.strip() or "Chapter"
        nodes = [{"title": default_chapter_title, "kind": WorkflowChecklistItemKind.CHAPTER.value, "children": []}]
    elif not chapter_found:
        existing_nodes = list(nodes)
        nodes = [
            {
                "title": title.strip() or "Chapter",
                "kind": WorkflowChecklistItemKind.CHAPTER.value,
                "children": existing_nodes,
            }
        ]
    return nodes


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
