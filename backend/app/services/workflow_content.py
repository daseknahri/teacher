from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ClassSession,
    WorkflowChecklistItem,
    WorkflowSessionChecklistAction,
    WorkflowSessionWriteup,
    WorkflowUnit,
    WorkflowUnitBlueprint,
)
from .workflow_generation import generate_session_writeup_package


def build_document_hash(content: bytes | str | None) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        payload = content.encode("utf-8", errors="ignore")
    else:
        payload = bytes(content)
    if not payload:
        return None
    return sha256(payload).hexdigest()


def save_unit_blueprint(
    db: Session,
    *,
    unit_id: int,
    provider: str,
    model: str | None,
    requested_session_count: int | None,
    document_hash: str | None,
    source_text: str,
    blueprint_json: dict,
    raw_provider_response: dict | None = None,
    status: str = "ready",
    error_message: str | None = None,
) -> WorkflowUnitBlueprint:
    row = db.scalar(select(WorkflowUnitBlueprint).where(WorkflowUnitBlueprint.unit_id == int(unit_id)))
    excerpt = str(source_text or "").strip()
    if len(excerpt) > 4000:
        excerpt = excerpt[:4000].rstrip() + "..."
    if row is None:
        row = WorkflowUnitBlueprint(
            unit_id=int(unit_id),
            provider=str(provider or "fallback").strip() or "fallback",
            model=model,
            status=str(status or "ready").strip() or "ready",
            requested_session_count=requested_session_count,
            document_hash=document_hash,
            source_text_excerpt=excerpt or None,
            blueprint_json=blueprint_json,
            raw_provider_response=raw_provider_response,
            error_message=error_message,
        )
        db.add(row)
        db.flush()
        return row

    row.provider = str(provider or row.provider or "fallback").strip() or "fallback"
    row.model = model
    row.status = str(status or row.status or "ready").strip() or "ready"
    row.requested_session_count = requested_session_count
    row.document_hash = document_hash
    row.source_text_excerpt = excerpt or None
    row.blueprint_json = blueprint_json
    row.raw_provider_response = raw_provider_response
    row.error_message = error_message
    db.flush()
    return row


def generate_and_store_session_writeup(
    db: Session,
    *,
    session_id: int,
    provider: str = "fallback",
    model: str | None = None,
) -> WorkflowSessionWriteup:
    session = db.get(ClassSession, int(session_id))
    if session is None:
        raise ValueError("Session not found.")

    unit = db.get(WorkflowUnit, int(session.unit_id)) if session.unit_id is not None else None
    checked_rows = db.execute(
        select(
            WorkflowChecklistItem.id,
            WorkflowChecklistItem.title,
        )
        .join(WorkflowSessionChecklistAction, WorkflowSessionChecklistAction.item_id == WorkflowChecklistItem.id)
        .where(
            WorkflowSessionChecklistAction.session_id == int(session_id),
            WorkflowSessionChecklistAction.checked.is_(True),
        )
        .order_by(WorkflowChecklistItem.position.asc(), WorkflowChecklistItem.id.asc())
    ).all()

    checked_item_ids = [int(row.id) for row in checked_rows]
    checked_titles = [str(row.title or "").strip() for row in checked_rows if str(row.title or "").strip()]
    session_number = session.unit_session_number or 0
    if session_number <= 0:
        session_number = _resolve_unit_session_number(db, session)

    note_text = str(session.note or "").strip()
    source_text = ""
    provider_context: dict | None = None
    if unit is not None and unit.blueprint is not None and unit.blueprint.source_text_excerpt:
        source_text = str(unit.blueprint.source_text_excerpt or "").strip()
    if unit is not None and unit.blueprint is not None and isinstance(unit.blueprint.blueprint_json, dict):
        raw_context = unit.blueprint.blueprint_json.get("provider_context")
        if isinstance(raw_context, dict):
            provider_context = raw_context

    package = generate_session_writeup_package(
        unit_title=str(unit.title or "").strip() if unit is not None else "",
        unit_type=unit.unit_type if unit is not None else None,
        session_number=session_number if session_number > 0 else None,
        checked_item_ids=checked_item_ids,
        checked_item_titles=checked_titles,
        note_text=note_text,
        source_text=source_text,
        provider=provider,
        document_path=str(unit.document_path or "").strip() if unit is not None else None,
        provider_context=provider_context,
    )

    row = db.scalar(select(WorkflowSessionWriteup).where(WorkflowSessionWriteup.session_id == int(session.id)))
    if row is None:
        row = WorkflowSessionWriteup(
            session_id=int(session.id),
            unit_id=int(session.unit_id) if session.unit_id is not None else None,
            provider=str(package.get("provider") or provider or "fallback").strip() or "fallback",
            model=str(package.get("model") or "").strip() or model,
            status=str(package.get("status") or "ready").strip() or "ready",
            title=str(package.get("title") or "").strip()[:255] or None,
            checked_item_ids_json=package.get("checked_item_ids") or checked_item_ids,
            checked_item_titles_json=package.get("checked_item_titles") or checked_titles,
            learning_focus_json=package.get("learning_focus") or [],
            teaching_content_json=package.get("teaching_content") or [],
            practice_items_json=package.get("practice_items") or [],
            teacher_note_snapshot=package.get("teacher_note_snapshot"),
            source_payload_json=package.get("source_payload"),
            raw_provider_response=package.get("raw_provider_response"),
            error_message=package.get("error_message"),
            approved=True,
        )
        db.add(row)
        db.flush()
        return row

    row.unit_id = int(session.unit_id) if session.unit_id is not None else None
    row.provider = str(package.get("provider") or row.provider or provider or "fallback").strip() or "fallback"
    row.model = str(package.get("model") or "").strip() or model
    row.status = str(package.get("status") or row.status or "ready").strip() or "ready"
    row.title = str(package.get("title") or row.title or "").strip()[:255] or row.title
    row.checked_item_ids_json = package.get("checked_item_ids") or checked_item_ids
    row.checked_item_titles_json = package.get("checked_item_titles") or checked_titles
    row.learning_focus_json = package.get("learning_focus") or []
    row.teaching_content_json = package.get("teaching_content") or []
    row.practice_items_json = package.get("practice_items") or []
    row.teacher_note_snapshot = package.get("teacher_note_snapshot")
    row.source_payload_json = package.get("source_payload")
    row.raw_provider_response = package.get("raw_provider_response")
    row.error_message = package.get("error_message")
    db.flush()
    return row


def _resolve_unit_session_number(db: Session, session: ClassSession) -> int:
    if session.unit_id is None:
        return 0
    sessions = db.scalars(
        select(ClassSession)
        .where(ClassSession.unit_id == int(session.unit_id))
        .order_by(ClassSession.session_date.asc(), ClassSession.start_time.asc().nulls_last(), ClassSession.id.asc())
    ).all()
    for index, row in enumerate(sessions, start=1):
        if int(row.id) == int(session.id):
            return index
    return 0
