from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import httpx

from .. import config as app_config
from ..config import OCR_LANG, OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS
from ..models import WorkflowChecklistItemKind, WorkflowUnitType
from .extraction import resolve_raw_text
from .workflow_generation import generate_unit_checklist_package, notebooklm_provider_ready


NUMBERED_HEADING_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:\s*[-.):]\s*|\s+)(.+)$")
CHAPTER_START_PATTERN = re.compile(r"^\s*(chapter|chapitre|title|titre|lesson|lecon)\b", re.IGNORECASE)
MIN_PDF_TEXT_CHARS = 80
MAX_PDF_OCR_PAGES = 8


def extract_text_from_document(file_path: str, provided_text: str | None = None) -> str:
    if provided_text and provided_text.strip():
        return provided_text.strip()
    source = Path(file_path)
    if not source.exists():
        return ""

    suffix = source.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        return resolve_raw_text(str(source), None)
    if suffix == ".pdf":
        return _extract_pdf_text(source)
    try:
        return source.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def generate_unit_checklist(
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None = None,
    document_path: str | None = None,
) -> dict[str, Any]:
    configured_provider = str(app_config.UNIT_PLANNER_PROVIDER or "fallback").strip().lower() or "fallback"
    notebooklm_ready = notebooklm_provider_ready()
    has_document = bool(str(document_path or "").strip())

    if has_document and notebooklm_ready:
        configured_provider = "notebooklm"
    elif configured_provider == "notebooklm" and not notebooklm_ready:
        configured_provider = "openai" if OPENAI_API_KEY else "fallback"
    elif configured_provider == "openai" and not OPENAI_API_KEY:
        configured_provider = "fallback"

    package = generate_unit_checklist_package(
        unit_type=unit_type,
        title=title,
        source_text=source_text,
        session_count=session_count,
        provider=configured_provider,
        document_path=document_path,
    )
    return {
        "source": package.get("source") or "fallback",
        "requested_provider": package.get("requested_provider") or configured_provider,
        "model": package.get("model"),
        "status": package.get("status") or "ready",
        "items": package.get("items") or [],
        "raw_provider_response": package.get("raw_provider_response"),
        "error_message": package.get("error_message"),
        "provider_context": package.get("provider_context") if isinstance(package.get("provider_context"), dict) else None,
    }


def _openai_generate_checklist(
    *,
    unit_type: WorkflowUnitType,
    title: str,
    source_text: str,
    session_count: int | None = None,
) -> list[dict[str, Any]] | None:
    if not OPENAI_API_KEY:
        return None

    if unit_type == WorkflowUnitType.CHAPTER:
        task_rules = (
            "Generate a HIERARCHICAL checklist tree for a middle-school math chapter. "
            "Include heading-only nodes (no full lesson content) using kinds: chapter, section, subsection, property, definition, example. "
            "Use concise titles as reminders. Preserve source order."
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
        "If uncertain, choose kind=other. Do not include any key other than title, kind, children, session_number."
    )
    session_rule = ""
    if session_count is not None and int(session_count) > 0:
        normalized_count = int(session_count)
        session_rule = (
            f"\nSession split rule: assign each leaf checklist item a session_number between 1 and {normalized_count}. "
            "Preserve source order and keep sequence continuity. "
            "Earlier concepts should be in earlier sessions. "
            "Distribute items realistically across sessions. "
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
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=OPENAI_TIMEOUT_SECONDS) as client:
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
    items = parsed.get("items")
    if not isinstance(items, list):
        return None
    return _sanitize_items(items)


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

    # Chapter fallback: keep heading-only reminders.
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
        # Avoid self-referential trees: wrap existing nodes in a new list root.
        existing_nodes = list(nodes)
        nodes = [
            {
                "title": title.strip() or "Chapter",
                "kind": WorkflowChecklistItemKind.CHAPTER.value,
                "children": existing_nodes,
            }
        ]
    return nodes


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


def _extract_pdf_text(source: Path) -> str:
    base_lines: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(source))
        for page in reader.pages:
            text = page.extract_text() or ""
            base_lines.extend(_split_text_blocks_into_lines([text]))
        base_lines.extend(_split_text_blocks_into_lines(_extract_pdf_outline_titles(reader)))
    except Exception:
        base_lines = []

    normalized = _unique_lines(base_lines)
    combined = "\n".join(normalized).strip()
    if len(combined) >= MIN_PDF_TEXT_CHARS:
        return combined

    ocr_lines = _split_text_blocks_into_lines(_ocr_pdf_pages(source, max_pages=MAX_PDF_OCR_PAGES))
    merged = _unique_lines([*normalized, *ocr_lines])
    return "\n".join(merged).strip()


def _extract_pdf_outline_titles(reader) -> list[str]:
    titles: list[str] = []
    outline = getattr(reader, "outline", None)
    if outline is None:
        return titles

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        title = getattr(node, "title", None)
        if title is None and isinstance(node, dict):
            title = node.get("/Title") or node.get("title")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())

    try:
        walk(outline)
    except Exception:
        return []
    return titles


def _ocr_pdf_pages(source: Path, *, max_pages: int) -> list[str]:
    try:
        import pypdfium2 as pdfium
        from PIL import ImageFilter, ImageOps
        import pytesseract
    except Exception:
        return []

    lines: list[str] = []
    try:
        document = pdfium.PdfDocument(str(source))
    except Exception:
        return []

    total_pages = min(len(document), max(1, int(max_pages)))
    for page_index in range(total_pages):
        try:
            page = document[page_index]
            pil = page.render(scale=2.2).to_pil()
            base = pil.convert("RGB")
            if max(base.size) < 1300:
                base = base.resize((max(1, base.size[0] * 2), max(1, base.size[1] * 2)))
            gray = ImageOps.grayscale(base)
            variants = [
                ImageOps.autocontrast(gray),
                ImageOps.autocontrast(gray.filter(ImageFilter.SHARPEN)),
                ImageOps.autocontrast(gray).point(lambda value: 255 if value > 165 else 0),
            ]
            best = ""
            best_len = 0
            for image in variants:
                for config in ("--psm 6", "--psm 4"):
                    text = ""
                    try:
                        text = pytesseract.image_to_string(image, lang=OCR_LANG, config=config)
                    except Exception:
                        try:
                            text = pytesseract.image_to_string(image, config=config)
                        except Exception:
                            text = ""
                    cleaned = text.strip()
                    if len(cleaned) > best_len:
                        best = cleaned
                        best_len = len(cleaned)
            if best:
                lines.append(best)
        except Exception:
            continue
    return lines


def _split_text_blocks_into_lines(blocks: list[str]) -> list[str]:
    output: list[str] = []
    for block in blocks:
        raw = str(block or "")
        if not raw.strip():
            continue
        for line in re.split(r"[\r\n]+", raw):
            value = re.sub(r"\s+", " ", str(line or "")).strip(" \t\r\n;,-")
            if value:
                output.append(value)
    return output


def _unique_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for raw in lines:
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output
