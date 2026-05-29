from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from io import BytesIO, StringIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from openpyxl import Workbook

from .. import config as app_config
from ..config import MAX_EXCEL_UPLOAD_BYTES
from ..database import get_db
from ..models import ClassSession, Exam, ExamArchiveState, ExamResult, SessionUpload, Student, User, WorkflowUnit, WorkflowUnitStatus, WorkflowUnitType
from ..security import ensure_class_access, ensure_class_writable, get_current_user, is_class_archived, require_teacher
from ..schemas import ExamCreate, ExamOut, ExamResultOut, ExamResultUpdate, ExamUpdate
from ..services.audit import log_audit
from ..services.excel import build_exam_template, build_exam_template_notescc, parse_exam_results_excel
from ..services.rate_limit import enforce_rate_limit
from ..services.upload_validation import (
    ALLOWED_EXCEL_EXTENSIONS,
    ALLOWED_EXCEL_MIME_TYPES,
    read_validated_upload,
)


router = APIRouter(tags=["exams"], dependencies=[Depends(require_teacher)])


def _sync_linked_workflow_titles_for_exam(db: Session, exam: Exam, *, previous_title: str | None = None) -> None:
    exam_title = str(exam.title or "").strip()
    if not exam_title:
        return
    previous = str(previous_title or "").strip()
    correction_title = f"Correction - {exam_title}"
    previous_correction_title = f"Correction - {previous}" if previous else ""

    units = db.scalars(
        select(WorkflowUnit).where(WorkflowUnit.exam_id == int(exam.id)).order_by(WorkflowUnit.id.asc())
    ).all()
    if not units:
        return

    for unit in units:
        if unit.unit_type == WorkflowUnitType.EXAM:
            unit.title = exam_title
            root_item = next((row for row in (unit.checklist_items or []) if row.parent_item_id is None), None)
            if root_item is not None:
                root_item.title = exam_title
        elif unit.unit_type == WorkflowUnitType.EXAM_CORRECTION:
            unit.title = correction_title
            root_item = next((row for row in (unit.checklist_items or []) if row.parent_item_id is None), None)
            if root_item is not None:
                if not previous_correction_title or str(root_item.title or "").strip() == previous_correction_title:
                    root_item.title = correction_title
                elif str(root_item.title or "").strip().lower().startswith("correction -"):
                    root_item.title = correction_title

        blueprint = getattr(unit, "blueprint", None)
        if blueprint is not None and isinstance(blueprint.blueprint_json, dict):
            payload = dict(blueprint.blueprint_json)
            payload["unit_title"] = unit.title
            blueprint.blueprint_json = payload


def _archive_flags_for_exams(db: Session, exam_ids: list[int]) -> dict[int, bool]:
    if not exam_ids:
        return {}
    rows = db.execute(
        select(ExamArchiveState.exam_id, ExamArchiveState.is_archived).where(
            ExamArchiveState.exam_id.in_(exam_ids)
        )
    ).all()
    return {row.exam_id: bool(row.is_archived) for row in rows}


def _attach_archive_flags(db: Session, exams: list[Exam]) -> list[Exam]:
    flags = _archive_flags_for_exams(db, [exam.id for exam in exams])
    for exam in exams:
        setattr(exam, "is_archived", flags.get(exam.id, False))
    return exams


def _attach_archive_flag(db: Session, exam: Exam) -> Exam:
    setattr(exam, "is_archived", _archive_flags_for_exams(db, [exam.id]).get(exam.id, False))
    return exam


def _attach_linked_workflow_flags(db: Session, exams: list[Exam]) -> list[Exam]:
    exam_ids = [int(exam.id) for exam in exams if int(getattr(exam, "id", 0) or 0) > 0]
    if not exam_ids:
        return exams
    rows = db.scalars(
        select(WorkflowUnit)
        .where(WorkflowUnit.exam_id.in_(exam_ids))
        .order_by(WorkflowUnit.created_at.desc(), WorkflowUnit.id.desc())
    ).all()
    by_exam: dict[int, dict[str, WorkflowUnit]] = {}
    for row in rows:
        exam_id = int(row.exam_id or 0)
        if not exam_id:
            continue
        bucket = by_exam.setdefault(exam_id, {})
        key = "exam" if row.unit_type == WorkflowUnitType.EXAM else "correction" if row.unit_type == WorkflowUnitType.EXAM_CORRECTION else None
        if key is None or key in bucket:
            continue
        bucket[key] = row

    for exam in exams:
        linked = by_exam.get(int(exam.id), {})
        exam_unit = linked.get("exam")
        correction_unit = linked.get("correction")
        setattr(exam, "linked_exam_workflow_unit_id", getattr(exam_unit, "id", None))
        setattr(exam, "linked_exam_workflow_status", getattr(getattr(exam_unit, "status", None), "value", None))
        setattr(exam, "linked_exam_workflow_title", getattr(exam_unit, "title", None))
        setattr(exam, "linked_correction_workflow_unit_id", getattr(correction_unit, "id", None))
        setattr(exam, "linked_correction_workflow_status", getattr(getattr(correction_unit, "status", None), "value", None))
        setattr(exam, "linked_correction_workflow_title", getattr(correction_unit, "title", None))
    return exams


def _is_exam_archived(db: Session, exam_id: int) -> bool:
    state = db.scalar(select(ExamArchiveState).where(ExamArchiveState.exam_id == exam_id))
    return bool(state and state.is_archived)


def _close_active_linked_workflow_units_for_exam(db: Session, exam: Exam) -> list[int]:
    active_units = db.scalars(
        select(WorkflowUnit)
        .where(
            WorkflowUnit.exam_id == int(exam.id),
            WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
        )
        .order_by(WorkflowUnit.created_at.desc(), WorkflowUnit.id.desc())
    ).all()
    if not active_units:
        return []

    active_unit_ids = [int(unit.id) for unit in active_units]
    open_session = db.scalar(
        select(ClassSession)
        .where(
            ClassSession.unit_id.in_(active_unit_ids),
            ClassSession.end_time.is_(None),
        )
        .limit(1)
    )
    if open_session is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Linked workflow session #{int(open_session.id)} is still open. End it before archiving this exam.",
        )

    now = datetime.now(UTC).replace(tzinfo=None)
    for unit in active_units:
        unit.status = WorkflowUnitStatus.CLOSED
        unit.closed_at = now
    return active_unit_ids


def _safe_unlink(path: str | None) -> bool:
    raw = str(path or "").strip()
    if not raw:
        return False
    try:
        file_path = Path(raw)
        if not file_path.exists():
            return False
        file_path.unlink()
        return True
    except OSError:
        return False


def _delete_future_linked_sessions_for_exam(db: Session, exam: Exam) -> tuple[list[int], int]:
    today_value = date.today()
    sessions = db.scalars(
        select(ClassSession)
        .join(WorkflowUnit, WorkflowUnit.id == ClassSession.unit_id)
        .where(
            WorkflowUnit.exam_id == int(exam.id),
            ClassSession.session_date > today_value,
        )
        .order_by(ClassSession.session_date.asc(), ClassSession.id.asc())
    ).all()
    if not sessions:
        return [], 0

    session_ids = [int(session.id) for session in sessions]
    upload_paths = db.scalars(
        select(SessionUpload.file_path).where(SessionUpload.session_id.in_(session_ids))
    ).all()
    for session in sessions:
        db.delete(session)
    deleted_upload_files_count = sum(1 for path in upload_paths if _safe_unlink(path))
    return session_ids, deleted_upload_files_count


def _exam_results_rows(db: Session, exam_id: int):
    return db.execute(
        select(
            ExamResult.id,
            ExamResult.student_id,
            Student.student_code,
            Student.full_name,
            ExamResult.score,
            ExamResult.note,
            ExamResult.teacher_comment,
        )
        .join(Student, Student.id == ExamResult.student_id)
        .where(ExamResult.exam_id == exam_id)
        .order_by(Student.full_name.asc())
    ).all()


@router.post("/classes/{class_id}/exams", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
def create_exam(
    class_id: int,
    payload: ExamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Exam:
    _ = ensure_class_writable(db, class_id, current_user)
    exam = Exam(
        class_id=class_id,
        title=payload.title.strip(),
        exam_date=payload.exam_date,
        max_score=payload.max_score,
        weight=payload.weight,
        paper_outline_text=str(payload.paper_outline_text or "").strip() or None,
    )
    db.add(exam)
    db.flush()
    log_audit(
        db,
        user=current_user,
        action="exam.create",
        entity_type="exam",
        entity_id=exam.id,
        class_id=class_id,
        details={"title": exam.title, "max_score": exam.max_score},
    )
    db.commit()
    db.refresh(exam)
    return _attach_linked_workflow_flags(db, [_attach_archive_flag(db, exam)])[0]


@router.get("/classes/{class_id}/exams", response_model=list[ExamOut])
def list_exams(
    class_id: int,
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Exam]:
    _ = ensure_class_access(db, class_id, current_user)
    exams = db.scalars(select(Exam).where(Exam.class_id == class_id).order_by(Exam.exam_date.desc(), Exam.id.desc())).all()
    exams = _attach_linked_workflow_flags(db, _attach_archive_flags(db, exams))
    if include_archived:
        return exams
    return [exam for exam in exams if not getattr(exam, "is_archived", False)]


@router.put("/exams/{exam_id}", response_model=ExamOut)
def update_exam(
    exam_id: int,
    payload: ExamUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Exam:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_writable(db, exam.class_id, current_user)
    if _is_exam_archived(db, exam_id):
        raise HTTPException(status_code=409, detail="Exam is archived and cannot be modified.")
    previous_title = str(exam.title or "").strip()

    if payload.title is not None:
        exam.title = payload.title.strip()
    if payload.exam_date is not None:
        exam.exam_date = payload.exam_date
    if payload.max_score is not None:
        exam.max_score = payload.max_score
    if payload.weight is not None:
        exam.weight = payload.weight
    if payload.paper_outline_text is not None:
        exam.paper_outline_text = str(payload.paper_outline_text or "").strip() or None

    if str(exam.title or "").strip() != previous_title:
        _sync_linked_workflow_titles_for_exam(db, exam, previous_title=previous_title)

    log_audit(
        db,
        user=current_user,
        action="exam.update",
        entity_type="exam",
        entity_id=exam.id,
        class_id=exam.class_id,
        details={
            "title": exam.title,
            "exam_date": exam.exam_date.isoformat(),
            "max_score": exam.max_score,
            "weight": exam.weight,
        },
    )
    db.commit()
    db.refresh(exam)
    return _attach_linked_workflow_flags(db, [_attach_archive_flag(db, exam)])[0]


@router.post("/exams/{exam_id}/archive")
def archive_exam(
    exam_id: int,
    reason: str | None = Query(default=None, max_length=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_access(db, exam.class_id, current_user)
    if is_class_archived(db, exam.class_id):
        raise HTTPException(status_code=409, detail="Class is archived and cannot be modified.")
    closed_linked_unit_ids = _close_active_linked_workflow_units_for_exam(db, exam)
    deleted_future_session_ids, deleted_future_upload_files_count = _delete_future_linked_sessions_for_exam(db, exam)
    now = datetime.now(UTC).replace(tzinfo=None)
    clean_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    state = db.scalar(select(ExamArchiveState).where(ExamArchiveState.exam_id == exam_id))
    if state is None:
        state = ExamArchiveState(
            exam_id=exam_id,
            is_archived=True,
            archived_at=now,
            reason=clean_reason,
        )
        db.add(state)
    else:
        state.is_archived = True
        state.archived_at = now
        if clean_reason is not None:
            state.reason = clean_reason

    log_audit(
        db,
        user=current_user,
        action="exam.archive",
        entity_type="exam",
        entity_id=exam.id,
        class_id=exam.class_id,
        details={
            "reason": clean_reason,
            "closed_linked_unit_ids": closed_linked_unit_ids,
            "deleted_future_session_ids": deleted_future_session_ids,
            "deleted_future_upload_files_count": deleted_future_upload_files_count,
        },
    )
    db.commit()
    db.refresh(state)
    return {
        "exam_id": exam_id,
        "class_id": exam.class_id,
        "is_archived": state.is_archived,
        "archived_at": state.archived_at.isoformat() if state.archived_at else None,
        "reason": state.reason,
        "closed_linked_unit_ids": closed_linked_unit_ids,
        "deleted_future_session_ids": deleted_future_session_ids,
        "deleted_future_upload_files_count": deleted_future_upload_files_count,
    }


@router.post("/exams/{exam_id}/restore")
def restore_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_access(db, exam.class_id, current_user)
    state = db.scalar(select(ExamArchiveState).where(ExamArchiveState.exam_id == exam_id))
    if state is None:
        state = ExamArchiveState(exam_id=exam_id, is_archived=False, archived_at=None, reason=None)
        db.add(state)
    else:
        state.is_archived = False
        state.archived_at = None
        state.reason = None

    log_audit(
        db,
        user=current_user,
        action="exam.restore",
        entity_type="exam",
        entity_id=exam.id,
        class_id=exam.class_id,
        details=None,
    )
    db.commit()
    db.refresh(state)
    return {"exam_id": exam_id, "class_id": exam.class_id, "is_archived": False, "archived_at": None, "reason": None}


@router.get("/exams/{exam_id}/template")
def download_exam_template(
    exam_id: int,
    template_format: str = Query(default="normalized", alias="format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    exam = _ensure_exam(db, exam_id)
    classroom = ensure_class_access(db, exam.class_id, current_user)
    students = db.scalars(select(Student).where(Student.class_id == exam.class_id).order_by(Student.full_name.asc())).all()
    student_rows = [
        {
            "student_code": student.student_code,
            "external_id": student.external_id,
            "full_name": student.full_name,
            "birth_date": student.birth_date,
        }
        for student in students
    ]
    if template_format.lower() == "notescc":
        content = build_exam_template_notescc(
            student_rows,
            exam_title=exam.title,
            class_name=classroom.name,
            subject=classroom.subject,
        )
    else:
        content = build_exam_template(student_rows)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="exam_{exam_id}_template_{template_format}.xlsx"'},
    )


@router.post("/exams/{exam_id}/results/import")
def import_exam_results(
    exam_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_access(db, exam.class_id, current_user)
    if is_class_archived(db, exam.class_id):
        raise HTTPException(status_code=409, detail="Class is archived and cannot be modified.")
    if _is_exam_archived(db, exam_id):
        raise HTTPException(status_code=409, detail="Exam is archived and cannot be modified.")
    enforce_rate_limit(
        scope="upload",
        user_id=current_user.id,
        limit=app_config.UPLOAD_RATE_LIMIT_COUNT,
        window_seconds=app_config.UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=exam.class_id,
    )
    content, _ = read_validated_upload(
        file,
        max_bytes=MAX_EXCEL_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_EXCEL_EXTENSIONS,
        allowed_mime_types=ALLOWED_EXCEL_MIME_TYPES,
        purpose="excel",
    )
    rows, errors = parse_exam_results_excel(content)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    students = db.scalars(select(Student).where(Student.class_id == exam.class_id)).all()
    student_by_code: dict[str, Student] = {}
    for student in students:
        student_by_code[student.student_code] = student
        if student.external_id:
            student_by_code[student.external_id] = student
    missing_codes: list[str] = []
    imported = 0

    for row in rows:
        student = student_by_code.get(row["student_code"])
        if student is None:
            missing_codes.append(row["student_code"])
            continue
        if row["score"] < 0 or row["score"] > exam.max_score:
            errors.append(
                f"student_code {row['student_code']}: score {row['score']} outside [0, {exam.max_score}] range."
            )
            continue
        existing = db.scalar(
            select(ExamResult).where(ExamResult.exam_id == exam_id, ExamResult.student_id == student.id)
        )
        if existing:
            existing.score = row["score"]
            existing.note = row["note"]
            existing.teacher_comment = row["teacher_comment"]
        else:
            db.add(
                ExamResult(
                    exam_id=exam_id,
                    student_id=student.id,
                    score=row["score"],
                    note=row["note"],
                    teacher_comment=row["teacher_comment"],
                )
            )
        imported += 1

    if missing_codes:
        errors.append(f"Unknown student_code values: {', '.join(sorted(set(missing_codes)))}")
    if errors:
        db.rollback()
        raise HTTPException(status_code=400, detail={"errors": errors})

    log_audit(
        db,
        user=current_user,
        action="exam.import_results",
        entity_type="exam_result",
        entity_id=exam_id,
        class_id=exam.class_id,
        details={"imported": imported},
    )
    db.commit()
    return {"imported": imported}


@router.get("/exams/{exam_id}/results", response_model=list[ExamResultOut])
def list_exam_results(exam_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[ExamResultOut]:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_access(db, exam.class_id, current_user)
    rows = _exam_results_rows(db, exam_id)
    return [
        ExamResultOut(
            id=getattr(row, "id", None),
            student_id=row.student_id,
            student_code=row.student_code,
            full_name=row.full_name,
            score=row.score,
            note=row.note,
            teacher_comment=row.teacher_comment,
        )
        for row in rows
    ]


@router.put("/exams/{exam_id}/results/{student_id}", response_model=ExamResultOut)
def update_exam_result(
    exam_id: int,
    student_id: int,
    payload: ExamResultUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExamResultOut:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_access(db, exam.class_id, current_user)
    if is_class_archived(db, exam.class_id):
        raise HTTPException(status_code=409, detail="Class is archived and cannot be modified.")
    if _is_exam_archived(db, exam_id):
        raise HTTPException(status_code=409, detail="Exam is archived and cannot be modified.")

    student = db.get(Student, student_id)
    if student is None or student.class_id != exam.class_id:
        raise HTTPException(status_code=404, detail="Student not found in this class.")

    result = db.scalar(select(ExamResult).where(ExamResult.exam_id == exam_id, ExamResult.student_id == student_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Exam result not found.")

    if payload.score is not None:
        if payload.score < 0 or payload.score > exam.max_score:
            raise HTTPException(status_code=400, detail=f"Score must be within [0, {exam.max_score}].")
        result.score = payload.score
    if "note" in payload.model_fields_set:
        result.note = payload.note
    if "teacher_comment" in payload.model_fields_set:
        result.teacher_comment = payload.teacher_comment

    log_audit(
        db,
        user=current_user,
        action="exam.update_result",
        entity_type="exam_result",
        entity_id=result.id,
        class_id=exam.class_id,
        details={"exam_id": exam_id, "student_id": student_id},
    )
    db.commit()
    db.refresh(result)
    return ExamResultOut(
        id=result.id,
        student_id=student.id,
        student_code=student.student_code,
        full_name=student.full_name,
        score=result.score,
        note=result.note,
        teacher_comment=result.teacher_comment,
    )


@router.get("/exams/{exam_id}/results.csv")
def download_exam_results_csv(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_access(db, exam.class_id, current_user)
    enforce_rate_limit(
        scope="export",
        user_id=current_user.id,
        limit=app_config.EXPORT_RATE_LIMIT_COUNT,
        window_seconds=app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=exam.class_id,
    )
    rows = _exam_results_rows(db, exam_id)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["student_code", "full_name", "score", "max_score", "note", "teacher_comment"])
    for row in rows:
        writer.writerow([row.student_code, row.full_name, row.score, exam.max_score, row.note or "", row.teacher_comment or ""])
    payload = output.getvalue().encode("utf-8")

    log_audit(
        db,
        user=current_user,
        action="exam.export_results_csv",
        entity_type="exam",
        entity_id=exam.id,
        class_id=exam.class_id,
        details={"rows": len(rows)},
    )
    db.commit()
    return StreamingResponse(
        BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="exam_{exam_id}_results.csv"'},
    )


@router.get("/exams/{exam_id}/results.xlsx")
def download_exam_results_xlsx(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    exam = _ensure_exam(db, exam_id)
    _ = ensure_class_access(db, exam.class_id, current_user)
    enforce_rate_limit(
        scope="export",
        user_id=current_user.id,
        limit=app_config.EXPORT_RATE_LIMIT_COUNT,
        window_seconds=app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=exam.class_id,
    )
    rows = _exam_results_rows(db, exam_id)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "exam_results"
    sheet.append(("student_code", "full_name", "score", "max_score", "note", "teacher_comment"))
    for row in rows:
        sheet.append((row.student_code, row.full_name, row.score, exam.max_score, row.note or "", row.teacher_comment or ""))
    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    log_audit(
        db,
        user=current_user,
        action="exam.export_results_xlsx",
        entity_type="exam",
        entity_id=exam.id,
        class_id=exam.class_id,
        details={"rows": len(rows)},
    )
    db.commit()
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="exam_{exam_id}_results.xlsx"'},
    )


def _ensure_exam(db: Session, exam_id: int) -> Exam:
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return exam
