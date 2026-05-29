from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..config import MAX_SCREENSHOT_UPLOAD_BYTES, UPLOADS_DIR
from ..database import get_db
from ..models import AttendanceRecord, AttendanceStatus, ClassSession, ExamArchiveState, ProgressItem, ProgressItemType, SessionUpload, Student, User, WorkflowUnit
from ..security import ensure_class_access, ensure_class_writable, get_current_user, is_class_archived, require_teacher
from ..schemas import (
    AttendanceIn,
    AttendanceOut,
    ConfirmExtractionIn,
    ExtractionLatestOut,
    ExtractionResponse,
    ProgressItemOut,
    QuickSubmitOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from ..services.audit import log_audit
from ..services.extraction import extract_structured_progress, resolve_raw_text
from ..services.holidays import find_blocked_holiday
from ..services.rate_limit import enforce_rate_limit
from ..services.upload_validation import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIME_TYPES,
    read_validated_upload,
)


router = APIRouter(tags=["sessions"], dependencies=[Depends(require_teacher)])


def _ensure_session_writable(db: Session, session: ClassSession) -> None:
    if is_class_archived(db, session.class_id):
        raise HTTPException(status_code=409, detail="Class is archived and cannot be modified.")
    if session.unit_id is not None:
        linked_exam_id = db.scalar(select(WorkflowUnit.exam_id).where(WorkflowUnit.id == int(session.unit_id)))
        if linked_exam_id is not None:
            archived = db.scalar(
                select(ExamArchiveState.is_archived).where(ExamArchiveState.exam_id == int(linked_exam_id))
            )
            if bool(archived):
                raise HTTPException(
                    status_code=409,
                    detail="Archived exam sessions are read-only until the exam is restored.",
                )


def _is_non_working_day(value) -> bool:
    try:
        return int(value.isoweekday()) == 7
    except Exception:
        return False


def _parse_absent_student_ids(raw: str | None) -> list[int]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("absent_student_ids must be a JSON array.")
        values = [int(item) for item in parsed]
    except Exception:
        parts = [chunk.strip() for chunk in text.split(",")]
        values = []
        for part in parts:
            if not part:
                continue
            try:
                values.append(int(part))
            except ValueError as exc:
                raise ValueError("absent_student_ids must be integers.") from exc
    return sorted(set(values))


def _normalize_text_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    rows: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            rows.append(text)
    return rows


def _build_extraction_items(
    lesson_headings: list[str],
    activities: list[str],
    exercises: list[str],
) -> list[dict]:
    rows: list[dict] = []
    position = 1
    occurrences: dict[tuple[str, str, str], int] = {}

    def append_row(item_type: str, heading: str, content: str | None) -> None:
        nonlocal position
        norm_heading = str(heading or "").strip()
        norm_content = str(content or "").strip()
        key = (item_type, norm_heading, norm_content)
        current = occurrences.get(key, 0) + 1
        occurrences[key] = current
        digest = hashlib.sha1(f"{item_type}|{norm_heading}|{norm_content}|{current}".encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "item_type": item_type,
                "heading": norm_heading,
                "content": norm_content or None,
                "position": position,
                "hint_id": f"ex_{digest}",
            }
        )
        position += 1

    for heading in lesson_headings:
        append_row(ProgressItemType.LESSON.value, heading, None)
    for activity in activities:
        append_row(ProgressItemType.ACTIVITY.value, "Activity", activity)
    for exercise in exercises:
        append_row(ProgressItemType.EXERCISE.value, "Exercise", exercise)
    return rows


def _normalized_extraction_payload(parsed: dict | None) -> dict:
    payload = parsed if isinstance(parsed, dict) else {}
    lesson_headings = _normalize_text_list(payload.get("lesson_headings"))
    activities = _normalize_text_list(payload.get("activities"))
    exercises = _normalize_text_list(payload.get("exercises"))
    raw_text = str(payload.get("raw_text") or "")
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    provider = str(payload.get("provider") or "heuristic").strip() or "heuristic"
    return {
        "confidence": confidence,
        "lesson_headings": lesson_headings,
        "activities": activities,
        "exercises": exercises,
        "raw_text": raw_text,
        "provider": provider,
        "model": payload.get("model"),
        "fallback_reason": payload.get("fallback_reason"),
        "items": _build_extraction_items(lesson_headings, activities, exercises),
    }


@router.post("/classes/{class_id}/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    class_id: int,
    payload: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClassSession:
    _ = ensure_class_writable(db, class_id, current_user)
    if _is_non_working_day(payload.session_date):
        raise HTTPException(status_code=409, detail="Sunday is a non-working day.")
    blocked = find_blocked_holiday(db, payload.session_date, country_code="MA")
    if blocked is not None:
        raise HTTPException(status_code=409, detail=f"Selected date is blocked holiday: {blocked.name}")
    session = ClassSession(
        class_id=class_id,
        session_date=payload.session_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        note=payload.note,
    )
    db.add(session)
    db.flush()
    log_audit(
        db,
        user=current_user,
        action="session.create",
        entity_type="session",
        entity_id=session.id,
        class_id=class_id,
        details={"session_date": payload.session_date.isoformat()},
    )
    db.commit()
    db.refresh(session)
    return session


@router.post("/classes/{class_id}/quick-submit", response_model=QuickSubmitOut, status_code=status.HTTP_201_CREATED)
def quick_submit_session(
    class_id: int,
    file: UploadFile = File(...),
    absent_student_ids: str | None = Form(default=None),
    raw_text: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_writable(db, class_id, current_user)
    enforce_rate_limit(
        scope="upload",
        user_id=current_user.id,
        limit=app_config.UPLOAD_RATE_LIMIT_COUNT,
        window_seconds=app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=class_id,
    )

    students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.id.asc())).all()
    if not students:
        raise HTTPException(status_code=400, detail="Class has no students.")

    try:
        absent_ids = _parse_absent_student_ids(absent_student_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    student_ids = {student.id for student in students}
    unknown_ids = sorted(set(absent_ids) - student_ids)
    if unknown_ids:
        raise HTTPException(status_code=400, detail=f"Unknown student ids: {unknown_ids}")
    absent_set = set(absent_ids)

    now = datetime.now()
    if _is_non_working_day(now.date()):
        raise HTTPException(status_code=409, detail="Sunday is a non-working day.")
    start_time = now.replace(second=0, microsecond=0).time()
    end_time = (now + timedelta(hours=1)).replace(second=0, microsecond=0).time()
    session = ClassSession(
        class_id=class_id,
        session_date=now.date(),
        start_time=start_time,
        end_time=end_time,
        note="Submitted from quick-submit workflow",
    )
    db.add(session)
    db.flush()

    for student in students:
        is_absent = student.id in absent_set
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                status=AttendanceStatus.ABSENT if is_absent else AttendanceStatus.PRESENT,
                minutes_late=0,
                comment="Absent in submitted session" if is_absent else None,
            )
        )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    content, extension = read_validated_upload(
        file,
        max_bytes=MAX_SCREENSHOT_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        allowed_mime_types=ALLOWED_IMAGE_MIME_TYPES,
        purpose="image",
    )
    filename = f"{uuid.uuid4().hex}{extension}"
    target = UPLOADS_DIR / filename
    with target.open("wb") as handle:
        handle.write(content)

    resolved_text = resolve_raw_text(str(target), raw_text)
    parsed = extract_structured_progress(resolved_text, image_path=str(target))
    upload = SessionUpload(
        session_id=session.id,
        file_path=str(target),
        ocr_text=parsed["raw_text"],
        ai_json=parsed,
        reviewed=True,
    )
    db.add(upload)
    db.flush()

    position = 1
    for heading in parsed.get("lesson_headings", []):
        db.add(
            ProgressItem(
                session_id=session.id,
                item_type=ProgressItemType.LESSON,
                heading=str(heading),
                content=None,
                position=position,
            )
        )
        position += 1
    for activity in parsed.get("activities", []):
        db.add(
            ProgressItem(
                session_id=session.id,
                item_type=ProgressItemType.ACTIVITY,
                heading="Activity",
                content=str(activity),
                position=position,
            )
        )
        position += 1
    for exercise in parsed.get("exercises", []):
        db.add(
            ProgressItem(
                session_id=session.id,
                item_type=ProgressItemType.EXERCISE,
                heading="Exercise",
                content=str(exercise),
                position=position,
            )
        )
        position += 1

    log_audit(
        db,
        user=current_user,
        action="session.quick_submit",
        entity_type="session",
        entity_id=session.id,
        class_id=class_id,
        details={
            "absent_students": len(absent_set),
            "provider": parsed.get("provider"),
            "model": parsed.get("model"),
            "lesson_headings_count": len(parsed.get("lesson_headings", [])),
            "activities_count": len(parsed.get("activities", [])),
            "exercises_count": len(parsed.get("exercises", [])),
        },
    )
    db.commit()
    return {
        "session_id": session.id,
        "class_id": class_id,
        "session_date": session.session_date,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "absent_students": len(absent_set),
        "lesson_headings_count": len(parsed.get("lesson_headings", [])),
        "activities_count": len(parsed.get("activities", [])),
        "exercises_count": len(parsed.get("exercises", [])),
        "provider": str(parsed.get("provider") or ""),
        "model": parsed.get("model"),
        "fallback_reason": parsed.get("fallback_reason"),
    }


@router.get("/classes/{class_id}/sessions", response_model=list[SessionOut])
def list_sessions(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[ClassSession]:
    _ = ensure_class_access(db, class_id, current_user)
    return db.scalars(
        select(ClassSession).where(ClassSession.class_id == class_id).order_by(ClassSession.session_date.desc(), ClassSession.id.desc())
    ).all()


@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = db.get(ClassSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    _ = ensure_class_access(db, session.class_id, current_user)

    attendance_rows = db.execute(
        select(
            AttendanceRecord.id,
            AttendanceRecord.student_id,
            Student.student_code,
            Student.full_name,
            AttendanceRecord.status,
            AttendanceRecord.minutes_late,
            AttendanceRecord.comment,
        )
        .join(Student, Student.id == AttendanceRecord.student_id)
        .where(AttendanceRecord.session_id == session_id)
        .order_by(Student.full_name.asc())
    ).all()

    progress_items = db.scalars(
        select(ProgressItem).where(ProgressItem.session_id == session_id).order_by(ProgressItem.position.asc(), ProgressItem.id.asc())
    ).all()
    uploads = db.scalars(select(SessionUpload).where(SessionUpload.session_id == session_id).order_by(SessionUpload.created_at.asc())).all()

    return {
        "unit_id": session.unit_id,
        "unit_session_number": session.unit_session_number,
        "session": {
            "id": session.id,
            "class_id": session.class_id,
            "unit_id": session.unit_id,
            "unit_session_number": session.unit_session_number,
            "session_date": session.session_date.isoformat(),
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
            "note": session.note,
        },
        "attendance": [
            {
                "id": row.id,
                "student_id": row.student_id,
                "student_code": row.student_code,
                "full_name": row.full_name,
                "status": row.status.value,
                "minutes_late": row.minutes_late,
                "comment": row.comment,
            }
            for row in attendance_rows
        ],
        "progress_items": [
            {
                "id": item.id,
                "item_type": item.item_type.value,
                "heading": item.heading,
                "content": item.content,
                "position": item.position,
            }
            for item in progress_items
        ],
        "uploads": [
            {
                "id": upload.id,
                "reviewed": upload.reviewed,
                "created_at": upload.created_at.isoformat(),
                "ocr_text": upload.ocr_text,
                "ai_json": upload.ai_json,
            }
            for upload in uploads
        ],
    }


@router.put("/sessions/{session_id}", response_model=SessionOut)
def update_session(
    session_id: int,
    payload: SessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClassSession:
    session = db.get(ClassSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    _ = ensure_class_access(db, session.class_id, current_user)
    _ensure_session_writable(db, session)

    time_fields_requested = any(
        (
            payload.session_date is not None,
            payload.start_time is not None,
            payload.end_time is not None,
        )
    )
    if time_fields_requested and session.unit_id is not None and session.session_date < datetime.utcnow().date():
        raise HTTPException(
            status_code=409,
            detail="Past workflow sessions are locked for date/time edits.",
        )

    if payload.session_date is not None:
        if _is_non_working_day(payload.session_date):
            raise HTTPException(status_code=409, detail="Sunday is a non-working day.")
        blocked = find_blocked_holiday(db, payload.session_date, country_code="MA")
        if blocked is not None:
            raise HTTPException(status_code=409, detail=f"Selected date is blocked holiday: {blocked.name}")
        session.session_date = payload.session_date
    if payload.start_time is not None:
        session.start_time = payload.start_time
    if payload.end_time is not None:
        session.end_time = payload.end_time
    if payload.note is not None:
        session.note = payload.note

    log_audit(
        db,
        user=current_user,
        action="session.update",
        entity_type="session",
        entity_id=session.id,
        class_id=session.class_id,
        details={
            "session_date": session.session_date.isoformat(),
            "has_note": bool(session.note),
        },
    )
    db.commit()
    db.refresh(session)
    return session


@router.put("/sessions/{session_id}/attendance", response_model=list[AttendanceOut])
def upsert_attendance(
    session_id: int,
    payload: list[AttendanceIn],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AttendanceRecord]:
    session = db.get(ClassSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    _ = ensure_class_access(db, session.class_id, current_user)
    _ensure_session_writable(db, session)

    student_ids = set(db.scalars(select(Student.id).where(Student.class_id == session.class_id)).all())
    for row in payload:
        if row.student_id not in student_ids:
            raise HTTPException(status_code=400, detail=f"Student {row.student_id} does not belong to the class.")

    db.execute(delete(AttendanceRecord).where(AttendanceRecord.session_id == session_id))
    for row in payload:
        db.add(
            AttendanceRecord(
                session_id=session_id,
                student_id=row.student_id,
                status=row.status,
                minutes_late=row.minutes_late,
                comment=row.comment,
            )
        )
    log_audit(
        db,
        user=current_user,
        action="attendance.upsert",
        entity_type="attendance",
        entity_id=session_id,
        class_id=session.class_id,
        details={"rows": len(payload)},
    )
    db.commit()
    return db.scalars(
        select(AttendanceRecord).where(AttendanceRecord.session_id == session_id).order_by(AttendanceRecord.student_id.asc())
    ).all()


@router.post("/sessions/{session_id}/uploads", response_model=ExtractionResponse, status_code=status.HTTP_201_CREATED)
def upload_session_screenshot(
    session_id: int,
    file: UploadFile = File(...),
    raw_text: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = db.get(ClassSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    _ = ensure_class_access(db, session.class_id, current_user)
    _ensure_session_writable(db, session)
    enforce_rate_limit(
        scope="upload",
        user_id=current_user.id,
        limit=app_config.UPLOAD_RATE_LIMIT_COUNT,
        window_seconds=app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=session.class_id,
    )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    content, extension = read_validated_upload(
        file,
        max_bytes=MAX_SCREENSHOT_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        allowed_mime_types=ALLOWED_IMAGE_MIME_TYPES,
        purpose="image",
    )
    filename = f"{uuid.uuid4().hex}{extension}"
    target = UPLOADS_DIR / filename
    with target.open("wb") as handle:
        handle.write(content)

    resolved_text = resolve_raw_text(str(target), raw_text)
    parsed = _normalized_extraction_payload(extract_structured_progress(resolved_text, image_path=str(target)))
    upload = SessionUpload(
        session_id=session_id,
        file_path=str(target),
        ocr_text=parsed["raw_text"],
        ai_json=parsed,
        reviewed=False,
    )
    db.add(upload)
    db.flush()
    log_audit(
        db,
        user=current_user,
        action="session.upload_extract",
        entity_type="session_upload",
        entity_id=upload.id,
        class_id=session.class_id,
        details={
            "confidence": parsed.get("confidence"),
            "provider": parsed.get("provider"),
            "model": parsed.get("model"),
        },
    )
    db.commit()
    db.refresh(upload)
    return {"upload_id": upload.id, **parsed}


@router.get("/sessions/{session_id}/uploads/latest", response_model=ExtractionLatestOut)
def get_latest_session_upload(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    session = db.get(ClassSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    _ = ensure_class_access(db, session.class_id, current_user)

    upload = db.scalar(
        select(SessionUpload)
        .where(SessionUpload.session_id == session_id)
        .order_by(SessionUpload.created_at.desc(), SessionUpload.id.desc())
    )
    if upload is None:
        raise HTTPException(status_code=404, detail="No extraction upload found for this session.")

    parsed = _normalized_extraction_payload(upload.ai_json if isinstance(upload.ai_json, dict) else {})
    return {
        "upload_id": upload.id,
        "session_id": session_id,
        "reviewed": bool(upload.reviewed),
        "created_at": upload.created_at,
        **parsed,
    }


@router.post("/sessions/{session_id}/confirm-extraction", response_model=list[ProgressItemOut])
def confirm_extraction(
    session_id: int,
    payload: ConfirmExtractionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProgressItem]:
    session = db.get(ClassSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    _ = ensure_class_access(db, session.class_id, current_user)
    _ensure_session_writable(db, session)

    existing_items = db.scalars(
        select(ProgressItem).where(ProgressItem.session_id == session_id).order_by(ProgressItem.position.asc(), ProgressItem.id.asc())
    ).all()
    previous_snapshot = [
        {
            "item_type": item.item_type.value,
            "heading": item.heading,
            "content": item.content,
            "position": item.position,
        }
        for item in existing_items
    ]

    mode = str(payload.mode or "replace").strip().lower()
    if mode == "replace":
        db.execute(delete(ProgressItem).where(ProgressItem.session_id == session_id))
        next_position = 1
    else:
        next_position = (max((item.position for item in existing_items), default=0) + 1)

    ordered_payload_items = sorted(
        enumerate(payload.items),
        key=lambda row: (int(row[1].position), row[0]),
    )
    for _, item in ordered_payload_items:
        db.add(
            ProgressItem(
                session_id=session_id,
                item_type=item.item_type,
                heading=item.heading,
                content=item.content,
                position=next_position,
            )
        )
        next_position += 1
    uploads = db.scalars(select(SessionUpload).where(SessionUpload.session_id == session_id)).all()
    for upload in uploads:
        upload.reviewed = True
    db.flush()
    all_items = db.scalars(
        select(ProgressItem).where(ProgressItem.session_id == session_id).order_by(ProgressItem.position.asc(), ProgressItem.id.asc())
    ).all()
    new_snapshot = [
        {
            "item_type": item.item_type.value,
            "heading": item.heading,
            "content": item.content,
            "position": item.position,
        }
        for item in all_items
    ]
    log_audit(
        db,
        user=current_user,
        action="extraction.confirm",
        entity_type="progress_item",
        entity_id=session_id,
        class_id=session.class_id,
        details={
            "mode": mode,
            "items": len(payload.items),
            "before_count": len(existing_items),
            "after_count": len(all_items),
            "uploads_marked_reviewed": len(uploads),
            "before_items": previous_snapshot[:50],
            "after_items": new_snapshot[:50],
        },
    )
    db.commit()
    return all_items
