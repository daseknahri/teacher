from __future__ import annotations

from io import BytesIO
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook
from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..config import MAX_SCREENSHOT_UPLOAD_BYTES, UPLOADS_DIR
from ..database import get_db
from ..models import (
    AttendanceRecord,
    AttendanceStatus,
    ClassAccess,
    ClassSession,
    ClassTimetableRule,
    Classroom,
    HolidayDay,
    TimetableVersion,
    TimetableRuleException,
    TimetableClassAlias,
    Exam,
    ExamResult,
    Student,
    User,
    UserRole,
    ProgressItem,
    ProgressItemType,
    SessionUpload,
    WorkflowChecklistItem,
    WorkflowChecklistItemAttachment,
    WorkflowChecklistItemKind,
    WorkflowLeafContent,
    WorkflowPreparedSection,
    WorkflowSessionChecklistAction,
    WorkflowUnitAssistantArtifact,
    WorkflowUnitMaterial,
    WorkflowSessionWriteup,
    WorkflowUnit,
    WorkflowUnitBlueprint,
    WorkflowUnitStatus,
    WorkflowUnitType,
)
from ..schemas import (
    ClassSetupInitIn,
    ClassSetupInitOut,
    HolidayDayOut,
    HolidayDayUpdateIn,
    ClassSetupStudentIn,
    TimetableImportApplyOut,
    TimetableImportApplyRowOut,
    TimetableVersionCompareOut,
    TimetableVersionCreateIn,
    TimetableVersionDetailOut,
    TimetableVersionExceptionOut,
    TimetableVersionOut,
    TimetableVersionRestoreOut,
    TimetableVersionRuleOut,
    TimetableClassAliasBulkSaveIn,
    TimetableClassAliasBulkSaveOut,
    TimetableClassAliasOut,
    TimetableClassAliasUpdateIn,
    TimetableRuleExceptionCreateIn,
    TimetableRuleExceptionOut,
    TimetableRuleExceptionUpdateIn,
    TimetableImportPreviewOut,
    TimetableRuleOut,
    ClassSetupTimetableRowIn,
    WorkflowCalendarSessionCreateIn,
    WorkflowCalendarAutoPlanIn,
    WorkflowCalendarAutoPlanOut,
    WorkflowCalendarPlannedSlotOut,
    WorkflowCalendarSlotActionIn,
    WorkflowCalendarSlotActionOut,
    WorkflowCalendarEventOut,
    WorkflowChecklistItemCreateIn,
    WorkflowChecklistItemAttachmentOut,
    WorkflowChecklistReorderIn,
    WorkflowChecklistReorderItemIn,
    WorkflowChecklistItemOut,
    WorkflowChecklistItemUpdateIn,
    WorkflowSessionConfirmIn,
    WorkflowSessionConfirmOut,
    WorkflowSessionEndIn,
    WorkflowSessionEnsureNextOut,
    WorkflowSessionOut,
    WorkflowSessionWriteupGenerateIn,
    WorkflowSessionWriteupImportAssistantIn,
    WorkflowSessionWriteupOut,
    WorkflowSessionWriteupUpdateIn,
    WorkflowSessionStartIn,
    WorkflowToggleItemIn,
    WorkflowUnitAssistantIn,
    WorkflowUnitAssistantArtifactOut,
    WorkflowUnitAssistantArtifactSaveIn,
    WorkflowUnitAssistantOut,
    WorkflowUnitMaterialGenerateIn,
    WorkflowUnitMaterialOut,
    WorkflowUnitExtractionReviewIn,
    WorkflowUnitBlueprintOut,
    WorkflowUnitDeleteOut,
    WorkflowExamLinkedUnitCreateIn,
    WorkflowExamLinkedUnitCreateOut,
    WorkflowUnitOut,
    WorkflowWorkspaceOut,
    WorkflowLeafContentGenerateIn,
    WorkflowLeafContentGenerateOut,
    WorkflowLeafContentOut,
    WorkflowLeafContentSummaryOut,
    WorkflowLeafContentUpsertIn,
    WorkflowPreparedSectionOut,
    WorkflowPreparedSectionPrepareIn,
    WorkflowPreparedSectionSummaryOut,
    WorkflowSectionLessonOut,
    WorkflowSectionLessonRequestIn,
)
from ..security import ensure_class_access, ensure_class_writable, get_current_user, require_owner, require_teacher
from ..services.audit import log_audit
from ..services.rate_limit import enforce_rate_limit
from ..services.upload_validation import (
    ALLOWED_EXCEL_EXTENSIONS,
    ALLOWED_EXCEL_MIME_TYPES,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIME_TYPES,
    read_validated_upload,
)
from ..services.holidays import (
    find_blocked_holiday,
    list_holidays_for_year,
    seed_morocco_fixed_holidays,
    upsert_owner_uploaded_holidays,
)
from ..services.timetable_import import (
    WEEKDAY_LABELS,
    parse_timetable_csv_preview,
    parse_timetable_ics_preview,
    parse_timetable_xlsx_preview,
)
from ..services.workflow import extract_text_from_document, generate_unit_checklist
from ..services.workflow_content import (
    _serialize_checked_item_contexts,
    build_session_outline_rows,
    build_document_hash,
    generate_and_store_session_writeup,
    save_unit_blueprint,
)
from ..services.workflow_generation import (
    NotebookLMGenerationUnavailableError,
    build_section_key,
    build_raw_section_index,
    build_raw_section_lesson_package,
    build_source_section_index,
    build_source_derived_leaf_content_package,
    build_source_section_lesson_package,
    delete_provider_unit_context,
    generate_leaf_content_package,
    initialize_unit_notebooklm_context,
    generate_unit_assistant_package,
    generate_unit_material_package,
    render_section_latex_source,
)
from ..services.report import build_calendar_summary_pdf
from ..services.excel import build_holiday_export_workbook, build_holiday_import_template, parse_holiday_excel


ALLOWED_WORKFLOW_DOC_EXTENSIONS = {".pdf"}
ALLOWED_WORKFLOW_DOC_MIME_TYPES = {
    "application/pdf",
}
ALLOWED_TIMETABLE_IMPORT_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".ics"}
ALLOWED_TIMETABLE_IMPORT_MIME_TYPES = {
    "text/csv",
    "application/csv",
    "text/calendar",
    "application/ics",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/octet-stream",
}

router = APIRouter(prefix="/workflow", tags=["workflow"], dependencies=[Depends(require_teacher)])
NON_WORKING_WEEKDAYS: set[int] = {7}  # Sunday
NUMBERED_ROW_START_PATTERN = re.compile(r"(?<!\S)\d+(?:\.\d+)+(?:[)\].:-])?(?:\s+|$)")
SLUG_LIKE_TITLE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$", re.IGNORECASE)
OUTLINE_BULLET_PREFIX_PATTERN = re.compile(r"^(?:[-*•]\s+|[a-zA-Z]\)\s+|\d+[.)]\s+|[ivxlcdmIVXLCDM]+[.)]\s+)")
logger = logging.getLogger("teacher_progress.workflow")
EXAM_TITLE_KEYWORD_PATTERN = re.compile(
    r"\b(examen|exam|devoir(?:\s+surveille)?|devoir\s+surveillé|controle|contr[oô]le|evaluation|évaluation|ds)\b",
    re.IGNORECASE,
)


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_non_working_day(value: date | None) -> bool:
    if value is None:
        return False
    return int(value.isoweekday()) in NON_WORKING_WEEKDAYS


def _safe_unlink(path_value: str | None) -> bool:
    if not path_value:
        return False
    try:
        path = Path(path_value)
    except Exception:
        return False
    try:
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except Exception:
        return False
    return False


def _ensure_active_unit(db: Session, class_id: int) -> WorkflowUnit:
    unit = db.scalar(
        select(WorkflowUnit)
        .where(WorkflowUnit.class_id == class_id, WorkflowUnit.status == WorkflowUnitStatus.ACTIVE)
        .order_by(WorkflowUnit.id.desc())
    )
    if unit is None:
        raise HTTPException(status_code=404, detail="No active unit found. Start a unit first.")
    return unit


def _upsert_session_action(db: Session, *, session_id: int, item_id: int, checked: bool) -> None:
    for pending in db.new:
        if not isinstance(pending, WorkflowSessionChecklistAction):
            continue
        if int(pending.session_id) == int(session_id) and int(pending.item_id) == int(item_id):
            pending.checked = checked
            return
    row = db.scalar(
        select(WorkflowSessionChecklistAction).where(
            WorkflowSessionChecklistAction.session_id == session_id,
            WorkflowSessionChecklistAction.item_id == item_id,
        )
    )
    if row is None:
        db.add(WorkflowSessionChecklistAction(session_id=session_id, item_id=item_id, checked=checked))
    else:
        row.checked = checked


def _refresh_item_completion(db: Session, item_id: int) -> None:
    item = db.get(WorkflowChecklistItem, item_id)
    if item is None:
        return
    children = db.scalars(
        select(WorkflowChecklistItem).where(WorkflowChecklistItem.parent_item_id == item_id).order_by(WorkflowChecklistItem.position.asc())
    ).all()
    if children:
        all_done = all(bool(child.is_completed) for child in children)
        if all_done:
            latest_child_session_id = next(
                (
                    int(child.completed_session_id)
                    for child in reversed(children)
                    if child.completed_session_id is not None
                ),
                None,
            )
            latest_child_completed_at = next(
                (
                    child.completed_at
                    for child in reversed(children)
                    if child.completed_at is not None
                ),
                None,
            )
            item.is_completed = True
            item.completed_session_id = latest_child_session_id
            item.completed_at = latest_child_completed_at
        else:
            item.is_completed = False
            item.completed_session_id = None
            item.completed_at = None
        return
    latest = db.scalar(
        select(WorkflowSessionChecklistAction)
        .where(WorkflowSessionChecklistAction.item_id == item_id)
        .order_by(
            WorkflowSessionChecklistAction.updated_at.desc(),
            WorkflowSessionChecklistAction.id.desc(),
        )
    )
    if latest and latest.checked:
        item.is_completed = True
        item.completed_session_id = latest.session_id
        item.completed_at = latest.updated_at
    else:
        item.is_completed = False
        item.completed_session_id = None
        item.completed_at = None


def _descendant_ids(db: Session, unit_id: int, root_item_id: int) -> list[int]:
    rows = db.execute(
        select(WorkflowChecklistItem.id, WorkflowChecklistItem.parent_item_id).where(WorkflowChecklistItem.unit_id == unit_id)
    ).all()
    if not rows:
        return []

    children_by_parent: dict[int, list[int]] = {}
    for row in rows:
        item_id = int(row.id)
        parent_id = row.parent_item_id
        if parent_id is None:
            continue
        children_by_parent.setdefault(int(parent_id), []).append(item_id)

    result: list[int] = []
    frontier = list(children_by_parent.get(int(root_item_id), []))
    while frontier:
        child_id = frontier.pop(0)
        result.append(child_id)
        frontier.extend(children_by_parent.get(child_id, []))
    return result


def _refresh_ancestors_completion(db: Session, item_id: int, session_id: int) -> None:
    current = db.get(WorkflowChecklistItem, item_id)
    while current is not None and current.parent_item_id is not None:
        parent = db.get(WorkflowChecklistItem, current.parent_item_id)
        if parent is None:
            return
        children = db.scalars(
            select(WorkflowChecklistItem).where(WorkflowChecklistItem.parent_item_id == parent.id).order_by(WorkflowChecklistItem.position.asc())
        ).all()
        all_done = bool(children) and all(child.is_completed for child in children)
        _upsert_session_action(db, session_id=session_id, item_id=parent.id, checked=all_done)
        if all_done:
            parent.is_completed = True
            parent.completed_session_id = session_id
            parent.completed_at = _utc_now_naive()
        else:
            parent.is_completed = False
            parent.completed_session_id = None
            parent.completed_at = None
        current = parent


def _filter_actionable_check_item_ids(db: Session, *, unit_id: int, item_ids: list[int]) -> list[int]:
    normalized_ids = sorted({int(value) for value in (item_ids or []) if int(value) > 0})
    if not normalized_ids:
        return []

    rows = db.scalars(
        select(WorkflowChecklistItem).where(WorkflowChecklistItem.unit_id == int(unit_id))
    ).all()
    if not rows:
        return []

    child_counts: dict[int, int] = {}
    by_id: dict[int, WorkflowChecklistItem] = {}
    for row in rows:
        by_id[int(row.id)] = row
        if row.parent_item_id is not None:
            parent_id = int(row.parent_item_id)
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1

    actionable_ids: list[int] = []
    for item_id in normalized_ids:
        item = by_id.get(int(item_id))
        if item is None:
            continue
        if child_counts.get(int(item.id), 0) > 0:
            continue
        actionable_ids.append(int(item.id))
    return actionable_ids


def _derive_leaf_item_paths(db: Session, *, unit_id: int, item_id: int) -> tuple[list[str] | None, list[str] | None]:
    items = db.scalars(
        select(WorkflowChecklistItem)
        .where(WorkflowChecklistItem.unit_id == int(unit_id))
        .order_by(WorkflowChecklistItem.position.asc(), WorkflowChecklistItem.id.asc())
    ).all()
    if not items:
        return None, None

    by_id = {int(row.id): row for row in items}
    row = by_id.get(int(item_id))
    if row is None:
        return None, None

    structural_kinds = {
        WorkflowChecklistItemKind.CHAPTER.value,
        WorkflowChecklistItemKind.SECTION.value,
        WorkflowChecklistItemKind.SUBSECTION.value,
    }

    path_nodes: list[WorkflowChecklistItem] = []
    seen_ids: set[int] = set()
    current = row
    while current is not None and int(current.id) not in seen_ids:
        seen_ids.add(int(current.id))
        path_nodes.append(current)
        parent_id = int(current.parent_item_id) if current.parent_item_id is not None else 0
        current = by_id.get(parent_id) if parent_id > 0 else None
    path_nodes.reverse()

    item_path = [str(node.title or "").strip() for node in path_nodes if str(node.title or "").strip()]
    if not item_path:
        return None, None

    section_path = [
        str(node.title or "").strip()
        for node in path_nodes
        if str(node.title or "").strip()
        and str(getattr(node.item_kind, "value", node.item_kind) or "").strip().lower() in structural_kinds
    ]
    if not section_path:
        section_path = item_path[:-1] or item_path
    return item_path, section_path


_LEAF_CONTENT_PAYLOAD_FIELDS = (
    "teaching_goal_md",
    "launch_activity_md",
    "explanation_md",
    "worked_example_md",
    "practice_md",
    "solution_md",
    "assessment_md",
    "teacher_notes_md",
    "source_excerpt_md",
)


def _leaf_content_payload_has_content(payload: dict[str, object] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(bool(str(payload.get(field) or "").strip()) for field in _LEAF_CONTENT_PAYLOAD_FIELDS)


def _apply_leaf_content_payload_to_row(
    row: WorkflowLeafContent,
    payload: dict[str, object],
    *,
    item_path: list[str] | None = None,
    section_path: list[str] | None = None,
    preserve_existing_paths: bool = True,
) -> None:
    if item_path is not None and (not preserve_existing_paths or row.item_path_json is None):
        row.item_path_json = [str(value).strip() for value in item_path if str(value).strip()] or None
    if section_path is not None and (not preserve_existing_paths or row.section_path_json is None):
        row.section_path_json = [str(value).strip() for value in section_path if str(value).strip()] or None

    row.provider = str(payload.get("provider") or row.provider or "manual").strip() or "manual"
    row.model = str(payload.get("model") or "").strip() or None
    row.status = str(payload.get("status") or row.status or "draft").strip() or "draft"

    for field in _LEAF_CONTENT_PAYLOAD_FIELDS:
        value = payload.get(field)
        setattr(row, field, str(value).strip() or None if value is not None else None)

    if isinstance(payload.get("source_payload"), dict):
        row.source_payload_json = {
            **payload["source_payload"],
            "item_path": row.item_path_json or [],
            "section_path": row.section_path_json or [],
        }
    elif "source_payload" in payload:
        row.source_payload_json = None

    if isinstance(payload.get("raw_provider_response"), dict):
        row.raw_provider_response_json = payload["raw_provider_response"]
    elif "raw_provider_response" in payload:
        row.raw_provider_response_json = None

    row.updated_at = _utc_now_naive()


def _leaf_content_field_has_value(value: object | None) -> bool:
    return bool(str(value or "").strip())


def _merge_generated_leaf_content_payload(
    *,
    existing: WorkflowLeafContent | None,
    generated: dict[str, object],
    merge_strategy: str,
    item_path: list[str] | None,
    section_path: list[str] | None,
) -> dict[str, object]:
    normalized_strategy = str(merge_strategy or "fill_missing").strip().lower() or "fill_missing"
    replace_all = normalized_strategy == "replace" or existing is None

    merged: dict[str, object] = dict(generated)
    filled_fields: list[str] = []
    retained_fields: list[str] = []

    if not replace_all and existing is not None:
        for field in _LEAF_CONTENT_PAYLOAD_FIELDS:
            existing_value = getattr(existing, field, None)
            generated_value = generated.get(field)
            if _leaf_content_field_has_value(existing_value):
                if not _leaf_content_field_has_value(generated_value):
                    retained_fields.append(field)
                else:
                    retained_fields.append(field)
                merged[field] = existing_value
            elif _leaf_content_field_has_value(generated_value):
                filled_fields.append(field)
                merged[field] = generated_value
            else:
                merged[field] = None

        base_source_payload = existing.source_payload_json if isinstance(existing.source_payload_json, dict) else None
        enhancement_source_payload = generated.get("source_payload") if isinstance(generated.get("source_payload"), dict) else None
        merged["source_payload"] = {
            "mode": "hybrid" if filled_fields else str((base_source_payload or {}).get("mode") or "source_derived"),
            "base": base_source_payload,
            "enhancement": enhancement_source_payload,
            "merge_strategy": normalized_strategy,
            "filled_fields": filled_fields,
            "retained_fields": retained_fields,
            "item_path": item_path or [],
            "section_path": section_path or [],
        }
        base_raw = existing.raw_provider_response_json if isinstance(existing.raw_provider_response_json, dict) else None
        enhancement_raw = generated.get("raw_provider_response") if isinstance(generated.get("raw_provider_response"), dict) else None
        merged["raw_provider_response"] = {
            "base": base_raw,
            "enhancement": enhancement_raw,
            "merge_strategy": normalized_strategy,
        }
        merged["provider"] = str(generated.get("provider") or existing.provider or "manual").strip() or "manual"
        merged["status"] = "ready" if any(_leaf_content_field_has_value(merged.get(field)) for field in _LEAF_CONTENT_PAYLOAD_FIELDS) else str(generated.get("status") or existing.status or "draft")
    else:
        merged["source_payload"] = {
            **(generated.get("source_payload") if isinstance(generated.get("source_payload"), dict) else {}),
            "merge_strategy": "replace",
            "item_path": item_path or [],
            "section_path": section_path or [],
        }
    return merged


def _seed_unit_leaf_content_from_blueprint(
    db: Session,
    *,
    unit_id: int,
    item_id: int | None = None,
) -> int:
    blueprint = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    content_blocks = blueprint.content_blocks_json if blueprint and isinstance(blueprint.content_blocks_json, list) else None
    if not content_blocks:
        return 0

    child_counts = {
        int(parent_id): int(count or 0)
        for parent_id, count in db.execute(
            select(WorkflowChecklistItem.parent_item_id, func.count(WorkflowChecklistItem.id))
            .where(WorkflowChecklistItem.unit_id == int(unit_id))
            .group_by(WorkflowChecklistItem.parent_item_id)
        ).all()
        if parent_id is not None
    }

    leaf_query = select(WorkflowChecklistItem).where(WorkflowChecklistItem.unit_id == int(unit_id))
    if item_id is not None:
        leaf_query = leaf_query.where(WorkflowChecklistItem.id == int(item_id))
    items = db.scalars(
        leaf_query.order_by(WorkflowChecklistItem.position.asc(), WorkflowChecklistItem.id.asc())
    ).all()

    existing_by_item_id = {
        int(row.checklist_item_id): row
        for row in db.scalars(
            select(WorkflowLeafContent).where(WorkflowLeafContent.unit_id == int(unit_id))
        ).all()
    }

    created_or_updated = 0
    for item in items:
        if child_counts.get(int(item.id), 0) > 0:
            continue
        if int(item.id) in existing_by_item_id:
            continue

        item_path, section_path = _derive_leaf_item_paths(db, unit_id=int(unit_id), item_id=int(item.id))
        payload = build_source_derived_leaf_content_package(
            item_title=str(item.title or "").strip(),
            item_kind=item.item_kind,
            item_path=item_path,
            section_path=section_path,
            content_blocks=content_blocks,
        )
        if not _leaf_content_payload_has_content(payload):
            continue

        row = WorkflowLeafContent(unit_id=int(unit_id), checklist_item_id=int(item.id))
        db.add(row)
        _apply_leaf_content_payload_to_row(
            row,
            payload,
            item_path=item_path,
            section_path=section_path,
            preserve_existing_paths=False,
        )
        created_or_updated += 1

    if created_or_updated:
        db.flush()
    return created_or_updated


def _serialize_prepared_section_summary(row: WorkflowPreparedSection) -> WorkflowPreparedSectionSummaryOut:
    source_blocks = row.source_blocks_json if isinstance(row.source_blocks_json, list) else []
    return WorkflowPreparedSectionSummaryOut(
        id=int(row.id),
        unit_id=int(row.unit_id),
        section_key=str(row.section_key or "").strip(),
        section_title=str(row.section_title or "").strip() or "Section",
        section_path_json=[str(value).strip() for value in (row.section_path_json or []) if str(value).strip()],
        order_index=int(row.order_index or 0),
        status=str(row.status or "indexed").strip() or "indexed",
        benchmark_status=str(row.benchmark_status or "pending").strip() or "pending",
        error_message=str(row.error_message or "").strip() or None,
        source_block_count=len([block for block in source_blocks if isinstance(block, dict) and str(block.get("content_md") or "").strip()]),
        provider=str(row.provider or "notebooklm").strip() or "notebooklm",
        updated_at=row.updated_at or row.created_at or _utc_now_naive(),
    )


def _serialize_prepared_section(row: WorkflowPreparedSection) -> WorkflowPreparedSectionOut:
    source_blocks = row.source_blocks_json if isinstance(row.source_blocks_json, list) else []
    return WorkflowPreparedSectionOut(
        id=int(row.id),
        unit_id=int(row.unit_id),
        section_key=str(row.section_key or "").strip(),
        section_title=str(row.section_title or "").strip() or "Section",
        section_path_json=[str(value).strip() for value in (row.section_path_json or []) if str(value).strip()],
        order_index=int(row.order_index or 0),
        source_blocks_json=source_blocks,
        source_excerpt_md=str(row.source_excerpt_md or "").strip() or None,
        latex_source=str(row.latex_source or "").strip() or None,
        provider=str(row.provider or "notebooklm").strip() or "notebooklm",
        model=str(row.model or "").strip() or None,
        status=str(row.status or "indexed").strip() or "indexed",
        benchmark_status=str(row.benchmark_status or "pending").strip() or "pending",
        benchmark_notes_md=str(row.benchmark_notes_md or "").strip() or None,
        raw_provider_response_json=row.raw_provider_response_json if isinstance(row.raw_provider_response_json, dict) else None,
        error_message=str(row.error_message or "").strip() or None,
        created_at=row.created_at or _utc_now_naive(),
        updated_at=row.updated_at or row.created_at or _utc_now_naive(),
    )


def _serialize_section_lesson_from_record(
    row: WorkflowPreparedSection,
    *,
    item_path: list[str] | None = None,
    item_title: str | None = None,
) -> WorkflowSectionLessonOut:
    source_blocks = row.source_blocks_json if isinstance(row.source_blocks_json, list) else []
    return WorkflowSectionLessonOut(
        section_title=str(row.section_title or "").strip() or "Section",
        section_path_json=[str(value).strip() for value in (row.section_path_json or []) if str(value).strip()],
        item_path_json=[str(value).strip() for value in (item_path or []) if str(value).strip()],
        item_title=str(item_title or "").strip() or None,
        source_block_count=len([block for block in source_blocks if isinstance(block, dict) and str(block.get("content_md") or "").strip()]),
        source_blocks=source_blocks,
        source_excerpt_md=str(row.source_excerpt_md or "").strip() or None,
    )


def _normalize_section_path_input(section_path: list[str] | None, *, fallback_title: str | None = None) -> list[str]:
    output = [str(value).strip() for value in (section_path or []) if str(value).strip()]
    if output:
        return output
    fallback = str(fallback_title or "").strip()
    return [fallback] if fallback else []


def _blueprint_content_pack(blueprint: WorkflowUnitBlueprint | None) -> dict | None:
    if blueprint is None or not isinstance(blueprint.raw_provider_response, dict):
        return None
    payload = blueprint.raw_provider_response.get("content_pack")
    return payload if isinstance(payload, dict) else None


def _index_unit_prepared_sections(
    db: Session,
    *,
    unit: WorkflowUnit,
    blueprint: WorkflowUnitBlueprint,
) -> list[WorkflowPreparedSection]:
    content_pack = _blueprint_content_pack(blueprint)
    section_rows = build_raw_section_index(content_pack) if content_pack else []
    if not section_rows:
        content_blocks = blueprint.content_blocks_json if isinstance(blueprint.content_blocks_json, list) else []
        section_rows = build_source_section_index(content_blocks)
    db.execute(delete(WorkflowPreparedSection).where(WorkflowPreparedSection.unit_id == int(unit.id)))
    created: list[WorkflowPreparedSection] = []
    provider_name = str(blueprint.provider or "notebooklm").strip() or "notebooklm"
    model_name = str(blueprint.model or "").strip() or None
    for row in section_rows:
        record = WorkflowPreparedSection(
            unit_id=int(unit.id),
            section_key=str(row.get("section_key") or "").strip() or build_section_key(row.get("section_path_json"), fallback_title=row.get("section_title")),
            section_title=str(row.get("section_title") or "").strip() or "Section",
            section_path_json=[str(value).strip() for value in (row.get("section_path_json") or []) if str(value).strip()] or None,
            order_index=int(row.get("order_index") or 0),
            provider=provider_name,
            model=model_name,
            status="indexed",
            benchmark_status="pending",
            raw_provider_response_json={
                "mode": "section_index",
                "provider": provider_name,
                "section_path": row.get("section_path_json") or [],
            },
        )
        db.add(record)
        created.append(record)
    if created:
        db.flush()
    return created


def _upsert_prepared_section_from_blueprint(
    db: Session,
    *,
    unit: WorkflowUnit,
    blueprint: WorkflowUnitBlueprint,
    section_path: list[str],
) -> WorkflowPreparedSection:
    normalized_section_path = _normalize_section_path_input(section_path)
    if not normalized_section_path:
        raise HTTPException(status_code=400, detail="section_path is required.")
    section_key = build_section_key(normalized_section_path, fallback_title=normalized_section_path[-1])
    record = db.scalar(
        select(WorkflowPreparedSection).where(
            WorkflowPreparedSection.unit_id == int(unit.id),
            WorkflowPreparedSection.section_key == section_key,
        )
    )
    if record is None:
        record = WorkflowPreparedSection(unit_id=int(unit.id), section_key=section_key)
        db.add(record)
    content_pack = _blueprint_content_pack(blueprint)
    lesson = build_raw_section_lesson_package(
        section_title=normalized_section_path[-1],
        section_path=normalized_section_path,
        content_pack=content_pack,
    ) if content_pack else None
    if lesson is None:
        lesson = build_source_section_lesson_package(
            section_title=normalized_section_path[-1],
            section_path=normalized_section_path,
            content_blocks=blueprint.content_blocks_json if isinstance(blueprint.content_blocks_json, list) else [],
        )
    source_blocks = lesson.get("source_blocks") if isinstance(lesson.get("source_blocks"), list) else []
    source_excerpt_md = str(lesson.get("source_excerpt_md") or "").strip() or None
    record.section_key = section_key
    record.section_title = str(lesson.get("section_title") or normalized_section_path[-1]).strip() or normalized_section_path[-1]
    record.section_path_json = normalized_section_path
    record.provider = str(blueprint.provider or "notebooklm").strip() or "notebooklm"
    record.model = str(blueprint.model or "").strip() or None
    indexed_rows = build_raw_section_index(content_pack) if content_pack else []
    if not indexed_rows:
        indexed_rows = build_source_section_index(blueprint.content_blocks_json if isinstance(blueprint.content_blocks_json, list) else [])
    index_lookup = {str(row.get("section_key") or "").strip(): row for row in indexed_rows}
    record.order_index = int((index_lookup.get(section_key) or {}).get("order_index") or 0)
    if source_blocks or source_excerpt_md:
        record.source_blocks_json = source_blocks
        record.source_excerpt_md = source_excerpt_md
        record.latex_source = render_section_latex_source(
            section_title=record.section_title,
            section_path=normalized_section_path,
            source_blocks=source_blocks,
        )
        record.status = "prepared"
        record.error_message = None
        record.raw_provider_response_json = {
            "mode": "section_prepare",
            "provider": record.provider,
            "section_path": normalized_section_path,
            "source_block_count": len(source_blocks),
        }
    else:
        record.source_blocks_json = []
        record.source_excerpt_md = None
        record.latex_source = None
        record.status = "failed"
        record.error_message = "No extracted section content was found for this section."
        record.raw_provider_response_json = {
            "mode": "section_prepare",
            "provider": record.provider,
            "section_path": normalized_section_path,
            "source_block_count": 0,
        }
    record.updated_at = _utc_now_naive()
    db.flush()
    return record


def _build_reorder_maps(
    payload_items: list[WorkflowChecklistReorderItemIn],
    unit_item_ids: set[int],
) -> tuple[dict[int, int | None], dict[int, int], dict[int, int]]:
    if len(payload_items) != len(unit_item_ids):
        raise HTTPException(
            status_code=400,
            detail="Reorder payload must include every checklist item in the unit.",
        )

    parent_by_id: dict[int, int | None] = {}
    raw_position_by_id: dict[int, int] = {}
    seen_ids: set[int] = set()

    for row in payload_items:
        item_id = int(row.id)
        if item_id in seen_ids:
            raise HTTPException(status_code=400, detail="Reorder payload contains duplicate checklist item ids.")
        if item_id not in unit_item_ids:
            raise HTTPException(status_code=404, detail=f"Checklist item {item_id} is not part of this unit.")

        parent_id = int(row.parent_item_id) if row.parent_item_id is not None else None
        if parent_id is not None and parent_id not in unit_item_ids:
            raise HTTPException(status_code=404, detail=f"Parent checklist item {parent_id} is not part of this unit.")
        if parent_id == item_id:
            raise HTTPException(status_code=400, detail="Checklist item cannot be parent of itself.")

        seen_ids.add(item_id)
        parent_by_id[item_id] = parent_id
        raw_position_by_id[item_id] = max(int(row.position), 0)

    missing = unit_item_ids - seen_ids
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing checklist item ids in reorder payload: {sorted(missing)}")

    # Detect parent cycles before writing.
    for item_id in unit_item_ids:
        seen_chain: set[int] = set()
        current_id = item_id
        while True:
            parent_id = parent_by_id.get(current_id)
            if parent_id is None:
                break
            if parent_id == item_id or parent_id in seen_chain:
                raise HTTPException(status_code=400, detail="Invalid parent hierarchy: cycle detected.")
            seen_chain.add(parent_id)
            current_id = parent_id

    depth_cache: dict[int, int] = {}

    def compute_depth(item_id: int) -> int:
        cached = depth_cache.get(item_id)
        if cached is not None:
            return cached
        parent_id = parent_by_id[item_id]
        if parent_id is None:
            depth_cache[item_id] = 0
            return 0
        depth = compute_depth(parent_id) + 1
        depth_cache[item_id] = depth
        return depth

    for item_id in unit_item_ids:
        compute_depth(item_id)

    return parent_by_id, depth_cache, raw_position_by_id


def _serialize_checklist(items: list[WorkflowChecklistItem]) -> list[WorkflowChecklistItemOut]:
    by_parent: dict[int | None, list[WorkflowChecklistItem]] = {}
    item_ids: set[int] = set()
    for item in items:
        item_id = _safe_int(item.id, default=0)
        if item_id > 0:
            item_ids.add(item_id)
        parent_item_id = _safe_optional_int(item.parent_item_id)
        by_parent.setdefault(parent_item_id, []).append(item)
    for rows in by_parent.values():
        rows.sort(key=lambda value: (_safe_int(value.position, default=0), _safe_int(value.id, default=0)))

    root_rows: list[WorkflowChecklistItem] = list(by_parent.get(None, []))
    seen_root_ids = {_safe_int(row.id, default=0) for row in root_rows}
    for row in items:
        row_id = _safe_int(row.id, default=0)
        parent_item_id = _safe_optional_int(row.parent_item_id)
        if row_id <= 0 or row_id in seen_root_ids:
            continue
        if parent_item_id is not None and parent_item_id not in item_ids:
            root_rows.append(row)
            seen_root_ids.add(row_id)
    root_rows.sort(key=lambda value: (_safe_int(value.position, default=0), _safe_int(value.id, default=0)))

    def to_node(row: WorkflowChecklistItem, lineage: set[int] | None = None) -> WorkflowChecklistItemOut:
        row_id = _safe_int(row.id, default=0)
        row_lineage = set(lineage or set())
        if row_id > 0 and row_id in row_lineage:
            logger.warning(
                "workflow.checklist_cycle_detected",
                extra={"item_id": row_id, "unit_id": _safe_int(row.unit_id, default=0)},
            )
            child_nodes: list[WorkflowChecklistItemOut] = []
        else:
            next_lineage = set(row_lineage)
            if row_id > 0:
                next_lineage.add(row_id)
            child_nodes = [to_node(child, next_lineage) for child in by_parent.get(row.id, [])]

        return WorkflowChecklistItemOut(
            id=_safe_int(row.id, default=0),
            unit_id=_safe_int(row.unit_id, default=0),
            parent_item_id=_safe_optional_int(row.parent_item_id),
            item_kind=_safe_checklist_kind(row.item_kind),
            title=_normalize_workflow_title(row.title, fallback="Checklist item"),
            position=_safe_int(row.position, default=0),
            depth=max(0, _safe_int(row.depth, default=0)),
            is_completed=bool(row.is_completed),
            completed_session_id=_safe_optional_int(row.completed_session_id),
            completed_at=row.completed_at,
            teacher_note=str(row.teacher_note or "").strip() or None,
            attachments=[
                WorkflowChecklistItemAttachmentOut(
                    id=_safe_int(attachment.id, default=0),
                    item_id=_safe_int(attachment.item_id, default=0),
                    file_name=str(attachment.file_name or "").strip() or None,
                    file_content_type=str(attachment.file_content_type or "").strip() or None,
                    created_at=attachment.created_at,
                )
                for attachment in sorted(
                    list(getattr(row, "attachments", []) or []),
                    key=lambda value: (
                        getattr(value, "created_at", None) or datetime.min,
                        _safe_int(getattr(value, "id", 0), default=0),
                    ),
                    reverse=True,
                )
            ],
            children=child_nodes,
        )

    return [to_node(root) for root in root_rows]


def _safe_int(value, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_workflow_title(value, *, fallback: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    return normalized or fallback


def _next_workflow_unit_order_index(db: Session, *, class_id: int) -> int:
    return int(
        db.scalar(select(func.coalesce(func.max(WorkflowUnit.order_index), 0)).where(WorkflowUnit.class_id == class_id)) or 0
    ) + 1


def _safe_checklist_kind(value) -> WorkflowChecklistItemKind:
    if isinstance(value, WorkflowChecklistItemKind):
        return value
    normalized = str(value or "").strip().lower()
    try:
        return WorkflowChecklistItemKind(normalized)
    except ValueError:
        return WorkflowChecklistItemKind.OTHER


def _safe_serialize_unit(db: Session, unit: WorkflowUnit, *, class_id: int) -> WorkflowUnitOut | None:
    try:
        return _serialize_unit(db, unit)
    except Exception:
        logger.exception(
            "workflow.serialize_unit_failed",
            extra={"class_id": int(class_id), "unit_id": _safe_int(getattr(unit, "id", 0), default=0)},
        )
        try:
            return WorkflowUnitOut(
                id=_safe_int(getattr(unit, "id", 0), default=0),
                class_id=_safe_int(getattr(unit, "class_id", class_id), default=int(class_id)),
                exam_id=_safe_optional_int(getattr(unit, "exam_id", None)),
                exam_title=str(getattr(getattr(unit, "exam", None), "title", "") or "").strip() or None,
                exam_results_count=0,
                exam_results_average_score=None,
                exam_results_passed_count=0,
                unit_type=getattr(unit, "unit_type", WorkflowUnitType.CHAPTER),
                status=getattr(unit, "status", WorkflowUnitStatus.ACTIVE),
                title=_normalize_workflow_title(getattr(unit, "title", None), fallback="Untitled unit"),
                planned_hours=getattr(unit, "planned_hours", None),
                document_name=getattr(unit, "document_name", None),
                created_at=getattr(unit, "created_at", _utc_now_naive()),
                closed_at=getattr(unit, "closed_at", None),
                progress_total=0,
                progress_done=0,
                extraction_source=str(getattr(getattr(unit, "blueprint", None), "provider", "") or "").strip() or None,
                extraction_model=getattr(getattr(unit, "blueprint", None), "model", None),
                extraction_status=str(getattr(getattr(unit, "blueprint", None), "status", "") or "").strip() or None,
                extraction_error=str(getattr(getattr(unit, "blueprint", None), "error_message", "") or "").strip() or None,
                extraction_structure_source=None,
                extraction_notebook_role=None,
                extraction_layout_heading_count=None,
                extraction_ocr_heading_count=None,
                extraction_reviewed=bool(getattr(getattr(unit, "blueprint", None), "reviewed", True)),
                extraction_reviewed_at=getattr(getattr(unit, "blueprint", None), "reviewed_at", None),
                checklist=[],
            )
        except Exception:
            logger.exception(
                "workflow.serialize_unit_fallback_failed",
                extra={"class_id": int(class_id), "unit_id": _safe_int(getattr(unit, "id", 0), default=0)},
            )
            return None


def _serialize_exam_results_summary(db: Session, exam: Exam | None) -> tuple[int, float | None, int]:
    exam_id = _safe_optional_int(getattr(exam, "id", None))
    if exam_id is None:
        return 0, None, 0
    max_score = float(getattr(exam, "max_score", 0) or 0)
    pass_mark = (max_score / 2.0) if max_score > 0 else 10.0
    row = db.execute(
        select(
            func.count(ExamResult.id),
            func.avg(ExamResult.score),
            func.coalesce(
                func.sum(case((ExamResult.score >= pass_mark, 1), else_=0)),
                0,
            ),
        ).where(ExamResult.exam_id == exam_id)
    ).one()
    count = int(row[0] or 0)
    average = float(row[1]) if row[1] is not None else None
    passed = int(row[2] or 0)
    return count, average, passed


def _safe_serialize_session(db: Session, session: ClassSession, *, class_id: int) -> WorkflowSessionOut | None:
    try:
        return _serialize_session(db, session)
    except Exception:
        logger.exception(
            "workflow.serialize_session_failed",
            extra={"class_id": int(class_id), "session_id": _safe_int(getattr(session, "id", 0), default=0)},
        )
        try:
            return WorkflowSessionOut(
                id=_safe_int(getattr(session, "id", 0), default=0),
                class_id=_safe_int(getattr(session, "class_id", class_id), default=int(class_id)),
                unit_id=_safe_optional_int(getattr(session, "unit_id", None)),
                unit_session_number=_safe_optional_int(getattr(session, "unit_session_number", None)),
                session_date=getattr(session, "session_date", date.today()),
                start_time=getattr(session, "start_time", None),
                end_time=getattr(session, "end_time", None),
                note=getattr(session, "note", None),
                absent_count=0,
                absent_student_ids=[],
                checked_items_count=0,
                has_saved_writeup=False,
            )
        except Exception:
            logger.exception(
                "workflow.serialize_session_fallback_failed",
                extra={"class_id": int(class_id), "session_id": _safe_int(getattr(session, "id", 0), default=0)},
            )
            return None


def _serialize_unit(db: Session, unit: WorkflowUnit) -> WorkflowUnitOut:
    items = db.scalars(
        select(WorkflowChecklistItem).where(WorkflowChecklistItem.unit_id == unit.id).order_by(WorkflowChecklistItem.position.asc())
    ).all()
    progress_total = len(items)
    progress_done = sum(1 for item in items if item.is_completed)
    blueprint = unit.blueprint
    blueprint_json = blueprint.blueprint_json if blueprint is not None and isinstance(blueprint.blueprint_json, dict) else {}
    provider_context = blueprint_json.get("provider_context") if isinstance(blueprint_json.get("provider_context"), dict) else {}
    raw_provider_response = blueprint.raw_provider_response if blueprint is not None and isinstance(blueprint.raw_provider_response, dict) else {}
    nested_raw_provider_response = raw_provider_response.get("raw_provider_response") if isinstance(raw_provider_response.get("raw_provider_response"), dict) else {}
    layout_diagnostics = raw_provider_response.get("pdf_layout_diagnostics") if isinstance(raw_provider_response.get("pdf_layout_diagnostics"), dict) else {}
    exam_results_count, exam_results_average_score, exam_results_passed_count = _serialize_exam_results_summary(
        db,
        getattr(unit, "exam", None),
    )
    return WorkflowUnitOut(
        id=unit.id,
        class_id=unit.class_id,
        exam_id=unit.exam_id,
        exam_title=str(getattr(getattr(unit, "exam", None), "title", "") or "").strip() or None,
        exam_results_count=exam_results_count,
        exam_results_average_score=exam_results_average_score,
        exam_results_passed_count=exam_results_passed_count,
        unit_type=unit.unit_type,
        status=unit.status,
        title=unit.title,
        planned_hours=unit.planned_hours,
        document_name=unit.document_name,
        created_at=unit.created_at,
        closed_at=unit.closed_at,
        progress_total=progress_total,
        progress_done=progress_done,
        extraction_source=str(getattr(blueprint, "provider", "") or "").strip() or None,
        extraction_model=getattr(blueprint, "model", None),
        extraction_status=str(getattr(blueprint, "status", "") or "").strip() or None,
        extraction_error=str(getattr(blueprint, "error_message", "") or "").strip() or None,
        extraction_structure_source=str(
            nested_raw_provider_response.get("selected_structure_source")
            or raw_provider_response.get("selected_structure_source")
            or ""
        ).strip() or None,
        extraction_notebook_role=str(provider_context.get("notebook_role") or "").strip() or None,
        extraction_layout_heading_count=_safe_optional_int(layout_diagnostics.get("layout_heading_count")),
        extraction_ocr_heading_count=_safe_optional_int(layout_diagnostics.get("ocr_heading_count")),
        extraction_reviewed=bool(getattr(blueprint, "reviewed", True)) if blueprint is not None else True,
        extraction_reviewed_at=getattr(blueprint, "reviewed_at", None) if blueprint is not None else None,
        checklist=_serialize_checklist(items),
    )


def _workflow_nodes_from_checklist_rows(items: list[WorkflowChecklistItem], *, root_title: str | None = None) -> list[dict[str, object]]:
    serialized = _serialize_checklist(items)

    def convert(node: WorkflowChecklistItemOut) -> dict[str, object]:
        return {
            "title": node.title,
            "kind": node.item_kind.value,
            "children": [convert(child) for child in node.children],
        }

    nodes = [convert(node) for node in serialized]
    if root_title:
        clean_root = str(root_title or "").strip()
        if clean_root:
            if len(nodes) == 1:
                nodes[0]["title"] = clean_root
            elif nodes:
                nodes = [{"title": clean_root, "kind": WorkflowChecklistItemKind.CHAPTER.value, "children": nodes}]
            else:
                nodes = [{"title": clean_root, "kind": WorkflowChecklistItemKind.CHAPTER.value, "children": []}]
    return nodes


def _kind_for_exam_outline_title(title: str, *, depth: int) -> str:
    lowered = str(title or "").strip().lower()
    if not lowered:
        return WorkflowChecklistItemKind.OTHER.value
    if "exercice" in lowered or "exercise" in lowered or "probleme" in lowered or "problem" in lowered:
        return WorkflowChecklistItemKind.EXERCISE.value
    if "exemple" in lowered or "example" in lowered:
        return WorkflowChecklistItemKind.EXAMPLE.value
    if "règle" in lowered or "regle" in lowered or "propriété" in lowered or "propriete" in lowered or "property" in lowered:
        return WorkflowChecklistItemKind.PROPERTY.value
    if "définition" in lowered or "definition" in lowered:
        return WorkflowChecklistItemKind.DEFINITION.value
    if "corrig" in lowered:
        return WorkflowChecklistItemKind.CORRECTION.value
    if "consigne" in lowered or "barème" in lowered or "bareme" in lowered or "surveillance" in lowered:
        return WorkflowChecklistItemKind.SUPERVISION.value
    if depth <= 0:
        return WorkflowChecklistItemKind.SECTION.value
    return WorkflowChecklistItemKind.SUBSECTION.value


def _build_exam_outline_nodes(*, root_title: str, outline_text: str | None) -> list[dict[str, object]] | None:
    lines = [line.rstrip() for line in str(outline_text or "").splitlines() if line.strip()]
    if not lines:
        return None
    root_node: dict[str, object] = {
        "title": str(root_title or "").strip() or "Exam",
        "kind": WorkflowChecklistItemKind.CHAPTER.value,
        "children": [],
    }
    stack: list[tuple[int, dict[str, object]]] = [(-1, root_node)]
    for raw_line in lines:
        indent_raw = len(raw_line) - len(raw_line.lstrip(" \t"))
        normalized_depth = max(0, indent_raw // 2)
        title = OUTLINE_BULLET_PREFIX_PATTERN.sub("", raw_line.lstrip()).strip()
        if not title:
            continue
        node = {
            "title": title,
            "kind": _kind_for_exam_outline_title(title, depth=normalized_depth),
            "children": [],
        }
        while stack and stack[-1][0] >= normalized_depth:
            stack.pop()
        parent = stack[-1][1] if stack else root_node
        parent_children = parent.get("children")
        if not isinstance(parent_children, list):
            parent_children = []
            parent["children"] = parent_children
        parent_children.append(node)
        stack.append((normalized_depth, node))
    children = root_node.get("children")
    return [root_node] if isinstance(children, list) and children else None


def _build_linked_exam_generated_payload(
    db: Session,
    *,
    class_id: int,
    exam: Exam,
    unit_type: WorkflowUnitType,
    title: str,
) -> dict[str, object]:
    if unit_type == WorkflowUnitType.EXAM:
        nodes = [
            {
                "title": title,
                "kind": WorkflowChecklistItemKind.CHAPTER.value,
                "children": [
                    {
                        "title": "Supervision d'examen",
                        "kind": WorkflowChecklistItemKind.SUPERVISION.value,
                        "children": [],
                    }
                ],
            }
        ]
    else:
        nodes = [
            {
                "title": title,
                "kind": WorkflowChecklistItemKind.CHAPTER.value,
                "children": [
                    {
                        "title": "Correction d'examen",
                        "kind": WorkflowChecklistItemKind.CORRECTION.value,
                        "children": [],
                    }
                ],
            }
        ]

    return {
        "source": "template",
        "status": "ready",
        "items": nodes,
        "provider_context": {
            "linked_exam_id": int(exam.id),
            "linked_exam_title": str(exam.title or "").strip(),
            "linked_unit_type": unit_type.value,
        },
    }


def _create_unit_with_seeded_checklist(
    db: Session,
    *,
    class_id: int,
    current_user: User,
    unit_type: WorkflowUnitType,
    title: str,
    generated: dict[str, object],
    planned_hours: float | None = None,
    exam_id: int | None = None,
) -> WorkflowUnit:
    normalized_title = str(title or "").strip()
    if not normalized_title:
        raise HTTPException(status_code=400, detail="Unit title is required.")
    if planned_hours is not None and float(planned_hours) <= 0:
        raise HTTPException(status_code=400, detail="planned_hours must be greater than zero.")
    if db.scalar(
        select(WorkflowUnit.id).where(
            WorkflowUnit.class_id == class_id,
            WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
        )
    ):
        raise HTTPException(status_code=409, detail="An active unit already exists. Close it first.")

    unit = WorkflowUnit(
        class_id=class_id,
        exam_id=exam_id,
        unit_type=unit_type,
        status=WorkflowUnitStatus.ACTIVE,
        title=normalized_title,
        planned_hours=planned_hours,
        order_index=_next_workflow_unit_order_index(db, class_id=class_id),
        created_by_user_id=current_user.id,
    )
    db.add(unit)
    db.flush()

    _store_generated_checklist_on_unit(
        db,
        unit=unit,
        generated=generated,
        extracted_text="",
        document_hash=None,
    )
    log_audit(
        db,
        user=current_user,
        action="workflow.unit.start",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={
            "unit_type": unit_type.value,
            "title": unit.title,
            "planned_hours": planned_hours,
            "generation_source": generated.get("source"),
            "exam_id": exam_id,
        },
    )
    return unit


def _reopen_workflow_unit_record(
    db: Session,
    *,
    class_id: int,
    unit: WorkflowUnit,
    current_user: User,
) -> WorkflowUnit:
    active_unit = db.scalar(
        select(WorkflowUnit).where(
            WorkflowUnit.class_id == class_id,
            WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
        )
    )
    if active_unit is not None:
        raise HTTPException(status_code=409, detail="An active unit already exists. Close it first.")

    open_workflow_session = db.scalar(
        select(ClassSession).where(
            ClassSession.class_id == class_id,
            ClassSession.unit_id.is_not(None),
            ClassSession.end_time.is_(None),
        )
    )
    if open_workflow_session is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Session #{open_workflow_session.id} is still open. End it first.",
        )

    unit.status = WorkflowUnitStatus.ACTIVE
    unit.closed_at = None
    unit.order_index = _next_workflow_unit_order_index(db, class_id=class_id)
    log_audit(
        db,
        user=current_user,
        action="workflow.unit.reopen",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={"title": unit.title, "unit_type": unit.unit_type.value},
    )
    return unit


def _session_time_sort_value(value: time | None) -> int:
    if value is None:
        return (24 * 60) + 1
    return (int(value.hour) * 60) + int(value.minute)


def _derive_unit_session_number_map(sessions: list[ClassSession]) -> dict[int, int]:
    grouped: dict[int, list[ClassSession]] = {}
    for session in sessions:
        if session.unit_id is None:
            continue
        grouped.setdefault(int(session.unit_id), []).append(session)

    output: dict[int, int] = {}
    for unit_sessions in grouped.values():
        sorted_rows = sorted(
            unit_sessions,
            key=lambda row: (row.session_date, _session_time_sort_value(row.start_time), row.id),
        )
        for idx, row in enumerate(sorted_rows, start=1):
            output[int(row.id)] = idx
    return output


def _compute_next_unit_session_number(db: Session, unit_id: int) -> int:
    stored_max = db.scalar(
        select(func.max(ClassSession.unit_session_number)).where(
            ClassSession.unit_id == unit_id,
            ClassSession.unit_session_number.is_not(None),
        )
    )
    if stored_max is not None:
        return int(stored_max) + 1

    # Legacy fallback: existing rows without stored sequence still count.
    legacy_count = int(
        db.scalar(select(func.count(ClassSession.id)).where(ClassSession.unit_id == unit_id))
        or 0
    )
    return legacy_count + 1


def _resolve_unit_session_number(db: Session, session: ClassSession) -> int | None:
    if session.unit_id is None:
        return None
    if session.unit_session_number is not None:
        return int(session.unit_session_number)

    rows = db.scalars(
        select(ClassSession).where(ClassSession.unit_id == session.unit_id)
    ).all()
    if not rows:
        return 1
    derived_map = _derive_unit_session_number_map(rows)
    return derived_map.get(int(session.id))


def _normalize_class_key(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return " ".join(raw.split())


def _list_accessible_classes(db: Session, current_user: User) -> list[Classroom]:
    if current_user.role == UserRole.OWNER:
        return db.scalars(select(Classroom).order_by(Classroom.id.asc())).all()

    class_ids = db.scalars(select(ClassAccess.class_id).where(ClassAccess.user_id == current_user.id)).all()
    unique_ids = sorted(set(int(cid) for cid in class_ids))
    if not unique_ids:
        return []
    return db.scalars(select(Classroom).where(Classroom.id.in_(unique_ids)).order_by(Classroom.id.asc())).all()


def _parse_hhmmss_time(value: str | None) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _clean_optional_text(value: str | None, *, max_length: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if max_length is not None and max_length > 0:
        return text[:max_length]
    return text


def _next_auto_student_code(existing_codes: set[str], seed: int = 1) -> tuple[str, int]:
    counter = max(1, int(seed or 1))
    while True:
        code = f"AUTO{counter:04d}"
        counter += 1
        if code not in existing_codes:
            return code, counter


def _timetable_rule_identity_tuple(
    *,
    weekday: int,
    start_time: time,
    end_time: time,
    subject: str | None,
    room: str | None,
    group_name: str | None,
    teacher_key: str | None,
) -> tuple:
    return (
        int(weekday),
        start_time.isoformat(),
        end_time.isoformat(),
        str(subject or "").strip().lower(),
        str(room or "").strip().lower(),
        str(group_name or "").strip().lower(),
        str(teacher_key or "").strip().lower(),
    )


def _build_checklist_order_maps(
    items: list[WorkflowChecklistItem],
) -> tuple[list[WorkflowChecklistItem], dict[int, int], dict[int, str]]:
    by_parent: dict[int | None, list[WorkflowChecklistItem]] = {}
    for row in items:
        by_parent.setdefault(row.parent_item_id, []).append(row)
    for siblings in by_parent.values():
        siblings.sort(key=lambda value: (int(value.position), int(value.id)))

    ordered: list[WorkflowChecklistItem] = []
    order_index_by_id: dict[int, int] = {}
    number_label_by_id: dict[int, str] = {}
    visited_ids: set[int] = set()

    def walk(parent_id: int | None, prefix: str) -> None:
        siblings = by_parent.get(parent_id, [])
        for idx, row in enumerate(siblings, start=1):
            row_id = int(row.id)
            if row_id in visited_ids:
                continue
            visited_ids.add(row_id)
            number_label = f"{prefix}.{idx}" if prefix else str(idx)
            order_index_by_id[row_id] = len(ordered)
            number_label_by_id[row_id] = number_label
            ordered.append(row)
            walk(row_id, number_label)

    walk(None, "")

    # Fallback for orphaned rows with missing parents.
    if len(ordered) < len(items):
        extras = sorted(
            (row for row in items if int(row.id) not in visited_ids),
            key=lambda value: (int(value.depth), int(value.position), int(value.id)),
        )
        for row in extras:
            row_id = int(row.id)
            order_index_by_id[row_id] = len(ordered)
            number_label_by_id[row_id] = str(len(ordered) + 1)
            ordered.append(row)

    return ordered, order_index_by_id, number_label_by_id


def _unit_checklist_order_maps(
    db: Session,
    unit_id: int,
) -> tuple[list[WorkflowChecklistItem], dict[int, int], dict[int, str]]:
    items = db.scalars(
        select(WorkflowChecklistItem)
        .where(WorkflowChecklistItem.unit_id == int(unit_id))
        .order_by(WorkflowChecklistItem.position.asc(), WorkflowChecklistItem.id.asc())
    ).all()
    if not items:
        return [], {}, {}
    return _build_checklist_order_maps(items)


def _format_checklist_item_label(number_label: str | None, title: str | None) -> str:
    text = str(title or "").strip() or "Checklist item"
    if not number_label:
        return text
    return f"{number_label}) {text}"


def _split_session_content_rows(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []

    lines = [
        re.sub(r"\s+", " ", segment).strip(" ;,-")
        for segment in re.split(r"[\r\n]+", raw)
        if str(segment or "").strip()
    ]
    output: list[str] = []
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
        value = str(row or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _title_looks_like_slug(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text and SLUG_LIKE_TITLE_PATTERN.match(text))


def _normalize_exam_title_candidate(value: str | None) -> str:
    text = " ".join(str(value or "").replace("_", " ").split()).strip(" :.-")
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()[:255]


def _title_needs_exam_inference(value: str | None, *, file_name: str | None = None) -> bool:
    text = _normalize_exam_title_candidate(value)
    if not text:
        return True
    lowered = text.lower()
    if _title_looks_like_slug(text):
        return True
    if lowered in {"exam", "examen", "devoir", "controle", "contrôle", "evaluation", "évaluation", "ds", "supervision d'examen"}:
        return True
    file_stem = Path(str(file_name or "")).stem.strip()
    if file_stem and _normalize_exam_title_candidate(file_stem).lower() == lowered:
        return True
    return False


def _infer_exam_title_from_source_text(
    extracted_text: str | None,
    *,
    fallback_title: str | None = None,
    file_name: str | None = None,
) -> str | None:
    lines = [
        _normalize_exam_title_candidate(row)
        for row in str(extracted_text or "").splitlines()
        if _normalize_exam_title_candidate(row)
    ]
    lines = [row for row in lines if len(row) >= 3][:20]
    if not lines:
        return None

    for index, line in enumerate(lines):
        if not EXAM_TITLE_KEYWORD_PATTERN.search(line):
            continue
        candidate = line
        if len(candidate) <= 18 and index + 1 < len(lines):
            next_line = lines[index + 1]
            if next_line and len(next_line) <= 80 and not EXAM_TITLE_KEYWORD_PATTERN.search(next_line):
                candidate = f"{candidate} - {next_line}"
        candidate = _normalize_exam_title_candidate(candidate)
        if candidate:
            return candidate

    fallback = _normalize_exam_title_candidate(fallback_title)
    if fallback and not _title_needs_exam_inference(fallback, file_name=file_name):
        return fallback
    file_stem = _normalize_exam_title_candidate(Path(str(file_name or "")).stem if file_name else "")
    if EXAM_TITLE_KEYWORD_PATTERN.search(file_stem):
        return file_stem
    return None


def _first_meaningful_generated_title(nodes: list[dict] | None) -> str | None:
    if not isinstance(nodes, list):
        return None

    def walk(items: list[dict]) -> str | None:
        for item in items:
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title") or "").split()).strip()
            if title and not _title_looks_like_slug(title):
                return title
            children = item.get("children")
            if isinstance(children, list) and children:
                nested = walk(children)
                if nested:
                    return nested
        return None

    return walk(nodes)


def _collect_unit_leaf_item_ids(db: Session, unit_id: int) -> list[int]:
    items, _, _ = _unit_checklist_order_maps(db, int(unit_id))
    if not items:
        return []
    parent_ids = {int(row.parent_item_id) for row in items if row.parent_item_id is not None}
    leaf_ids = [int(row.id) for row in items if int(row.id) not in parent_ids]
    if leaf_ids:
        return leaf_ids
    return [int(row.id) for row in items]


def _distribute_item_ids_across_sessions(item_ids: list[int], session_count: int) -> list[list[int]]:
    normalized_session_count = max(0, int(session_count or 0))
    if normalized_session_count <= 0:
        return []
    ordered_ids = [int(value) for value in (item_ids or []) if int(value) > 0]
    buckets: list[list[int]] = []
    cursor = 0
    remaining = len(ordered_ids)
    for idx in range(normalized_session_count):
        sessions_left = normalized_session_count - idx
        if remaining <= 0:
            buckets.append([])
            continue
        take = max(1, (remaining + sessions_left - 1) // sessions_left)
        chunk = ordered_ids[cursor: cursor + take]
        buckets.append(chunk)
        cursor += len(chunk)
        remaining -= len(chunk)
    return buckets


def _distribute_item_ids_with_session_hints(
    *,
    item_ids: list[int],
    session_count: int,
    session_hints_by_item_id: dict[int, int] | None,
) -> list[list[int]]:
    normalized_session_count = max(0, int(session_count or 0))
    if normalized_session_count <= 0:
        return []
    ordered_ids = [int(value) for value in (item_ids or []) if int(value) > 0]
    if not ordered_ids:
        return [[] for _ in range(normalized_session_count)]

    hints = session_hints_by_item_id or {}
    buckets: list[list[int]] = [[] for _ in range(normalized_session_count)]
    pending_ids: list[int] = []
    for item_id in ordered_ids:
        hint = hints.get(int(item_id))
        if hint is None:
            pending_ids.append(int(item_id))
            continue
        if int(hint) <= 0:
            pending_ids.append(int(item_id))
            continue
        target_index = min(normalized_session_count, int(hint)) - 1
        buckets[target_index].append(int(item_id))

    if pending_ids:
        fill = _distribute_item_ids_across_sessions(pending_ids, normalized_session_count)
        for index in range(normalized_session_count):
            if index < len(fill):
                buckets[index].extend(fill[index])
    return buckets


def _append_unit_session_exercise_filler_item(
    db: Session,
    *,
    unit_id: int,
    session_number: int,
) -> int:
    root_position = (
        int(
            db.scalar(
                select(func.coalesce(func.max(WorkflowChecklistItem.position), 0)).where(
                    WorkflowChecklistItem.unit_id == int(unit_id),
                    WorkflowChecklistItem.parent_item_id.is_(None),
                )
            )
            or 0
        )
        + 1
    )
    row = WorkflowChecklistItem(
        unit_id=int(unit_id),
        parent_item_id=None,
        item_kind=WorkflowChecklistItemKind.EXERCISE,
        title=f"Practice exercise - Session {int(session_number)}",
        position=root_position,
        depth=0,
        is_completed=False,
    )
    db.add(row)
    db.flush()
    return int(row.id)


def _apply_checked_items_to_session(
    db: Session,
    *,
    unit_id: int,
    session_id: int,
    checked_item_ids: list[int],
) -> int:
    selected_ids = _filter_actionable_check_item_ids(
        db,
        unit_id=int(unit_id),
        item_ids=[int(value) for value in (checked_item_ids or []) if int(value) > 0],
    )
    if not selected_ids:
        return 0

    unit_items = db.scalars(
        select(WorkflowChecklistItem).where(WorkflowChecklistItem.unit_id == int(unit_id))
    ).all()
    unit_item_ids = {int(row.id) for row in unit_items}
    invalid_checked_ids = sorted(set(selected_ids) - unit_item_ids)
    if invalid_checked_ids:
        raise HTTPException(status_code=400, detail=f"Unknown checklist item ids for this unit: {invalid_checked_ids}")

    affected_ids: set[int] = {int(item_id) for item_id in selected_ids}

    for item_id in sorted(affected_ids):
        _upsert_session_action(db, session_id=int(session_id), item_id=int(item_id), checked=True)
    db.flush()
    for item_id in sorted(affected_ids):
        _refresh_item_completion(db, int(item_id))
    for item_id in selected_ids:
        _refresh_ancestors_completion(db, int(item_id), int(session_id))
    return len(selected_ids)


def _list_unit_sessions_ordered(db: Session, unit_id: int) -> list[ClassSession]:
    return db.scalars(
        select(ClassSession)
        .where(ClassSession.unit_id == int(unit_id))
        .order_by(
            ClassSession.session_date.asc(),
            ClassSession.start_time.asc().nulls_last(),
            ClassSession.id.asc(),
        )
    ).all()


def _select_auto_confirm_item_ids(db: Session, *, unit_id: int, session_id: int) -> list[int]:
    ordered_sessions = _list_unit_sessions_ordered(db, int(unit_id))
    if not ordered_sessions:
        return []

    current_index = next(
        (idx for idx, row in enumerate(ordered_sessions) if int(row.id) == int(session_id)),
        None,
    )
    if current_index is None:
        return []

    remaining_sessions = ordered_sessions[current_index:]
    if not remaining_sessions:
        return []

    leaf_ids = _collect_unit_leaf_item_ids(db, int(unit_id))
    if not leaf_ids:
        return []

    completed_item_ids = set(
        int(value)
        for value in db.scalars(
            select(WorkflowChecklistItem.id).where(
                WorkflowChecklistItem.unit_id == int(unit_id),
                WorkflowChecklistItem.is_completed.is_(True),
            )
        ).all()
    )
    remaining_leaf_ids = [item_id for item_id in leaf_ids if int(item_id) not in completed_item_ids]
    if not remaining_leaf_ids:
        return []

    distribution = _distribute_item_ids_across_sessions(remaining_leaf_ids, len(remaining_sessions))
    return distribution[0] if distribution else []


def _progress_item_from_checklist(item: WorkflowChecklistItem) -> tuple[ProgressItemType, str, str | None]:
    kind = item.item_kind
    title = str(item.title or "").strip() or "Checklist item"
    if kind == WorkflowChecklistItemKind.EXERCISE:
        return ProgressItemType.EXERCISE, "Exercise", title
    if kind in {
        WorkflowChecklistItemKind.EXAMPLE,
        WorkflowChecklistItemKind.SUPERVISION,
        WorkflowChecklistItemKind.CORRECTION,
    }:
        return ProgressItemType.ACTIVITY, "Activity", title
    return ProgressItemType.LESSON, title, None


def _append_progress_items_from_checklist(
    db: Session,
    *,
    session_id: int,
    item_ids: list[int],
) -> int:
    normalized_ids = [int(value) for value in (item_ids or []) if int(value) > 0]
    if not normalized_ids:
        return 0

    checklist_rows = db.scalars(
        select(WorkflowChecklistItem)
        .where(WorkflowChecklistItem.id.in_(normalized_ids))
        .order_by(WorkflowChecklistItem.position.asc(), WorkflowChecklistItem.id.asc())
    ).all()
    if not checklist_rows:
        return 0
    by_id = {int(row.id): row for row in checklist_rows}

    unit_ids = {int(row.unit_id) for row in checklist_rows}
    order_index_by_id: dict[int, int] = {}
    number_label_by_id: dict[int, str] = {}
    if len(unit_ids) == 1:
        _, order_index_by_id, number_label_by_id = _unit_checklist_order_maps(db, next(iter(unit_ids)))

    existing_rows = db.scalars(
        select(ProgressItem)
        .where(ProgressItem.session_id == int(session_id))
        .order_by(ProgressItem.position.asc(), ProgressItem.id.asc())
    ).all()
    next_position = max((int(row.position) for row in existing_rows), default=0) + 1
    seen_keys: set[tuple[str, str, str]] = {
        (
            str(row.item_type.value),
            str(row.heading or "").strip().lower(),
            str(row.content or "").strip().lower(),
        )
        for row in existing_rows
    }

    created_count = 0
    ordered_item_ids = sorted(
        {int(item_id) for item_id in normalized_ids if int(item_id) in by_id},
        key=lambda value: (order_index_by_id.get(int(value), 10**9), int(value)),
    )
    for item_id in ordered_item_ids:
        item = by_id.get(int(item_id))
        if item is None:
            continue
        item_type, heading, content = _progress_item_from_checklist(item)
        number_label = number_label_by_id.get(int(item.id))
        if number_label:
            if content:
                content = _format_checklist_item_label(number_label, content)
            else:
                heading = _format_checklist_item_label(number_label, heading)
        base_heading = str(heading or "").strip() or "Lesson"
        base_content = str(content or "").strip() or None
        split_target = base_content if base_content else base_heading
        split_rows = _split_session_content_rows(split_target)
        if not split_rows:
            split_rows = [split_target]

        row_pairs: list[tuple[str, str | None]] = []
        if base_content:
            row_pairs = [(base_heading, str(row).strip() or base_content) for row in split_rows]
        else:
            row_pairs = [(str(row).strip() or base_heading, None) for row in split_rows]

        for row_heading, row_content in row_pairs:
            normalized_heading = str(row_heading or "").strip() or "Lesson"
            normalized_content = str(row_content or "").strip() or None
            dedupe_key = (
                str(item_type.value),
                normalized_heading.lower(),
                str(normalized_content or "").lower(),
            )
            if dedupe_key in seen_keys:
                continue
            db.add(
                ProgressItem(
                    session_id=int(session_id),
                    item_type=item_type,
                    heading=normalized_heading,
                    content=normalized_content,
                    position=next_position,
                )
            )
            seen_keys.add(dedupe_key)
            next_position += 1
            created_count += 1
    return created_count


def _remaining_leaf_items_count(db: Session, *, unit_id: int) -> int:
    leaf_ids = _collect_unit_leaf_item_ids(db, int(unit_id))
    if not leaf_ids:
        return 0
    completed_item_ids = set(
        int(value)
        for value in db.scalars(
            select(WorkflowChecklistItem.id).where(
                WorkflowChecklistItem.unit_id == int(unit_id),
                WorkflowChecklistItem.is_completed.is_(True),
            )
        ).all()
    )
    return len([item_id for item_id in leaf_ids if int(item_id) not in completed_item_ids])


def _auto_close_completed_past_unit(db: Session, *, unit_id: int) -> bool:
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or unit.status != WorkflowUnitStatus.ACTIVE:
        return False

    if _remaining_leaf_items_count(db, unit_id=int(unit_id)) > 0:
        return False

    today_value = date.today()
    latest_session_date = db.scalar(
        select(func.max(ClassSession.session_date)).where(ClassSession.unit_id == int(unit_id))
    )
    if latest_session_date is None or latest_session_date >= today_value:
        return False

    has_open_sessions = db.scalar(
        select(ClassSession.id)
        .where(ClassSession.unit_id == int(unit_id), ClassSession.end_time.is_(None))
        .limit(1)
    )
    if has_open_sessions is not None:
        return False

    unit.status = WorkflowUnitStatus.CLOSED
    unit.closed_at = _utc_now_naive()
    return True


def _has_session_start_conflict(
    db: Session,
    *,
    class_id: int,
    session_date: date,
    start_time: time,
) -> bool:
    row_id = db.scalar(
        select(ClassSession.id).where(
            ClassSession.class_id == int(class_id),
            ClassSession.session_date == session_date,
            ClassSession.start_time == start_time,
        ).limit(1)
    )
    return row_id is not None


def _start_of_week_date(value: date) -> date:
    # Monday = start of school week.
    weekday = int(value.isoweekday()) if value else 1
    return value - timedelta(days=max(weekday - 1, 0))


def _rule_applies_to_day(rule: ClassTimetableRule, day: date) -> bool:
    if day < rule.effective_from:
        return False
    if rule.effective_to is not None and day > rule.effective_to:
        return False
    return True


def _list_blocked_holiday_dates(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    country_code: str = "MA",
) -> set[date]:
    output: set[date] = set()
    for year in range(int(date_from.year), int(date_to.year) + 1):
        rows = list_holidays_for_year(db, year=year, country_code=country_code)
        for row in rows:
            if not row.is_blocked:
                continue
            holiday_day = row.holiday_date
            if holiday_day < date_from or holiday_day > date_to:
                continue
            output.add(holiday_day)
    return output


def _collect_existing_session_start_keys(
    db: Session,
    *,
    class_id: int,
    date_from: date,
    date_to: date,
) -> set[tuple[date, time]]:
    rows = db.execute(
        select(ClassSession.session_date, ClassSession.start_time).where(
            ClassSession.class_id == int(class_id),
            ClassSession.session_date >= date_from,
            ClassSession.session_date <= date_to,
            ClassSession.start_time.is_not(None),
        )
    ).all()
    output: set[tuple[date, time]] = set()
    for row in rows:
        if row.start_time is None:
            continue
        output.add((row.session_date, row.start_time))
    return output


def _list_timetable_exceptions_for_range(
    db: Session,
    *,
    class_id: int,
    date_from: date,
    date_to: date,
) -> list[TimetableRuleException]:
    source_window = and_(
        TimetableRuleException.exception_date >= date_from,
        TimetableRuleException.exception_date <= date_to,
    )
    target_window = and_(
        TimetableRuleException.target_date.is_not(None),
        TimetableRuleException.target_date >= date_from,
        TimetableRuleException.target_date <= date_to,
    )
    stmt = (
        select(TimetableRuleException)
        .where(TimetableRuleException.class_id == int(class_id))
        .where(or_(source_window, target_window))
        .order_by(TimetableRuleException.exception_date.asc(), TimetableRuleException.id.asc())
    )
    return db.scalars(stmt).all()


def _build_timetable_candidates_for_range(
    *,
    date_from: date,
    date_to: date,
    rules: list[ClassTimetableRule],
    exceptions: list[TimetableRuleException],
    blocked_holiday_dates: set[date],
    existing_start_keys: set[tuple[date, time]],
) -> tuple[list[dict], dict[str, int]]:
    stats = {
        "skipped_holiday_count": 0,
        "skipped_existing_count": 0,
        "skipped_exception_count": 0,
        "skipped_duplicate_count": 0,
    }
    rules_by_id = {int(rule.id): rule for rule in (rules or [])}
    source_exception_by_key: dict[tuple[int, date], TimetableRuleException] = {}
    for row in (exceptions or []):
        exception_type = str(row.exception_type or "").strip().lower()
        if exception_type not in {"cancel", "move"}:
            continue
        key = (int(row.rule_id), row.exception_date)
        existing = source_exception_by_key.get(key)
        if existing is None:
            source_exception_by_key[key] = row
            continue
        existing_type = str(existing.exception_type or "").strip().lower()
        if existing_type != "move" and exception_type == "move":
            source_exception_by_key[key] = row

    candidate_by_key: dict[tuple[date, time], dict] = {}

    def add_candidate(
        *,
        session_date: date,
        start_time: time,
        end_time: time | None,
        rule: ClassTimetableRule,
        moved_from_date: date | None = None,
        exception_note: str | None = None,
    ) -> None:
        key = (session_date, start_time)
        if key in candidate_by_key:
            stats["skipped_duplicate_count"] += 1
            return
        if key in existing_start_keys:
            stats["skipped_existing_count"] += 1
            return
        if session_date in blocked_holiday_dates:
            stats["skipped_holiday_count"] += 1
            return
        candidate_by_key[key] = {
            "session_date": session_date,
            "start_time": start_time,
            "end_time": end_time,
            "rule": rule,
            "moved_from_date": moved_from_date,
            "exception_note": str(exception_note or "").strip() or None,
        }

    current = date_from
    while current <= date_to:
        weekday = int(current.isoweekday())
        if weekday in NON_WORKING_WEEKDAYS:
            current += timedelta(days=1)
            continue
        for rule in rules:
            if int(rule.weekday) in NON_WORKING_WEEKDAYS:
                continue
            if int(rule.weekday) != weekday:
                continue
            if not _rule_applies_to_day(rule, current):
                continue
            source_exception = source_exception_by_key.get((int(rule.id), current))
            if source_exception is not None:
                source_exception_type = str(source_exception.exception_type or "").strip().lower()
                if source_exception_type in {"cancel", "move"}:
                    stats["skipped_exception_count"] += 1
                    continue
            add_candidate(
                session_date=current,
                start_time=rule.start_time,
                end_time=rule.end_time,
                rule=rule,
            )
        current += timedelta(days=1)

    for exception_row in (exceptions or []):
        exception_type = str(exception_row.exception_type or "").strip().lower()
        if exception_type != "move":
            continue
        rule = rules_by_id.get(int(exception_row.rule_id))
        if rule is None:
            continue
        source_date = exception_row.exception_date
        target_date = exception_row.target_date
        target_start = exception_row.target_start_time
        if target_date is None or target_start is None:
            continue
        if _is_non_working_day(target_date):
            stats["skipped_exception_count"] += 1
            continue
        if target_date < date_from or target_date > date_to:
            continue
        if int(rule.weekday) in NON_WORKING_WEEKDAYS:
            continue
        if not _rule_applies_to_day(rule, source_date):
            continue
        add_candidate(
            session_date=target_date,
            start_time=target_start,
            end_time=exception_row.target_end_time or rule.end_time,
            rule=rule,
            moved_from_date=source_date,
            exception_note=exception_row.note,
        )

    candidates = sorted(
        candidate_by_key.values(),
        key=lambda row: (
            row["session_date"],
            row["start_time"] or time(hour=23, minute=59, second=59),
            int(row["rule"].id),
        ),
    )
    return candidates, stats


def _build_timetable_candidates_for_count(
    db: Session,
    *,
    class_id: int,
    start_date: date,
    start_time_floor: time | None = None,
    requested_count: int,
    rules: list[ClassTimetableRule],
    skip_blocked_holidays: bool = True,
    max_search_days: int = 365,
    country_code: str = "MA",
) -> tuple[list[dict], dict[str, int], date]:
    stats = {
        "skipped_holiday_count": 0,
        "skipped_existing_count": 0,
        "skipped_exception_count": 0,
        "skipped_duplicate_count": 0,
    }
    safe_requested = max(0, int(requested_count))
    safe_max_days = max(28, min(int(max_search_days or 365), 730))
    search_end_date = start_date + timedelta(days=safe_max_days - 1)
    if safe_requested <= 0:
        return [], stats, search_end_date
    active_rules = [row for row in (rules or []) if int(row.weekday) not in NON_WORKING_WEEKDAYS]
    if not active_rules:
        return [], stats, search_end_date

    selected: list[dict] = []
    selected_keys: set[tuple[date, time]] = set()
    cursor = start_date
    window_days = 84

    while cursor <= search_end_date and len(selected) < safe_requested:
        window_end = min(cursor + timedelta(days=window_days - 1), search_end_date)
        exceptions = _list_timetable_exceptions_for_range(
            db,
            class_id=int(class_id),
            date_from=cursor,
            date_to=window_end,
        )
        blocked_holidays = (
            _list_blocked_holiday_dates(
                db,
                date_from=cursor,
                date_to=window_end,
                country_code=country_code,
            )
            if skip_blocked_holidays
            else set()
        )
        existing_start_keys = _collect_existing_session_start_keys(
            db,
            class_id=int(class_id),
            date_from=cursor,
            date_to=window_end,
        )
        existing_start_keys.update(selected_keys)

        candidates, window_stats = _build_timetable_candidates_for_range(
            date_from=cursor,
            date_to=window_end,
            rules=active_rules,
            exceptions=exceptions,
            blocked_holiday_dates=blocked_holidays,
            existing_start_keys=existing_start_keys,
        )
        for key in stats:
            stats[key] += int(window_stats.get(key, 0))

        for candidate in candidates:
            if len(selected) >= safe_requested:
                break
            if (
                start_time_floor is not None
                and candidate["session_date"] == start_date
                and (
                    candidate.get("start_time") is None
                    or candidate["start_time"] <= start_time_floor
                )
            ):
                continue
            key = (candidate["session_date"], candidate["start_time"])
            if key in selected_keys:
                stats["skipped_duplicate_count"] += 1
                continue
            selected.append(candidate)
            selected_keys.add(key)

        cursor = window_end + timedelta(days=1)

    return selected, stats, search_end_date


def _unit_has_upcoming_session(
    db: Session,
    *,
    unit_id: int,
    after_date: date,
    after_time: time | None = None,
    exclude_session_id: int | None = None,
) -> bool:
    conditions = [
        ClassSession.unit_id == int(unit_id),
    ]
    if exclude_session_id is not None:
        conditions.append(ClassSession.id != int(exclude_session_id))

    if after_time is None:
        conditions.append(ClassSession.session_date >= after_date)
    else:
        conditions.append(
            or_(
                ClassSession.session_date > after_date,
                and_(
                    ClassSession.session_date == after_date,
                    or_(
                        ClassSession.start_time.is_(None),
                        ClassSession.start_time > after_time,
                    ),
                ),
            )
        )

    row_id = db.scalar(
        select(ClassSession.id)
        .where(*conditions)
        .order_by(ClassSession.session_date.asc(), ClassSession.start_time.asc().nulls_last(), ClassSession.id.asc())
        .limit(1)
    )
    return row_id is not None


def _ensure_next_unit_session_from_timetable(
    db: Session,
    *,
    class_id: int,
    source_session: ClassSession,
    current_user: User,
) -> tuple[ClassSession | None, str]:
    if source_session.unit_id is None:
        return None, "no_unit"

    unit = db.get(WorkflowUnit, int(source_session.unit_id))
    if unit is None or unit.class_id != int(class_id):
        return None, "unit_missing"
    if unit.status != WorkflowUnitStatus.ACTIVE:
        return None, "unit_not_active"

    reference_time = source_session.end_time or source_session.start_time
    if _unit_has_upcoming_session(
        db,
        unit_id=int(unit.id),
        after_date=source_session.session_date,
        after_time=reference_time,
        exclude_session_id=int(source_session.id),
    ):
        return None, "upcoming_exists"

    rules = db.scalars(
        select(ClassTimetableRule)
        .where(ClassTimetableRule.class_id == int(class_id))
        .order_by(
            ClassTimetableRule.weekday.asc(),
            ClassTimetableRule.start_time.asc(),
            ClassTimetableRule.effective_from.asc(),
            ClassTimetableRule.id.asc(),
        )
    ).all()
    if not rules:
        return None, "no_timetable_rules"

    students = db.scalars(select(Student).where(Student.class_id == int(class_id)).order_by(Student.id.asc())).all()
    if not students:
        return None, "no_students"

    selected, _stats, _search_end_date = _build_timetable_candidates_for_count(
        db,
        class_id=int(class_id),
        start_date=source_session.session_date,
        start_time_floor=reference_time,
        requested_count=1,
        rules=rules,
        skip_blocked_holidays=True,
        max_search_days=180,
        country_code="MA",
    )
    if not selected:
        return None, "no_available_slot"

    candidate = selected[0]
    rule = candidate["rule"]
    note = _session_note_from_rule(
        prefix=f"Auto-planned next {unit.title} session",
        rule=rule,
        moved_from_date=candidate.get("moved_from_date"),
        exception_note=candidate.get("exception_note"),
    )
    created = _create_workflow_session_with_students(
        db,
        class_id=int(class_id),
        students=students,
        session_date=candidate["session_date"],
        start_time=candidate["start_time"],
        end_time=candidate.get("end_time"),
        note=note,
        current_user=current_user,
        unit_id=int(unit.id),
        audit_action="workflow.session.auto_schedule_next",
        audit_details={
            "source_session_id": int(source_session.id),
        },
    )
    return created, "created"


def _suggest_session_schedule_for_unit_start(
    db: Session,
    *,
    class_id: int,
    unit_id: int,
    now_dt: datetime,
) -> dict | None:
    rules = db.scalars(
        select(ClassTimetableRule)
        .where(ClassTimetableRule.class_id == int(class_id))
        .order_by(
            ClassTimetableRule.weekday.asc(),
            ClassTimetableRule.start_time.asc(),
            ClassTimetableRule.effective_from.asc(),
            ClassTimetableRule.id.asc(),
        )
    ).all()
    if not rules:
        return None

    latest_session = db.scalar(
        select(ClassSession)
        .where(ClassSession.unit_id == int(unit_id))
        .order_by(
            ClassSession.session_date.desc(),
            ClassSession.start_time.desc().nulls_last(),
            ClassSession.id.desc(),
        )
        .limit(1)
    )

    if latest_session is not None:
        start_date = latest_session.session_date
        start_time_floor = latest_session.end_time or latest_session.start_time
    else:
        start_date = now_dt.date()
        start_time_floor = now_dt.replace(second=0, microsecond=0).time()

    selected, _stats, _search_end_date = _build_timetable_candidates_for_count(
        db,
        class_id=int(class_id),
        start_date=start_date,
        start_time_floor=start_time_floor,
        requested_count=1,
        rules=rules,
        skip_blocked_holidays=True,
        max_search_days=180,
        country_code="MA",
    )
    if not selected:
        return None
    return selected[0]


def _session_note_from_rule(
    *,
    prefix: str,
    rule: ClassTimetableRule,
    moved_from_date: date | None = None,
    exception_note: str | None = None,
) -> str:
    details: list[str] = []
    if rule.subject:
        details.append(str(rule.subject).strip())
    if rule.room:
        details.append(f"room {str(rule.room).strip()}")
    if rule.group_name:
        details.append(f"group {str(rule.group_name).strip()}")
    if moved_from_date is not None:
        details.append(f"moved from {moved_from_date.isoformat()}")
    if exception_note:
        details.append(str(exception_note).strip())
    details = [part for part in details if part]
    if not details:
        return str(prefix).strip()
    return f"{str(prefix).strip()}: {' | '.join(details)}"


def _create_workflow_session_with_students(
    db: Session,
    *,
    class_id: int,
    students: list[Student],
    session_date: date,
    start_time: time | None,
    end_time: time | None,
    note: str | None,
    current_user: User,
    unit_id: int | None = None,
    audit_action: str = "workflow.session.create",
    audit_details: dict | None = None,
) -> ClassSession:
    session = ClassSession(
        class_id=int(class_id),
        unit_id=int(unit_id) if unit_id is not None else None,
        unit_session_number=_compute_next_unit_session_number(db, int(unit_id)) if unit_id is not None else None,
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        note=note,
    )
    db.add(session)
    db.flush()

    for student in students:
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                status=AttendanceStatus.PRESENT,
                minutes_late=0,
                comment=None,
            )
        )

    details = {
        "unit_id": session.unit_id,
        "unit_session_number": session.unit_session_number,
        "session_date": session.session_date.isoformat(),
        "start_time": session.start_time.isoformat() if session.start_time else None,
        "end_time": session.end_time.isoformat() if session.end_time else None,
    }
    if isinstance(audit_details, dict):
        details.update(audit_details)
    log_audit(
        db,
        user=current_user,
        action=audit_action,
        entity_type="session",
        entity_id=session.id,
        class_id=int(class_id),
        details=details,
    )
    return session


def _serialize_timetable_rule(rule: ClassTimetableRule) -> TimetableRuleOut:
    return TimetableRuleOut(
        id=rule.id,
        class_id=rule.class_id,
        teacher_key=rule.teacher_key,
        subject=rule.subject,
        weekday=rule.weekday,
        weekday_label=WEEKDAY_LABELS.get(int(rule.weekday)),
        start_time=rule.start_time.isoformat() if rule.start_time else "",
        end_time=rule.end_time.isoformat() if rule.end_time else "",
        room=rule.room,
        group=rule.group_name,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
        source=rule.source,
    )


def _serialize_timetable_exception(row: TimetableRuleException) -> TimetableRuleExceptionOut:
    return TimetableRuleExceptionOut(
        id=row.id,
        class_id=row.class_id,
        rule_id=row.rule_id,
        exception_date=row.exception_date,
        exception_type=row.exception_type,
        target_date=row.target_date,
        target_start_time=row.target_start_time,
        target_end_time=row.target_end_time,
        note=row.note,
        created_at=row.created_at,
    )


def _serialize_timetable_alias(row: TimetableClassAlias, class_name: str) -> TimetableClassAliasOut:
    return TimetableClassAliasOut(
        id=row.id,
        class_id=row.class_id,
        class_name=class_name,
        alias_name=row.alias_name,
        alias_key=row.alias_key,
    )


def _parse_iso_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_iso_time(value: str | None) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        return None


def _normalize_snapshot_rule_payload(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    weekday = int(raw.get("weekday") or 0)
    start_time = str(raw.get("start_time") or "").strip()
    end_time = str(raw.get("end_time") or "").strip() or start_time
    effective_from = str(raw.get("effective_from") or "").strip()
    effective_to_raw = str(raw.get("effective_to") or "").strip()
    effective_to = effective_to_raw or None
    if weekday < 1 or weekday > 7:
        return None
    if _parse_iso_time(start_time) is None or _parse_iso_time(end_time) is None:
        return None
    if _parse_iso_date(effective_from) is None:
        return None
    if effective_to is not None and _parse_iso_date(effective_to) is None:
        return None
    return {
        "weekday": weekday,
        "start_time": start_time,
        "end_time": end_time,
        "subject": str(raw.get("subject") or "").strip() or None,
        "room": str(raw.get("room") or "").strip() or None,
        "group": str(raw.get("group") or "").strip() or None,
        "teacher_key": str(raw.get("teacher_key") or "").strip() or None,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": str(raw.get("source") or "").strip() or None,
    }


def _normalize_snapshot_exception_payload(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    rule = _normalize_snapshot_rule_payload(raw.get("rule"))
    if rule is None:
        return None
    exception_date = str(raw.get("exception_date") or "").strip()
    exception_type = str(raw.get("exception_type") or "").strip().lower()
    if _parse_iso_date(exception_date) is None:
        return None
    if exception_type not in {"cancel", "move"}:
        return None

    target_date_raw = str(raw.get("target_date") or "").strip()
    target_start_raw = str(raw.get("target_start_time") or "").strip()
    target_end_raw = str(raw.get("target_end_time") or "").strip()
    target_date = target_date_raw or None
    target_start_time = target_start_raw or None
    target_end_time = target_end_raw or None
    if target_date is not None and _parse_iso_date(target_date) is None:
        return None
    if target_start_time is not None and _parse_iso_time(target_start_time) is None:
        return None
    if target_end_time is not None and _parse_iso_time(target_end_time) is None:
        return None

    if exception_type == "cancel":
        target_date = None
        target_start_time = None
        target_end_time = None
    elif target_date is None or target_start_time is None:
        return None

    return {
        "exception_date": exception_date,
        "exception_type": exception_type,
        "target_date": target_date,
        "target_start_time": target_start_time,
        "target_end_time": target_end_time,
        "note": str(raw.get("note") or "").strip() or None,
        "rule": rule,
    }


def _rule_payload_key(payload: dict) -> tuple:
    return (
        int(payload["weekday"]),
        str(payload["start_time"]),
        str(payload["end_time"]),
        str(payload.get("subject") or "").strip().lower(),
        str(payload.get("room") or "").strip().lower(),
        str(payload.get("group") or "").strip().lower(),
        str(payload.get("teacher_key") or "").strip().lower(),
        str(payload["effective_from"]),
        str(payload.get("effective_to") or ""),
    )


def _exception_payload_key(payload: dict) -> tuple:
    return (
        str(payload["exception_date"]),
        str(payload["exception_type"]),
        str(payload.get("target_date") or ""),
        str(payload.get("target_start_time") or ""),
        str(payload.get("target_end_time") or ""),
        str(payload.get("note") or "").strip().lower(),
        _rule_payload_key(payload["rule"]),
    )


def _rule_payload_sort_key(payload: dict) -> tuple:
    return (
        int(payload["weekday"]),
        str(payload["start_time"]),
        str(payload["effective_from"]),
        str(payload.get("subject") or "").lower(),
        str(payload.get("room") or "").lower(),
        str(payload.get("group") or "").lower(),
        str(payload.get("teacher_key") or "").lower(),
        str(payload["end_time"]),
        str(payload.get("effective_to") or ""),
    )


def _exception_payload_sort_key(payload: dict) -> tuple:
    return (
        str(payload["exception_date"]),
        str(payload["exception_type"]),
        str(payload.get("target_date") or ""),
        str(payload.get("target_start_time") or ""),
        _rule_payload_sort_key(payload["rule"]),
    )


def _rule_payload_to_snapshot(rule: ClassTimetableRule) -> dict:
    return {
        "weekday": int(rule.weekday),
        "start_time": rule.start_time.isoformat() if rule.start_time else "",
        "end_time": rule.end_time.isoformat() if rule.end_time else "",
        "subject": str(rule.subject or "").strip() or None,
        "room": str(rule.room or "").strip() or None,
        "group": str(rule.group_name or "").strip() or None,
        "teacher_key": str(rule.teacher_key or "").strip() or None,
        "effective_from": rule.effective_from.isoformat(),
        "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
        "source": str(rule.source or "").strip() or None,
    }


def _exception_payload_to_snapshot(row: TimetableRuleException, *, rule_payload: dict) -> dict:
    return {
        "exception_date": row.exception_date.isoformat(),
        "exception_type": str(row.exception_type or "").strip().lower(),
        "target_date": row.target_date.isoformat() if row.target_date else None,
        "target_start_time": row.target_start_time.isoformat() if row.target_start_time else None,
        "target_end_time": row.target_end_time.isoformat() if row.target_end_time else None,
        "note": str(row.note or "").strip() or None,
        "rule": rule_payload,
    }


def _collect_timetable_snapshot(db: Session, *, class_id: int) -> dict:
    rules = db.scalars(
        select(ClassTimetableRule)
        .where(ClassTimetableRule.class_id == int(class_id))
        .order_by(
            ClassTimetableRule.weekday.asc(),
            ClassTimetableRule.start_time.asc(),
            ClassTimetableRule.effective_from.asc(),
            ClassTimetableRule.id.asc(),
        )
    ).all()
    rule_payload_by_id: dict[int, dict] = {}
    normalized_rules: list[dict] = []
    for row in rules:
        payload = _normalize_snapshot_rule_payload(_rule_payload_to_snapshot(row))
        if payload is None:
            continue
        rule_payload_by_id[int(row.id)] = payload
        normalized_rules.append(payload)

    exceptions = db.scalars(
        select(TimetableRuleException)
        .where(TimetableRuleException.class_id == int(class_id))
        .order_by(TimetableRuleException.exception_date.asc(), TimetableRuleException.id.asc())
    ).all()
    normalized_exceptions: list[dict] = []
    for row in exceptions:
        payload_rule = rule_payload_by_id.get(int(row.rule_id))
        if payload_rule is None:
            rule_row = db.get(ClassTimetableRule, int(row.rule_id))
            if rule_row is None:
                continue
            payload_rule = _normalize_snapshot_rule_payload(_rule_payload_to_snapshot(rule_row))
            if payload_rule is None:
                continue
        exception_payload = _normalize_snapshot_exception_payload(
            _exception_payload_to_snapshot(row, rule_payload=payload_rule)
        )
        if exception_payload is None:
            continue
        normalized_exceptions.append(exception_payload)

    unique_rules_by_key = {_rule_payload_key(payload): payload for payload in normalized_rules}
    unique_exceptions_by_key = {_exception_payload_key(payload): payload for payload in normalized_exceptions}
    return {
        "rules": sorted(unique_rules_by_key.values(), key=_rule_payload_sort_key),
        "exceptions": sorted(unique_exceptions_by_key.values(), key=_exception_payload_sort_key),
    }


def _normalize_snapshot_bundle(snapshot: dict | None) -> tuple[list[dict], list[dict]]:
    if not isinstance(snapshot, dict):
        return [], []
    rules_raw = snapshot.get("rules")
    exceptions_raw = snapshot.get("exceptions")
    rules = [
        row
        for row in (
            _normalize_snapshot_rule_payload(raw)
            for raw in (rules_raw if isinstance(rules_raw, list) else [])
        )
        if row is not None
    ]
    exceptions = [
        row
        for row in (
            _normalize_snapshot_exception_payload(raw)
            for raw in (exceptions_raw if isinstance(exceptions_raw, list) else [])
        )
        if row is not None
    ]
    unique_rules_by_key = {_rule_payload_key(payload): payload for payload in rules}
    unique_exceptions_by_key = {_exception_payload_key(payload): payload for payload in exceptions}
    return (
        sorted(unique_rules_by_key.values(), key=_rule_payload_sort_key),
        sorted(unique_exceptions_by_key.values(), key=_exception_payload_sort_key),
    )


def _serialize_timetable_version_rule(payload: dict) -> TimetableVersionRuleOut | None:
    normalized = _normalize_snapshot_rule_payload(payload)
    if normalized is None:
        return None
    effective_from = _parse_iso_date(normalized["effective_from"])
    if effective_from is None:
        return None
    effective_to = _parse_iso_date(normalized["effective_to"]) if normalized.get("effective_to") else None
    return TimetableVersionRuleOut(
        weekday=int(normalized["weekday"]),
        weekday_label=WEEKDAY_LABELS.get(int(normalized["weekday"])),
        start_time=str(normalized["start_time"]),
        end_time=str(normalized["end_time"]),
        subject=normalized.get("subject"),
        room=normalized.get("room"),
        group=normalized.get("group"),
        teacher_key=normalized.get("teacher_key"),
        effective_from=effective_from,
        effective_to=effective_to,
        source=normalized.get("source"),
    )


def _serialize_timetable_version_exception(payload: dict) -> TimetableVersionExceptionOut | None:
    normalized = _normalize_snapshot_exception_payload(payload)
    if normalized is None:
        return None
    rule_out = _serialize_timetable_version_rule(normalized["rule"])
    exception_date = _parse_iso_date(normalized["exception_date"])
    if rule_out is None or exception_date is None:
        return None
    target_date = _parse_iso_date(normalized["target_date"]) if normalized.get("target_date") else None
    target_start_time = _parse_iso_time(normalized["target_start_time"]) if normalized.get("target_start_time") else None
    target_end_time = _parse_iso_time(normalized["target_end_time"]) if normalized.get("target_end_time") else None
    return TimetableVersionExceptionOut(
        exception_date=exception_date,
        exception_type=str(normalized["exception_type"]),
        target_date=target_date,
        target_start_time=target_start_time,
        target_end_time=target_end_time,
        note=normalized.get("note"),
        rule=rule_out,
    )


def _serialize_timetable_version_row(row: TimetableVersion) -> TimetableVersionOut:
    return TimetableVersionOut(
        id=int(row.id),
        class_id=int(row.class_id),
        label=str(row.label or "").strip() or None,
        source=str(row.source or "").strip() or None,
        is_active=bool(row.is_active),
        rules_count=int(row.rules_count or 0),
        exceptions_count=int(row.exceptions_count or 0),
        created_by_user_id=int(row.created_by_user_id) if row.created_by_user_id is not None else None,
        activated_at=row.activated_at,
        created_at=row.created_at,
    )


def _serialize_timetable_version_detail_row(row: TimetableVersion) -> TimetableVersionDetailOut:
    base = _serialize_timetable_version_row(row)
    rules_payload, exceptions_payload = _normalize_snapshot_bundle(row.snapshot)
    rules_out = [entry for entry in (_serialize_timetable_version_rule(payload) for payload in rules_payload) if entry is not None]
    exceptions_out = [
        entry
        for entry in (_serialize_timetable_version_exception(payload) for payload in exceptions_payload)
        if entry is not None
    ]
    return TimetableVersionDetailOut(
        **base.model_dump(),
        rules=rules_out,
        exceptions=exceptions_out,
    )


def _set_active_timetable_version(db: Session, *, class_id: int, version_id: int) -> None:
    rows = db.scalars(select(TimetableVersion).where(TimetableVersion.class_id == int(class_id))).all()
    activated_at = _utc_now_naive()
    for row in rows:
        is_target = int(row.id) == int(version_id)
        row.is_active = is_target
        if is_target:
            row.activated_at = activated_at


def _serialize_unit_blueprint(row: WorkflowUnitBlueprint) -> WorkflowUnitBlueprintOut:
    return WorkflowUnitBlueprintOut(
        id=int(row.id),
        unit_id=int(row.unit_id),
        provider=str(row.provider or "fallback"),
        model=row.model,
        status=str(row.status or "ready"),
        requested_session_count=row.requested_session_count,
        document_hash=row.document_hash,
        source_text_excerpt=row.source_text_excerpt,
        blueprint_json=row.blueprint_json or {},
        unit_map_json=row.unit_map_json or None,
        content_blocks_json=row.content_blocks_json if isinstance(row.content_blocks_json, list) else None,
        raw_provider_response=row.raw_provider_response,
        error_message=row.error_message,
        reviewed=bool(row.reviewed),
        reviewed_at=row.reviewed_at,
        reviewed_by_user_id=row.reviewed_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _serialize_unit_material(row: WorkflowUnitMaterial) -> WorkflowUnitMaterialOut:
    return WorkflowUnitMaterialOut(
        id=int(row.id),
        unit_id=int(row.unit_id),
        material_type=str(row.material_type or "study_guide"),
        provider=str(row.provider or "fallback"),
        model=row.model,
        status=str(row.status or "ready"),
        title=row.title,
        notebook_artifact_id=str(row.notebook_artifact_id or "").strip() or None,
        source_payload=row.source_payload_json if isinstance(row.source_payload_json, dict) else None,
        content_markdown=str(row.content_markdown or "").strip() or None,
        file_name=str(row.file_name or "").strip() or None,
        file_content_type=str(row.file_content_type or "").strip() or None,
        raw_provider_response=row.raw_provider_response if isinstance(row.raw_provider_response, dict) else None,
        error_message=row.error_message,
        created_by_user_id=int(row.created_by_user_id) if row.created_by_user_id is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _build_unit_material_download_filename(unit: WorkflowUnit, material: WorkflowUnitMaterial) -> str:
    raw_unit_title = str(unit.title or "").strip() or f"unit-{int(unit.id)}"
    raw_material_title = str(material.title or material.material_type or "material").strip() or "material"
    stem = f"{raw_unit_title}-{raw_material_title}".lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem)
    stem = stem.strip("-") or f"unit-{int(unit.id)}-material"
    return f"{stem}.md"


def _serialize_unit_assistant_artifact(row: WorkflowUnitAssistantArtifact) -> WorkflowUnitAssistantArtifactOut:
    return WorkflowUnitAssistantArtifactOut(
        id=int(row.id),
        unit_id=int(row.unit_id),
        checklist_item_id=int(row.checklist_item_id) if row.checklist_item_id is not None else None,
        artifact_kind=str(row.artifact_kind or "teacher_notes"),
        provider=str(row.provider or "notebooklm"),
        model=row.model,
        section_title=str(row.section_title or "").strip() or None,
        section_path=[str(value) for value in (row.section_path_json or []) if str(value or "").strip()],
        action=str(row.action or "").strip() or None,
        title=str(row.title or "").strip() or None,
        content_markdown=str(row.content_markdown or "").strip() or None,
        source_payload=row.source_payload_json if isinstance(row.source_payload_json, dict) else None,
        raw_provider_response=row.raw_provider_response if isinstance(row.raw_provider_response, dict) else None,
        created_by_user_id=int(row.created_by_user_id) if row.created_by_user_id is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _assistant_artifact_kind_label(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "teacher_notes": "Teacher notes",
        "guided_practice": "Guided practice",
        "quick_quiz_draft": "Quick quiz draft",
    }
    return mapping.get(normalized, "Saved guidance")


def _build_unit_assistant_artifact_markdown(
    *,
    unit: WorkflowUnit,
    payload: WorkflowUnitAssistantArtifactSaveIn,
) -> str:
    title = str(payload.title or "").strip() or _assistant_artifact_kind_label(payload.artifact_kind)
    section_title = str(payload.section_title or "").strip()
    section_path = [str(value).strip() for value in (payload.section_path or []) if str(value).strip()]
    action = str(payload.action or "").strip()
    provider = str(payload.provider or "").strip()
    answer_rows = [str(value).strip() for value in (payload.answer_rows or []) if str(value).strip()]
    followups = [str(value).strip() for value in (payload.suggested_followups or []) if str(value).strip()]
    lines = [
        f"# {title}",
        "",
        f"- Unit: {str(unit.title or '').strip() or f'Unit {int(unit.id)}'}",
        f"- Kind: {_assistant_artifact_kind_label(payload.artifact_kind)}",
    ]
    if section_title:
        lines.append(f"- Section: {section_title}")
    if section_path:
        lines.append(f"- Path: {' -> '.join(section_path)}")
    if action:
        lines.append(f"- Action: {action}")
    if provider:
        lines.append(f"- Provider: {provider}")
    lines.extend(["", "## Guidance", ""])
    if answer_rows:
        lines.extend(f"- {row}" for row in answer_rows)
    else:
        lines.append("- No structured guidance returned.")
    if followups:
        lines.extend(["", "## Suggested follow-ups", ""])
        lines.extend(f"- {row}" for row in followups)
    return "\n".join(lines).strip()


def _build_unit_assistant_artifact_download_filename(
    unit: WorkflowUnit,
    artifact: WorkflowUnitAssistantArtifact,
) -> str:
    raw_unit_title = str(unit.title or "").strip() or f"unit-{int(unit.id)}"
    raw_section_title = str(artifact.section_title or artifact.title or artifact.artifact_kind or "guidance").strip()
    stem = f"{raw_unit_title}-{raw_section_title}-{artifact.artifact_kind}".lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem)
    stem = stem.strip("-") or f"unit-{int(unit.id)}-guidance"
    return f"{stem}.md"


def _serialize_session_writeup(row: WorkflowSessionWriteup) -> WorkflowSessionWriteupOut:
    checked_ids = row.checked_item_ids_json if isinstance(row.checked_item_ids_json, list) else []
    checked_titles = row.checked_item_titles_json if isinstance(row.checked_item_titles_json, list) else []
    learning_focus = row.learning_focus_json if isinstance(row.learning_focus_json, list) else []
    teaching_content = row.teaching_content_json if isinstance(row.teaching_content_json, list) else []
    practice_items = row.practice_items_json if isinstance(row.practice_items_json, list) else []
    return WorkflowSessionWriteupOut(
        id=int(row.id),
        session_id=int(row.session_id),
        unit_id=int(row.unit_id) if row.unit_id is not None else None,
        provider=str(row.provider or "fallback"),
        model=row.model,
        status=str(row.status or "ready"),
        title=row.title,
        checked_item_ids=[int(value) for value in checked_ids if int(value) > 0],
        checked_item_titles=[str(value) for value in checked_titles if str(value or "").strip()],
        learning_focus=[str(value) for value in learning_focus if str(value or "").strip()],
        teaching_content=[str(value) for value in teaching_content if str(value or "").strip()],
        practice_items=[str(value) for value in practice_items if str(value or "").strip()],
        teacher_note_snapshot=row.teacher_note_snapshot,
        source_payload=row.source_payload_json if isinstance(row.source_payload_json, dict) else None,
        raw_provider_response=row.raw_provider_response if isinstance(row.raw_provider_response, dict) else None,
        error_message=row.error_message,
        approved=bool(row.approved),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _normalize_writeup_rows(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(str(raw or "").split()).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _extract_assistant_artifact_answer_rows(artifact: WorkflowUnitAssistantArtifact) -> list[str]:
    payload = artifact.source_payload_json if isinstance(artifact.source_payload_json, dict) else {}
    raw_rows = payload.get("answer_rows") if isinstance(payload.get("answer_rows"), list) else None
    normalized = _normalize_writeup_rows([str(value) for value in (raw_rows or []) if str(value or "").strip()])
    if normalized:
        return normalized
    content = str(artifact.content_markdown or "").strip()
    if not content:
        return []
    rows: list[str] = []
    in_guidance = False
    for raw_line in content.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if line.startswith("## "):
            in_guidance = line.lower() == "## guidance"
            continue
        if not in_guidance:
            continue
        if line.startswith("- "):
            rows.append(line[2:].strip())
    return _normalize_writeup_rows(rows) or []


def _merge_writeup_rows(existing: list[str] | None, incoming: list[str] | None) -> list[str]:
    merged = [str(value) for value in (existing or []) if str(value or "").strip()]
    merged.extend(str(value) for value in (incoming or []) if str(value or "").strip())
    return _normalize_writeup_rows(merged) or []


def _merge_assistant_artifact_into_writeup(
    *,
    row: WorkflowSessionWriteup,
    artifact: WorkflowUnitAssistantArtifact,
) -> None:
    answer_rows = _extract_assistant_artifact_answer_rows(artifact)
    focus_rows = row.learning_focus_json if isinstance(row.learning_focus_json, list) else []
    content_rows = row.teaching_content_json if isinstance(row.teaching_content_json, list) else []
    practice_rows = row.practice_items_json if isinstance(row.practice_items_json, list) else []
    section_title = str(artifact.section_title or "").strip()
    if section_title:
        focus_rows = _merge_writeup_rows(focus_rows, [section_title])
    kind = str(artifact.artifact_kind or "").strip().lower()
    if kind == "teacher_notes":
        content_rows = _merge_writeup_rows(content_rows, answer_rows)
    elif kind in {"guided_practice", "quick_quiz_draft"}:
        practice_rows = _merge_writeup_rows(practice_rows, answer_rows)
    else:
        content_rows = _merge_writeup_rows(content_rows, answer_rows)
    row.learning_focus_json = focus_rows
    row.teaching_content_json = content_rows
    row.practice_items_json = practice_rows
    if not row.title:
        row.title = (str(artifact.title or "").strip() or section_title or row.title or "")[:255] or None
    row.provider = str(row.provider or artifact.provider or "notebooklm").strip() or "notebooklm"
    row.model = row.model or artifact.model
    row.status = "ready"
    row.approved = False
    base_payload = row.source_payload_json if isinstance(row.source_payload_json, dict) else {}
    imported = base_payload.get("imported_assistant_artifacts") if isinstance(base_payload.get("imported_assistant_artifacts"), list) else []
    imported.append(
        {
            "artifact_id": int(artifact.id),
            "artifact_kind": kind or None,
            "section_title": section_title or None,
            "action": str(artifact.action or "").strip() or None,
        }
    )
    deduped: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for entry in imported:
        if not isinstance(entry, dict):
            continue
        try:
            artifact_id = int(entry.get("artifact_id"))
        except Exception:
            continue
        if artifact_id in seen_ids:
            continue
        seen_ids.add(artifact_id)
        deduped.append(entry)
    base_payload["imported_assistant_artifacts"] = deduped
    row.source_payload_json = base_payload


def _serialize_session(db: Session, session: ClassSession) -> WorkflowSessionOut:
    absent_ids = db.scalars(
        select(AttendanceRecord.student_id).where(
            AttendanceRecord.session_id == session.id,
            AttendanceRecord.status == AttendanceStatus.ABSENT,
        )
    ).all()
    absent_count = len(absent_ids)
    has_saved_writeup = bool(
        db.scalar(select(WorkflowSessionWriteup.id).where(WorkflowSessionWriteup.session_id == int(session.id)))
    )
    checked_ids = [
        int(value)
        for value in db.scalars(
            select(WorkflowSessionChecklistAction.item_id).where(
                WorkflowSessionChecklistAction.session_id == session.id,
                WorkflowSessionChecklistAction.checked.is_(True),
            )
        ).all()
        if int(value) > 0
    ]
    if session.unit_id is not None and checked_ids:
        checked_ids = _filter_actionable_check_item_ids(
            db,
            unit_id=int(session.unit_id),
            item_ids=checked_ids,
        )
    checked_items_count = len(checked_ids)
    checked_contexts = (
        _serialize_checked_item_contexts(
            db,
            unit_id=int(session.unit_id),
            checked_item_ids=checked_ids,
        )
        if session.unit_id is not None and checked_ids
        else []
    )
    return WorkflowSessionOut(
        id=session.id,
        class_id=session.class_id,
        unit_id=session.unit_id,
        unit_session_number=_resolve_unit_session_number(db, session),
        session_date=session.session_date,
        start_time=session.start_time,
        end_time=session.end_time,
        note=session.note,
        absent_count=absent_count,
        absent_student_ids=sorted(int(value) for value in absent_ids),
        checked_items_count=checked_items_count,
        checked_item_paths=[
            [str(part).strip() for part in (row.get("item_path") or []) if str(part).strip()]
            for row in checked_contexts
            if isinstance(row, dict)
        ],
        checked_section_paths=[
            [str(part).strip() for part in (row.get("section_path") or []) if str(part).strip()]
            for row in checked_contexts
            if isinstance(row, dict)
        ],
        has_saved_writeup=has_saved_writeup,
    )


def _create_unit_with_generated_checklist(
    db: Session,
    *,
    class_id: int,
    current_user: User,
    unit_type: WorkflowUnitType,
    title: str,
    planned_hours: float | None,
    file: UploadFile | None,
    source_text: str | None,
    enforce_upload_limits: bool,
    checklist_session_count: int | None = None,
    checklist_session_hint_out: dict[int, int] | None = None,
) -> WorkflowUnit:
    normalized_title = str(title or "").strip()
    if not normalized_title:
        raise HTTPException(status_code=400, detail="Unit title is required.")
    if planned_hours is not None and float(planned_hours) <= 0:
        raise HTTPException(status_code=400, detail="planned_hours must be greater than zero.")
    if db.scalar(
        select(WorkflowUnit.id).where(
            WorkflowUnit.class_id == class_id,
            WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
        )
    ):
        raise HTTPException(status_code=409, detail="An active unit already exists. Close it first.")

    has_source_text = bool(source_text and source_text.strip())
    if unit_type in {WorkflowUnitType.CHAPTER, WorkflowUnitType.EXERCISE_SERIES} and file is None and not has_source_text:
        raise HTTPException(status_code=400, detail="Document file or source text is required for chapter or exercise series.")
    if file is not None and Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents are supported for checklist generation.")

    if enforce_upload_limits:
        enforce_rate_limit(
            scope="upload",
            user_id=current_user.id,
            limit=app_config.UPLOAD_RATE_LIMIT_COUNT,
            window_seconds=app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
            resource_id=class_id,
        )

    order_index = int(
        db.scalar(select(func.coalesce(func.max(WorkflowUnit.order_index), 0)).where(WorkflowUnit.class_id == class_id)) or 0
    ) + 1
    unit = WorkflowUnit(
        class_id=class_id,
        unit_type=unit_type,
        status=WorkflowUnitStatus.ACTIVE,
        title=normalized_title,
        planned_hours=planned_hours,
        order_index=order_index,
        created_by_user_id=current_user.id,
    )
    db.add(unit)
    db.flush()

    extracted_text = source_text or ""
    document_hash: str | None = build_document_hash(extracted_text) if extracted_text else None
    uploaded_document_path: Path | None = None
    try:
        if file is not None:
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            workflow_dir = UPLOADS_DIR / "workflow"
            workflow_dir.mkdir(parents=True, exist_ok=True)
            content, extension = read_validated_upload(
                file,
                max_bytes=max(MAX_SCREENSHOT_UPLOAD_BYTES, app_config.MAX_EXCEL_UPLOAD_BYTES),
                allowed_extensions=ALLOWED_WORKFLOW_DOC_EXTENSIONS,
                allowed_mime_types=ALLOWED_WORKFLOW_DOC_MIME_TYPES,
                purpose="document",
            )
            file_name = f"{uuid.uuid4().hex}{extension}"
            target = workflow_dir / file_name
            with target.open("wb") as handle:
                handle.write(content)
            uploaded_document_path = target
            unit.document_name = file.filename
            unit.document_path = str(target)
            document_hash = build_document_hash(content)
            extracted_text = extract_text_from_document(str(target), source_text)
            if not document_hash:
                document_hash = build_document_hash(extracted_text)
            if unit_type == WorkflowUnitType.EXAM and _title_needs_exam_inference(unit.title, file_name=file.filename):
                inferred_exam_title = _infer_exam_title_from_source_text(
                    extracted_text,
                    fallback_title=unit.title,
                    file_name=file.filename,
                )
                if inferred_exam_title:
                    unit.title = inferred_exam_title[:255]

        generated = generate_unit_checklist(
            unit_type=unit_type,
            title=unit.title,
            source_text=extracted_text,
            session_count=checklist_session_count,
            document_path=unit.document_path,
        )
    except NotebookLMGenerationUnavailableError as exc:
        if uploaded_document_path is not None:
            try:
                uploaded_document_path.unlink(missing_ok=True)
            except Exception:
                pass
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if uploaded_document_path is not None:
            try:
                uploaded_document_path.unlink(missing_ok=True)
            except Exception:
                pass
        db.rollback()
        logger.exception(
            "workflow.unit.start_failed",
            extra={
                "class_id": int(class_id),
                "unit_type": str(unit_type.value),
                "title": str(unit.title or "").strip(),
                "has_file": bool(file is not None),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=f"Unit start failed while processing the source content ({exc.__class__.__name__}).",
        ) from exc
    _store_generated_checklist_on_unit(
        db,
        unit=unit,
        generated=generated,
        extracted_text=extracted_text,
        document_hash=document_hash,
        checklist_session_count=checklist_session_count,
        checklist_session_hint_out=checklist_session_hint_out,
    )

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.start",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={
            "unit_type": unit_type.value,
            "title": unit.title,
            "planned_hours": planned_hours,
            "generation_source": generated.get("source"),
        },
    )
    return unit


def _store_generated_checklist_on_unit(
    db: Session,
    *,
    unit: WorkflowUnit,
    generated: dict[str, object],
    extracted_text: str,
    document_hash: str | None,
    checklist_session_count: int | None = None,
    checklist_session_hint_out: dict[int, int] | None = None,
) -> None:
    nodes = generated.get("items") or []
    if _title_looks_like_slug(unit.title):
        better_title = _first_meaningful_generated_title(nodes)
        if better_title:
            unit.title = better_title[:255]

    db.execute(delete(WorkflowLeafContent).where(WorkflowLeafContent.unit_id == int(unit.id)))
    db.execute(delete(WorkflowChecklistItem).where(WorkflowChecklistItem.unit_id == int(unit.id)))
    db.flush()

    position_counter = 1

    def create_items(
        children: list[dict],
        *,
        parent_id: int | None,
        depth: int,
        inherited_session_number: int | None = None,
    ) -> None:
        nonlocal position_counter
        for child in children:
            raw_kind = str(child.get("kind", WorkflowChecklistItemKind.OTHER.value)).strip().lower()
            kind_values = {kind.value for kind in WorkflowChecklistItemKind}
            item_kind = WorkflowChecklistItemKind(raw_kind if raw_kind in kind_values else WorkflowChecklistItemKind.OTHER.value)
            raw_session_number = child.get("session_number")
            session_number = inherited_session_number
            if raw_session_number is not None:
                try:
                    parsed_session_number = int(raw_session_number)
                except Exception:
                    parsed_session_number = None
                if parsed_session_number is not None and parsed_session_number > 0:
                    session_number = parsed_session_number
            row = WorkflowChecklistItem(
                unit_id=unit.id,
                parent_item_id=parent_id,
                item_kind=item_kind,
                title=str(child.get("title", "")).strip()[:500],
                position=position_counter,
                depth=depth,
            )
            position_counter += 1
            db.add(row)
            db.flush()
            nested = child.get("children")
            if isinstance(nested, list) and nested:
                create_items(
                    nested,
                    parent_id=row.id,
                    depth=depth + 1,
                    inherited_session_number=session_number,
                )
            elif checklist_session_hint_out is not None and session_number is not None and session_number > 0:
                checklist_session_hint_out[int(row.id)] = int(session_number)

    create_items(nodes, parent_id=None, depth=0, inherited_session_number=None)

    save_unit_blueprint(
        db,
        unit_id=int(unit.id),
        provider=str(generated.get("source") or "fallback"),
        model=str(generated.get("model") or "").strip() or None,
        requested_session_count=checklist_session_count,
        document_hash=document_hash,
        source_text=extracted_text,
        blueprint_json={
            "unit_title": unit.title,
            "unit_type": unit.unit_type.value,
            "requested_session_count": checklist_session_count,
            "items": nodes,
            "provider_context": generated.get("provider_context") if isinstance(generated.get("provider_context"), dict) else None,
        },
        unit_map_json=generated.get("unit_map") if isinstance(generated.get("unit_map"), dict) else None,
        content_blocks_json=generated.get("content_blocks") if isinstance(generated.get("content_blocks"), list) else None,
        raw_provider_response=generated if isinstance(generated, dict) else None,
        status=str(generated.get("status") or "ready").strip() or "ready",
        error_message=str(generated.get("error_message") or "").strip() or None,
        reviewed=bool(str(generated.get("source") or "").strip() == "template"),
        reviewed_at=_utc_now_naive() if str(generated.get("source") or "").strip() == "template" else None,
    )
    _seed_unit_leaf_content_from_blueprint(db, unit_id=int(unit.id))


@router.post("/classes/{class_id}/units/start", response_model=WorkflowUnitOut, status_code=status.HTTP_201_CREATED)
def start_unit(
    class_id: int,
    unit_type: WorkflowUnitType = Form(...),
    title: str = Form(...),
    planned_hours: float | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    source_text: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = _create_unit_with_generated_checklist(
        db,
        class_id=class_id,
        current_user=current_user,
        unit_type=unit_type,
        title=title,
        planned_hours=planned_hours,
        file=file,
        source_text=source_text,
        enforce_upload_limits=True,
    )
    db.commit()
    db.refresh(unit)
    return _serialize_unit(db, unit)


@router.post("/classes/{class_id}/exams/{exam_id}/linked-unit", response_model=WorkflowExamLinkedUnitCreateOut)
def create_linked_exam_workflow_unit(
    class_id: int,
    exam_id: int,
    payload: WorkflowExamLinkedUnitCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowExamLinkedUnitCreateOut:
    _ = ensure_class_writable(db, class_id, current_user)
    exam = db.get(Exam, exam_id)
    if exam is None or int(exam.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Exam not found.")
    requested_type = payload.unit_type
    if requested_type not in {WorkflowUnitType.EXAM, WorkflowUnitType.EXAM_CORRECTION}:
        raise HTTPException(status_code=400, detail="Only exam or exam_correction workflow units can be linked to an exam.")

    existing_active = db.scalar(
        select(WorkflowUnit)
        .where(
            WorkflowUnit.class_id == class_id,
            WorkflowUnit.exam_id == exam_id,
            WorkflowUnit.unit_type == requested_type,
            WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
        )
        .order_by(WorkflowUnit.created_at.desc(), WorkflowUnit.id.desc())
    )
    if existing_active is not None:
        return WorkflowExamLinkedUnitCreateOut(
            created=False,
            reopened=False,
            unit=_serialize_unit(db, existing_active),
        )

    existing_latest = db.scalar(
        select(WorkflowUnit)
        .where(
            WorkflowUnit.class_id == class_id,
            WorkflowUnit.exam_id == exam_id,
            WorkflowUnit.unit_type == requested_type,
        )
        .order_by(WorkflowUnit.created_at.desc(), WorkflowUnit.id.desc())
    )
    if existing_latest is not None and existing_latest.status == WorkflowUnitStatus.CLOSED:
        _reopen_workflow_unit_record(
            db,
            class_id=class_id,
            unit=existing_latest,
            current_user=current_user,
        )
        db.commit()
        db.refresh(existing_latest)
        return WorkflowExamLinkedUnitCreateOut(
            created=False,
            reopened=True,
            unit=_serialize_unit(db, existing_latest),
        )

    default_title = exam.title if requested_type == WorkflowUnitType.EXAM else f"Correction - {exam.title}"
    title = _normalize_workflow_title(payload.title, fallback=default_title)
    generated = _build_linked_exam_generated_payload(
        db,
        class_id=class_id,
        exam=exam,
        unit_type=requested_type,
        title=title,
    )
    unit = _create_unit_with_seeded_checklist(
        db,
        class_id=class_id,
        current_user=current_user,
        unit_type=requested_type,
        title=title,
        generated=generated,
        exam_id=exam.id,
    )
    db.commit()
    db.refresh(unit)
    return WorkflowExamLinkedUnitCreateOut(created=True, reopened=False, unit=_serialize_unit(db, unit))


def _serialize_checklist_attachment(row: WorkflowChecklistItemAttachment) -> WorkflowChecklistItemAttachmentOut:
    return WorkflowChecklistItemAttachmentOut(
        id=_safe_int(row.id, default=0),
        item_id=_safe_int(row.item_id, default=0),
        file_name=str(row.file_name or "").strip() or None,
        file_content_type=str(row.file_content_type or "").strip() or None,
        created_at=row.created_at,
    )


@router.post(
    "/classes/{class_id}/units/{unit_id}/items/{item_id}/attachments",
    response_model=WorkflowChecklistItemAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_workflow_checklist_item_attachment(
    class_id: int,
    unit_id: int,
    item_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowChecklistItemAttachmentOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only active units can receive checklist screenshots.")
    item = db.get(WorkflowChecklistItem, item_id)
    if item is None or int(item.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Checklist item not found.")

    enforce_rate_limit(
        scope="upload",
        user_id=current_user.id,
        limit=20,
        window_seconds=3600,
        resource_id=int(item_id),
    )
    content, extension = read_validated_upload(
        file,
        max_bytes=MAX_SCREENSHOT_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        allowed_mime_types=ALLOWED_IMAGE_MIME_TYPES,
        purpose="image",
    )
    target_dir = UPLOADS_DIR / "workflow-checklist" / str(class_id) / str(unit_id) / str(item_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{uuid.uuid4().hex}{extension}"
    target = target_dir / target_name
    target.write_bytes(content)

    attachment = WorkflowChecklistItemAttachment(
        item_id=int(item_id),
        file_path=str(target),
        file_name=str(file.filename or target_name).strip() or target_name,
        file_content_type=str(file.content_type or "").strip() or None,
        created_by_user_id=current_user.id,
    )
    db.add(attachment)
    db.flush()
    log_audit(
        db,
        user=current_user,
        action="workflow.item.attachment.upload",
        entity_type="workflow_item_attachment",
        entity_id=attachment.id,
        class_id=class_id,
        details={"unit_id": int(unit_id), "item_id": int(item_id), "file_name": attachment.file_name},
    )
    db.commit()
    db.refresh(attachment)
    return _serialize_checklist_attachment(attachment)


@router.get("/classes/{class_id}/units/{unit_id}/items/{item_id}/attachments/{attachment_id}")
def download_workflow_checklist_item_attachment(
    class_id: int,
    unit_id: int,
    item_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = ensure_class_access(db, class_id, current_user)
    item = db.get(WorkflowChecklistItem, item_id)
    if item is None or int(item.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Checklist item not found.")
    attachment = db.get(WorkflowChecklistItemAttachment, attachment_id)
    if attachment is None or int(attachment.item_id) != int(item_id):
        raise HTTPException(status_code=404, detail="Checklist attachment not found.")
    path = Path(str(attachment.file_path or "").strip())
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Checklist attachment file not found.")
    filename = str(attachment.file_name or path.name).strip() or path.name
    return FileResponse(path=str(path), media_type=str(attachment.file_content_type or "application/octet-stream"), filename=filename)


@router.delete("/classes/{class_id}/units/{unit_id}/items/{item_id}/attachments/{attachment_id}")
def delete_workflow_checklist_item_attachment(
    class_id: int,
    unit_id: int,
    item_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only active units can update checklist screenshots.")
    item = db.get(WorkflowChecklistItem, item_id)
    if item is None or int(item.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Checklist item not found.")
    attachment = db.get(WorkflowChecklistItemAttachment, attachment_id)
    if attachment is None or int(attachment.item_id) != int(item_id):
        raise HTTPException(status_code=404, detail="Checklist attachment not found.")
    deleted_file = _safe_unlink(str(attachment.file_path or "").strip())
    deleted_id = int(attachment.id)
    file_name = str(attachment.file_name or "").strip() or None
    db.delete(attachment)
    log_audit(
        db,
        user=current_user,
        action="workflow.item.attachment.delete",
        entity_type="workflow_item_attachment",
        entity_id=deleted_id,
        class_id=class_id,
        details={"unit_id": int(unit_id), "item_id": int(item_id), "file_name": file_name, "deleted_file": deleted_file},
    )
    db.commit()
    return {"deleted_attachment_id": deleted_id, "deleted_file": deleted_file}


@router.post("/classes/{class_id}/units/{unit_id}/items", response_model=WorkflowChecklistItemOut, status_code=status.HTTP_201_CREATED)
def create_workflow_checklist_item(
    class_id: int,
    unit_id: int,
    payload: WorkflowChecklistItemCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowChecklistItemOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or unit.class_id != class_id:
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only active unit checklist can be edited.")

    title = str(payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Checklist item title is required.")

    parent_item: WorkflowChecklistItem | None = None
    if payload.parent_item_id is not None:
        parent_item = db.get(WorkflowChecklistItem, payload.parent_item_id)
        if parent_item is None or parent_item.unit_id != unit.id:
            raise HTTPException(status_code=404, detail="Parent checklist item not found in this unit.")

    depth = (parent_item.depth + 1) if parent_item is not None else 0
    parent_condition = (
        WorkflowChecklistItem.parent_item_id == parent_item.id
        if parent_item is not None
        else WorkflowChecklistItem.parent_item_id.is_(None)
    )
    position = (
        int(
            db.scalar(
                select(func.coalesce(func.max(WorkflowChecklistItem.position), 0)).where(
                    WorkflowChecklistItem.unit_id == unit.id,
                    parent_condition,
                )
            )
            or 0
        )
        + 1
    )

    item = WorkflowChecklistItem(
        unit_id=unit.id,
        parent_item_id=parent_item.id if parent_item is not None else None,
        item_kind=payload.item_kind,
        title=title[:500],
        teacher_note=str(payload.teacher_note or "").strip()[:4000] or None,
        position=position,
        depth=depth,
        is_completed=False,
    )
    db.add(item)
    db.flush()

    log_audit(
        db,
        user=current_user,
        action="workflow.item.create",
        entity_type="workflow_item",
        entity_id=item.id,
        class_id=class_id,
        details={
            "unit_id": unit.id,
            "parent_item_id": item.parent_item_id,
            "item_kind": item.item_kind.value,
            "title": item.title,
            "position": position,
        },
    )
    db.commit()
    db.refresh(item)
    return WorkflowChecklistItemOut(
        id=item.id,
        unit_id=item.unit_id,
        parent_item_id=item.parent_item_id,
        item_kind=item.item_kind,
        title=item.title,
        position=item.position,
        depth=item.depth,
        is_completed=item.is_completed,
        completed_session_id=item.completed_session_id,
        completed_at=item.completed_at,
        teacher_note=str(item.teacher_note or "").strip() or None,
        children=[],
    )


@router.post("/classes/{class_id}/units/{unit_id}/items/reorder")
def reorder_workflow_checklist_items(
    class_id: int,
    unit_id: int,
    payload: WorkflowChecklistReorderIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or unit.class_id != class_id:
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only active unit checklist can be edited.")

    rows = db.scalars(
        select(WorkflowChecklistItem).where(WorkflowChecklistItem.unit_id == unit.id).order_by(WorkflowChecklistItem.id.asc())
    ).all()
    if not rows:
        raise HTTPException(status_code=400, detail="Unit has no checklist items to reorder.")

    unit_item_ids = {row.id for row in rows}
    parent_by_id, depth_by_id, raw_position_by_id = _build_reorder_maps(payload.items, unit_item_ids)
    previous_by_id = {row.id: (row.parent_item_id, row.position) for row in rows}

    # Re-index siblings to deterministic 1..N positions based on payload.
    siblings_by_parent: dict[int | None, list[tuple[int, int, int]]] = {}
    for index, row in enumerate(payload.items):
        siblings_by_parent.setdefault(parent_by_id[row.id], []).append((raw_position_by_id[row.id], index, row.id))

    final_position_by_id: dict[int, int] = {}
    for siblings in siblings_by_parent.values():
        siblings.sort(key=lambda value: (value[0], value[1], value[2]))
        for sibling_position, (_, _, item_id) in enumerate(siblings, start=1):
            final_position_by_id[item_id] = sibling_position

    moved_count = 0
    for row in rows:
        previous_parent, previous_position = previous_by_id[row.id]
        if previous_parent != parent_by_id[row.id] or previous_position != final_position_by_id[row.id]:
            moved_count += 1

    # Two-phase write avoids unique(parent_item_id, position) conflicts during reshuffle.
    for temp_index, row in enumerate(rows, start=1):
        row.position = 100000 + temp_index
    db.flush()

    for row in rows:
        row.parent_item_id = parent_by_id[row.id]
        row.depth = depth_by_id[row.id]
        row.position = final_position_by_id[row.id]

    log_audit(
        db,
        user=current_user,
        action="workflow.item.reorder",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={
            "unit_id": unit.id,
            "updated_items": len(rows),
            "moved_items": moved_count,
        },
    )
    db.commit()
    return {"updated": len(rows), "moved": moved_count}


@router.put("/classes/{class_id}/units/{unit_id}/items/{item_id}", response_model=WorkflowChecklistItemOut)
def update_workflow_checklist_item(
    class_id: int,
    unit_id: int,
    item_id: int,
    payload: WorkflowChecklistItemUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowChecklistItemOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or unit.class_id != class_id:
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only active unit checklist can be edited.")

    item = db.get(WorkflowChecklistItem, item_id)
    if item is None or item.unit_id != unit.id:
        raise HTTPException(status_code=404, detail="Checklist item not found in this unit.")

    if payload.title is not None:
        title = str(payload.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Checklist item title cannot be empty.")
        item.title = title[:500]
    if payload.item_kind is not None:
        item.item_kind = payload.item_kind
    if payload.teacher_note is not None:
        item.teacher_note = str(payload.teacher_note or "").strip()[:4000] or None

    log_audit(
        db,
        user=current_user,
        action="workflow.item.update",
        entity_type="workflow_item",
        entity_id=item.id,
        class_id=class_id,
        details={
            "unit_id": unit.id,
            "title": item.title,
            "item_kind": item.item_kind.value,
            "has_teacher_note": bool(str(item.teacher_note or "").strip()),
        },
    )
    db.commit()
    db.refresh(item)
    return WorkflowChecklistItemOut(
        id=item.id,
        unit_id=item.unit_id,
        parent_item_id=item.parent_item_id,
        item_kind=item.item_kind,
        title=item.title,
        position=item.position,
        depth=item.depth,
        is_completed=item.is_completed,
        completed_session_id=item.completed_session_id,
        completed_at=item.completed_at,
        teacher_note=str(item.teacher_note or "").strip() or None,
        children=[],
    )


@router.delete("/classes/{class_id}/units/{unit_id}/items/{item_id}")
def delete_workflow_checklist_item(
    class_id: int,
    unit_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or unit.class_id != class_id:
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only active unit checklist can be edited.")

    item = db.get(WorkflowChecklistItem, item_id)
    if item is None or item.unit_id != unit.id:
        raise HTTPException(status_code=404, detail="Checklist item not found in this unit.")

    deleted_id = item.id
    deleted_title = item.title
    db.delete(item)
    log_audit(
        db,
        user=current_user,
        action="workflow.item.delete",
        entity_type="workflow_item",
        entity_id=deleted_id,
        class_id=class_id,
        details={
            "unit_id": unit.id,
            "title": deleted_title,
        },
    )
    db.commit()
    return {"deleted": True, "item_id": deleted_id}


@router.get("/classes/{class_id}", response_model=WorkflowWorkspaceOut)
def get_class_workflow(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowWorkspaceOut:
    _ = ensure_class_access(db, class_id, current_user)
    try:
        units = db.scalars(
            select(WorkflowUnit).where(WorkflowUnit.class_id == class_id).order_by(WorkflowUnit.order_index.desc(), WorkflowUnit.id.desc())
        ).all()
    except Exception:
        logger.exception("workflow.workspace_units_query_failed", extra={"class_id": int(class_id)})
        units = []
    active_unit = next((unit for unit in units if unit.status == WorkflowUnitStatus.ACTIVE), None)
    closed_units = [unit for unit in units if unit.status == WorkflowUnitStatus.CLOSED]

    try:
        active_session = db.scalar(
            select(ClassSession)
            .where(
                ClassSession.class_id == class_id,
                ClassSession.unit_id.is_not(None),
                ClassSession.end_time.is_(None),
            )
            .order_by(ClassSession.id.desc())
        )
    except Exception:
        logger.exception("workflow.workspace_active_session_query_failed", extra={"class_id": int(class_id)})
        active_session = None
    try:
        recent_sessions = db.scalars(
            select(ClassSession)
            .where(ClassSession.class_id == class_id, ClassSession.unit_id.is_not(None))
            .order_by(ClassSession.session_date.desc(), ClassSession.id.desc())
            .limit(20)
        ).all()
    except Exception:
        logger.exception("workflow.workspace_recent_sessions_query_failed", extra={"class_id": int(class_id)})
        recent_sessions = []

    active_unit_payload = _safe_serialize_unit(db, active_unit, class_id=class_id) if active_unit else None
    closed_units_payload = [row for row in (_safe_serialize_unit(db, unit, class_id=class_id) for unit in closed_units) if row is not None]
    active_session_payload = _safe_serialize_session(db, active_session, class_id=class_id) if active_session else None
    recent_sessions_payload = [row for row in (_safe_serialize_session(db, session, class_id=class_id) for session in recent_sessions) if row is not None]
    return WorkflowWorkspaceOut(
        class_id=class_id,
        active_unit=active_unit_payload,
        closed_units=closed_units_payload,
        active_session=active_session_payload,
        recent_sessions=recent_sessions_payload,
    )


@router.get("/units/{unit_id}/sessions", response_model=list[WorkflowSessionOut])
def list_unit_sessions(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowSessionOut]:
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found.")
    _ = ensure_class_access(db, unit.class_id, current_user)

    try:
        sessions = db.scalars(
            select(ClassSession)
            .where(ClassSession.unit_id == unit.id)
            .order_by(
                ClassSession.session_date.asc(),
                ClassSession.start_time.asc().nulls_last(),
                ClassSession.id.asc(),
            )
        ).all()
    except Exception:
        logger.exception("workflow.unit_sessions_query_failed", extra={"class_id": int(unit.class_id), "unit_id": int(unit.id)})
        sessions = []
    return [row for row in (_safe_serialize_session(db, session, class_id=unit.class_id) for session in sessions) if row is not None]


@router.get("/holidays", response_model=list[HolidayDayOut])
def list_workflow_holidays(
    year: int,
    country_code: str = "MA",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[HolidayDayOut]:
    _ = current_user
    rows = list_holidays_for_year(db, year=year, country_code=country_code)
    # Persist auto-seeded fixed holidays (if any).
    db.commit()
    return rows


@router.post("/holidays/seed/morocco/{year}", response_model=list[HolidayDayOut])
def seed_morocco_holidays(
    year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[HolidayDayOut]:
    _ = current_user
    seed_morocco_fixed_holidays(db, year=year)
    db.commit()
    return list_holidays_for_year(db, year=year, country_code="MA")


@router.get("/holidays/template.xlsx")
def download_holiday_template(
    _: User = Depends(require_owner),
) -> StreamingResponse:
    content = build_holiday_import_template()
    filename = f"holiday-import-template-{_utc_now_naive().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/holidays/export.xlsx")
def export_workflow_holidays(
    year: int,
    country_code: str = "MA",
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
) -> StreamingResponse:
    rows = list_holidays_for_year(db, year=year, country_code=country_code)
    db.commit()
    content = build_holiday_export_workbook(rows)
    filename = f"holidays-{str(country_code or 'MA').lower()}-{int(year)}-{_utc_now_naive().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/holidays/import")
def import_workflow_holidays(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    owner_user: User = Depends(require_owner),
) -> dict:
    enforce_rate_limit(
        scope="upload",
        user_id=owner_user.id,
        limit=app_config.UPLOAD_RATE_LIMIT_COUNT,
        window_seconds=app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=0,
    )
    content, _ = read_validated_upload(
        file,
        max_bytes=app_config.MAX_EXCEL_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_EXCEL_EXTENSIONS,
        allowed_mime_types=ALLOWED_EXCEL_MIME_TYPES,
        purpose="excel",
    )
    rows, errors = parse_holiday_excel(content)
    if errors:
        preview = "; ".join(errors[:5])
        if len(errors) > 5:
            preview = f"{preview}; +{len(errors) - 5} more"
        raise HTTPException(status_code=400, detail=f"Holiday file has errors. {preview}")

    summary = upsert_owner_uploaded_holidays(db, rows=rows, country_code="MA")
    log_audit(
        db,
        user=owner_user,
        action="holidays.import",
        entity_type="holiday_day",
        details=summary,
    )
    db.commit()
    return summary


@router.patch("/holidays/{holiday_id}", response_model=HolidayDayOut)
def update_workflow_holiday(
    holiday_id: int,
    payload: HolidayDayUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HolidayDayOut:
    _ = current_user
    row = db.get(HolidayDay, holiday_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Holiday not found.")
    if payload.name is not None:
        title = str(payload.name).strip()
        if not title:
            raise HTTPException(status_code=400, detail="Holiday name cannot be empty.")
        row.name = title
    if payload.is_blocked is not None:
        row.is_blocked = bool(payload.is_blocked)
    db.commit()
    db.refresh(row)
    return row


def _normalize_setup_students(
    rows: list[ClassSetupStudentIn],
) -> list[dict]:
    normalized: list[dict] = []
    seen_codes: set[str] = set()
    for idx, row in enumerate(rows, start=1):
        full_name = str(row.full_name or "").strip()
        if not full_name:
            raise HTTPException(status_code=400, detail=f"Student row {idx}: full_name is required.")
        student_code = _clean_optional_text(row.student_code, max_length=64)
        external_id = _clean_optional_text(row.external_id, max_length=64)
        if student_code is not None:
            if student_code in seen_codes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Student row {idx}: duplicate student_code '{student_code}' in payload.",
                )
            seen_codes.add(student_code)
        normalized.append(
            {
                "full_name": full_name,
                "student_code": student_code,
                "external_id": external_id,
                "birth_date": row.birth_date,
            }
        )
    return normalized


def _normalize_setup_timetable_rows(
    rows: list[ClassSetupTimetableRowIn],
) -> list[dict]:
    normalized: list[dict] = []
    for idx, row in enumerate(rows, start=1):
        if int(row.weekday) in NON_WORKING_WEEKDAYS:
            raise HTTPException(
                status_code=400,
                detail=f"Timetable row {idx}: Sunday is a non-working day.",
            )
        if row.end_time <= row.start_time:
            raise HTTPException(
                status_code=400,
                detail=f"Timetable row {idx}: end_time must be greater than start_time.",
            )
        normalized.append(
            {
                "weekday": int(row.weekday),
                "start_time": row.start_time,
                "end_time": row.end_time,
                "subject": _clean_optional_text(row.subject, max_length=255),
                "room": _clean_optional_text(row.room, max_length=120),
                "group_name": _clean_optional_text(row.group, max_length=120),
                "teacher_key": _clean_optional_text(row.teacher_key, max_length=255),
            }
        )
    return normalized


@router.post("/class-setup", response_model=ClassSetupInitOut)
def submit_class_setup(
    payload: ClassSetupInitIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClassSetupInitOut:
    class_name_input = _clean_optional_text(payload.class_name, max_length=255)
    subject_input = _clean_optional_text(payload.subject, max_length=255)
    level_input = _clean_optional_text(payload.level, max_length=120)

    created_class = False
    if payload.class_id is not None:
        classroom = ensure_class_writable(db, int(payload.class_id), current_user)
        if class_name_input is not None:
            classroom.name = class_name_input
        if payload.subject is not None:
            classroom.subject = subject_input
        if payload.level is not None:
            classroom.level = level_input
    else:
        if not class_name_input:
            raise HTTPException(status_code=400, detail="class_name is required when class_id is not provided.")
        classroom = Classroom(
            name=class_name_input,
            subject=subject_input,
            level=level_input,
        )
        db.add(classroom)
        db.flush()
        if current_user.role == UserRole.TEACHER:
            has_link = db.scalar(
                select(ClassAccess.id).where(
                    ClassAccess.class_id == classroom.id,
                    ClassAccess.user_id == current_user.id,
                )
            )
            if has_link is None:
                db.add(ClassAccess(class_id=classroom.id, user_id=current_user.id))
        created_class = True

    normalized_student_mode = str(payload.student_mode or "append_new").strip().lower()
    students_created = 0
    students_updated = 0
    students_skipped = 0
    if normalized_student_mode == "ignore":
        students_skipped = len(payload.students or [])
    else:
        incoming_students = _normalize_setup_students(payload.students or [])
        if normalized_student_mode == "replace_all":
            db.execute(delete(Student).where(Student.class_id == int(classroom.id)))
            db.flush()

        existing_students = db.scalars(
            select(Student).where(Student.class_id == int(classroom.id)).order_by(Student.id.asc())
        ).all()
        existing_by_code: dict[str, Student] = {}
        existing_codes: set[str] = set()
        auto_code_counter = 1
        for row in existing_students:
            code = str(row.student_code or "").strip()
            if not code:
                continue
            existing_by_code[code] = row
            existing_codes.add(code)
            if code.upper().startswith("AUTO") and code[4:].isdigit():
                auto_code_counter = max(auto_code_counter, int(code[4:]) + 1)

        for row in incoming_students:
            student_code = row["student_code"]
            if student_code is None:
                student_code, auto_code_counter = _next_auto_student_code(existing_codes, auto_code_counter)
            existing = existing_by_code.get(student_code)
            if existing is not None and normalized_student_mode == "append_new":
                students_skipped += 1
                continue
            if existing is None:
                db.add(
                    Student(
                        class_id=int(classroom.id),
                        student_code=student_code,
                        external_id=row["external_id"],
                        full_name=row["full_name"],
                        birth_date=row["birth_date"],
                    )
                )
                existing_codes.add(student_code)
                students_created += 1
                continue

            changed = False
            if existing.full_name != row["full_name"]:
                existing.full_name = row["full_name"]
                changed = True
            if existing.external_id != row["external_id"]:
                existing.external_id = row["external_id"]
                changed = True
            if existing.birth_date != row["birth_date"]:
                existing.birth_date = row["birth_date"]
                changed = True
            if changed:
                students_updated += 1
            else:
                students_skipped += 1

    normalized_timetable_mode = str(payload.timetable_mode or "replace_future_from_date").strip().lower()
    timetable_total_rows = len(payload.timetable_rows or [])
    timetable_applied_rows = 0
    timetable_skipped_duplicates = 0
    timetable_replaced_existing_count = 0
    effective_date = payload.effective_from or datetime.now(UTC).date()
    effective_to = payload.effective_to

    if normalized_timetable_mode != "ignore":
        if effective_to is not None and effective_to < effective_date:
            raise HTTPException(status_code=400, detail="effective_to must be greater than or equal to effective_from.")
        normalized_timetable_rows = _normalize_setup_timetable_rows(payload.timetable_rows or [])

        if normalized_timetable_mode == "replace_future_from_date":
            impacted_rows = db.scalars(
                select(ClassTimetableRule).where(
                    ClassTimetableRule.class_id == int(classroom.id),
                    (ClassTimetableRule.effective_to.is_(None) | (ClassTimetableRule.effective_to >= effective_date)),
                )
            ).all()
            for existing_row in impacted_rows:
                if existing_row.effective_from < effective_date:
                    existing_row.effective_to = effective_date - timedelta(days=1)
                else:
                    db.delete(existing_row)
                timetable_replaced_existing_count += 1
            db.flush()

        existing_query = select(ClassTimetableRule).where(
            ClassTimetableRule.class_id == int(classroom.id),
            ClassTimetableRule.effective_from == effective_date,
        )
        if effective_to is None:
            existing_query = existing_query.where(ClassTimetableRule.effective_to.is_(None))
        else:
            existing_query = existing_query.where(ClassTimetableRule.effective_to == effective_to)

        existing_window_rows = db.scalars(existing_query).all()
        seen_rule_keys = {
            _timetable_rule_identity_tuple(
                weekday=row.weekday,
                start_time=row.start_time,
                end_time=row.end_time,
                subject=row.subject,
                room=row.room,
                group_name=row.group_name,
                teacher_key=row.teacher_key,
            )
            for row in existing_window_rows
        }

        for row in normalized_timetable_rows:
            row_key = _timetable_rule_identity_tuple(
                weekday=row["weekday"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                subject=row["subject"],
                room=row["room"],
                group_name=row["group_name"],
                teacher_key=row["teacher_key"],
            )
            if row_key in seen_rule_keys:
                timetable_skipped_duplicates += 1
                continue
            db.add(
                ClassTimetableRule(
                    class_id=int(classroom.id),
                    teacher_key=row["teacher_key"],
                    subject=row["subject"],
                    weekday=row["weekday"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    room=row["room"],
                    group_name=row["group_name"],
                    effective_from=effective_date,
                    effective_to=effective_to,
                    source="class-setup-form",
                )
            )
            seen_rule_keys.add(row_key)
            timetable_applied_rows += 1

    log_audit(
        db,
        user=current_user,
        action="workflow.class_setup.submit",
        entity_type="class",
        entity_id=int(classroom.id),
        class_id=int(classroom.id),
        details={
            "created_class": created_class,
            "student_mode": normalized_student_mode,
            "students_created": students_created,
            "students_updated": students_updated,
            "students_skipped": students_skipped,
            "timetable_mode": normalized_timetable_mode,
            "timetable_total_rows": timetable_total_rows,
            "timetable_applied_rows": timetable_applied_rows,
            "timetable_skipped_duplicates": timetable_skipped_duplicates,
            "timetable_replaced_existing_count": timetable_replaced_existing_count,
            "effective_from": effective_date.isoformat() if normalized_timetable_mode != "ignore" else None,
            "effective_to": effective_to.isoformat() if effective_to is not None else None,
        },
    )
    db.commit()
    db.refresh(classroom)

    students_total = int(
        db.scalar(select(func.count(Student.id)).where(Student.class_id == int(classroom.id)))
        or 0
    )
    return ClassSetupInitOut(
        class_id=int(classroom.id),
        class_name=str(classroom.name),
        created_class=created_class,
        students_created=students_created,
        students_updated=students_updated,
        students_skipped=students_skipped,
        students_total=students_total,
        timetable_total_rows=timetable_total_rows,
        timetable_applied_rows=timetable_applied_rows,
        timetable_skipped_duplicates=timetable_skipped_duplicates,
        timetable_replaced_existing_count=timetable_replaced_existing_count,
        effective_from=effective_date if normalized_timetable_mode != "ignore" else None,
        effective_to=effective_to if normalized_timetable_mode != "ignore" else None,
    )


@router.post("/timetable/import/preview", response_model=TimetableImportPreviewOut)
def preview_timetable_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableImportPreviewOut:
    enforce_rate_limit(
        scope="upload",
        user_id=current_user.id,
        limit=app_config.UPLOAD_RATE_LIMIT_COUNT,
        window_seconds=app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=0,
    )
    content, extension = read_validated_upload(
        file,
        max_bytes=app_config.MAX_EXCEL_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_TIMETABLE_IMPORT_EXTENSIONS,
        allowed_mime_types=ALLOWED_TIMETABLE_IMPORT_MIME_TYPES,
        purpose="timetable import",
    )

    if extension == ".csv":
        rows = parse_timetable_csv_preview(content)
    elif extension in {".xlsx", ".xlsm"}:
        rows = parse_timetable_xlsx_preview(content)
    else:
        rows = parse_timetable_ics_preview(content)
    total_rows = len(rows)
    valid_rows = sum(1 for row in rows if row.get("is_valid"))
    invalid_rows = total_rows - valid_rows
    return TimetableImportPreviewOut(
        total_rows=total_rows,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        rows=rows,
    )


@router.get("/classes/{class_id}/timetable-rules", response_model=list[TimetableRuleOut])
def list_class_timetable_rules(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TimetableRuleOut]:
    _ = ensure_class_access(db, class_id, current_user)
    rows = db.scalars(
        select(ClassTimetableRule)
        .where(ClassTimetableRule.class_id == class_id)
        .order_by(
            ClassTimetableRule.weekday.asc(),
            ClassTimetableRule.start_time.asc(),
            ClassTimetableRule.effective_from.desc(),
            ClassTimetableRule.id.asc(),
        )
    ).all()
    return [_serialize_timetable_rule(row) for row in rows]


@router.get("/classes/{class_id}/timetable-exceptions", response_model=list[TimetableRuleExceptionOut])
def list_class_timetable_exceptions(
    class_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TimetableRuleExceptionOut]:
    _ = ensure_class_access(db, class_id, current_user)
    stmt = select(TimetableRuleException).where(TimetableRuleException.class_id == class_id)
    if date_from is not None or date_to is not None:
        source_filters = []
        target_filters = []
        if date_from is not None:
            source_filters.append(TimetableRuleException.exception_date >= date_from)
            target_filters.append(TimetableRuleException.target_date >= date_from)
        if date_to is not None:
            source_filters.append(TimetableRuleException.exception_date <= date_to)
            target_filters.append(TimetableRuleException.target_date <= date_to)
        source_window = and_(*source_filters) if source_filters else None
        target_window = and_(*target_filters) if target_filters else None
        if source_window is not None and target_window is not None:
            stmt = stmt.where(
                or_(
                    source_window,
                    and_(TimetableRuleException.target_date.is_not(None), target_window),
                )
            )
        elif source_window is not None:
            stmt = stmt.where(source_window)
    stmt = stmt.order_by(TimetableRuleException.exception_date.asc(), TimetableRuleException.id.asc())
    rows = db.scalars(stmt).all()
    return [_serialize_timetable_exception(row) for row in rows]


@router.post("/classes/{class_id}/timetable-exceptions", response_model=TimetableRuleExceptionOut, status_code=status.HTTP_201_CREATED)
def create_class_timetable_exception(
    class_id: int,
    payload: TimetableRuleExceptionCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableRuleExceptionOut:
    _ = ensure_class_writable(db, class_id, current_user)
    rule = db.get(ClassTimetableRule, int(payload.rule_id))
    if rule is None or int(rule.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Timetable rule not found.")

    exception_type = str(payload.exception_type or "").strip().lower()
    if exception_type not in {"cancel", "move"}:
        raise HTTPException(status_code=400, detail="Unsupported exception_type. Use cancel or move.")

    target_date = payload.target_date
    target_start_time = payload.target_start_time
    target_end_time = payload.target_end_time
    allow_overlap = bool(payload.allow_overlap)
    existing = db.scalar(
        select(TimetableRuleException).where(
            TimetableRuleException.rule_id == int(rule.id),
            TimetableRuleException.exception_date == payload.exception_date,
            TimetableRuleException.exception_type == exception_type,
        )
    )
    if exception_type == "move":
        if target_date is None:
            raise HTTPException(status_code=400, detail="target_date is required for move exception.")
        if target_start_time is None:
            raise HTTPException(status_code=400, detail="target_start_time is required for move exception.")
        if target_end_time is not None and target_end_time < target_start_time:
            raise HTTPException(status_code=400, detail="target_end_time must be greater than or equal to target_start_time.")
        target_changed = (
            existing is None
            or existing.target_date != target_date
            or existing.target_start_time != target_start_time
        )
        if target_changed and _has_session_start_conflict(
            db,
            class_id=int(class_id),
            session_date=target_date,
            start_time=target_start_time,
        ):
            if not allow_overlap:
                raise HTTPException(
                    status_code=409,
                    detail="Target slot overlaps an existing real session start. Set allow_overlap=true to proceed.",
                )
    else:
        target_date = None
        target_start_time = None
        target_end_time = None
    normalized_note = str(payload.note or "").strip() or None
    if existing is not None:
        if (
            existing.note != normalized_note
            or existing.target_date != target_date
            or existing.target_start_time != target_start_time
            or existing.target_end_time != target_end_time
        ):
            existing.note = normalized_note
            existing.target_date = target_date
            existing.target_start_time = target_start_time
            existing.target_end_time = target_end_time
            db.commit()
            db.refresh(existing)
        return _serialize_timetable_exception(existing)

    row = TimetableRuleException(
        class_id=int(class_id),
        rule_id=int(rule.id),
        exception_date=payload.exception_date,
        exception_type=exception_type,
        target_date=target_date,
        target_start_time=target_start_time,
        target_end_time=target_end_time,
        note=normalized_note,
        created_by_user_id=int(current_user.id),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_timetable_exception(row)


@router.patch("/timetable-exceptions/{exception_id}", response_model=TimetableRuleExceptionOut)
def update_class_timetable_exception(
    exception_id: int,
    payload: TimetableRuleExceptionUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableRuleExceptionOut:
    row = db.get(TimetableRuleException, exception_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Timetable exception not found.")
    _ = ensure_class_writable(db, int(row.class_id), current_user)

    exception_type = str(row.exception_type or "").strip().lower()
    if exception_type not in {"cancel", "move"}:
        raise HTTPException(status_code=400, detail="Unsupported exception_type for update.")

    next_exception_date = payload.exception_date or row.exception_date
    duplicate = db.scalar(
        select(TimetableRuleException).where(
            TimetableRuleException.rule_id == int(row.rule_id),
            TimetableRuleException.exception_type == exception_type,
            TimetableRuleException.exception_date == next_exception_date,
            TimetableRuleException.id != int(row.id),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Exception already exists for this rule/date/type.")

    row.exception_date = next_exception_date
    if payload.note is not None:
        row.note = str(payload.note).strip() or None

    if exception_type == "move":
        next_target_date = payload.target_date if payload.target_date is not None else row.target_date
        next_target_start = payload.target_start_time if payload.target_start_time is not None else row.target_start_time
        next_target_end = payload.target_end_time if payload.target_end_time is not None else row.target_end_time
        if next_target_date is None:
            raise HTTPException(status_code=400, detail="target_date is required for move exception.")
        if next_target_start is None:
            raise HTTPException(status_code=400, detail="target_start_time is required for move exception.")
        if next_target_end is not None and next_target_end < next_target_start:
            raise HTTPException(status_code=400, detail="target_end_time must be greater than or equal to target_start_time.")
        target_changed = (
            next_target_date != row.target_date
            or next_target_start != row.target_start_time
        )
        allow_overlap = bool(payload.allow_overlap)
        if target_changed and _has_session_start_conflict(
            db,
            class_id=int(row.class_id),
            session_date=next_target_date,
            start_time=next_target_start,
        ):
            if not allow_overlap:
                raise HTTPException(
                    status_code=409,
                    detail="Target slot overlaps an existing real session start. Set allow_overlap=true to proceed.",
                )
        row.target_date = next_target_date
        row.target_start_time = next_target_start
        row.target_end_time = next_target_end
    else:
        row.target_date = None
        row.target_start_time = None
        row.target_end_time = None

    db.commit()
    db.refresh(row)
    return _serialize_timetable_exception(row)


@router.delete("/timetable-exceptions/{exception_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_class_timetable_exception(
    exception_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    row = db.get(TimetableRuleException, exception_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Timetable exception not found.")
    _ = ensure_class_writable(db, int(row.class_id), current_user)
    db.delete(row)
    db.commit()
    return None


@router.get("/timetable/class-mappings", response_model=list[TimetableClassAliasOut])
def list_timetable_class_mappings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TimetableClassAliasOut]:
    accessible_classes = _list_accessible_classes(db, current_user)
    classes_by_id = {int(row.id): row for row in accessible_classes}
    if not classes_by_id:
        return []

    rows = db.scalars(
        select(TimetableClassAlias)
        .where(
            TimetableClassAlias.user_id == current_user.id,
            TimetableClassAlias.class_id.in_(list(classes_by_id.keys())),
        )
        .order_by(TimetableClassAlias.alias_name.asc(), TimetableClassAlias.id.asc())
    ).all()
    return [
        _serialize_timetable_alias(row, classes_by_id[int(row.class_id)].name)
        for row in rows
        if int(row.class_id) in classes_by_id
    ]


@router.post("/timetable/class-mappings/bulk-save", response_model=TimetableClassAliasBulkSaveOut)
def bulk_save_timetable_class_mappings(
    payload: TimetableClassAliasBulkSaveIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableClassAliasBulkSaveOut:
    normalized_input = payload.mappings if isinstance(payload.mappings, dict) else {}
    if not normalized_input:
        return TimetableClassAliasBulkSaveOut(saved_count=0, skipped_count=0, rows=[])

    accessible_classes = _list_accessible_classes(db, current_user)
    classes_by_id = {int(row.id): row for row in accessible_classes}
    if not classes_by_id:
        raise HTTPException(status_code=400, detail="No accessible classes available for mapping.")

    normalized_map: dict[str, dict] = {}
    skipped_count = 0
    invalid_target_ids: set[int] = set()
    for raw_alias_name, raw_target_id in normalized_input.items():
        alias_name = str(raw_alias_name or "").strip()
        alias_key = _normalize_class_key(alias_name)
        target_id = int(raw_target_id)
        if not alias_key:
            skipped_count += 1
            continue
        if target_id <= 0:
            skipped_count += 1
            continue
        target_class = classes_by_id.get(target_id)
        if target_class is None:
            invalid_target_ids.add(target_id)
            continue
        normalized_map[alias_key] = {
            "alias_name": alias_name or alias_key,
            "target_class": target_class,
        }

    if invalid_target_ids:
        raise HTTPException(status_code=400, detail=f"Mapped class ids not accessible: {sorted(invalid_target_ids)}")
    if not normalized_map:
        return TimetableClassAliasBulkSaveOut(saved_count=0, skipped_count=skipped_count, rows=[])

    alias_keys = list(normalized_map.keys())
    existing_rows = db.scalars(
        select(TimetableClassAlias).where(
            TimetableClassAlias.user_id == current_user.id,
            TimetableClassAlias.alias_key.in_(alias_keys),
        )
    ).all()
    existing_by_key = {str(row.alias_key): row for row in existing_rows}

    changed_rows: list[TimetableClassAlias] = []
    for alias_key in alias_keys:
        row_payload = normalized_map[alias_key]
        alias_name = str(row_payload["alias_name"])
        target_class = row_payload["target_class"]
        existing_row = existing_by_key.get(alias_key)
        if existing_row is None:
            created_row = TimetableClassAlias(
                user_id=current_user.id,
                class_id=int(target_class.id),
                alias_name=alias_name,
                alias_key=alias_key,
            )
            db.add(created_row)
            changed_rows.append(created_row)
            continue
        if int(existing_row.class_id) != int(target_class.id) or str(existing_row.alias_name) != alias_name:
            existing_row.class_id = int(target_class.id)
            existing_row.alias_name = alias_name
            changed_rows.append(existing_row)

    db.commit()
    for row in changed_rows:
        db.refresh(row)

    serialized = [
        _serialize_timetable_alias(row, classes_by_id[int(row.class_id)].name)
        for row in changed_rows
        if int(row.class_id) in classes_by_id
    ]
    serialized.sort(key=lambda row: (str(row.alias_name).lower(), int(row.id)))
    return TimetableClassAliasBulkSaveOut(
        saved_count=len(serialized),
        skipped_count=skipped_count,
        rows=serialized,
    )


@router.patch("/timetable/class-mappings/{mapping_id}", response_model=TimetableClassAliasOut)
def update_timetable_class_mapping(
    mapping_id: int,
    payload: TimetableClassAliasUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableClassAliasOut:
    row = db.get(TimetableClassAlias, mapping_id)
    if row is None or int(row.user_id) != int(current_user.id):
        raise HTTPException(status_code=404, detail="Class mapping not found.")

    target_class = db.get(Classroom, int(payload.class_id))
    if target_class is None:
        raise HTTPException(status_code=404, detail="Target class not found.")

    if current_user.role != UserRole.OWNER:
        has_access_old = db.scalar(
            select(ClassAccess.id).where(
                ClassAccess.user_id == current_user.id,
                ClassAccess.class_id == row.class_id,
            )
        )
        has_access_target = db.scalar(
            select(ClassAccess.id).where(
                ClassAccess.user_id == current_user.id,
                ClassAccess.class_id == int(payload.class_id),
            )
        )
        if has_access_old is None or has_access_target is None:
            raise HTTPException(status_code=404, detail="Class mapping not found.")

    row.class_id = int(payload.class_id)
    db.commit()
    db.refresh(row)
    return _serialize_timetable_alias(row, target_class.name)


@router.delete("/timetable/class-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_timetable_class_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    row = db.get(TimetableClassAlias, mapping_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Class mapping not found.")
    if int(row.user_id) != int(current_user.id):
        raise HTTPException(status_code=404, detail="Class mapping not found.")

    if current_user.role != UserRole.OWNER:
        has_access = db.scalar(
            select(ClassAccess.id).where(
                ClassAccess.user_id == current_user.id,
                ClassAccess.class_id == row.class_id,
            )
        )
        if has_access is None:
            raise HTTPException(status_code=404, detail="Class mapping not found.")

    db.delete(row)
    db.commit()
    return None


@router.post("/timetable/import/apply", response_model=TimetableImportApplyOut)
def apply_timetable_import(
    file: UploadFile = File(...),
    mode: str = Form(default="dry_run_only"),
    effective_from: date | None = Form(default=None),
    effective_to: date | None = Form(default=None),
    create_missing_classes: bool = Form(default=False),
    class_mappings_json: str | None = Form(default=None),
    save_class_mappings: bool = Form(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableImportApplyOut:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"dry_run_only", "append_new_slots", "replace_future_from_date"}:
        raise HTTPException(status_code=400, detail="Invalid mode. Use dry_run_only, append_new_slots, or replace_future_from_date.")

    enforce_rate_limit(
        scope="upload",
        user_id=current_user.id,
        limit=app_config.UPLOAD_RATE_LIMIT_COUNT,
        window_seconds=app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=0,
    )
    content, extension = read_validated_upload(
        file,
        max_bytes=app_config.MAX_EXCEL_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_TIMETABLE_IMPORT_EXTENSIONS,
        allowed_mime_types=ALLOWED_TIMETABLE_IMPORT_MIME_TYPES,
        purpose="timetable import",
    )
    if extension == ".csv":
        parsed_rows = parse_timetable_csv_preview(content)
    elif extension in {".xlsx", ".xlsm"}:
        parsed_rows = parse_timetable_xlsx_preview(content)
    else:
        parsed_rows = parse_timetable_ics_preview(content)

    total_rows = len(parsed_rows)
    valid_rows = sum(1 for row in parsed_rows if row.get("is_valid"))
    invalid_rows = total_rows - valid_rows
    effective_date = effective_from or datetime.now(UTC).date()
    if effective_to is not None and effective_to < effective_date:
        raise HTTPException(status_code=400, detail="effective_to must be greater than or equal to effective_from.")
    dry_run = normalized_mode == "dry_run_only"

    accessible_classes = _list_accessible_classes(db, current_user)

    classes_by_key: dict[str, list[Classroom]] = {}
    classes_by_id: dict[int, Classroom] = {}
    for classroom in accessible_classes:
        classes_by_id[int(classroom.id)] = classroom
        key = _normalize_class_key(classroom.name)
        if not key:
            continue
        classes_by_key.setdefault(key, []).append(classroom)

    class_mapping_by_key: dict[str, Classroom] = {}
    persisted_alias_by_key: dict[str, TimetableClassAlias] = {}
    if classes_by_id:
        alias_rows = db.scalars(
            select(TimetableClassAlias).where(
                TimetableClassAlias.user_id == current_user.id,
                TimetableClassAlias.class_id.in_(list(classes_by_id.keys())),
            )
        ).all()
        for alias in alias_rows:
            alias_key = _normalize_class_key(alias.alias_key)
            resolved_target = classes_by_id.get(int(alias.class_id))
            if not alias_key or resolved_target is None:
                continue
            persisted_alias_by_key[alias_key] = alias
            class_mapping_by_key.setdefault(alias_key, resolved_target)

    explicit_mapping_by_key: dict[str, dict] = {}
    if class_mappings_json is not None and class_mappings_json.strip():
        try:
            raw_mappings = json.loads(class_mappings_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid class_mappings_json. Expected JSON object mapping import class names to class ids.",
            ) from exc
        if not isinstance(raw_mappings, dict):
            raise HTTPException(
                status_code=400,
                detail="Invalid class_mappings_json. Expected JSON object mapping import class names to class ids.",
            )

        invalid_mapping_ids: set[int] = set()
        invalid_mapping_values = False
        for raw_name, raw_target in raw_mappings.items():
            source_key = _normalize_class_key(str(raw_name or ""))
            if not source_key:
                continue

            target_id: int | None = None
            if isinstance(raw_target, bool):
                target_id = None
            elif isinstance(raw_target, int):
                target_id = int(raw_target)
            elif isinstance(raw_target, float) and raw_target.is_integer():
                target_id = int(raw_target)
            else:
                target_text = str(raw_target or "").strip()
                if target_text.isdigit():
                    target_id = int(target_text)
            if target_id is None:
                invalid_mapping_values = True
                continue

            resolved_target = classes_by_id.get(int(target_id))
            if resolved_target is None:
                invalid_mapping_ids.add(int(target_id))
                continue
            class_mapping_by_key[source_key] = resolved_target
            explicit_mapping_by_key[source_key] = {
                "alias_name": str(raw_name or "").strip() or source_key,
                "classroom": resolved_target,
            }

        if invalid_mapping_values:
            raise HTTPException(
                status_code=400,
                detail="Invalid class_mappings_json values. Each mapping target must be an accessible class id.",
            )
        if invalid_mapping_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Mapped class ids not accessible: {sorted(invalid_mapping_ids)}",
            )

    mapping_updates_applied = False
    if save_class_mappings and explicit_mapping_by_key:
        for alias_key, payload in explicit_mapping_by_key.items():
            alias_name = str(payload["alias_name"]).strip() or alias_key
            target_class = payload["classroom"]
            existing_alias = persisted_alias_by_key.get(alias_key)
            if existing_alias is None:
                new_alias = TimetableClassAlias(
                    user_id=current_user.id,
                    class_id=int(target_class.id),
                    alias_name=alias_name,
                    alias_key=alias_key,
                )
                db.add(new_alias)
                persisted_alias_by_key[alias_key] = new_alias
                mapping_updates_applied = True
                continue
            if int(existing_alias.class_id) != int(target_class.id) or str(existing_alias.alias_name) != alias_name:
                existing_alias.class_id = int(target_class.id)
                existing_alias.alias_name = alias_name
                mapping_updates_applied = True

    unresolved_class_names: list[str] = []
    result_rows: list[TimetableImportApplyRowOut] = []
    candidates: list[dict] = []
    created_classes_count = 0

    for row in parsed_rows:
        row_index = int(row.get("row_index") or 0)
        row_class_name = str(row.get("class_name") or "").strip() or None
        row_issues = list(row.get("issues") or [])
        if not row.get("is_valid"):
            result_rows.append(
                TimetableImportApplyRowOut(
                    row_index=row_index,
                    class_name=row_class_name,
                    class_id=None,
                    action="invalid",
                    issues=row_issues,
                )
            )
            continue

        class_key = _normalize_class_key(row_class_name)
        resolved_class: Classroom | None = None
        mapped_class = class_mapping_by_key.get(class_key)
        if mapped_class is not None:
            resolved_class = mapped_class
        else:
            class_matches = classes_by_key.get(class_key, [])
            if len(class_matches) > 1:
                unresolved_class_names.append(row_class_name or "")
                result_rows.append(
                    TimetableImportApplyRowOut(
                        row_index=row_index,
                        class_name=row_class_name,
                        class_id=None,
                        action="unresolved_class",
                        issues=["Ambiguous class name mapping. Add class_mappings_json entry to disambiguate."],
                    )
                )
                continue
            if len(class_matches) == 1:
                resolved_class = class_matches[0]
            elif create_missing_classes and row_class_name:
                if dry_run:
                    result_rows.append(
                        TimetableImportApplyRowOut(
                            row_index=row_index,
                            class_name=row_class_name,
                            class_id=None,
                            action="dry_run_create_class",
                            issues=[],
                        )
                    )
                    candidates.append(
                        {
                            "row_index": row_index,
                            "class_name": row_class_name,
                            "class_id": None,
                            "teacher_key": row.get("teacher_key"),
                            "subject": row.get("subject"),
                            "weekday": row.get("weekday"),
                            "start_time": row.get("start_time"),
                            "end_time": row.get("end_time"),
                            "room": row.get("room"),
                            "group": row.get("group"),
                        }
                    )
                    continue
                resolved_class = Classroom(name=row_class_name, subject=row.get("subject"), level=None)
                db.add(resolved_class)
                db.flush()
                if current_user.role == UserRole.TEACHER:
                    db.add(ClassAccess(class_id=resolved_class.id, user_id=current_user.id))
                classes_by_key.setdefault(class_key, []).append(resolved_class)
                classes_by_id[int(resolved_class.id)] = resolved_class
                created_classes_count += 1
            else:
                unresolved_class_names.append(row_class_name or "")
                result_rows.append(
                    TimetableImportApplyRowOut(
                        row_index=row_index,
                        class_name=row_class_name,
                        class_id=None,
                        action="unresolved_class",
                        issues=["Class not found. Add mapping or import with create_missing_classes=true to create it."],
                    )
                )
                continue

        start_time = _parse_hhmmss_time(str(row.get("start_time") or ""))
        end_time = _parse_hhmmss_time(str(row.get("end_time") or ""))
        if start_time is None or end_time is None:
            result_rows.append(
                TimetableImportApplyRowOut(
                    row_index=row_index,
                    class_name=row_class_name,
                    class_id=resolved_class.id if resolved_class is not None else None,
                    action="invalid",
                    issues=["Invalid start_time or end_time."],
                )
            )
            continue
        candidates.append(
            {
                "row_index": row_index,
                "class_name": row_class_name,
                "class_id": resolved_class.id,
                "teacher_key": row.get("teacher_key"),
                "subject": row.get("subject"),
                "weekday": int(row.get("weekday")),
                "start_time": start_time,
                "end_time": end_time,
                "room": row.get("room"),
                "group": row.get("group"),
            }
        )

    unresolved_class_names = sorted(set(name for name in unresolved_class_names if name))
    planned_apply_rows = len(candidates)
    applied_rows = 0
    skipped_duplicate_rows = 0
    skipped_unresolved_rows = sum(1 for row in result_rows if row.action == "unresolved_class")

    if dry_run:
        for candidate in candidates:
            if candidate["class_id"] is None:
                continue
            result_rows.append(
                TimetableImportApplyRowOut(
                    row_index=int(candidate["row_index"]),
                    class_name=candidate["class_name"],
                    class_id=int(candidate["class_id"]),
                    action="dry_run_ready",
                    issues=[],
                )
            )
        if mapping_updates_applied:
            db.commit()
        else:
            db.rollback()
    else:
        affected_class_ids = sorted({int(candidate["class_id"]) for candidate in candidates if candidate["class_id"] is not None})
        if normalized_mode == "replace_future_from_date" and affected_class_ids:
            rows_to_update = db.scalars(
                select(ClassTimetableRule).where(
                    ClassTimetableRule.class_id.in_(affected_class_ids),
                    (ClassTimetableRule.effective_to.is_(None) | (ClassTimetableRule.effective_to >= effective_date)),
                )
            ).all()
            for existing in rows_to_update:
                if existing.effective_from < effective_date:
                    existing.effective_to = effective_date - timedelta(days=1)
                else:
                    db.delete(existing)
            db.flush()

        existing_rules = []
        if affected_class_ids:
            existing_query = select(ClassTimetableRule).where(
                ClassTimetableRule.class_id.in_(affected_class_ids),
                ClassTimetableRule.effective_from == effective_date,
            )
            if effective_to is None:
                existing_query = existing_query.where(ClassTimetableRule.effective_to.is_(None))
            else:
                existing_query = existing_query.where(ClassTimetableRule.effective_to == effective_to)
            existing_rules = db.scalars(existing_query).all()

        def key_tuple(
            class_id: int,
            weekday: int,
            start_t: time,
            end_t: time,
            subject: str | None,
            room: str | None,
            group_name: str | None,
            teacher_key: str | None,
        ) -> tuple:
            return (
                int(class_id),
                int(weekday),
                start_t.isoformat(),
                end_t.isoformat(),
                str(subject or "").strip().lower(),
                str(room or "").strip().lower(),
                str(group_name or "").strip().lower(),
                str(teacher_key or "").strip().lower(),
            )

        seen_keys = {
            key_tuple(
                row.class_id,
                row.weekday,
                row.start_time,
                row.end_time,
                row.subject,
                row.room,
                row.group_name,
                row.teacher_key,
            )
            for row in existing_rules
        }

        for candidate in candidates:
            class_id = candidate.get("class_id")
            if class_id is None:
                continue
            tuple_key = key_tuple(
                class_id,
                candidate["weekday"],
                candidate["start_time"],
                candidate["end_time"],
                candidate["subject"],
                candidate["room"],
                candidate["group"],
                candidate["teacher_key"],
            )
            if tuple_key in seen_keys:
                skipped_duplicate_rows += 1
                result_rows.append(
                    TimetableImportApplyRowOut(
                        row_index=int(candidate["row_index"]),
                        class_name=candidate["class_name"],
                        class_id=int(class_id),
                        action="duplicate",
                        issues=["Duplicate timetable slot for effective date."],
                    )
                )
                continue

            rule = ClassTimetableRule(
                class_id=int(class_id),
                teacher_key=str(candidate["teacher_key"]).strip() if candidate.get("teacher_key") else None,
                subject=str(candidate["subject"]).strip() if candidate.get("subject") else None,
                weekday=int(candidate["weekday"]),
                start_time=candidate["start_time"],
                end_time=candidate["end_time"],
                room=str(candidate["room"]).strip() if candidate.get("room") else None,
                group_name=str(candidate["group"]).strip() if candidate.get("group") else None,
                effective_from=effective_date,
                effective_to=effective_to,
                source="timetable-import",
            )
            db.add(rule)
            seen_keys.add(tuple_key)
            applied_rows += 1
            result_rows.append(
                TimetableImportApplyRowOut(
                    row_index=int(candidate["row_index"]),
                    class_name=candidate["class_name"],
                    class_id=int(class_id),
                    action="applied",
                    issues=[],
                )
            )

        db.commit()

    result_rows.sort(key=lambda row: (int(row.row_index), str(row.action)))
    return TimetableImportApplyOut(
        mode=normalized_mode,
        effective_from=effective_date,
        effective_to=effective_to,
        total_rows=total_rows,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        planned_apply_rows=planned_apply_rows,
        applied_rows=applied_rows,
        skipped_duplicate_rows=skipped_duplicate_rows,
        skipped_unresolved_rows=skipped_unresolved_rows,
        created_classes_count=created_classes_count,
        unresolved_class_names=unresolved_class_names,
        rows=result_rows,
    )


@router.get("/classes/{class_id}/timetable-versions", response_model=list[TimetableVersionOut])
def list_timetable_versions(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TimetableVersionOut]:
    _ = ensure_class_access(db, class_id, current_user)
    rows = db.scalars(
        select(TimetableVersion)
        .where(TimetableVersion.class_id == int(class_id))
        .order_by(TimetableVersion.created_at.desc(), TimetableVersion.id.desc())
    ).all()
    return [_serialize_timetable_version_row(row) for row in rows]


@router.post("/classes/{class_id}/timetable-versions", response_model=TimetableVersionOut, status_code=status.HTTP_201_CREATED)
def create_timetable_version_snapshot(
    class_id: int,
    payload: TimetableVersionCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableVersionOut:
    _ = ensure_class_writable(db, class_id, current_user)
    snapshot = _collect_timetable_snapshot(db, class_id=int(class_id))
    rules_payload, exceptions_payload = _normalize_snapshot_bundle(snapshot)
    label = str(payload.label or "").strip() or f"Snapshot {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
    source = str(payload.source or "").strip() or "manual"
    row = TimetableVersion(
        class_id=int(class_id),
        created_by_user_id=int(current_user.id),
        label=label,
        source=source,
        is_active=True,
        rules_count=len(rules_payload),
        exceptions_count=len(exceptions_payload),
        snapshot={"rules": rules_payload, "exceptions": exceptions_payload},
    )
    db.add(row)
    db.flush()
    _set_active_timetable_version(db, class_id=int(class_id), version_id=int(row.id))
    log_audit(
        db,
        user=current_user,
        action="workflow.timetable_version.create",
        entity_type="timetable_version",
        entity_id=int(row.id),
        class_id=int(class_id),
        details={
            "label": row.label,
            "source": row.source,
            "rules_count": int(row.rules_count),
            "exceptions_count": int(row.exceptions_count),
        },
    )
    db.commit()
    db.refresh(row)
    return _serialize_timetable_version_row(row)


@router.get("/classes/{class_id}/timetable-versions/{version_id}", response_model=TimetableVersionDetailOut)
def get_timetable_version_detail(
    class_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableVersionDetailOut:
    _ = ensure_class_access(db, class_id, current_user)
    row = db.get(TimetableVersion, int(version_id))
    if row is None or int(row.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Timetable version not found.")
    return _serialize_timetable_version_detail_row(row)


@router.get("/classes/{class_id}/timetable-versions/{version_id}/compare-current", response_model=TimetableVersionCompareOut)
def compare_timetable_version_with_current(
    class_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableVersionCompareOut:
    _ = ensure_class_access(db, class_id, current_user)
    row = db.get(TimetableVersion, int(version_id))
    if row is None or int(row.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Timetable version not found.")

    snapshot_rules, snapshot_exceptions = _normalize_snapshot_bundle(row.snapshot)
    current_snapshot = _collect_timetable_snapshot(db, class_id=int(class_id))
    current_rules, current_exceptions = _normalize_snapshot_bundle(current_snapshot)

    snapshot_rules_by_key = {_rule_payload_key(payload): payload for payload in snapshot_rules}
    current_rules_by_key = {_rule_payload_key(payload): payload for payload in current_rules}
    snapshot_exceptions_by_key = {_exception_payload_key(payload): payload for payload in snapshot_exceptions}
    current_exceptions_by_key = {_exception_payload_key(payload): payload for payload in current_exceptions}

    snapshot_only_rule_keys = sorted(
        set(snapshot_rules_by_key.keys()) - set(current_rules_by_key.keys()),
        key=lambda key: _rule_payload_sort_key(snapshot_rules_by_key[key]),
    )
    current_only_rule_keys = sorted(
        set(current_rules_by_key.keys()) - set(snapshot_rules_by_key.keys()),
        key=lambda key: _rule_payload_sort_key(current_rules_by_key[key]),
    )
    snapshot_only_exception_keys = sorted(
        set(snapshot_exceptions_by_key.keys()) - set(current_exceptions_by_key.keys()),
        key=lambda key: _exception_payload_sort_key(snapshot_exceptions_by_key[key]),
    )
    current_only_exception_keys = sorted(
        set(current_exceptions_by_key.keys()) - set(snapshot_exceptions_by_key.keys()),
        key=lambda key: _exception_payload_sort_key(current_exceptions_by_key[key]),
    )

    snapshot_only_rules = [
        entry
        for entry in (
            _serialize_timetable_version_rule(snapshot_rules_by_key[key])
            for key in snapshot_only_rule_keys
        )
        if entry is not None
    ]
    current_only_rules = [
        entry
        for entry in (
            _serialize_timetable_version_rule(current_rules_by_key[key])
            for key in current_only_rule_keys
        )
        if entry is not None
    ]
    snapshot_only_exceptions = [
        entry
        for entry in (
            _serialize_timetable_version_exception(snapshot_exceptions_by_key[key])
            for key in snapshot_only_exception_keys
        )
        if entry is not None
    ]
    current_only_exceptions = [
        entry
        for entry in (
            _serialize_timetable_version_exception(current_exceptions_by_key[key])
            for key in current_only_exception_keys
        )
        if entry is not None
    ]

    return TimetableVersionCompareOut(
        version_id=int(row.id),
        class_id=int(class_id),
        snapshot_rules_count=len(snapshot_rules),
        snapshot_exceptions_count=len(snapshot_exceptions),
        current_rules_count=len(current_rules),
        current_exceptions_count=len(current_exceptions),
        snapshot_only_rules_count=len(snapshot_only_rules),
        current_only_rules_count=len(current_only_rules),
        snapshot_only_exceptions_count=len(snapshot_only_exceptions),
        current_only_exceptions_count=len(current_only_exceptions),
        snapshot_only_rules=snapshot_only_rules,
        current_only_rules=current_only_rules,
        snapshot_only_exceptions=snapshot_only_exceptions,
        current_only_exceptions=current_only_exceptions,
    )


@router.post("/classes/{class_id}/timetable-versions/{version_id}/restore", response_model=TimetableVersionRestoreOut)
def restore_timetable_version(
    class_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimetableVersionRestoreOut:
    _ = ensure_class_writable(db, class_id, current_user)
    row = db.get(TimetableVersion, int(version_id))
    if row is None or int(row.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Timetable version not found.")

    rules_payload, exceptions_payload = _normalize_snapshot_bundle(row.snapshot)
    existing_rules = db.scalars(select(ClassTimetableRule).where(ClassTimetableRule.class_id == int(class_id))).all()
    existing_exceptions = db.scalars(
        select(TimetableRuleException).where(TimetableRuleException.class_id == int(class_id))
    ).all()
    removed_rules_count = len(existing_rules)
    removed_exceptions_count = len(existing_exceptions)

    for existing in existing_exceptions:
        db.delete(existing)
    for existing in existing_rules:
        db.delete(existing)
    db.flush()

    restored_rules_count = 0
    restored_exceptions_count = 0
    rule_by_key: dict[tuple, ClassTimetableRule] = {}
    seen_rule_keys: set[tuple] = set()
    for payload_rule in rules_payload:
        rule_key = _rule_payload_key(payload_rule)
        if rule_key in seen_rule_keys:
            continue
        start_time = _parse_iso_time(payload_rule.get("start_time"))
        end_time = _parse_iso_time(payload_rule.get("end_time"))
        effective_from = _parse_iso_date(payload_rule.get("effective_from"))
        effective_to = _parse_iso_date(payload_rule.get("effective_to")) if payload_rule.get("effective_to") else None
        if start_time is None or end_time is None or effective_from is None:
            continue
        rule = ClassTimetableRule(
            class_id=int(class_id),
            teacher_key=payload_rule.get("teacher_key"),
            subject=payload_rule.get("subject"),
            weekday=int(payload_rule["weekday"]),
            start_time=start_time,
            end_time=end_time,
            room=payload_rule.get("room"),
            group_name=payload_rule.get("group"),
            effective_from=effective_from,
            effective_to=effective_to,
            source=payload_rule.get("source"),
        )
        db.add(rule)
        db.flush()
        seen_rule_keys.add(rule_key)
        rule_by_key[rule_key] = rule
        restored_rules_count += 1

    seen_exception_keys: set[tuple] = set()
    for payload_exception in exceptions_payload:
        exception_key = _exception_payload_key(payload_exception)
        if exception_key in seen_exception_keys:
            continue
        rule_key = _rule_payload_key(payload_exception["rule"])
        target_rule = rule_by_key.get(rule_key)
        if target_rule is None:
            continue
        exception_date = _parse_iso_date(payload_exception.get("exception_date"))
        if exception_date is None:
            continue
        target_date = _parse_iso_date(payload_exception.get("target_date")) if payload_exception.get("target_date") else None
        target_start_time = _parse_iso_time(payload_exception.get("target_start_time")) if payload_exception.get("target_start_time") else None
        target_end_time = _parse_iso_time(payload_exception.get("target_end_time")) if payload_exception.get("target_end_time") else None
        if str(payload_exception.get("exception_type")) == "move" and (target_date is None or target_start_time is None):
            continue
        restore_row = TimetableRuleException(
            class_id=int(class_id),
            rule_id=int(target_rule.id),
            exception_date=exception_date,
            exception_type=str(payload_exception["exception_type"]),
            target_date=target_date,
            target_start_time=target_start_time,
            target_end_time=target_end_time,
            note=payload_exception.get("note"),
            created_by_user_id=int(current_user.id),
        )
        db.add(restore_row)
        seen_exception_keys.add(exception_key)
        restored_exceptions_count += 1

    _set_active_timetable_version(db, class_id=int(class_id), version_id=int(row.id))
    log_audit(
        db,
        user=current_user,
        action="workflow.timetable_version.restore",
        entity_type="timetable_version",
        entity_id=int(row.id),
        class_id=int(class_id),
        details={
            "restored_rules_count": restored_rules_count,
            "restored_exceptions_count": restored_exceptions_count,
            "removed_rules_count": removed_rules_count,
            "removed_exceptions_count": removed_exceptions_count,
        },
    )
    db.commit()
    db.refresh(row)
    return TimetableVersionRestoreOut(
        version_id=int(row.id),
        class_id=int(class_id),
        restored_rules_count=restored_rules_count,
        restored_exceptions_count=restored_exceptions_count,
        removed_rules_count=removed_rules_count,
        removed_exceptions_count=removed_exceptions_count,
        active_version_id=int(row.id),
    )


@router.post("/classes/{class_id}/sessions", response_model=WorkflowSessionOut, status_code=status.HTTP_201_CREATED)
def create_workflow_calendar_session(
    class_id: int,
    payload: WorkflowCalendarSessionCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionOut:
    _ = ensure_class_writable(db, class_id, current_user)
    if _is_non_working_day(payload.session_date):
        raise HTTPException(status_code=409, detail="Sunday is a non-working day.")
    if payload.start_time is not None and payload.end_time is not None and payload.end_time < payload.start_time:
        raise HTTPException(status_code=400, detail="end_time must be greater than or equal to start_time.")
    if payload.start_time is not None and _has_session_start_conflict(
        db,
        class_id=int(class_id),
        session_date=payload.session_date,
        start_time=payload.start_time,
    ):
        raise HTTPException(status_code=409, detail="A session already exists at this date and start time.")
    if not payload.allow_on_holiday:
        blocked = find_blocked_holiday(db, payload.session_date, country_code="MA")
        if blocked is not None:
            raise HTTPException(status_code=409, detail=f"Selected date is blocked holiday: {blocked.name}")

    unit: WorkflowUnit | None = None
    if payload.unit_id is not None:
        unit = db.get(WorkflowUnit, payload.unit_id)
        if unit is None or unit.class_id != class_id:
            raise HTTPException(status_code=404, detail="Workflow unit not found.")

    students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.id.asc())).all()
    student_ids = {student.id for student in students}
    absent_ids = sorted(set(int(value) for value in payload.absent_student_ids))
    unknown_ids = sorted(set(absent_ids) - student_ids)
    if unknown_ids:
        raise HTTPException(status_code=400, detail=f"Unknown student ids: {unknown_ids}")
    session = ClassSession(
        class_id=class_id,
        unit_id=unit.id if unit is not None else None,
        unit_session_number=_compute_next_unit_session_number(db, unit.id) if unit is not None else None,
        session_date=payload.session_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        note=payload.note,
    )
    db.add(session)
    db.flush()

    absent_set = set(absent_ids)
    for student in students:
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                status=AttendanceStatus.ABSENT if student.id in absent_set else AttendanceStatus.PRESENT,
                minutes_late=0,
                comment=None,
            )
        )

    log_audit(
        db,
        user=current_user,
        action="workflow.session.create",
        entity_type="session",
        entity_id=session.id,
        class_id=class_id,
        details={
            "unit_id": session.unit_id,
            "unit_session_number": session.unit_session_number,
            "session_date": session.session_date.isoformat(),
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
            "absent_count": len(absent_set),
        },
    )
    db.commit()
    db.refresh(session)
    return _serialize_session(db, session)


@router.post("/classes/{class_id}/slot-actions", response_model=WorkflowCalendarSlotActionOut, status_code=status.HTTP_201_CREATED)
def create_workflow_slot_action(
    class_id: int,
    payload: WorkflowCalendarSlotActionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowCalendarSlotActionOut:
    _ = ensure_class_writable(db, class_id, current_user)
    if _is_non_working_day(payload.session_date):
        raise HTTPException(status_code=409, detail="Sunday is a non-working day.")
    if payload.start_time is not None and payload.end_time is not None and payload.end_time < payload.start_time:
        raise HTTPException(status_code=400, detail="end_time must be greater than or equal to start_time.")
    if payload.start_time is not None and _has_session_start_conflict(
        db,
        class_id=int(class_id),
        session_date=payload.session_date,
        start_time=payload.start_time,
    ):
        raise HTTPException(status_code=409, detail="A session already exists at this date and start time.")
    if not payload.allow_on_holiday:
        blocked = find_blocked_holiday(db, payload.session_date, country_code="MA")
        if blocked is not None:
            raise HTTPException(status_code=409, detail=f"Selected date is blocked holiday: {blocked.name}")

    students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.id.asc())).all()
    student_ids = {student.id for student in students}
    absent_ids = sorted(set(int(value) for value in payload.absent_student_ids))
    unknown_ids = sorted(set(absent_ids) - student_ids)
    if unknown_ids:
        raise HTTPException(status_code=400, detail=f"Unknown student ids: {unknown_ids}")
    checked_item_ids = sorted({int(value) for value in (payload.checked_item_ids or []) if int(value) > 0})

    action = str(payload.action or "").strip().lower()
    created_unit: WorkflowUnit | None = None
    target_unit: WorkflowUnit | None = None

    if action == "new_unit_session":
        if payload.unit_type is None:
            raise HTTPException(status_code=400, detail="unit_type is required for new_unit_session.")
        unit_title = str(payload.unit_title or "").strip()
        if not unit_title:
            raise HTTPException(status_code=400, detail="unit_title is required for new_unit_session.")
        source_text = str(payload.source_text or "").strip()
        if payload.unit_type in {WorkflowUnitType.CHAPTER, WorkflowUnitType.EXERCISE_SERIES} and not source_text:
            source_text = unit_title
        created_unit = _create_unit_with_generated_checklist(
            db,
            class_id=class_id,
            current_user=current_user,
            unit_type=payload.unit_type,
            title=unit_title,
            planned_hours=payload.planned_hours,
            file=None,
            source_text=source_text or None,
            enforce_upload_limits=False,
        )
        target_unit = created_unit
    elif action == "continue_unit_session":
        if payload.unit_id is not None:
            target_unit = db.get(WorkflowUnit, payload.unit_id)
            if target_unit is None or target_unit.class_id != class_id:
                raise HTTPException(status_code=404, detail="Workflow unit not found.")
        else:
            target_unit = _ensure_active_unit(db, class_id)
        if target_unit.status != WorkflowUnitStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="Selected workflow unit is not active.")
    else:
        raise HTTPException(status_code=400, detail="Unsupported slot action.")

    if target_unit is None:
        raise HTTPException(status_code=400, detail="Unable to resolve workflow unit for slot action.")

    session = ClassSession(
        class_id=class_id,
        unit_id=target_unit.id,
        unit_session_number=_compute_next_unit_session_number(db, target_unit.id),
        session_date=payload.session_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        note=payload.note,
    )
    db.add(session)
    db.flush()

    absent_set = set(absent_ids)
    for student in students:
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                status=AttendanceStatus.ABSENT if student.id in absent_set else AttendanceStatus.PRESENT,
                minutes_late=0,
                comment=None,
            )
        )

    checked_items_count = 0
    if checked_item_ids:
        checked_items_count = _apply_checked_items_to_session(
            db,
            unit_id=int(target_unit.id),
            session_id=int(session.id),
            checked_item_ids=checked_item_ids,
        )

    log_audit(
        db,
        user=current_user,
        action="workflow.slot_action.create",
        entity_type="session",
        entity_id=session.id,
        class_id=class_id,
        details={
            "action": action,
            "unit_id": session.unit_id,
            "unit_session_number": session.unit_session_number,
            "session_date": session.session_date.isoformat(),
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
            "absent_count": len(absent_set),
            "checked_items_count": checked_items_count,
        },
    )
    db.commit()
    if created_unit is not None:
        db.refresh(created_unit)
    db.refresh(session)
    return WorkflowCalendarSlotActionOut(
        unit=_serialize_unit(db, created_unit) if created_unit is not None else None,
        session=_serialize_session(db, session),
    )


@router.post("/classes/{class_id}/auto-plan", response_model=WorkflowCalendarAutoPlanOut)
def auto_plan_workflow_calendar(
    class_id: int,
    payload: WorkflowCalendarAutoPlanIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowCalendarAutoPlanOut:
    _ = ensure_class_writable(db, class_id, current_user)
    action = str(payload.action or "").strip().lower()
    dry_run = bool(payload.dry_run)
    if action not in {"load_week_plan", "plan_unit"}:
        raise HTTPException(status_code=400, detail="Unsupported auto-plan action.")

    rules = db.scalars(
        select(ClassTimetableRule)
        .where(ClassTimetableRule.class_id == int(class_id))
        .order_by(
            ClassTimetableRule.weekday.asc(),
            ClassTimetableRule.start_time.asc(),
            ClassTimetableRule.effective_from.asc(),
            ClassTimetableRule.id.asc(),
        )
    ).all()
    students = db.scalars(select(Student).where(Student.class_id == int(class_id)).order_by(Student.id.asc())).all()

    created_rows: list[ClassSession] = []
    target_unit: WorkflowUnit | None = None
    requested_count = 0
    failed_count = 0
    skipped_holiday_count = 0
    skipped_existing_count = 0
    skipped_exception_count = 0
    skipped_duplicate_count = 0
    search_end_date: date | None = None
    planned_slots: list[WorkflowCalendarPlannedSlotOut] = []
    target_unit_title: str | None = None

    def add_planned_slot(candidate: dict, note: str) -> None:
        rule = candidate["rule"]
        planned_slots.append(
            WorkflowCalendarPlannedSlotOut(
                session_date=candidate["session_date"],
                start_time=candidate.get("start_time"),
                end_time=candidate.get("end_time"),
                note=note,
                subject=rule.subject,
                room=rule.room,
                group_name=rule.group_name,
                moved_from_date=candidate.get("moved_from_date"),
            )
        )

    if action == "load_week_plan":
        base_day = payload.week_start or date.today()
        week_start = _start_of_week_date(base_day)
        week_end = week_start + timedelta(days=6)

        exceptions = _list_timetable_exceptions_for_range(
            db,
            class_id=class_id,
            date_from=week_start,
            date_to=week_end,
        )
        blocked_holidays = _list_blocked_holiday_dates(
            db,
            date_from=week_start,
            date_to=week_end,
            country_code="MA",
        )
        existing_start_keys = _collect_existing_session_start_keys(
            db,
            class_id=class_id,
            date_from=week_start,
            date_to=week_end,
        )
        candidates, stats = _build_timetable_candidates_for_range(
            date_from=week_start,
            date_to=week_end,
            rules=rules,
            exceptions=exceptions,
            blocked_holiday_dates=blocked_holidays,
            existing_start_keys=existing_start_keys,
        )
        requested_count = len(candidates)
        skipped_holiday_count = int(stats.get("skipped_holiday_count", 0))
        skipped_existing_count = int(stats.get("skipped_existing_count", 0))
        skipped_exception_count = int(stats.get("skipped_exception_count", 0))
        skipped_duplicate_count = int(stats.get("skipped_duplicate_count", 0))
        search_end_date = week_end

        for candidate in candidates:
            rule = candidate["rule"]
            note = _session_note_from_rule(
                prefix="Auto-planned from timetable",
                rule=rule,
                moved_from_date=candidate.get("moved_from_date"),
                exception_note=candidate.get("exception_note"),
            )
            add_planned_slot(candidate, note)
            if dry_run:
                continue
            created_rows.append(
                _create_workflow_session_with_students(
                    db,
                    class_id=class_id,
                    students=students,
                    session_date=candidate["session_date"],
                    start_time=candidate["start_time"],
                    end_time=candidate.get("end_time"),
                    note=note,
                    current_user=current_user,
                    unit_id=None,
                    audit_action="workflow.auto_plan.week.create_session",
                )
            )
    else:
        plan_mode = str(payload.plan_mode or "").strip().lower()
        if plan_mode not in {"new_unit", "continue_unit"}:
            raise HTTPException(status_code=400, detail="plan_mode is required for plan_unit action.")
        if payload.start_date is None:
            raise HTTPException(status_code=400, detail="start_date is required for plan_unit action.")
        if payload.session_count is None or int(payload.session_count) <= 0:
            raise HTTPException(status_code=400, detail="session_count must be greater than zero.")

        new_unit_title: str | None = None
        new_unit_type: WorkflowUnitType | None = None
        new_unit_source_text: str | None = None
        if plan_mode == "new_unit":
            if payload.unit_type is None:
                raise HTTPException(status_code=400, detail="unit_type is required for new_unit planning.")
            title = str(payload.unit_title or "").strip()
            if not title:
                raise HTTPException(status_code=400, detail="unit_title is required for new_unit planning.")
            active_unit_exists = db.scalar(
                select(WorkflowUnit.id).where(
                    WorkflowUnit.class_id == int(class_id),
                    WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
                )
            )
            if active_unit_exists is not None:
                raise HTTPException(status_code=409, detail="An active unit already exists. Close it first.")
            source_text = str(payload.source_text or "").strip()
            if payload.unit_type in {WorkflowUnitType.CHAPTER, WorkflowUnitType.EXERCISE_SERIES} and not source_text:
                source_text = title
            new_unit_title = title
            new_unit_type = payload.unit_type
            new_unit_source_text = source_text or None
            target_unit_title = title

        requested_count = int(payload.session_count)
        start_date = payload.start_date
        max_search_days = int(payload.max_search_days or min(730, max(120, requested_count * 21)))
        skip_blocked_holidays = bool(payload.skip_blocked_holidays)
        selected, stats, search_end_date = _build_timetable_candidates_for_count(
            db,
            class_id=int(class_id),
            start_date=start_date,
            requested_count=requested_count,
            rules=rules,
            skip_blocked_holidays=skip_blocked_holidays,
            max_search_days=max_search_days,
            country_code="MA",
        )
        if not selected:
            raise HTTPException(status_code=409, detail="No valid timetable slots available for this planning window.")

        skipped_holiday_count = int(stats.get("skipped_holiday_count", 0))
        skipped_existing_count = int(stats.get("skipped_existing_count", 0))
        skipped_exception_count = int(stats.get("skipped_exception_count", 0))
        skipped_duplicate_count = int(stats.get("skipped_duplicate_count", 0))

        if plan_mode == "new_unit":
            if new_unit_type is None or not new_unit_title:
                raise HTTPException(status_code=400, detail="Invalid new unit planning payload.")
            if not dry_run:
                target_unit = _create_unit_with_generated_checklist(
                    db,
                    class_id=class_id,
                    current_user=current_user,
                    unit_type=new_unit_type,
                    title=new_unit_title,
                    planned_hours=payload.planned_hours,
                    file=None,
                    source_text=new_unit_source_text,
                    enforce_upload_limits=False,
                )
        else:
            target_unit = _ensure_active_unit(db, class_id)
            if target_unit.status != WorkflowUnitStatus.ACTIVE:
                raise HTTPException(status_code=409, detail="Selected workflow unit is not active.")
            target_unit_title = target_unit.title

        total_selected = len(selected)
        title_for_note = target_unit.title if target_unit is not None else (target_unit_title or "unit")
        for index, candidate in enumerate(selected, start=1):
            rule = candidate["rule"]
            prefix = f"Auto-plan {title_for_note} session {index}/{total_selected}"
            note = _session_note_from_rule(
                prefix=prefix,
                rule=rule,
                moved_from_date=candidate.get("moved_from_date"),
                exception_note=candidate.get("exception_note"),
            )
            add_planned_slot(candidate, note)
            if dry_run:
                continue
            created_rows.append(
                _create_workflow_session_with_students(
                    db,
                    class_id=class_id,
                    students=students,
                    session_date=candidate["session_date"],
                    start_time=candidate["start_time"],
                    end_time=candidate.get("end_time"),
                    note=note,
                    current_user=current_user,
                    unit_id=target_unit.id if target_unit is not None else None,
                    audit_action="workflow.auto_plan.unit.create_session",
                    audit_details={
                        "auto_plan_mode": plan_mode,
                        "auto_plan_index": index,
                        "auto_plan_total": total_selected,
                    },
                )
            )
        planned_or_created = len(selected) if dry_run else len(created_rows)
        failed_count = max(0, requested_count - planned_or_created)

    if dry_run:
        db.rollback()
        return WorkflowCalendarAutoPlanOut(
            action=action,
            requested_count=requested_count,
            planned_count=len(planned_slots),
            created_count=0,
            failed_count=failed_count,
            search_end_date=search_end_date,
            skipped_holiday_count=skipped_holiday_count,
            skipped_existing_count=skipped_existing_count,
            skipped_exception_count=skipped_exception_count,
            skipped_duplicate_count=skipped_duplicate_count,
            target_unit_id=target_unit.id if target_unit is not None else None,
            target_unit_title=target_unit.title if target_unit is not None else target_unit_title,
            planned_slots=planned_slots,
            created_sessions=[],
        )

    log_audit(
        db,
        user=current_user,
        action="workflow.auto_plan.execute",
        entity_type="classroom",
        entity_id=class_id,
        class_id=class_id,
        details={
            "action": action,
            "dry_run": False,
            "requested_count": requested_count,
            "created_count": len(created_rows),
            "planned_count": len(planned_slots),
            "failed_count": failed_count,
            "search_end_date": search_end_date.isoformat() if search_end_date is not None else None,
            "skipped_holiday_count": skipped_holiday_count,
            "skipped_existing_count": skipped_existing_count,
            "skipped_exception_count": skipped_exception_count,
            "skipped_duplicate_count": skipped_duplicate_count,
            "target_unit_id": target_unit.id if target_unit is not None else None,
        },
    )
    db.commit()
    if target_unit is not None:
        db.refresh(target_unit)
    for row in created_rows:
        db.refresh(row)

    created_sessions = [_serialize_session(db, row) for row in created_rows]
    return WorkflowCalendarAutoPlanOut(
        action=action,
        requested_count=requested_count,
        planned_count=len(planned_slots),
        created_count=len(created_sessions),
        failed_count=failed_count,
        search_end_date=search_end_date,
        skipped_holiday_count=skipped_holiday_count,
        skipped_existing_count=skipped_existing_count,
        skipped_exception_count=skipped_exception_count,
        skipped_duplicate_count=skipped_duplicate_count,
        target_unit_id=target_unit.id if target_unit is not None else None,
        target_unit_title=target_unit.title if target_unit is not None else target_unit_title,
        planned_slots=planned_slots,
        created_sessions=created_sessions,
    )


@router.post("/classes/{class_id}/auto-setup-from-doc", response_model=WorkflowCalendarAutoPlanOut)
def auto_setup_from_document(
    class_id: int,
    unit_type: WorkflowUnitType = Form(...),
    unit_title: str = Form(...),
    session_count: int = Form(...),
    start_date: date = Form(...),
    planned_hours: float | None = Form(default=None),
    source_text: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    skip_blocked_holidays: bool = Form(default=True),
    max_search_days: int | None = Form(default=None),
    auto_check_items: bool = Form(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowCalendarAutoPlanOut:
    _ = ensure_class_writable(db, class_id, current_user)
    requested_count = max(0, int(session_count or 0))
    if requested_count <= 0:
        raise HTTPException(status_code=400, detail="session_count must be greater than zero.")

    rules = db.scalars(
        select(ClassTimetableRule)
        .where(ClassTimetableRule.class_id == int(class_id))
        .order_by(
            ClassTimetableRule.weekday.asc(),
            ClassTimetableRule.start_time.asc(),
            ClassTimetableRule.effective_from.asc(),
            ClassTimetableRule.id.asc(),
        )
    ).all()
    if not rules:
        raise HTTPException(status_code=409, detail="No timetable rules available. Import emploi first.")
    students = db.scalars(select(Student).where(Student.class_id == int(class_id)).order_by(Student.id.asc())).all()

    search_horizon_days = int(max_search_days or min(730, max(120, requested_count * 21)))
    selected, stats, search_end_date = _build_timetable_candidates_for_count(
        db,
        class_id=int(class_id),
        start_date=start_date,
        requested_count=requested_count,
        rules=rules,
        skip_blocked_holidays=bool(skip_blocked_holidays),
        max_search_days=search_horizon_days,
        country_code="MA",
    )
    if not selected:
        raise HTTPException(status_code=409, detail="No valid timetable slots available for this planning window.")

    checklist_session_hints: dict[int, int] = {}
    unit = _create_unit_with_generated_checklist(
        db,
        class_id=class_id,
        current_user=current_user,
        unit_type=unit_type,
        title=unit_title,
        planned_hours=planned_hours,
        file=file,
        source_text=source_text,
        enforce_upload_limits=True,
        checklist_session_count=requested_count,
        checklist_session_hint_out=checklist_session_hints,
    )

    created_rows: list[ClassSession] = []
    planned_slots: list[WorkflowCalendarPlannedSlotOut] = []
    total_selected = len(selected)
    for index, candidate in enumerate(selected, start=1):
        rule = candidate["rule"]
        prefix = f"Doc plan {unit.title} session {index}/{total_selected}"
        note = _session_note_from_rule(
            prefix=prefix,
            rule=rule,
            moved_from_date=candidate.get("moved_from_date"),
            exception_note=candidate.get("exception_note"),
        )
        planned_slots.append(
            WorkflowCalendarPlannedSlotOut(
                session_date=candidate["session_date"],
                start_time=candidate.get("start_time"),
                end_time=candidate.get("end_time"),
                note=note,
                subject=rule.subject,
                room=rule.room,
                group_name=rule.group_name,
                moved_from_date=candidate.get("moved_from_date"),
            )
        )
        created_rows.append(
            _create_workflow_session_with_students(
                db,
                class_id=class_id,
                students=students,
                session_date=candidate["session_date"],
                start_time=candidate["start_time"],
                end_time=candidate.get("end_time"),
                note=note,
                current_user=current_user,
                unit_id=unit.id,
                audit_action="workflow.auto_setup.document.create_session",
                audit_details={
                    "auto_plan_index": index,
                    "auto_plan_total": total_selected,
                },
            )
        )

    auto_checked_items_count = 0
    auto_generated_exercise_items = 0
    if auto_check_items and created_rows:
        leaf_item_ids = _collect_unit_leaf_item_ids(db, int(unit.id))
        distribution = _distribute_item_ids_with_session_hints(
            item_ids=leaf_item_ids,
            session_count=len(created_rows),
            session_hints_by_item_id=checklist_session_hints,
        )
        empty_bucket_indexes = [idx for idx, bucket in enumerate(distribution) if not bucket]
        if empty_bucket_indexes:
            for bucket_index in empty_bucket_indexes:
                session_number = int(bucket_index) + 1
                filler_item_id = _append_unit_session_exercise_filler_item(
                    db,
                    unit_id=int(unit.id),
                    session_number=session_number,
                )
                checklist_session_hints[filler_item_id] = session_number
                leaf_item_ids.append(int(filler_item_id))
                auto_generated_exercise_items += 1
            distribution = _distribute_item_ids_with_session_hints(
                item_ids=leaf_item_ids,
                session_count=len(created_rows),
                session_hints_by_item_id=checklist_session_hints,
            )
        for idx, row in enumerate(created_rows):
            item_ids = distribution[idx] if idx < len(distribution) else []
            if not item_ids:
                continue
            auto_checked_items_count += _apply_checked_items_to_session(
                db,
                unit_id=int(unit.id),
                session_id=int(row.id),
                checked_item_ids=item_ids,
            )

    unit_closed_by_auto = False
    if auto_check_items:
        unit_closed_by_auto = _auto_close_completed_past_unit(db, unit_id=int(unit.id))

    failed_count = max(0, requested_count - len(created_rows))
    log_audit(
        db,
        user=current_user,
        action="workflow.auto_setup.document.execute",
        entity_type="workflow_unit",
        entity_id=int(unit.id),
        class_id=int(class_id),
        details={
            "requested_count": requested_count,
            "created_count": len(created_rows),
            "failed_count": failed_count,
            "search_end_date": search_end_date.isoformat() if search_end_date is not None else None,
            "skipped_holiday_count": int(stats.get("skipped_holiday_count", 0)),
            "skipped_existing_count": int(stats.get("skipped_existing_count", 0)),
            "skipped_exception_count": int(stats.get("skipped_exception_count", 0)),
            "skipped_duplicate_count": int(stats.get("skipped_duplicate_count", 0)),
            "auto_check_items": bool(auto_check_items),
            "auto_checked_items_count": auto_checked_items_count,
            "auto_generated_exercise_items": int(auto_generated_exercise_items),
            "unit_closed_by_auto": unit_closed_by_auto,
        },
    )
    db.commit()
    db.refresh(unit)
    for row in created_rows:
        db.refresh(row)

    return WorkflowCalendarAutoPlanOut(
        action="plan_document_unit",
        requested_count=requested_count,
        planned_count=len(planned_slots),
        created_count=len(created_rows),
        failed_count=failed_count,
        search_end_date=search_end_date,
        skipped_holiday_count=int(stats.get("skipped_holiday_count", 0)),
        skipped_existing_count=int(stats.get("skipped_existing_count", 0)),
        skipped_exception_count=int(stats.get("skipped_exception_count", 0)),
        skipped_duplicate_count=int(stats.get("skipped_duplicate_count", 0)),
        target_unit_id=int(unit.id),
        target_unit_title=str(unit.title),
        planned_slots=planned_slots,
        created_sessions=[_serialize_session(db, row) for row in created_rows],
    )


@router.post("/classes/{class_id}/sessions/start", response_model=WorkflowSessionOut, status_code=status.HTTP_201_CREATED)
def start_workflow_session(
    class_id: int,
    payload: WorkflowSessionStartIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionOut:
    _ = ensure_class_writable(db, class_id, current_user)
    now = datetime.now()
    unit = _ensure_active_unit(db, class_id)
    open_existing = db.scalar(
        select(ClassSession).where(
            ClassSession.class_id == class_id,
            ClassSession.unit_id == unit.id,
            ClassSession.end_time.is_(None),
        )
    )
    if open_existing is not None:
        raise HTTPException(status_code=409, detail=f"Session #{open_existing.id} is already open for this unit.")

    students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.id.asc())).all()
    if not students:
        raise HTTPException(status_code=400, detail="Class has no students.")
    student_ids = {student.id for student in students}
    absent_ids = sorted(set(int(value) for value in payload.absent_student_ids))
    unknown_ids = sorted(set(absent_ids) - student_ids)
    if unknown_ids:
        raise HTTPException(status_code=400, detail=f"Unknown student ids: {unknown_ids}")

    suggested_slot = _suggest_session_schedule_for_unit_start(
        db,
        class_id=class_id,
        unit_id=int(unit.id),
        now_dt=now,
    )
    if suggested_slot is not None:
        session_date = suggested_slot["session_date"]
        start_time = suggested_slot.get("start_time")
        note = _session_note_from_rule(
            prefix=f"Workflow session for {unit.title}",
            rule=suggested_slot["rule"],
            moved_from_date=suggested_slot.get("moved_from_date"),
            exception_note=suggested_slot.get("exception_note"),
        )
    else:
        if _is_non_working_day(now.date()):
            raise HTTPException(status_code=409, detail="Sunday is a non-working day.")
        session_date = now.date()
        start_time = now.replace(second=0, microsecond=0).time()
        note = f"Workflow session for {unit.title}"

    session = ClassSession(
        class_id=class_id,
        unit_id=unit.id,
        unit_session_number=_compute_next_unit_session_number(db, unit.id),
        session_date=session_date,
        start_time=start_time,
        end_time=None,
        note=note,
    )
    db.add(session)
    db.flush()

    absent_set = set(absent_ids)
    for student in students:
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                status=AttendanceStatus.ABSENT if student.id in absent_set else AttendanceStatus.PRESENT,
                minutes_late=0,
                comment=None,
            )
        )

    log_audit(
        db,
        user=current_user,
        action="workflow.session.start",
        entity_type="session",
        entity_id=session.id,
        class_id=class_id,
        details={
            "unit_id": unit.id,
            "unit_session_number": session.unit_session_number,
            "absent_count": len(absent_set),
        },
    )
    db.commit()
    db.refresh(session)
    return _serialize_session(db, session)


@router.post("/classes/{class_id}/sessions/{session_id}/items/{item_id}/toggle", response_model=WorkflowChecklistItemOut)
def toggle_workflow_item(
    class_id: int,
    session_id: int,
    item_id: int,
    payload: WorkflowToggleItemIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowChecklistItemOut:
    _ = ensure_class_writable(db, class_id, current_user)
    session = db.get(ClassSession, session_id)
    if session is None or session.class_id != class_id or session.unit_id is None:
        raise HTTPException(status_code=404, detail="Workflow session not found.")
    if session.end_time is not None:
        raise HTTPException(status_code=409, detail="Session is already closed. Checklist cannot be changed.")
    if not payload.checked:
        raise HTTPException(status_code=409, detail="Checklist items cannot be unchecked once completed.")
    item = db.get(WorkflowChecklistItem, item_id)
    if item is None or item.unit_id != session.unit_id:
        raise HTTPException(status_code=404, detail="Checklist item not found for this session.")
    has_children = db.scalar(
        select(WorkflowChecklistItem.id)
        .where(WorkflowChecklistItem.parent_item_id == int(item.id))
        .limit(1)
    )
    if has_children is not None:
        raise HTTPException(
            status_code=409,
            detail="Checklist headings auto-complete after their child rows are completed.",
        )
    target_ids = [item.id]

    for target_id in target_ids:
        _upsert_session_action(db, session_id=session.id, item_id=target_id, checked=payload.checked)
    db.flush()

    for target_id in target_ids:
        _refresh_item_completion(db, target_id)
    _refresh_ancestors_completion(db, item.id, session.id)

    log_audit(
        db,
        user=current_user,
        action="workflow.item.toggle",
        entity_type="workflow_item",
        entity_id=item.id,
        class_id=class_id,
        details={"session_id": session.id, "checked": payload.checked, "affected_items": target_ids},
    )
    db.commit()
    db.refresh(item)
    return WorkflowChecklistItemOut(
        id=item.id,
        unit_id=item.unit_id,
        parent_item_id=item.parent_item_id,
        item_kind=item.item_kind,
        title=item.title,
        position=item.position,
        depth=item.depth,
        is_completed=item.is_completed,
        completed_session_id=item.completed_session_id,
        completed_at=item.completed_at,
        teacher_note=str(item.teacher_note or "").strip() or None,
        children=[],
    )


@router.post("/classes/{class_id}/sessions/{session_id}/end", response_model=WorkflowSessionOut)
def end_workflow_session(
    class_id: int,
    session_id: int,
    payload: WorkflowSessionEndIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionOut:
    _ = ensure_class_writable(db, class_id, current_user)
    session = db.get(ClassSession, session_id)
    if session is None or session.class_id != class_id or session.unit_id is None:
        raise HTTPException(status_code=404, detail="Workflow session not found.")

    now_time = _utc_now_naive().replace(second=0, microsecond=0).time()
    was_closed_before_update = session.end_time is not None
    empty_payload_close = (
        payload.session_date is None
        and payload.start_time is None
        and payload.end_time is None
        and payload.absent_student_ids is None
        and payload.note is None
    )

    session.session_date = payload.session_date or session.session_date
    if _is_non_working_day(session.session_date):
        raise HTTPException(status_code=409, detail="Sunday is a non-working day.")
    if payload.start_time is not None:
        session.start_time = payload.start_time
    elif session.start_time is None:
        session.start_time = now_time

    if payload.end_time is not None:
        session.end_time = payload.end_time
    elif session.end_time is None and empty_payload_close:
        # Backward-compatible close behavior for legacy callers posting {}.
        session.end_time = now_time
    if session.start_time is not None and session.end_time is not None and session.end_time < session.start_time:
        raise HTTPException(status_code=400, detail="end_time must be greater than or equal to start_time.")
    if payload.note is not None:
        session.note = payload.note

    if payload.absent_student_ids is not None:
        students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.id.asc())).all()
        student_ids = {student.id for student in students}
        absent_ids = sorted(set(int(value) for value in payload.absent_student_ids))
        unknown_ids = sorted(set(absent_ids) - student_ids)
        if unknown_ids:
            raise HTTPException(status_code=400, detail=f"Unknown student ids: {unknown_ids}")
        absent_set = set(absent_ids)
        existing_rows = db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id)).all()
        by_student = {row.student_id: row for row in existing_rows}
        for student in students:
            row = by_student.get(student.id)
            status_value = AttendanceStatus.ABSENT if student.id in absent_set else AttendanceStatus.PRESENT
            if row is None:
                db.add(
                    AttendanceRecord(
                        session_id=session.id,
                        student_id=student.id,
                        status=status_value,
                        minutes_late=0,
                    )
                )
            else:
                row.status = status_value
                row.minutes_late = 0
                row.comment = None

    auto_closed_unit = False
    if session.unit_id is not None and session.end_time is not None:
        auto_closed_unit = _auto_close_completed_past_unit(db, unit_id=int(session.unit_id))

    log_audit(
        db,
        user=current_user,
        action="workflow.session.end",
        entity_type="session",
        entity_id=session.id,
        class_id=class_id,
        details={
            "session_date": session.session_date.isoformat(),
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
            "was_closed_before_update": was_closed_before_update,
            "empty_payload_close": empty_payload_close,
            "auto_closed_unit": auto_closed_unit,
        },
    )
    db.commit()
    db.refresh(session)
    return _serialize_session(db, session)


@router.post("/classes/{class_id}/sessions/{session_id}/ensure-next", response_model=WorkflowSessionEnsureNextOut)
def ensure_next_workflow_session(
    class_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionEnsureNextOut:
    _ = ensure_class_writable(db, class_id, current_user)
    session = db.get(ClassSession, session_id)
    if session is None or session.class_id != class_id or session.unit_id is None:
        raise HTTPException(status_code=404, detail="Workflow session not found.")

    created, reason = _ensure_next_unit_session_from_timetable(
        db,
        class_id=class_id,
        source_session=session,
        current_user=current_user,
    )
    if created is None:
        db.rollback()
        return WorkflowSessionEnsureNextOut(created=False, reason=reason, session=None)

    db.commit()
    db.refresh(created)
    return WorkflowSessionEnsureNextOut(
        created=True,
        reason=reason,
        session=_serialize_session(db, created),
    )


@router.post("/classes/{class_id}/sessions/{session_id}/confirm", response_model=WorkflowSessionConfirmOut)
def confirm_workflow_session(
    class_id: int,
    session_id: int,
    payload: WorkflowSessionConfirmIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionConfirmOut:
    _ = ensure_class_writable(db, class_id, current_user)
    session = db.get(ClassSession, session_id)
    if session is None or session.class_id != class_id or session.unit_id is None:
        raise HTTPException(status_code=404, detail="Workflow session not found.")
    if session.session_date > date.today():
        raise HTTPException(status_code=409, detail="Future sessions cannot be confirmed yet.")
    already_confirmed = bool(
        db.scalar(select(WorkflowSessionWriteup.id).where(WorkflowSessionWriteup.session_id == int(session.id)))
    ) or bool(
        db.scalar(
            select(WorkflowSessionChecklistAction.id).where(
                WorkflowSessionChecklistAction.session_id == int(session.id),
                WorkflowSessionChecklistAction.checked.is_(True),
            )
        )
    ) or bool(
        db.scalar(select(ProgressItem.id).where(ProgressItem.session_id == int(session.id)))
    )
    if already_confirmed:
        raise HTTPException(status_code=409, detail="This session is already confirmed.")

    now_time = _utc_now_naive().replace(second=0, microsecond=0).time()
    if session.start_time is None:
        session.start_time = now_time
    if session.end_time is None:
        close_time = now_time
        if session.start_time is not None and close_time < session.start_time:
            close_time = session.start_time
        session.end_time = close_time
    if session.start_time is not None and session.end_time is not None and session.end_time < session.start_time:
        session.end_time = session.start_time

    selected_item_ids = _select_auto_confirm_item_ids(
        db,
        unit_id=int(session.unit_id),
        session_id=int(session.id),
    )

    checked_items_count = 0
    if selected_item_ids:
        checked_items_count = _apply_checked_items_to_session(
            db,
            unit_id=int(session.unit_id),
            session_id=int(session.id),
            checked_item_ids=selected_item_ids,
        )

    progress_items_created = 0
    if bool(payload.create_progress_items) and selected_item_ids:
        progress_items_created = _append_progress_items_from_checklist(
            db,
            session_id=int(session.id),
            item_ids=selected_item_ids,
        )

    remaining_items_count = _remaining_leaf_items_count(db, unit_id=int(session.unit_id))
    unit_closed = False
    if bool(payload.auto_close_unit) and remaining_items_count <= 0:
        unit_closed = _auto_close_completed_past_unit(db, unit_id=int(session.unit_id))

    writeup_generated = False
    if bool(payload.generate_session_writeup):
        try:
            generate_and_store_session_writeup(
                db,
                session_id=int(session.id),
                provider=app_config.SESSION_WRITER_PROVIDER,
                model=app_config.OPENAI_MODEL if app_config.SESSION_WRITER_PROVIDER == "openai" else None,
            )
        except NotebookLMGenerationUnavailableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        writeup_generated = True

    log_audit(
        db,
        user=current_user,
        action="workflow.session.confirm",
        entity_type="session",
        entity_id=session.id,
        class_id=class_id,
        details={
            "unit_id": int(session.unit_id),
            "checked_items_count": checked_items_count,
            "progress_items_created": progress_items_created,
            "remaining_items_count": remaining_items_count,
            "unit_closed": unit_closed,
            "writeup_generated": writeup_generated,
        },
    )
    db.commit()
    db.refresh(session)
    return WorkflowSessionConfirmOut(
        session=_serialize_session(db, session),
        checked_items_count=checked_items_count,
        progress_items_created=progress_items_created,
        unit_closed=unit_closed,
        unit_id=int(session.unit_id),
        remaining_items_count=remaining_items_count,
        writeup_generated=writeup_generated,
    )


@router.get("/classes/{class_id}/units/{unit_id}/blueprint", response_model=WorkflowUnitBlueprintOut)
def get_workflow_unit_blueprint(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitBlueprintOut:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    row = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    if row is None:
        raise HTTPException(status_code=404, detail="Unit blueprint not found.")
    return _serialize_unit_blueprint(row)


@router.post("/classes/{class_id}/units/{unit_id}/review", response_model=WorkflowUnitOut)
def review_workflow_unit_extraction(
    class_id: int,
    unit_id: int,
    payload: WorkflowUnitExtractionReviewIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    row = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    if row is None:
        raise HTTPException(status_code=404, detail="Unit blueprint not found.")

    row.reviewed = bool(payload.reviewed)
    row.reviewed_at = _utc_now_naive() if row.reviewed else None
    row.reviewed_by_user_id = int(current_user.id) if row.reviewed else None

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.review_extraction",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={"reviewed": bool(row.reviewed)},
    )
    db.commit()
    db.refresh(unit)
    return _serialize_unit(db, unit)


@router.post("/classes/{class_id}/units/{unit_id}/reextract", response_model=WorkflowUnitOut)
def reextract_workflow_unit(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")

    linked_sessions_count = int(
        db.scalar(select(func.count(ClassSession.id)).where(ClassSession.unit_id == int(unit.id))) or 0
    )
    if linked_sessions_count > 0:
        raise HTTPException(
            status_code=409,
            detail="This unit already has linked sessions. Re-extraction is only allowed before teaching starts.",
        )

    source_text = ""
    if unit.document_path and Path(str(unit.document_path)).exists():
        source_text = extract_text_from_document(str(unit.document_path), None)
    elif unit.blueprint is not None and unit.blueprint.source_text_excerpt:
        source_text = str(unit.blueprint.source_text_excerpt or "").strip()
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="No source content is available to re-run extraction.")

    document_hash = None
    if unit.blueprint is not None and unit.blueprint.document_hash:
        document_hash = str(unit.blueprint.document_hash or "").strip() or None
    if document_hash is None and unit.document_path and Path(str(unit.document_path)).exists():
        try:
            document_hash = build_document_hash(Path(str(unit.document_path)).read_bytes())
        except Exception:
            document_hash = None
    if document_hash is None:
        document_hash = build_document_hash(source_text)

    requested_session_count = unit.blueprint.requested_session_count if unit.blueprint is not None else None
    previous_provider_context = None
    if unit.blueprint is not None and isinstance(unit.blueprint.blueprint_json, dict):
        raw_context = unit.blueprint.blueprint_json.get("provider_context")
        if isinstance(raw_context, dict):
            previous_provider_context = raw_context

    try:
        generated = generate_unit_checklist(
            unit_type=unit.unit_type,
            title=unit.title,
            source_text=source_text,
            session_count=requested_session_count,
            document_path=unit.document_path,
        )
    except NotebookLMGenerationUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _store_generated_checklist_on_unit(
        db,
        unit=unit,
        generated=generated,
        extracted_text=source_text,
        document_hash=document_hash,
        checklist_session_count=requested_session_count,
        checklist_session_hint_out=None,
    )

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.reextract",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={
            "title": unit.title,
            "unit_type": unit.unit_type.value,
            "generation_source": generated.get("source"),
        },
    )
    db.commit()

    new_provider_context = None
    if unit.blueprint is not None and isinstance(unit.blueprint.blueprint_json, dict):
        raw_context = unit.blueprint.blueprint_json.get("provider_context")
        if isinstance(raw_context, dict):
            new_provider_context = raw_context
    previous_notebook_id = str((previous_provider_context or {}).get("notebook_id") or "").strip()
    new_notebook_id = str((new_provider_context or {}).get("notebook_id") or "").strip()
    if previous_notebook_id and previous_notebook_id != new_notebook_id:
        _ = delete_provider_unit_context(provider_context=previous_provider_context)

    db.refresh(unit)
    return _serialize_unit(db, unit)


@router.post("/classes/{class_id}/units/{unit_id}/assistant", response_model=WorkflowUnitAssistantOut)
def ask_workflow_unit_assistant(
    class_id: int,
    unit_id: int,
    payload: WorkflowUnitAssistantIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitAssistantOut:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    row = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    if row is None:
        raise HTTPException(status_code=404, detail="Unit blueprint not found.")

    source_text = ""
    if unit.document_path and Path(str(unit.document_path)).exists():
        source_text = extract_text_from_document(str(unit.document_path), None)
    elif row.source_text_excerpt:
        source_text = str(row.source_text_excerpt or "").strip()

    provider_context = None
    if isinstance(row.blueprint_json, dict):
        raw_context = row.blueprint_json.get("provider_context")
        if isinstance(raw_context, dict):
            provider_context = raw_context

    try:
        result = generate_unit_assistant_package(
            unit_title=unit.title,
            unit_type=unit.unit_type,
            section_title=payload.section_title,
            section_path=payload.section_path,
            action=payload.action,
            teacher_request=payload.teacher_request,
            source_text=source_text,
            document_path=unit.document_path,
            provider_context=provider_context,
            unit_map=row.unit_map_json if isinstance(row.unit_map_json, dict) else None,
            content_blocks=row.content_blocks_json if isinstance(row.content_blocks_json, list) else None,
            provider="notebooklm",
        )
    except NotebookLMGenerationUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.ask_assistant",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={
            "section_title": str(payload.section_title or "").strip() or None,
            "action": str(payload.action or "").strip() or None,
            "provider": str(result.get("provider") or "notebooklm"),
            "status": str(result.get("status") or "ready"),
        },
    )
    return WorkflowUnitAssistantOut(**result)


@router.get("/classes/{class_id}/units/{unit_id}/assistant/artifacts", response_model=list[WorkflowUnitAssistantArtifactOut])
def list_workflow_unit_assistant_artifacts(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowUnitAssistantArtifactOut]:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    rows = db.scalars(
        select(WorkflowUnitAssistantArtifact)
        .where(WorkflowUnitAssistantArtifact.unit_id == int(unit_id))
        .order_by(WorkflowUnitAssistantArtifact.updated_at.desc(), WorkflowUnitAssistantArtifact.id.desc())
    ).all()
    return [_serialize_unit_assistant_artifact(row) for row in rows]


@router.post("/classes/{class_id}/units/{unit_id}/assistant/artifacts", response_model=WorkflowUnitAssistantArtifactOut)
def save_workflow_unit_assistant_artifact(
    class_id: int,
    unit_id: int,
    payload: WorkflowUnitAssistantArtifactSaveIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitAssistantArtifactOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    checklist_item_id = int(payload.checklist_item_id) if payload.checklist_item_id is not None else None
    if checklist_item_id is not None:
        item = db.get(WorkflowChecklistItem, checklist_item_id)
        if item is None or int(item.unit_id) != int(unit_id):
            raise HTTPException(status_code=404, detail="Checklist item not found for this workflow unit.")
    artifact = WorkflowUnitAssistantArtifact(
        unit_id=int(unit_id),
        checklist_item_id=checklist_item_id,
        artifact_kind=str(payload.artifact_kind or "teacher_notes").strip().lower(),
        provider=str(payload.provider or "notebooklm").strip() or "notebooklm",
        model=str(payload.model or "").strip() or None,
        section_title=str(payload.section_title or "").strip() or None,
        section_path_json=[str(value).strip() for value in (payload.section_path or []) if str(value).strip()] or None,
        action=str(payload.action or "").strip() or None,
        title=str(payload.title or "").strip() or None,
        content_markdown=_build_unit_assistant_artifact_markdown(unit=unit, payload=payload),
        source_payload_json={
            **(payload.source_payload if isinstance(payload.source_payload, dict) else {}),
            "answer_rows": [str(value).strip() for value in (payload.answer_rows or []) if str(value).strip()],
            "suggested_followups": [str(value).strip() for value in (payload.suggested_followups or []) if str(value).strip()],
            "section_title": str(payload.section_title or "").strip() or None,
            "section_path": [str(value).strip() for value in (payload.section_path or []) if str(value).strip()],
            "action": str(payload.action or "").strip() or None,
        },
        raw_provider_response=payload.raw_provider_response if isinstance(payload.raw_provider_response, dict) else None,
        created_by_user_id=int(current_user.id),
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    log_audit(
        db,
        user=current_user,
        action="workflow.unit.save_assistant_artifact",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={
            "artifact_kind": artifact.artifact_kind,
            "checklist_item_id": artifact.checklist_item_id,
            "section_title": artifact.section_title,
            "action": artifact.action,
        },
    )
    return _serialize_unit_assistant_artifact(artifact)


@router.get("/classes/{class_id}/units/{unit_id}/assistant/artifacts/{artifact_id}/download")
def download_workflow_unit_assistant_artifact(
    class_id: int,
    unit_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    artifact = db.get(WorkflowUnitAssistantArtifact, int(artifact_id))
    if artifact is None or int(artifact.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Workflow assistant artifact not found.")
    content = str(artifact.content_markdown or "").strip()
    if not content:
        raise HTTPException(status_code=409, detail="This saved guidance does not have downloadable content yet.")
    filename = _build_unit_assistant_artifact_download_filename(unit, artifact)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        BytesIO(content.encode("utf-8")),
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@router.delete("/classes/{class_id}/units/{unit_id}/assistant/artifacts/{artifact_id}")
def delete_workflow_unit_assistant_artifact(
    class_id: int,
    unit_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    artifact = db.get(WorkflowUnitAssistantArtifact, int(artifact_id))
    if artifact is None or int(artifact.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Workflow assistant artifact not found.")
    details = {
        "artifact_kind": str(artifact.artifact_kind or "").strip() or None,
        "section_title": str(artifact.section_title or "").strip() or None,
        "action": str(artifact.action or "").strip() or None,
    }
    db.delete(artifact)
    db.commit()
    log_audit(
        db,
        user=current_user,
        action="workflow.unit.delete_assistant_artifact",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details=details,
    )
    return {"ok": True}


@router.get("/classes/{class_id}/units/{unit_id}/materials", response_model=list[WorkflowUnitMaterialOut])
def list_workflow_unit_materials(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowUnitMaterialOut]:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    rows = db.scalars(
        select(WorkflowUnitMaterial)
        .where(WorkflowUnitMaterial.unit_id == int(unit_id))
        .order_by(WorkflowUnitMaterial.updated_at.desc(), WorkflowUnitMaterial.id.desc())
    ).all()
    return [_serialize_unit_material(row) for row in rows]


@router.get("/classes/{class_id}/units/{unit_id}/materials/{material_id}/download")
def download_workflow_unit_material(
    class_id: int,
    unit_id: int,
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    material = db.get(WorkflowUnitMaterial, int(material_id))
    if material is None or int(material.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Workflow unit material not found.")
    file_path = Path(str(material.file_path or "").strip()) if str(material.file_path or "").strip() else None
    if file_path and file_path.exists() and file_path.is_file():
        filename = str(material.file_name or "").strip() or file_path.name
        media_type = str(material.file_content_type or "").strip() or None
        return FileResponse(path=str(file_path), filename=filename, media_type=media_type)
    content = str(material.content_markdown or "").strip()
    if not content:
        raise HTTPException(status_code=409, detail="This material does not have downloadable content yet.")
    filename = _build_unit_material_download_filename(unit, material)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        BytesIO(content.encode("utf-8")),
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@router.post("/classes/{class_id}/units/{unit_id}/materials/generate", response_model=WorkflowUnitMaterialOut)
def generate_workflow_unit_material(
    class_id: int,
    unit_id: int,
    payload: WorkflowUnitMaterialGenerateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitMaterialOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    row = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    if row is None:
        raise HTTPException(status_code=404, detail="Unit blueprint not found.")

    source_text = ""
    if unit.document_path and Path(str(unit.document_path)).exists():
        source_text = extract_text_from_document(str(unit.document_path), None)
    elif row.source_text_excerpt:
        source_text = str(row.source_text_excerpt or "").strip()

    provider_context = None
    if isinstance(row.blueprint_json, dict):
        raw_context = row.blueprint_json.get("provider_context")
        if isinstance(raw_context, dict):
            provider_context = raw_context

    try:
        result = generate_unit_material_package(
            unit_id=int(unit_id),
            unit_title=unit.title,
            material_type=payload.material_type,
            source_text=source_text,
            document_path=unit.document_path,
            provider_context=provider_context,
            unit_map=row.unit_map_json if isinstance(row.unit_map_json, dict) else None,
            content_blocks=row.content_blocks_json if isinstance(row.content_blocks_json, list) else None,
            provider="notebooklm",
        )
    except NotebookLMGenerationUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    material_type = str(result.get("material_type") or payload.material_type or "study_guide").strip().lower() or "study_guide"
    existing = db.scalar(
        select(WorkflowUnitMaterial).where(
            WorkflowUnitMaterial.unit_id == int(unit_id),
            WorkflowUnitMaterial.material_type == material_type,
        )
    )
    if existing is None:
        existing = WorkflowUnitMaterial(
            unit_id=int(unit_id),
            material_type=material_type,
            created_by_user_id=int(current_user.id),
        )
        db.add(existing)
    previous_file_path = str(existing.file_path or "").strip()

    existing.provider = str(result.get("provider") or "fallback")
    existing.model = str(result.get("model") or "").strip() or None
    existing.status = str(result.get("status") or "ready")
    existing.title = str(result.get("title") or "").strip() or None
    existing.notebook_artifact_id = str(result.get("notebook_artifact_id") or "").strip() or None
    existing.source_payload_json = result.get("source_payload") if isinstance(result.get("source_payload"), dict) else None
    existing.content_markdown = str(result.get("content_markdown") or "").strip() or None
    existing.file_path = str(result.get("file_path") or "").strip() or None
    existing.file_name = str(result.get("file_name") or "").strip() or None
    existing.file_content_type = str(result.get("file_content_type") or "").strip() or None
    existing.raw_provider_response = result.get("raw_provider_response") if isinstance(result.get("raw_provider_response"), dict) else None
    existing.error_message = str(result.get("error_message") or "").strip() or None
    existing.updated_at = _utc_now_naive()
    db.commit()
    db.refresh(existing)
    if previous_file_path and previous_file_path != str(existing.file_path or "").strip():
        try:
            previous_path = Path(previous_file_path)
            if previous_path.exists() and previous_path.is_file():
                previous_path.unlink()
        except Exception:
            pass

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.generate_material",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={
            "material_type": material_type,
            "provider": existing.provider,
            "status": existing.status,
        },
    )
    return _serialize_unit_material(existing)


@router.get("/classes/{class_id}/sessions/{session_id}/writeup", response_model=WorkflowSessionWriteupOut)
def get_workflow_session_writeup(
    class_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionWriteupOut:
    _ = ensure_class_access(db, class_id, current_user)
    session = db.get(ClassSession, int(session_id))
    if session is None or int(session.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow session not found.")
    row = db.scalar(select(WorkflowSessionWriteup).where(WorkflowSessionWriteup.session_id == int(session_id)))
    if row is None:
        raise HTTPException(status_code=404, detail="Session write-up not found.")
    return _serialize_session_writeup(row)


@router.patch("/classes/{class_id}/sessions/{session_id}/writeup", response_model=WorkflowSessionWriteupOut)
def update_workflow_session_writeup(
    class_id: int,
    session_id: int,
    payload: WorkflowSessionWriteupUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionWriteupOut:
    _ = ensure_class_writable(db, class_id, current_user)
    session = db.get(ClassSession, int(session_id))
    if session is None or int(session.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow session not found.")
    row = db.scalar(select(WorkflowSessionWriteup).where(WorkflowSessionWriteup.session_id == int(session_id)))
    if row is None:
        raise HTTPException(status_code=404, detail="Session write-up not found.")

    if payload.title is not None:
        title = " ".join(str(payload.title or "").split()).strip()
        row.title = title[:255] or None
    normalized_focus = _normalize_writeup_rows(payload.learning_focus)
    if normalized_focus is not None:
        row.learning_focus_json = normalized_focus
    normalized_content = _normalize_writeup_rows(payload.teaching_content)
    if normalized_content is not None:
        row.teaching_content_json = normalized_content
    normalized_practice = _normalize_writeup_rows(payload.practice_items)
    if normalized_practice is not None:
        row.practice_items_json = normalized_practice
    if payload.approved is not None:
        row.approved = bool(payload.approved)

    log_audit(
        db,
        user=current_user,
        action="workflow.session.writeup.update",
        entity_type="workflow_session_writeup",
        entity_id=int(row.id),
        class_id=int(class_id),
        details={
            "session_id": int(session_id),
            "unit_id": int(session.unit_id) if session.unit_id is not None else None,
            "approved": bool(row.approved),
        },
    )
    db.commit()
    db.refresh(row)
    return _serialize_session_writeup(row)


@router.post("/classes/{class_id}/sessions/{session_id}/writeup/import-assistant-artifact", response_model=WorkflowSessionWriteupOut)
def import_workflow_session_writeup_assistant_artifact(
    class_id: int,
    session_id: int,
    payload: WorkflowSessionWriteupImportAssistantIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionWriteupOut:
    _ = ensure_class_writable(db, class_id, current_user)
    session = db.get(ClassSession, int(session_id))
    if session is None or int(session.class_id) != int(class_id) or session.unit_id is None:
        raise HTTPException(status_code=404, detail="Workflow session not found.")
    artifact = db.get(WorkflowUnitAssistantArtifact, int(payload.artifact_id))
    if artifact is None or int(artifact.unit_id) != int(session.unit_id):
        raise HTTPException(status_code=404, detail="Saved guidance not found for this session unit.")

    row = db.scalar(select(WorkflowSessionWriteup).where(WorkflowSessionWriteup.session_id == int(session_id)))
    if row is None:
        row = WorkflowSessionWriteup(
            session_id=int(session.id),
            unit_id=int(session.unit_id),
            provider=str(artifact.provider or "notebooklm").strip() or "notebooklm",
            model=str(artifact.model or "").strip() or None,
            status="ready",
            title=(str(artifact.title or "").strip() or str(artifact.section_title or "").strip() or None),
            checked_item_ids_json=[],
            checked_item_titles_json=[],
            learning_focus_json=[],
            teaching_content_json=[],
            practice_items_json=[],
            approved=False,
        )
        db.add(row)
        db.flush()

    _merge_assistant_artifact_into_writeup(row=row, artifact=artifact)
    log_audit(
        db,
        user=current_user,
        action="workflow.session.writeup.import_assistant_artifact",
        entity_type="workflow_session_writeup",
        entity_id=int(row.id),
        class_id=int(class_id),
        details={
            "session_id": int(session_id),
            "unit_id": int(session.unit_id),
            "artifact_id": int(artifact.id),
            "artifact_kind": str(artifact.artifact_kind or "").strip() or None,
        },
    )
    db.commit()
    db.refresh(row)
    return _serialize_session_writeup(row)


@router.post("/classes/{class_id}/sessions/{session_id}/writeup/generate", response_model=WorkflowSessionWriteupOut)
def generate_workflow_session_writeup(
    class_id: int,
    session_id: int,
    payload: WorkflowSessionWriteupGenerateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowSessionWriteupOut:
    _ = ensure_class_writable(db, class_id, current_user)
    session = db.get(ClassSession, int(session_id))
    if session is None or int(session.class_id) != int(class_id) or session.unit_id is None:
        raise HTTPException(status_code=404, detail="Workflow session not found.")
    if session.session_date > date.today():
        raise HTTPException(status_code=409, detail="Future sessions cannot generate a write-up yet.")

    existing = db.scalar(select(WorkflowSessionWriteup).where(WorkflowSessionWriteup.session_id == int(session_id)))
    if existing is not None and not bool(payload.regenerate):
        return _serialize_session_writeup(existing)

    try:
        row = generate_and_store_session_writeup(
            db,
            session_id=int(session_id),
            provider=app_config.SESSION_WRITER_PROVIDER,
            model=app_config.OPENAI_MODEL if app_config.SESSION_WRITER_PROVIDER == "openai" else None,
        )
    except NotebookLMGenerationUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_audit(
        db,
        user=current_user,
        action="workflow.session.writeup.generate",
        entity_type="workflow_session_writeup",
        entity_id=int(row.id),
        class_id=int(class_id),
        details={
            "session_id": int(session_id),
            "unit_id": int(session.unit_id) if session.unit_id is not None else None,
            "provider": row.provider,
            "regenerate": bool(payload.regenerate),
        },
    )
    db.commit()
    db.refresh(row)
    return _serialize_session_writeup(row)


@router.post("/classes/{class_id}/units/{unit_id}/close", response_model=WorkflowUnitOut)
def close_workflow_unit(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or unit.class_id != class_id:
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Unit is already closed.")
    open_session = db.scalar(
        select(ClassSession).where(
            ClassSession.class_id == class_id,
            ClassSession.unit_id == unit.id,
            ClassSession.end_time.is_(None),
        )
    )
    if open_session is not None:
        raise HTTPException(status_code=409, detail=f"Session #{open_session.id} is still open. End it first.")
    unit.status = WorkflowUnitStatus.CLOSED
    unit.closed_at = _utc_now_naive()

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.close",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={"title": unit.title, "unit_type": unit.unit_type.value},
    )
    db.commit()
    db.refresh(unit)
    return _serialize_unit(db, unit)


@router.post("/classes/{class_id}/units/{unit_id}/reopen", response_model=WorkflowUnitOut)
def reopen_workflow_unit(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or unit.class_id != class_id:
        raise HTTPException(status_code=404, detail="Unit not found.")
    if unit.status != WorkflowUnitStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Only closed unit can be reopened.")

    _reopen_workflow_unit_record(
        db,
        class_id=class_id,
        unit=unit,
        current_user=current_user,
    )
    db.commit()
    db.refresh(unit)
    return _serialize_unit(db, unit)


@router.post("/classes/{class_id}/units/{unit_id}/notebooklm/start", response_model=WorkflowUnitOut)
def start_notebooklm_for_workflow_unit(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    if unit.unit_type not in {WorkflowUnitType.EXAM, WorkflowUnitType.EXAM_CORRECTION}:
        raise HTTPException(status_code=400, detail="NotebookLM manual start is only available for exam units right now.")

    blueprint = unit.blueprint
    if blueprint is None:
        raise HTTPException(status_code=400, detail="No unit blueprint is available for this unit.")
    blueprint_json = blueprint.blueprint_json if isinstance(blueprint.blueprint_json, dict) else {}
    existing_provider_context = blueprint_json.get("provider_context") if isinstance(blueprint_json.get("provider_context"), dict) else {}
    existing_notebook_id = str(existing_provider_context.get("notebook_id") or "").strip()
    if existing_notebook_id:
        return _serialize_unit(db, unit)

    source_text = ""
    if unit.document_path and Path(str(unit.document_path)).exists():
        source_text = extract_text_from_document(str(unit.document_path), None)
    elif blueprint.source_text_excerpt:
        source_text = str(blueprint.source_text_excerpt or "").strip()

    if not source_text.strip() and not (unit.document_path and Path(str(unit.document_path)).exists()):
        raise HTTPException(status_code=400, detail="No exam PDF or source text is available to start NotebookLM.")

    try:
        provider_context, raw_context_response = initialize_unit_notebooklm_context(
            unit_type=unit.unit_type,
            title=unit.title,
            source_text=source_text,
            document_path=unit.document_path,
        )
    except NotebookLMGenerationUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"NotebookLM start failed for this unit ({exc.__class__.__name__}: {exc}).",
        ) from exc

    updated_blueprint_json = {
        **blueprint_json,
        "provider_context": provider_context,
    }
    raw_provider_response = blueprint.raw_provider_response if isinstance(blueprint.raw_provider_response, dict) else {}
    blueprint.blueprint_json = updated_blueprint_json
    blueprint.raw_provider_response = {
        **raw_provider_response,
        "notebooklm_context_init": raw_context_response,
    }
    blueprint.updated_at = _utc_now_naive()

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.start_notebooklm",
        entity_type="workflow_unit",
        entity_id=unit.id,
        class_id=class_id,
        details={"unit_type": unit.unit_type.value, "title": unit.title},
    )
    db.commit()
    db.refresh(unit)
    return _serialize_unit(db, unit)


@router.delete("/classes/{class_id}/units/{unit_id}", response_model=WorkflowUnitDeleteOut)
def delete_workflow_unit(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowUnitDeleteOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None or unit.class_id != class_id:
        raise HTTPException(status_code=404, detail="Unit not found.")

    unit_document_path = unit.document_path
    provider_context: dict | None = None
    if unit.blueprint is not None and isinstance(unit.blueprint.blueprint_json, dict):
        raw_context = unit.blueprint.blueprint_json.get("provider_context")
        if isinstance(raw_context, dict):
            provider_context = raw_context
    sessions = db.scalars(
        select(ClassSession).where(
            ClassSession.class_id == class_id,
            ClassSession.unit_id == unit.id,
        )
    ).all()
    deleted_sessions_count = len(sessions)
    session_ids = [int(row.id) for row in sessions]
    upload_paths: list[str] = []
    if session_ids:
        upload_paths = list(
            db.scalars(
                select(SessionUpload.file_path).where(SessionUpload.session_id.in_(session_ids))
            ).all()
        )

    for session in sessions:
        db.delete(session)
    db.delete(unit)

    log_audit(
        db,
        user=current_user,
        action="workflow.unit.delete",
        entity_type="workflow_unit",
        entity_id=unit_id,
        class_id=class_id,
        details={
            "title": unit.title,
            "unit_type": unit.unit_type.value,
            "status": unit.status.value,
            "deleted_sessions_count": deleted_sessions_count,
        },
    )
    db.commit()

    unique_upload_paths = sorted({str(path).strip() for path in upload_paths if str(path).strip()})
    deleted_upload_files_count = sum(1 for path in unique_upload_paths if _safe_unlink(path))
    deleted_document_file = _safe_unlink(unit_document_path)
    _ = delete_provider_unit_context(provider_context=provider_context)

    return WorkflowUnitDeleteOut(
        deleted_unit_id=unit_id,
        deleted_sessions_count=deleted_sessions_count,
        deleted_upload_files_count=deleted_upload_files_count,
        deleted_document_file=deleted_document_file,
    )


@router.get("/classes/{class_id}/calendar", response_model=list[WorkflowCalendarEventOut])
def get_workflow_calendar(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowCalendarEventOut]:
    _ = ensure_class_access(db, class_id, current_user)
    return _build_calendar_events(db, class_id)


def _build_calendar_events(db: Session, class_id: int) -> list[WorkflowCalendarEventOut]:
    sessions = db.scalars(
        select(ClassSession)
        .where(ClassSession.class_id == class_id, ClassSession.unit_id.is_not(None))
        .order_by(
            ClassSession.session_date.desc(),
            ClassSession.start_time.desc().nulls_last(),
            ClassSession.id.desc(),
        )
        .limit(180)
    ).all()
    if not sessions:
        return []
    unit_ids = {session.unit_id for session in sessions if session.unit_id is not None}
    if unit_ids:
        all_unit_sessions = db.scalars(
            select(ClassSession).where(ClassSession.unit_id.in_(unit_ids))
        ).all()
        derived_numbers = _derive_unit_session_number_map(all_unit_sessions)
    else:
        derived_numbers = {}
    units = db.scalars(select(WorkflowUnit).where(WorkflowUnit.id.in_(unit_ids))).all()
    unit_by_id = {unit.id: unit for unit in units}
    unit_item_order_cache: dict[int, dict[int, int]] = {}
    unit_item_number_cache: dict[int, dict[int, str]] = {}

    events: list[WorkflowCalendarEventOut] = []
    for session in sessions:
        absent_ids = db.scalars(
            select(AttendanceRecord.student_id).where(
                AttendanceRecord.session_id == session.id,
                AttendanceRecord.status == AttendanceStatus.ABSENT,
            )
        ).all()
        absent_count = len(absent_ids)
        checked_rows = db.execute(
            select(WorkflowChecklistItem.id, WorkflowChecklistItem.title)
            .join(WorkflowSessionChecklistAction, WorkflowSessionChecklistAction.item_id == WorkflowChecklistItem.id)
            .where(
                WorkflowSessionChecklistAction.session_id == session.id,
                WorkflowSessionChecklistAction.checked.is_(True),
            )
        ).all()
        order_index_by_id: dict[int, int] = {}
        number_label_by_id: dict[int, str] = {}
        if session.unit_id is not None:
            cached_order = unit_item_order_cache.get(int(session.unit_id))
            cached_numbers = unit_item_number_cache.get(int(session.unit_id))
            if cached_order is None or cached_numbers is None:
                _, cached_order, cached_numbers = _unit_checklist_order_maps(db, int(session.unit_id))
                unit_item_order_cache[int(session.unit_id)] = cached_order
                unit_item_number_cache[int(session.unit_id)] = cached_numbers
            order_index_by_id = cached_order
            number_label_by_id = cached_numbers
        actionable_checked_ids = (
            _filter_actionable_check_item_ids(
                db,
                unit_id=int(session.unit_id),
                item_ids=[int(row.id) for row in checked_rows],
            )
            if session.unit_id is not None
            else [int(row.id) for row in checked_rows]
        )
        actionable_checked_id_set = {int(value) for value in actionable_checked_ids}
        checked_rows = [row for row in checked_rows if int(row.id) in actionable_checked_id_set]
        sorted_checked_rows = sorted(
            checked_rows,
            key=lambda row: (order_index_by_id.get(int(row.id), 10**9), int(row.id)),
        )
        checked_items = [
            _format_checklist_item_label(number_label_by_id.get(int(row.id)), str(row.title or ""))
            for row in sorted_checked_rows
        ]
        checked_item_contexts = (
            _serialize_checked_item_contexts(
                db,
                unit_id=int(session.unit_id),
                checked_item_ids=[int(row.id) for row in sorted_checked_rows],
            )
            if session.unit_id is not None and sorted_checked_rows
            else []
        )
        outline_rows = build_session_outline_rows(checked_item_contexts)
        unit = unit_by_id.get(session.unit_id)
        events.append(
            WorkflowCalendarEventOut(
                session_id=session.id,
                class_id=class_id,
                unit_id=session.unit_id,
                unit_session_number=int(session.unit_session_number) if session.unit_session_number is not None else derived_numbers.get(int(session.id)),
                unit_title=unit.title if unit else None,
                unit_type=unit.unit_type if unit else None,
                session_date=session.session_date,
                start_time=session.start_time,
                end_time=session.end_time,
                absent_count=absent_count,
                absent_student_ids=sorted(int(value) for value in absent_ids),
                checked_items_count=len(sorted_checked_rows),
                checked_items=outline_rows or checked_items,
                checked_item_ids=[int(row.id) for row in sorted_checked_rows],
                checked_item_paths=[
                    [str(part).strip() for part in (row.get("item_path") or []) if str(part).strip()]
                    for row in checked_item_contexts
                    if isinstance(row, dict)
                ],
                checked_section_paths=[
                    [str(part).strip() for part in (row.get("section_path") or []) if str(part).strip()]
                    for row in checked_item_contexts
                    if isinstance(row, dict)
                ],
                note=session.note,
            )
        )
    return events


@router.get("/classes/{class_id}/calendar/export.xlsx")
def export_workflow_calendar_xlsx(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _ = ensure_class_access(db, class_id, current_user)
    events = _build_calendar_events(db, class_id)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "workflow_calendar"
    sheet.append(
        [
            "session_id",
            "session_date",
            "start_time",
            "end_time",
            "unit_type",
            "unit_title",
            "unit_session_number",
            "absent_count",
            "absent_student_ids",
            "checked_items_count",
            "checked_items",
            "note",
        ]
    )

    for event in events:
        sheet.append(
            [
                event.session_id,
                event.session_date.isoformat() if event.session_date else None,
                event.start_time.isoformat() if event.start_time else None,
                event.end_time.isoformat() if event.end_time else None,
                event.unit_type.value if event.unit_type else None,
                event.unit_title,
                event.unit_session_number,
                event.absent_count,
                ", ".join(str(value) for value in event.absent_student_ids),
                event.checked_items_count,
                " | ".join(event.checked_items),
                event.note,
            ]
        )

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = f"class_{class_id}_workflow_calendar_{_utc_now_naive().strftime('%Y%m%d_%H%M%S')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/classes/{class_id}/calendar/export.pdf")
def export_workflow_calendar_pdf(
    class_id: int,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    ai_enhance: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _ = ensure_class_access(db, class_id, current_user)
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to must be greater than or equal to date_from.")

    content = build_calendar_summary_pdf(
        db,
        class_id=int(class_id),
        date_from=date_from,
        date_to=date_to,
        ai_enhance=bool(ai_enhance),
    )
    output = BytesIO(content)
    output.seek(0)
    filename = f"class_{class_id}_calendar_summary_{_utc_now_naive().strftime('%Y%m%d_%H%M%S')}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(output, media_type="application/pdf", headers=headers)


@router.get("/units/{unit_id}/document")
def download_workflow_unit_document(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    unit = db.get(WorkflowUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found.")
    _ = ensure_class_access(db, unit.class_id, current_user)
    if not unit.document_path:
        raise HTTPException(status_code=404, detail="No document attached to this unit.")
    file_path = Path(unit.document_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found on server.")
    filename = unit.document_name or file_path.name
    return FileResponse(path=str(file_path), filename=filename)


@router.post("/classes/{class_id}/units/{unit_id}/sections/index", response_model=list[WorkflowPreparedSectionSummaryOut])
def index_unit_sections(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowPreparedSectionSummaryOut]:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    blueprint = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    has_content_pack = isinstance(_blueprint_content_pack(blueprint), dict)
    has_content_blocks = isinstance(getattr(blueprint, "content_blocks_json", None), list) and bool(blueprint.content_blocks_json)
    if blueprint is None or (not has_content_pack and not has_content_blocks):
        raise HTTPException(status_code=409, detail="Unit extracted content is required before sections can be prepared.")
    rows = _index_unit_prepared_sections(db, unit=unit, blueprint=blueprint)
    db.commit()
    return [_serialize_prepared_section_summary(row) for row in rows]


@router.get("/classes/{class_id}/units/{unit_id}/sections", response_model=list[WorkflowPreparedSectionSummaryOut])
def list_unit_sections(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowPreparedSectionSummaryOut]:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    rows = db.scalars(
        select(WorkflowPreparedSection)
        .where(WorkflowPreparedSection.unit_id == int(unit_id))
        .order_by(WorkflowPreparedSection.order_index.asc(), WorkflowPreparedSection.id.asc())
    ).all()
    return [_serialize_prepared_section_summary(row) for row in rows]


@router.post("/classes/{class_id}/units/{unit_id}/sections/prepare", response_model=WorkflowPreparedSectionOut)
def prepare_unit_section(
    class_id: int,
    unit_id: int,
    payload: WorkflowPreparedSectionPrepareIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowPreparedSectionOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    blueprint = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    has_content_pack = isinstance(_blueprint_content_pack(blueprint), dict)
    has_content_blocks = isinstance(getattr(blueprint, "content_blocks_json", None), list) and bool(blueprint.content_blocks_json)
    if blueprint is None or (not has_content_pack and not has_content_blocks):
        raise HTTPException(status_code=409, detail="Unit extracted content is required before a section can be prepared.")
    record = _upsert_prepared_section_from_blueprint(
        db,
        unit=unit,
        blueprint=blueprint,
        section_path=_normalize_section_path_input(payload.section_path),
    )
    db.commit()
    db.refresh(record)
    return _serialize_prepared_section(record)


@router.get("/classes/{class_id}/units/{unit_id}/sections/{section_key}", response_model=WorkflowPreparedSectionOut)
def get_unit_section(
    class_id: int,
    unit_id: int,
    section_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowPreparedSectionOut:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    row = db.scalar(
        select(WorkflowPreparedSection).where(
            WorkflowPreparedSection.unit_id == int(unit_id),
            WorkflowPreparedSection.section_key == str(section_key or "").strip(),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Prepared section not found.")
    return _serialize_prepared_section(row)


@router.get("/classes/{class_id}/units/{unit_id}/leaf-content", response_model=list[WorkflowLeafContentSummaryOut])
def list_leaf_content_summaries(
    class_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowLeafContent]:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    if _seed_unit_leaf_content_from_blueprint(db, unit_id=int(unit_id)) > 0:
        db.commit()
    rows = db.scalars(
        select(WorkflowLeafContent)
        .where(WorkflowLeafContent.unit_id == int(unit_id))
        .order_by(WorkflowLeafContent.updated_at.desc(), WorkflowLeafContent.id.desc())
    ).all()
    return list(rows)


@router.post("/classes/{class_id}/units/{unit_id}/section-lesson", response_model=WorkflowSectionLessonOut)
def get_section_lesson(
    class_id: int,
    unit_id: int,
    payload: WorkflowSectionLessonRequestIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")

    normalized_section_path = [str(value).strip() for value in (payload.section_path or []) if str(value).strip()]
    normalized_item_path = [str(value).strip() for value in (payload.item_path or []) if str(value).strip()]
    if not normalized_section_path and len(normalized_item_path) > 1:
        normalized_section_path = normalized_item_path[:-1]
    if not normalized_section_path:
        raise HTTPException(status_code=400, detail="section_path is required to open a section lesson.")
    section_key = build_section_key(normalized_section_path, fallback_title=normalized_section_path[-1])
    row = db.scalar(
        select(WorkflowPreparedSection).where(
            WorkflowPreparedSection.unit_id == int(unit_id),
            WorkflowPreparedSection.section_key == section_key,
        )
    )
    if row is not None and str(row.status or "").strip().lower() == "prepared":
        return _serialize_section_lesson_from_record(
            row,
            item_path=normalized_item_path,
            item_title=payload.item_title,
        ).model_dump()

    blueprint = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    content_pack = _blueprint_content_pack(blueprint)
    has_content_blocks = isinstance(getattr(blueprint, "content_blocks_json", None), list) and bool(blueprint.content_blocks_json)
    if blueprint is None or (not isinstance(content_pack, dict) and not has_content_blocks):
        raise HTTPException(status_code=409, detail="Unit extracted content is required before opening a section lesson.")
    lesson = build_raw_section_lesson_package(
        section_title=normalized_section_path[-1] if normalized_section_path else None,
        section_path=normalized_section_path,
        item_path=normalized_item_path,
        item_title=payload.item_title,
        content_pack=content_pack,
    ) if content_pack else None
    if lesson is None:
        lesson = build_source_section_lesson_package(
            section_title=normalized_section_path[-1] if normalized_section_path else None,
            section_path=normalized_section_path,
            item_path=normalized_item_path,
            item_title=payload.item_title,
            content_blocks=blueprint.content_blocks_json,
        )
    if int(lesson.get("source_block_count") or 0) <= 0 and not str(lesson.get("source_excerpt_md") or "").strip():
        raise HTTPException(status_code=404, detail="No extracted section content found for this lesson.")
    return lesson


@router.get("/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}", response_model=WorkflowLeafContentOut)
def get_leaf_content(
    class_id: int,
    unit_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowLeafContent:
    _ = ensure_class_access(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    item = db.get(WorkflowChecklistItem, int(item_id))
    if item is None or int(item.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Checklist item not found in this unit.")
    child_count = db.scalar(
        select(func.count()).select_from(WorkflowChecklistItem).where(WorkflowChecklistItem.parent_item_id == int(item_id))
    ) or 0
    if child_count > 0:
        raise HTTPException(status_code=400, detail="Only leaf checklist items can have content records.")
    row = db.scalar(
        select(WorkflowLeafContent).where(
            WorkflowLeafContent.unit_id == int(unit_id),
            WorkflowLeafContent.checklist_item_id == int(item_id),
        )
    )
    if row is None:
        if _seed_unit_leaf_content_from_blueprint(db, unit_id=int(unit_id), item_id=int(item_id)) > 0:
            db.commit()
        row = db.scalar(
            select(WorkflowLeafContent).where(
                WorkflowLeafContent.unit_id == int(unit_id),
                WorkflowLeafContent.checklist_item_id == int(item_id),
            )
        )
    if row is None:
        raise HTTPException(status_code=404, detail="No leaf content record found for this item.")
    return row


@router.put("/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}", response_model=WorkflowLeafContentOut)
def upsert_leaf_content(
    class_id: int,
    unit_id: int,
    item_id: int,
    payload: WorkflowLeafContentUpsertIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowLeafContent:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Leaf content can only be saved for an active unit.")
    item = db.get(WorkflowChecklistItem, int(item_id))
    if item is None or int(item.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Checklist item not found in this unit.")
    child_count = db.scalar(
        select(func.count()).select_from(WorkflowChecklistItem).where(WorkflowChecklistItem.parent_item_id == int(item_id))
    ) or 0
    if child_count > 0:
        raise HTTPException(status_code=400, detail="Only leaf checklist items can have content records.")
    row = db.scalar(
        select(WorkflowLeafContent).where(
            WorkflowLeafContent.unit_id == int(unit_id),
            WorkflowLeafContent.checklist_item_id == int(item_id),
        )
    )
    if row is None:
        row = WorkflowLeafContent(unit_id=int(unit_id), checklist_item_id=int(item_id))
        db.add(row)
    normalized_item_path = (
        [str(value).strip() for value in (payload.item_path or []) if str(value).strip()]
        if payload.item_path is not None
        else None
    )
    normalized_section_path = (
        [str(value).strip() for value in (payload.section_path or []) if str(value).strip()]
        if payload.section_path is not None
        else None
    )
    if normalized_item_path is not None:
        row.item_path_json = normalized_item_path or None
    if normalized_section_path is not None:
        row.section_path_json = normalized_section_path or None
    if row.item_path_json is None or row.section_path_json is None:
        derived_item_path, derived_section_path = _derive_leaf_item_paths(
            db,
            unit_id=int(unit_id),
            item_id=int(item_id),
        )
        if row.item_path_json is None and derived_item_path:
            row.item_path_json = derived_item_path
        if row.section_path_json is None and derived_section_path:
            row.section_path_json = derived_section_path
    if payload.provider is not None:
        row.provider = payload.provider
    if payload.model is not None:
        row.model = payload.model
    if payload.status is not None:
        row.status = payload.status
    if payload.teaching_goal_md is not None:
        row.teaching_goal_md = payload.teaching_goal_md
    if payload.launch_activity_md is not None:
        row.launch_activity_md = payload.launch_activity_md
    if payload.explanation_md is not None:
        row.explanation_md = payload.explanation_md
    if payload.worked_example_md is not None:
        row.worked_example_md = payload.worked_example_md
    if payload.practice_md is not None:
        row.practice_md = payload.practice_md
    if payload.solution_md is not None:
        row.solution_md = payload.solution_md
    if payload.assessment_md is not None:
        row.assessment_md = payload.assessment_md
    if payload.teacher_notes_md is not None:
        row.teacher_notes_md = payload.teacher_notes_md
    if payload.source_excerpt_md is not None:
        row.source_excerpt_md = payload.source_excerpt_md
    if payload.source_payload is not None:
        row.source_payload_json = payload.source_payload
    if payload.raw_provider_response is not None:
        row.raw_provider_response_json = payload.raw_provider_response
    db.commit()
    db.refresh(row)
    return row


@router.post(
    "/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}/generate",
    response_model=WorkflowLeafContentGenerateOut,
)
def generate_leaf_content(
    class_id: int,
    unit_id: int,
    item_id: int,
    payload: WorkflowLeafContentGenerateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowLeafContentGenerateOut:
    _ = ensure_class_writable(db, class_id, current_user)
    unit = db.get(WorkflowUnit, int(unit_id))
    if unit is None or int(unit.class_id) != int(class_id):
        raise HTTPException(status_code=404, detail="Workflow unit not found.")
    if unit.status != WorkflowUnitStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Leaf content can only be generated for an active unit.")
    item = db.get(WorkflowChecklistItem, int(item_id))
    if item is None or int(item.unit_id) != int(unit_id):
        raise HTTPException(status_code=404, detail="Checklist item not found in this unit.")
    child_count = db.scalar(
        select(func.count()).select_from(WorkflowChecklistItem).where(WorkflowChecklistItem.parent_item_id == int(item_id))
    ) or 0
    if child_count > 0:
        raise HTTPException(status_code=400, detail="Only leaf checklist items can have content records.")

    blueprint = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    if blueprint is None:
        raise HTTPException(status_code=409, detail="Unit blueprint is required for leaf content generation. Generate the unit blueprint first.")

    provider_context: dict | None = None
    if isinstance(blueprint.blueprint_json, dict):
        raw_context = blueprint.blueprint_json.get("provider_context")
        if isinstance(raw_context, dict):
            provider_context = raw_context

    source_text = ""
    if unit.document_path and Path(str(unit.document_path)).exists():
        source_text = extract_text_from_document(str(unit.document_path), None)
    elif blueprint.source_text_excerpt:
        source_text = str(blueprint.source_text_excerpt or "").strip()

    existing = db.scalar(
        select(WorkflowLeafContent).where(
            WorkflowLeafContent.unit_id == int(unit_id),
            WorkflowLeafContent.checklist_item_id == int(item_id),
        )
    )

    item_path: list[str] | None = existing.item_path_json if existing and isinstance(existing.item_path_json, list) else None
    section_path: list[str] | None = existing.section_path_json if existing and isinstance(existing.section_path_json, list) else None
    if item_path is None or section_path is None:
        derived_item_path, derived_section_path = _derive_leaf_item_paths(db, unit_id=int(unit_id), item_id=int(item_id))
        if item_path is None:
            item_path = derived_item_path
        if section_path is None:
            section_path = derived_section_path

    if existing is not None and not bool(payload.regenerate):
        return WorkflowLeafContentGenerateOut(
            requested_provider=str(payload.provider or existing.provider or "notebooklm").strip() or "notebooklm",
            provider=str(existing.provider or "notebooklm").strip() or "notebooklm",
            status=str(existing.status or "ready").strip() or "ready",
            leaf_content=WorkflowLeafContentOut.model_validate(existing),
        )

    merge_strategy = str(payload.merge_strategy or "fill_missing").strip().lower() or "fill_missing"
    if merge_strategy not in {"fill_missing", "replace"}:
        raise HTTPException(status_code=400, detail="merge_strategy must be 'fill_missing' or 'replace'.")

    try:
        result = generate_leaf_content_package(
            unit_title=str(unit.title or "").strip(),
            item_title=str(item.title or "").strip(),
            item_path=item_path,
            section_path=section_path,
            source_text=source_text,
            document_path=unit.document_path,
            provider_context=provider_context,
            unit_map=blueprint.unit_map_json if isinstance(blueprint.unit_map_json, dict) else None,
            content_blocks=blueprint.content_blocks_json if isinstance(blueprint.content_blocks_json, list) else None,
            source_text_excerpt=str(blueprint.source_text_excerpt or "").strip() or None,
            provider=payload.provider,
        )
    except NotebookLMGenerationUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if existing is None:
        existing = WorkflowLeafContent(unit_id=int(unit_id), checklist_item_id=int(item_id))
        db.add(existing)

    merged_result = _merge_generated_leaf_content_payload(
        existing=existing,
        generated=result,
        merge_strategy=merge_strategy,
        item_path=item_path,
        section_path=section_path,
    )
    _apply_leaf_content_payload_to_row(
        existing,
        merged_result,
        item_path=item_path,
        section_path=section_path,
        preserve_existing_paths=False,
    )
    db.commit()
    db.refresh(existing)

    log_audit(
        db,
        user=current_user,
        action="workflow.leaf_content.generate",
        entity_type="workflow_leaf_content",
        entity_id=existing.id,
        class_id=class_id,
        details={
            "item_id": int(item_id),
            "unit_id": int(unit_id),
            "provider": existing.provider,
            "status": existing.status,
            "merge_strategy": merge_strategy,
        },
    )
    return WorkflowLeafContentGenerateOut(
        requested_provider=str(result.get("requested_provider") or "notebooklm"),
        provider=existing.provider,
        status=existing.status,
        leaf_content=WorkflowLeafContentOut.model_validate(existing),
    )
