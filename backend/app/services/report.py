from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time
from io import BytesIO
from pathlib import Path
import json
import re
import unicodedata

import httpx
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import config as app_config
try:
    import arabic_reshaper
except Exception:  # pragma: no cover - optional dependency runtime guard
    arabic_reshaper = None

try:
    from bidi.algorithm import get_display
except Exception:  # pragma: no cover - optional dependency runtime guard
    get_display = None

from ..models import (
    AttendanceRecord,
    AttendanceStatus,
    ClassSession,
    Classroom,
    Exam,
    ExamResult,
    ProgressItem,
    SessionUpload,
    Student,
    WorkflowChecklistItem,
    WorkflowSessionWriteup,
    WorkflowSessionChecklistAction,
    WorkflowUnit,
)


def _line(pdf: canvas.Canvas, text: str, x: int, y: int) -> int:
    pdf.drawString(x, y, text[:120])
    return y - 16


def _format_time(value: time | None) -> str:
    return value.strftime("%H:%M") if value is not None else "-"


def _session_sort_value(value: time | None) -> int:
    if value is None:
        return (24 * 60) + 1
    return (int(value.hour) * 60) + int(value.minute)


def _normalize_focus_item(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^[\-\u2022]+\s*", "", value)
    value = re.sub(r"^\d+\s*[\)\.\-:]\s*", "", value)
    value = " ".join(value.split())
    if not value:
        return ""
    value = value[0].upper() + value[1:] if value else value
    if value[-1] not in ".!?":
        value = f"{value}."
    return value


def _normalize_outline_item(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^[\-\u2022]+\s*", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*\s*[\)\].:-]?\s*", "", value)
    value = " ".join(value.split()).strip(" ;,-")
    if not value:
        return ""
    return value[0].upper() + value[1:]


def _normalize_overlap_key(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    folded = unicodedata.normalize("NFKD", raw)
    without_accents = "".join(ch for ch in folded if not unicodedata.combining(ch))
    compact = re.sub(r"[^a-z0-9]+", " ", without_accents).strip()
    return " ".join(compact.split())


def _outline_text_rows(outline_sections: list[dict]) -> list[str]:
    rows: list[str] = []
    for section in outline_sections:
        if not isinstance(section, dict):
            continue
        heading = _normalize_outline_item(str(section.get("heading") or ""))
        if heading:
            rows.append(heading)
        subheadings = section.get("subheadings")
        if isinstance(subheadings, list):
            for subheading in subheadings:
                cleaned = _normalize_outline_item(str(subheading or ""))
                if cleaned:
                    rows.append(cleaned)
    return rows


def _dedupe_focus_items_against_outline(focus_items: list[str], outline_sections: list[dict]) -> list[str]:
    outline_keys = {
        _normalize_overlap_key(row)
        for row in _outline_text_rows(outline_sections)
        if _normalize_overlap_key(row)
    }
    if not outline_keys:
        return focus_items
    filtered: list[str] = []
    for row in focus_items:
        key = _normalize_overlap_key(row)
        if key and key in outline_keys:
            continue
        filtered.append(row)
    return filtered


def _build_focus_summary_from_outline(outline_sections: list[dict]) -> str:
    rows = _outline_text_rows(outline_sections)
    if not rows:
        return "Consolider les acquis de la seance et les mobiliser dans des exercices guides."
    if len(rows) == 1:
        return _ensure_sentence(f"Consolider {rows[0].lower()} puis l'appliquer dans des exercices de renforcement")
    return _ensure_sentence(
        f"Consolider {rows[0].lower()} et {rows[1].lower()} a travers des activites progressives de renforcement"
    )


def _format_date_french(value: date) -> str:
    weekdays = [
        "lundi",
        "mardi",
        "mercredi",
        "jeudi",
        "vendredi",
        "samedi",
        "dimanche",
    ]
    months = [
        "janvier",
        "fevrier",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "aout",
        "septembre",
        "octobre",
        "novembre",
        "decembre",
    ]
    return f"{weekdays[value.weekday()]} {value.day:02d} {months[value.month - 1]} {value.year}"


def _unit_type_label_fr(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "chapter": "chapitre",
        "exercise_series": "serie d'exercices",
        "exam": "evaluation",
        "exam_correction": "correction",
    }
    return mapping.get(normalized, normalized or "unite")


def _split_numbered_report_rows(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    lines = [
        re.sub(r"\s+", " ", segment).strip(" ;,-")
        for segment in re.split(r"[\r\n]+", raw)
        if str(segment or "").strip()
    ]
    pattern = re.compile(r"(?<!\S)\d+(?:\.\d+)+(?:[)\].:-])?(?:\s+|$)")
    output: list[str] = []
    for line in lines:
        matches = list(pattern.finditer(line))
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
        value = str(row or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _merge_headline_candidates(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            value = str(raw or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
    return merged


def _extract_headline_candidates_from_progress_item(item: ProgressItem) -> list[str]:
    heading = str(item.heading or "").strip()
    content = str(item.content or "").strip()
    heading_key = heading.lower()
    generic_headings = {"activity", "exercise", "activite", "exercice"}
    if content:
        text = f"{heading}: {content}" if heading and heading_key not in generic_headings else content
    else:
        text = heading
    text = str(text or "").strip()
    if not text:
        return []
    rows = _split_numbered_report_rows(text)
    return rows if rows else [text]


def _resolve_pdf_font_names() -> tuple[str, str]:
    regular_name = "Helvetica"
    bold_name = "Helvetica-Bold"
    regular_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    bold_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not regular_path.exists() or not bold_path.exists():
        return regular_name, bold_name

    custom_regular = "TeacherDejaVuSans"
    custom_bold = "TeacherDejaVuSans-Bold"
    try:
        registered = set(pdfmetrics.getRegisteredFontNames())
        if custom_regular not in registered:
            pdfmetrics.registerFont(TTFont(custom_regular, str(regular_path)))
        if custom_bold not in registered:
            pdfmetrics.registerFont(TTFont(custom_bold, str(bold_path)))
        return custom_regular, custom_bold
    except Exception:
        return regular_name, bold_name


_ARABIC_CHAR_PATTERN = re.compile(r"[\u0600-\u06FF]")
_REPORT_AI_SESSION_CHUNK_SIZE = 18
_REPORT_AI_HEADLINE_LIMIT = 8


def _shape_arabic_text(value: str) -> str:
    text = str(value or "").strip()
    if not text or not _ARABIC_CHAR_PATTERN.search(text):
        return text
    if arabic_reshaper is None or get_display is None:
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _json_object_from_text(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    chunk = raw[start : end + 1]
    try:
        return json.loads(chunk)
    except Exception:
        return None


def _ensure_sentence(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if text[-1] not in ".!?":
        return f"{text}."
    return text


def _extract_focus_items_from_checked_titles(checked_titles: list[str], *, limit: int = _REPORT_AI_HEADLINE_LIMIT) -> list[str]:
    output: list[str] = []
    for raw in checked_titles:
        split_rows = _split_numbered_report_rows(raw)
        candidates = split_rows if split_rows else [str(raw or "").strip()]
        for candidate in candidates:
            cleaned = _normalize_focus_item(candidate)
            if not cleaned or cleaned in output:
                continue
            output.append(cleaned)
            if len(output) >= limit:
                return output
    return output


def _default_focus_items() -> list[str]:
    return ["Consolidation des acquis precedents par des activites guidees et des exercices d'application."]


def _default_session_outline(*, focus_items: list[str], checked_titles: list[str]) -> list[dict[str, list[str] | str]]:
    normalized_titles: list[str] = []
    for raw in checked_titles:
        rows = _split_numbered_report_rows(raw)
        candidates = rows if rows else [str(raw or "").strip()]
        for candidate in candidates:
            cleaned = _normalize_outline_item(candidate)
            if cleaned and cleaned not in normalized_titles:
                normalized_titles.append(cleaned)

    if normalized_titles:
        primary_heading = _normalize_outline_item(str(focus_items[0] if focus_items else "Contenus traites").rstrip("."))
        primary_heading = primary_heading or "Contenus traites"
        subheadings = [row for row in normalized_titles if row != primary_heading][: min(6, len(normalized_titles))]
        if subheadings:
            return [{"heading": primary_heading, "subheadings": subheadings}]

    output: list[dict[str, list[str] | str]] = []
    for focus in focus_items[: min(4, len(focus_items))]:
        heading = _normalize_outline_item(str(focus).rstrip("."))
        if heading:
            output.append({"heading": heading, "subheadings": []})
    if output:
        return output
    return [{"heading": "Contenus traites", "subheadings": []}]


def _fallback_session_narrative(*, focus_items: list[str], note_text: str) -> str:
    cleaned_note = _ensure_sentence(note_text)
    if cleaned_note:
        return cleaned_note
    anchors = [str(item or "").strip().rstrip(".") for item in focus_items if str(item or "").strip()]
    if len(anchors) >= 2:
        return _ensure_sentence(
            f"La seance a developpe {anchors[0].lower()} et {anchors[1].lower()} a travers des explications guidees et des exercices de consolidation"
        )
    if anchors:
        return _ensure_sentence(
            f"La seance a ete centree sur {anchors[0].lower()} avec des activites de guidage et de renforcement"
        )
    return "La seance a permis une consolidation guidee des apprentissages a travers des activites progressives."


def _collect_ai_session_narratives(session_rows: list[dict]) -> dict[int, dict]:
    if not app_config.OPENAI_API_KEY:
        return {}
    if not session_rows:
        return {}

    system_prompt = (
        "Tu es un assistant de redaction pedagogique pour un rapport administratif de collegiens en mathematiques. "
        "Return STRICT JSON only with schema: "
        "{\"sessions\":[{\"session_id\":1,\"paragraph\":\"...\"}]}. "
        "Regles: ecris uniquement en francais formel, reste strictement fidele aux informations fournies, "
        "n'invente ni contenus, ni notes, ni absences, ni evaluations. "
        "Utilise les contenus confirmes de la seance tels qu'ils sont fournis. "
        "paragraph doit etre court (2 a 3 phrases, max 60 mots), clair, et de style pedagogique."
    )
    headers = {
        "Authorization": f"Bearer {app_config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    output: dict[int, dict] = {}
    for start in range(0, len(session_rows), _REPORT_AI_SESSION_CHUNK_SIZE):
        chunk = session_rows[start : start + _REPORT_AI_SESSION_CHUNK_SIZE]
        user_prompt = (
            "Produis un court Developpement pedagogique pour chaque seance.\n"
            "Ne renvoie qu'un paragraphe court par seance, sans titres additionnels.\n\n"
            f"{json.dumps({'sessions': chunk}, ensure_ascii=False)}"
        )
        payload = {
            "model": app_config.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        try:
            with httpx.Client(timeout=app_config.OPENAI_TIMEOUT_SECONDS) as client:
                response = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception:
            continue

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        parsed = _json_object_from_text(content)
        rows = parsed.get("sessions") if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                session_id = int(row.get("session_id"))
            except Exception:
                continue
            if session_id <= 0:
                continue

            paragraph = _ensure_sentence(str(row.get("paragraph") or ""))
            output[session_id] = {
                "paragraph": paragraph,
            }
    return output


def _derive_unit_session_number_map(sessions: list[ClassSession]) -> dict[int, int]:
    grouped: dict[int, list[ClassSession]] = {}
    for session in sessions:
        if session.unit_id is None:
            continue
        grouped.setdefault(int(session.unit_id), []).append(session)
    output: dict[int, int] = {}
    for unit_sessions in grouped.values():
        ordered = sorted(
            unit_sessions,
            key=lambda row: (row.session_date, _session_sort_value(row.start_time), row.id),
        )
        for index, row in enumerate(ordered, start=1):
            output[int(row.id)] = index
    return output


def _build_checklist_order_maps(items: list[WorkflowChecklistItem]) -> tuple[dict[int, int], dict[int, str]]:
    by_parent: dict[int | None, list[WorkflowChecklistItem]] = {}
    for row in items:
        by_parent.setdefault(row.parent_item_id, []).append(row)
    for siblings in by_parent.values():
        siblings.sort(key=lambda value: (int(value.position), int(value.id)))

    order_index_by_id: dict[int, int] = {}
    number_label_by_id: dict[int, str] = {}
    ordered_count = 0
    visited_ids: set[int] = set()

    def walk(parent_id: int | None, prefix: str) -> None:
        nonlocal ordered_count
        siblings = by_parent.get(parent_id, [])
        for idx, row in enumerate(siblings, start=1):
            row_id = int(row.id)
            if row_id in visited_ids:
                continue
            visited_ids.add(row_id)
            number_label = f"{prefix}.{idx}" if prefix else str(idx)
            order_index_by_id[row_id] = ordered_count
            number_label_by_id[row_id] = number_label
            ordered_count += 1
            walk(row_id, number_label)

    walk(None, "")

    if len(order_index_by_id) < len(items):
        extras = sorted(
            (row for row in items if int(row.id) not in visited_ids),
            key=lambda value: (int(value.depth), int(value.position), int(value.id)),
        )
        for row in extras:
            row_id = int(row.id)
            order_index_by_id[row_id] = ordered_count
            number_label_by_id[row_id] = str(ordered_count + 1)
            ordered_count += 1
    return order_index_by_id, number_label_by_id


def _filter_actionable_report_check_rows(rows: list) -> list:
    if not rows:
        return []
    child_counts: dict[int, int] = {}
    for row in rows:
        parent_id = getattr(row, "parent_item_id", None)
        if parent_id is None:
            continue
        parent_key = int(parent_id)
        child_counts[parent_key] = child_counts.get(parent_key, 0) + 1

    filtered: list = []
    for row in rows:
        item_id = int(getattr(row, "item_id", getattr(row, "id", 0)) or 0)
        if item_id <= 0:
            continue
        if child_counts.get(item_id, 0) > 0:
            continue
        filtered.append(row)
    return filtered


def _format_progress_item(row: ProgressItem) -> str:
    heading = str(row.heading or "").strip()
    content = str(row.content or "").strip()
    if content and heading:
        return f"[{row.item_type.value}] {heading}: {content}"
    if heading:
        return f"[{row.item_type.value}] {heading}"
    if content:
        return f"[{row.item_type.value}] {content}"
    return f"[{row.item_type.value}] (empty)"


def _format_attendance_detail(row, masked_labels: dict[int, str], mask_personal_data: bool) -> str:
    status_value = str(row.status.value if hasattr(row.status, "value") else row.status).lower()
    if mask_personal_data:
        student_label = masked_labels.get(int(row.student_id), f"ANON{int(row.student_id):03d}")
    else:
        code = str(row.student_code or "").strip()
        name = str(row.full_name or "").strip() or f"Student #{int(row.student_id)}"
        student_label = f"{code} - {name}" if code else name
    suffix_parts: list[str] = []
    if status_value == AttendanceStatus.LATE.value and int(row.minutes_late or 0) > 0:
        suffix_parts.append(f"{int(row.minutes_late)} min late")
    if row.comment:
        suffix_parts.append(str(row.comment).strip())
    suffix = f" ({'; '.join(part for part in suffix_parts if part)})" if suffix_parts else ""
    return f"{student_label}: {status_value}{suffix}"


def build_class_pdf_report(db: Session, class_id: int, mask_personal_data: bool = False) -> bytes:
    classroom = db.get(Classroom, class_id)
    if classroom is None:
        raise ValueError("Class not found.")

    sessions = db.scalars(
        select(ClassSession)
        .where(ClassSession.class_id == class_id)
        .order_by(
            ClassSession.session_date.asc(),
            ClassSession.start_time.asc().nulls_last(),
            ClassSession.id.asc(),
        )
    ).all()
    session_ids = [int(row.id) for row in sessions]
    unit_ids = sorted({int(row.unit_id) for row in sessions if row.unit_id is not None})

    students_count = int(db.scalar(select(func.count(Student.id)).where(Student.class_id == class_id)) or 0)
    units = db.scalars(select(WorkflowUnit).where(WorkflowUnit.id.in_(unit_ids))).all() if unit_ids else []
    unit_by_id = {int(row.id): row for row in units}
    derived_unit_session_numbers = _derive_unit_session_number_map(sessions)

    progress_by_session: dict[int, list[ProgressItem]] = defaultdict(list)
    attendance_by_session: dict[int, list] = defaultdict(list)
    upload_summary_by_session: dict[int, tuple[int, int]] = {}
    checklist_labels_by_session: dict[int, list[str]] = {}

    if session_ids:
        progress_rows = db.scalars(
            select(ProgressItem)
            .where(ProgressItem.session_id.in_(session_ids))
            .order_by(ProgressItem.session_id.asc(), ProgressItem.position.asc(), ProgressItem.id.asc())
        ).all()
        for row in progress_rows:
            progress_by_session[int(row.session_id)].append(row)

        attendance_rows = db.execute(
            select(
                AttendanceRecord.session_id,
                AttendanceRecord.student_id,
                AttendanceRecord.status,
                AttendanceRecord.minutes_late,
                AttendanceRecord.comment,
                Student.student_code,
                Student.full_name,
            )
            .join(Student, Student.id == AttendanceRecord.student_id)
            .where(AttendanceRecord.session_id.in_(session_ids))
            .order_by(AttendanceRecord.session_id.asc(), Student.full_name.asc(), Student.id.asc())
        ).all()
        for row in attendance_rows:
            attendance_by_session[int(row.session_id)].append(row)

        upload_rows = db.execute(
            select(
                SessionUpload.session_id,
                func.count(SessionUpload.id).label("total_count"),
                func.sum(case((SessionUpload.reviewed.is_(True), 1), else_=0)).label("reviewed_count"),
            )
            .where(SessionUpload.session_id.in_(session_ids))
            .group_by(SessionUpload.session_id)
        ).all()
        upload_summary_by_session = {
            int(row.session_id): (int(row.total_count or 0), int(row.reviewed_count or 0))
            for row in upload_rows
        }

        checked_rows = db.execute(
            select(
                WorkflowSessionChecklistAction.session_id,
                WorkflowChecklistItem.id.label("item_id"),
                WorkflowChecklistItem.title,
                WorkflowChecklistItem.unit_id,
                WorkflowChecklistItem.parent_item_id,
            )
            .join(WorkflowChecklistItem, WorkflowSessionChecklistAction.item_id == WorkflowChecklistItem.id)
            .where(
                WorkflowSessionChecklistAction.session_id.in_(session_ids),
                WorkflowSessionChecklistAction.checked.is_(True),
            )
        ).all()
        checked_by_session: dict[int, list] = defaultdict(list)
        checked_unit_ids: set[int] = set()
        for row in checked_rows:
            checked_by_session[int(row.session_id)].append(row)
            if row.unit_id is not None:
                checked_unit_ids.add(int(row.unit_id))

        unit_order_map: dict[int, dict[int, int]] = {}
        unit_number_map: dict[int, dict[int, str]] = {}
        if checked_unit_ids:
            checklist_items = db.scalars(
                select(WorkflowChecklistItem)
                .where(WorkflowChecklistItem.unit_id.in_(sorted(checked_unit_ids)))
                .order_by(
                    WorkflowChecklistItem.unit_id.asc(),
                    WorkflowChecklistItem.position.asc(),
                    WorkflowChecklistItem.id.asc(),
                )
            ).all()
            items_by_unit: dict[int, list[WorkflowChecklistItem]] = defaultdict(list)
            for item in checklist_items:
                items_by_unit[int(item.unit_id)].append(item)
            for unit_id, rows in items_by_unit.items():
                order_index_by_id, number_label_by_id = _build_checklist_order_maps(rows)
                unit_order_map[int(unit_id)] = order_index_by_id
                unit_number_map[int(unit_id)] = number_label_by_id

        for session_id, rows in checked_by_session.items():
            rows = _filter_actionable_report_check_rows(rows)
            unit_id = next((int(row.unit_id) for row in rows if row.unit_id is not None), None)
            order_map = unit_order_map.get(unit_id, {}) if unit_id is not None else {}
            number_map = unit_number_map.get(unit_id, {}) if unit_id is not None else {}
            sorted_rows = sorted(
                rows,
                key=lambda row: (order_map.get(int(row.item_id), 10**9), int(row.item_id)),
            )
            labels: list[str] = []
            for row in sorted_rows:
                title = str(row.title or "").strip() or "Checklist item"
                number = number_map.get(int(row.item_id))
                labels.append(f"{number}) {title}" if number else title)
            checklist_labels_by_session[int(session_id)] = labels

    masked_labels_by_student_id: dict[int, str] = {}
    if mask_personal_data:
        students = db.scalars(
            select(Student)
            .where(Student.class_id == class_id)
            .order_by(Student.full_name.asc(), Student.id.asc())
        ).all()
        masked_labels_by_student_id = {
            int(student.id): f"ANON{idx:03d} - Student {idx:03d}"
            for idx, student in enumerate(students, start=1)
        }

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    page_width, page_height = A4
    left = 36
    right = 36
    top = 34
    bottom = 34
    content_width = page_width - left - right
    line_height = 13
    y = page_height - top
    generated_stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    def draw_page_header() -> float:
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawString(left, page_height - top, f"Class Sessions Report: {classroom.name}")
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(page_width - right, page_height - top, f"Generated {generated_stamp}")
        line_y = page_height - top - 6
        pdf.line(left, line_y, page_width - right, line_y)
        return line_y - 12

    y = draw_page_header()

    def ensure_space(required_lines: int = 1) -> None:
        nonlocal y
        if y - (required_lines * line_height) >= bottom:
            return
        pdf.showPage()
        y = draw_page_header()

    def draw_text(
        text: str,
        *,
        font_name: str = "Helvetica",
        font_size: int = 9,
        indent: int = 0,
    ) -> None:
        nonlocal y
        x = left + indent
        width = max(80, content_width - indent)
        lines = simpleSplit(str(text or ""), font_name, font_size, width)
        if not lines:
            lines = [""]
        ensure_space(len(lines))
        pdf.setFont(font_name, font_size)
        for line in lines:
            pdf.drawString(x, y, line)
            y -= line_height

    def add_gap(points: int = 4) -> None:
        nonlocal y
        y -= points
        if y < bottom:
            pdf.showPage()
            y = draw_page_header()

    draw_text("Summary", font_name="Helvetica-Bold", font_size=11)
    draw_text(f"Class: {classroom.name}")
    draw_text(f"Subject: {classroom.subject or '-'}")
    draw_text(f"Level: {classroom.level or '-'}")
    draw_text(f"Privacy mode: {'masked' if mask_personal_data else 'full'}")
    draw_text(f"Students: {students_count}")
    draw_text(f"Sessions total: {len(sessions)}")
    draw_text(f"Workflow sessions: {sum(1 for row in sessions if row.unit_id is not None)}")
    add_gap(8)

    draw_text("Sessions (Chronological)", font_name="Helvetica-Bold", font_size=11)
    add_gap(2)
    if not sessions:
        draw_text("No sessions recorded for this class yet.", font_name="Helvetica-Oblique")
    else:
        for index, session in enumerate(sessions, start=1):
            ensure_space(8)
            unit = unit_by_id.get(int(session.unit_id)) if session.unit_id is not None else None
            unit_session_number = (
                int(session.unit_session_number)
                if session.unit_session_number is not None
                else derived_unit_session_numbers.get(int(session.id))
            )
            unit_bits: list[str] = []
            if unit is not None:
                unit_bits.append(f"{unit.title} [{unit.unit_type.value}]")
            if unit_session_number is not None:
                unit_bits.append(f"session #{unit_session_number}")
            unit_text = " | ".join(unit_bits) if unit_bits else "non-workflow session"

            draw_text(
                f"Session {index} - {session.session_date.isoformat()} "
                f"({_format_time(session.start_time)} -> {_format_time(session.end_time)})",
                font_name="Helvetica-Bold",
                font_size=10,
            )
            draw_text(f"Unit: {unit_text}")
            draw_text(f"Note: {str(session.note or '-').strip() or '-'}")
            total_uploads, reviewed_uploads = upload_summary_by_session.get(int(session.id), (0, 0))
            draw_text(f"Uploads: {total_uploads} (reviewed {reviewed_uploads})")

            checked_labels = checklist_labels_by_session.get(int(session.id), [])
            draw_text(f"Checklist checked: {len(checked_labels)}")
            if checked_labels:
                for label in checked_labels:
                    draw_text(f"- {label}", indent=16)
            else:
                draw_text("- No checked checklist items.", indent=16)

            progress_rows = progress_by_session.get(int(session.id), [])
            draw_text(f"Progress rows: {len(progress_rows)}")
            if progress_rows:
                for row in progress_rows:
                    draw_text(f"- {_format_progress_item(row)}", indent=16)
            else:
                draw_text("- No progress rows.", indent=16)

            attendance_rows = attendance_by_session.get(int(session.id), [])
            status_counts = {
                AttendanceStatus.PRESENT.value: 0,
                AttendanceStatus.ABSENT.value: 0,
                AttendanceStatus.LATE.value: 0,
                AttendanceStatus.EXCUSED.value: 0,
            }
            for row in attendance_rows:
                key = str(row.status.value if hasattr(row.status, "value") else row.status).lower()
                status_counts[key] = int(status_counts.get(key, 0)) + 1
            draw_text(
                "Attendance: "
                f"rows={len(attendance_rows)} | "
                f"present={status_counts.get(AttendanceStatus.PRESENT.value, 0)} | "
                f"absent={status_counts.get(AttendanceStatus.ABSENT.value, 0)} | "
                f"late={status_counts.get(AttendanceStatus.LATE.value, 0)} | "
                f"excused={status_counts.get(AttendanceStatus.EXCUSED.value, 0)}"
            )
            attendance_flags = [
                row
                for row in attendance_rows
                if str(row.status.value if hasattr(row.status, "value") else row.status).lower() != AttendanceStatus.PRESENT.value
                or int(row.minutes_late or 0) > 0
                or bool(row.comment)
            ]
            if attendance_flags:
                draw_text("Attendance details:", indent=16)
                for row in attendance_flags:
                    detail = _format_attendance_detail(row, masked_labels_by_student_id, mask_personal_data)
                    draw_text(f"- {detail}", indent=24)
            else:
                draw_text("- No attendance alerts.", indent=16)
            add_gap(8)

    add_gap(4)
    exams = db.scalars(select(Exam).where(Exam.class_id == class_id).order_by(Exam.exam_date.asc(), Exam.id.asc())).all()
    draw_text("Exam Summary", font_name="Helvetica-Bold", font_size=11)
    if not exams:
        draw_text("No exams recorded.")
    else:
        for exam in exams:
            result_count = int(
                db.scalar(select(func.count(ExamResult.id)).where(ExamResult.exam_id == int(exam.id))) or 0
            )
            draw_text(
                f"- {exam.exam_date.isoformat()} | {exam.title} | max={exam.max_score} | results={result_count}"
            )

    pdf.save()
    output.seek(0)
    return output.read()


def build_calendar_summary_pdf(
    db: Session,
    class_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    ai_enhance: bool = False,
) -> bytes:
    classroom = db.get(Classroom, class_id)
    if classroom is None:
        raise ValueError("Class not found.")

    query = select(ClassSession).where(ClassSession.class_id == int(class_id))
    if date_from is not None:
        query = query.where(ClassSession.session_date >= date_from)
    if date_to is not None:
        query = query.where(ClassSession.session_date <= date_to)
    sessions = db.scalars(
        query.order_by(
            ClassSession.session_date.asc(),
            ClassSession.start_time.asc().nulls_last(),
            ClassSession.id.asc(),
        )
    ).all()
    session_ids = [int(row.id) for row in sessions]
    students_count = int(db.scalar(select(func.count(Student.id)).where(Student.class_id == int(class_id))) or 0)
    student_rows = db.scalars(
        select(Student)
        .where(Student.class_id == int(class_id))
        .order_by(Student.student_code.asc(), Student.full_name.asc(), Student.id.asc())
    ).all()
    student_entries: list[dict[str, str]] = []
    for student in student_rows:
        code = str(student.student_code or "").strip()
        name = str(student.full_name or "").strip() or "Student"
        student_entries.append({"code": code, "name": name})

    unit_ids = sorted({int(row.unit_id) for row in sessions if row.unit_id is not None})
    units = db.scalars(select(WorkflowUnit).where(WorkflowUnit.id.in_(unit_ids))).all() if unit_ids else []
    unit_by_id = {int(row.id): row for row in units}

    checked_titles_by_session: dict[int, list[str]] = defaultdict(list)
    progress_titles_by_session: dict[int, list[str]] = defaultdict(list)
    checked_count_by_session: dict[int, int] = defaultdict(int)
    writeup_by_session: dict[int, WorkflowSessionWriteup] = {}
    attendance_counts_by_session: dict[int, dict[str, int]] = defaultdict(
        lambda: {
            AttendanceStatus.PRESENT.value: 0,
            AttendanceStatus.ABSENT.value: 0,
            AttendanceStatus.LATE.value: 0,
            AttendanceStatus.EXCUSED.value: 0,
        }
    )

    if session_ids:
        checked_rows = db.execute(
            select(
                WorkflowSessionChecklistAction.session_id,
                WorkflowChecklistItem.id.label("item_id"),
                WorkflowChecklistItem.parent_item_id,
                WorkflowChecklistItem.title,
            )
            .join(WorkflowChecklistItem, WorkflowSessionChecklistAction.item_id == WorkflowChecklistItem.id)
            .where(
                WorkflowSessionChecklistAction.session_id.in_(session_ids),
                WorkflowSessionChecklistAction.checked.is_(True),
            )
            .order_by(
                WorkflowSessionChecklistAction.session_id.asc(),
                WorkflowChecklistItem.position.asc(),
                WorkflowChecklistItem.id.asc(),
            )
        ).all()
        filtered_checked_rows = _filter_actionable_report_check_rows(list(checked_rows))
        for row in filtered_checked_rows:
            session_key = int(row.session_id)
            title = str(row.title or "").strip()
            if title:
                checked_titles_by_session[session_key].append(title)
            checked_count_by_session[session_key] += 1

        progress_rows = db.scalars(
            select(ProgressItem)
            .where(ProgressItem.session_id.in_(session_ids))
            .order_by(ProgressItem.session_id.asc(), ProgressItem.position.asc(), ProgressItem.id.asc())
        ).all()
        for row in progress_rows:
            session_key = int(row.session_id)
            for candidate in _extract_headline_candidates_from_progress_item(row):
                progress_titles_by_session[session_key].append(candidate)

        writeup_rows = db.scalars(
            select(WorkflowSessionWriteup)
            .where(WorkflowSessionWriteup.session_id.in_(session_ids))
            .order_by(WorkflowSessionWriteup.session_id.asc(), WorkflowSessionWriteup.updated_at.desc())
        ).all()
        for row in writeup_rows:
            writeup_by_session[int(row.session_id)] = row

        attendance_rows = db.execute(
            select(
                AttendanceRecord.session_id,
                AttendanceRecord.status,
                func.count(AttendanceRecord.id).label("total_count"),
            )
            .where(AttendanceRecord.session_id.in_(session_ids))
            .group_by(AttendanceRecord.session_id, AttendanceRecord.status)
            .order_by(AttendanceRecord.session_id.asc())
        ).all()
        for row in attendance_rows:
            session_key = int(row.session_id)
            status_value = str(row.status.value if hasattr(row.status, "value") else row.status).lower()
            attendance_counts_by_session[session_key][status_value] = int(row.total_count or 0)

    total_attendance_rows = 0
    total_present_like = 0
    for counts in attendance_counts_by_session.values():
        present = int(counts.get(AttendanceStatus.PRESENT.value, 0))
        absent = int(counts.get(AttendanceStatus.ABSENT.value, 0))
        late = int(counts.get(AttendanceStatus.LATE.value, 0))
        excused = int(counts.get(AttendanceStatus.EXCUSED.value, 0))
        total_attendance_rows += present + absent + late + excused
        total_present_like += present + late + excused
    attendance_rate = (total_present_like / total_attendance_rows) if total_attendance_rows > 0 else None

    ordered_unit_labels: list[str] = []
    unit_summary: dict[str, dict[str, int]] = {}
    for session in sessions:
        unit = unit_by_id.get(int(session.unit_id)) if session.unit_id is not None else None
        if unit is not None:
            label = f"{unit.title} ({_unit_type_label_fr(unit.unit_type.value)})"
        else:
            label = "Seance generale de classe"
        if label not in unit_summary:
            unit_summary[label] = {"sessions": 0, "checked_items": 0}
            ordered_unit_labels.append(label)
        unit_summary[label]["sessions"] += 1
        unit_summary[label]["checked_items"] += int(checked_count_by_session.get(int(session.id), 0))

    session_content_by_session: dict[int, list[str]] = {}
    ai_request_rows: list[dict] = []
    for index, session in enumerate(sessions, start=1):
        session_id = int(session.id)
        writeup = writeup_by_session.get(session_id)
        checked_titles = checked_titles_by_session.get(session_id, [])
        progress_titles = progress_titles_by_session.get(session_id, [])
        writeup_focus = (
            [str(value) for value in writeup.learning_focus_json if str(value or "").strip()]
            if writeup is not None and isinstance(writeup.learning_focus_json, list)
            else []
        )
        if writeup_focus:
            session_content = writeup_focus
        elif checked_titles:
            session_content = _merge_headline_candidates(checked_titles)
        else:
            session_content = _merge_headline_candidates(progress_titles)
        if not session_content:
            session_content = _default_focus_items()
        session_content_by_session[session_id] = session_content

        if ai_enhance:
            attendance = attendance_counts_by_session.get(session_id, {})
            present = int(attendance.get(AttendanceStatus.PRESENT.value, 0))
            absent = int(attendance.get(AttendanceStatus.ABSENT.value, 0))
            late = int(attendance.get(AttendanceStatus.LATE.value, 0))
            excused = int(attendance.get(AttendanceStatus.EXCUSED.value, 0))
            unit = unit_by_id.get(int(session.unit_id)) if session.unit_id is not None else None
            unit_label = (
                f"{unit.title} ({_unit_type_label_fr(unit.unit_type.value)})"
                if unit is not None
                else "Seance generale de classe"
            )
            ai_request_rows.append(
                {
                    "session_id": session_id,
                    "session_index": index,
                    "session_date": session.session_date.isoformat(),
                    "start_time": _format_time(session.start_time),
                    "end_time": _format_time(session.end_time),
                    "unit": unit_label,
                    "session_content": session_content[:32],
                    "confirmed_checklist_titles": checked_titles[:24],
                    "confirmed_checklist_count": int(checked_count_by_session.get(session_id, 0)),
                    "teacher_note": str(session.note or "").strip(),
                    "attendance_summary": {
                        "present": present,
                        "absent": absent,
                        "late": late,
                        "excused": excused,
                    },
                }
            )

    ai_narrative_by_session: dict[int, dict] = _collect_ai_session_narratives(ai_request_rows) if ai_enhance else {}

    period_text = "Toutes les dates enregistrees"
    if date_from is not None and date_to is not None:
        period_text = f"Du {date_from.isoformat()} au {date_to.isoformat()}"
    elif date_from is not None:
        period_text = f"A partir du {date_from.isoformat()}"
    elif date_to is not None:
        period_text = f"Jusqu'au {date_to.isoformat()}"

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    font_regular, font_bold = _resolve_pdf_font_names()
    page_width, page_height = A4
    left = 38
    right = 38
    top = 34
    bottom = 34
    content_width = page_width - left - right
    line_height = 13
    y = page_height - top
    generated_stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    def draw_page_header() -> float:
        pdf.setFont(font_bold, 16)
        pdf.drawString(left, page_height - top, _shape_arabic_text("Synthese du calendrier pedagogique"))
        pdf.setFont(font_regular, 8)
        pdf.drawRightString(page_width - right, page_height - top + 1, _shape_arabic_text(f"Genere le {generated_stamp}"))
        title_y = page_height - top - 16
        pdf.setFont(font_bold, 11)
        pdf.drawString(left, title_y, str(classroom.name or "Class"))
        pdf.setFont(font_regular, 9)
        pdf.drawString(left, title_y - 12, _shape_arabic_text(f"Matiere : {classroom.subject or '-'}  |  Niveau : {classroom.level or '-'}"))
        pdf.drawString(left, title_y - 24, _shape_arabic_text(f"Periode : {period_text}"))
        line_y = title_y - 30
        pdf.line(left, line_y, page_width - right, line_y)
        return line_y - 12

    y = draw_page_header()

    def ensure_space(required_lines: int = 1) -> None:
        nonlocal y
        if y - (required_lines * line_height) >= bottom:
            return
        pdf.showPage()
        y = draw_page_header()

    def draw_text(text: str, *, font_name: str | None = None, font_size: int = 9, indent: int = 0) -> None:
        nonlocal y
        active_font = str(font_name or font_regular)
        x = left + indent
        width = max(80, content_width - indent)
        lines = simpleSplit(str(text or ""), active_font, font_size, width)
        if not lines:
            lines = [""]
        ensure_space(len(lines))
        pdf.setFont(active_font, font_size)
        for line in lines:
            pdf.drawString(x, y, _shape_arabic_text(line))
            y -= line_height

    def add_gap(points: int = 5) -> None:
        nonlocal y
        y -= points
        if y < bottom:
            pdf.showPage()
            y = draw_page_header()

    def draw_section(title: str) -> None:
        draw_text(title, font_name=font_bold, font_size=11)
        add_gap(2)

    def draw_student_list_first_page(entries: list[dict[str, str]]) -> None:
        nonlocal y
        draw_section("Liste des eleves")
        if not entries:
            draw_text("Aucun eleve n'est inscrit dans cette classe.", font_name=font_regular, indent=8)
            add_gap(7)
            return

        column_count = 2
        column_gap = 16
        row_height = 10
        reserve_bottom = bottom + 80
        max_rows = max(1, int((y - reserve_bottom) // row_height))
        max_items = max_rows * column_count
        visible = list(entries)
        if len(visible) > max_items:
            keep = max(1, max_items - 1)
            hidden = len(visible) - keep
            visible = visible[:keep] + [{"code": "", "name": f"... et {hidden} autres eleves"}]

        row_count = (len(visible) + column_count - 1) // column_count
        left_col_x = left + 8
        col_width = max(120, (content_width - column_gap) / column_count)
        right_col_x = left_col_x + col_width + column_gap

        def trim_to_width(text: str, max_width: float) -> str:
            value = str(text or "").strip()
            if not value:
                return ""
            if pdfmetrics.stringWidth(value, font_regular, 8) <= max_width:
                return value
            suffix = "..."
            candidate = value
            while candidate and pdfmetrics.stringWidth(f"{candidate}{suffix}", font_regular, 8) > max_width:
                candidate = candidate[:-1]
            candidate = candidate.rstrip()
            return f"{candidate}{suffix}" if candidate else suffix

        def draw_student_entry(x: float, entry: dict[str, str]) -> None:
            code = str(entry.get("code") or "").strip()
            name_raw = str(entry.get("name") or "").strip()
            if not code:
                plain = trim_to_width(f"- {name_raw}", col_width)
                pdf.drawString(x, y, _shape_arabic_text(plain))
                return

            code_text = trim_to_width(f"- {code}", col_width * 0.42)
            code_width = pdfmetrics.stringWidth(code_text, font_regular, 8)
            name_width = max(20.0, col_width - code_width - 6.0)
            name_text = trim_to_width(name_raw, name_width)
            pdf.drawString(x, y, code_text)
            pdf.drawRightString(x + col_width, y, _shape_arabic_text(name_text))

        pdf.setFont(font_regular, 8)
        for row_idx in range(row_count):
            left_entry = visible[row_idx] if row_idx < len(visible) else None
            right_index = row_idx + row_count
            right_entry = visible[right_index] if right_index < len(visible) else None
            if left_entry:
                draw_student_entry(left_col_x, left_entry)
            if right_entry:
                draw_student_entry(right_col_x, right_entry)
            y -= row_height
        add_gap(7)

    draw_section("Vue d'ensemble")
    draw_text(
        f"Ce document presente, en francais, la progression pedagogique observee pour la classe {classroom.name}. "
        "Il est redige sous une forme narrative et structuree afin de pouvoir etre transmis a l'administration."
    )
    draw_text(f"Effectif total : {students_count} eleve(s)")
    draw_text(f"Nombre total de seances sur la periode : {len(sessions)}")
    draw_text(f"Nombre d'unites traitees : {len(ordered_unit_labels)}")
    draw_text(
        f"Taux global d'assiduite : {round(attendance_rate * 100, 1)} %"
        if attendance_rate is not None
        else "Taux global d'assiduite : aucune donnee d'assiduite disponible"
    )
    add_gap(7)

    draw_student_list_first_page(student_entries)

    draw_section("Progression des unites")
    if not ordered_unit_labels:
        draw_text("Aucune seance n'a ete trouvee sur la periode selectionnee.", font_name=font_regular)
    else:
        for index, label in enumerate(ordered_unit_labels, start=1):
            stats = unit_summary.get(label) or {"sessions": 0, "checked_items": 0}
            draw_text(
                f"{index}. {label} : {int(stats['sessions'])} seance(s), "
                f"{int(stats['checked_items'])} point(s) de progression confirme(s).",
                indent=8,
            )
    add_gap(7)

    draw_section("Presentation des seances")
    if not sessions:
        draw_text("Aucune seance a integrer dans ce document.")
    else:
        for index, session in enumerate(sessions, start=1):
            ensure_space(8)
            date_label = _format_date_french(session.session_date)
            window = f"{_format_time(session.start_time)} - {_format_time(session.end_time)}"
            unit = unit_by_id.get(int(session.unit_id)) if session.unit_id is not None else None
            unit_label = (
                f"{unit.title} ({_unit_type_label_fr(unit.unit_type.value)})"
                if unit is not None
                else "Seance generale de classe"
            )
            draw_text(f"Seance {index} : {date_label} ({window})", font_name=font_bold, font_size=10)
            draw_text(f"Unite : {unit_label}", indent=8)

            session_id = int(session.id)
            ai_block = ai_narrative_by_session.get(session_id, {})
            writeup = writeup_by_session.get(session_id)
            session_content = list(session_content_by_session.get(session_id) or _default_focus_items())
            draw_text("Contenus de la seance :", indent=8, font_name=font_bold)
            if checked_titles_by_session.get(session_id):
                draw_text("Checklist :", indent=16, font_name=font_bold)
                list_indent = 24
            else:
                list_indent = 16
            for item in session_content[:12]:
                draw_text(f"- {item}", indent=list_indent)

            note_text = str(session.note or "").strip()
            writeup_paragraphs = (
                [str(value) for value in writeup.teaching_content_json if str(value or "").strip()]
                if writeup is not None and isinstance(writeup.teaching_content_json, list)
                else []
            )
            paragraph_text = _ensure_sentence(" ".join(writeup_paragraphs[:3]).strip())
            if not paragraph_text:
                paragraph_text = _ensure_sentence(str(ai_block.get("paragraph") or ""))
            if not paragraph_text:
                fallback_focus = _extract_focus_items_from_checked_titles(session_content) or _default_focus_items()
                paragraph_text = _fallback_session_narrative(focus_items=fallback_focus, note_text=note_text)
            draw_text(f"Developpement pedagogique : {paragraph_text}", indent=8)

            writeup_practice = (
                [str(value) for value in writeup.practice_items_json if str(value or "").strip()]
                if writeup is not None and isinstance(writeup.practice_items_json, list)
                else []
            )
            if writeup_practice:
                draw_text("Exercices et entrainement :", indent=8, font_name=font_bold)
                for item in writeup_practice[:6]:
                    draw_text(f"- {item}", indent=16)

            attendance = attendance_counts_by_session.get(int(session.id), {})
            present = int(attendance.get(AttendanceStatus.PRESENT.value, 0))
            absent = int(attendance.get(AttendanceStatus.ABSENT.value, 0))
            late = int(attendance.get(AttendanceStatus.LATE.value, 0))
            excused = int(attendance.get(AttendanceStatus.EXCUSED.value, 0))
            draw_text(
                f"Assiduite : presents {present}, absents {absent}, retards {late}, dispenses {excused}.",
                indent=8,
            )
            add_gap(7)

    pdf.save()
    output.seek(0)
    return output.read()


def build_student_profile_pdf(
    db: Session,
    class_id: int,
    student_id: int,
    *,
    mask_personal_data: bool = False,
    masked_student_code: str | None = None,
    masked_full_name: str | None = None,
) -> bytes:
    classroom = db.get(Classroom, class_id)
    if classroom is None:
        raise ValueError("Class not found.")
    student = db.get(Student, student_id)
    if student is None or student.class_id != class_id:
        raise ValueError("Student not found in class.")

    attendance_rows = db.execute(
        select(
            ClassSession.session_date,
            AttendanceRecord.status,
            AttendanceRecord.minutes_late,
            AttendanceRecord.comment,
        )
        .join(ClassSession, AttendanceRecord.session_id == ClassSession.id)
        .where(
            AttendanceRecord.student_id == student_id,
            ClassSession.class_id == class_id,
        )
        .order_by(ClassSession.session_date.asc(), ClassSession.id.asc())
    ).all()
    attendance_counts = {"present": 0, "absent": 0, "late": 0, "excused": 0}
    for row in attendance_rows:
        attendance_counts[row.status.value] += 1

    exam_rows = db.execute(
        select(
            Exam.title,
            Exam.exam_date,
            Exam.max_score,
            ExamResult.score,
            ExamResult.note,
            ExamResult.teacher_comment,
        )
        .join(ExamResult, ExamResult.exam_id == Exam.id)
        .where(
            Exam.class_id == class_id,
            ExamResult.student_id == student_id,
        )
        .order_by(Exam.exam_date.asc(), Exam.id.asc())
    ).all()
    scores = [float(row.score) for row in exam_rows]
    average_score = round(sum(scores) / len(scores), 2) if scores else None

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    _, height = A4
    x = 40
    y = height - 40

    display_name = masked_full_name if mask_personal_data and masked_full_name else student.full_name
    display_code = masked_student_code if mask_personal_data and masked_student_code else student.student_code

    y = _line(pdf, f"Student Profile Report: {display_name}", x, y)
    y = _line(pdf, f"Class: {classroom.name}", x, y)
    y = _line(pdf, f"Student Code: {display_code}", x, y)
    y = _line(pdf, f"Privacy mode: {'masked' if mask_personal_data else 'full'}", x, y)
    y = _line(pdf, "", x, y)
    y = _line(
        pdf,
        (
            "Attendance totals -> "
            f"present:{attendance_counts['present']} absent:{attendance_counts['absent']} "
            f"late:{attendance_counts['late']} excused:{attendance_counts['excused']}"
        ),
        x,
        y,
    )
    y = _line(pdf, f"Attendance rows: {len(attendance_rows)}", x, y)
    y = _line(pdf, "", x, y)
    y = _line(pdf, "Attendance Details:", x, y)

    for row in attendance_rows:
        if y < 90:
            pdf.showPage()
            y = height - 40
        late = f" ({row.minutes_late}m late)" if row.status.value == "late" and row.minutes_late else ""
        comment = f" | {row.comment}" if row.comment else ""
        y = _line(pdf, f"- {row.session_date.isoformat()} | {row.status.value}{late}{comment}", x, y)

    if y < 90:
        pdf.showPage()
        y = height - 40
    y = _line(pdf, "", x, y)
    y = _line(pdf, f"Exam Summary: count={len(exam_rows)} average={average_score if average_score is not None else '-'}", x, y)
    for row in exam_rows:
        if y < 90:
            pdf.showPage()
            y = height - 40
        note = f" | note:{row.note}" if row.note else ""
        comment = f" | comment:{row.teacher_comment}" if row.teacher_comment else ""
        y = _line(
            pdf,
            f"- {row.exam_date.isoformat()} {row.title}: {row.score}/{row.max_score}{note}{comment}",
            x,
            y,
        )

    pdf.save()
    output.seek(0)
    return output.read()
