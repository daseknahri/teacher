import csv
from datetime import UTC, date, datetime
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..config import MAX_EXCEL_UPLOAD_BYTES
from ..database import get_db
from ..models import (
    AttendanceRecord,
    ClassAccess,
    ClassArchiveState,
    ClassSession,
    Classroom,
    Exam,
    ExamResult,
    ProgressItem,
    SessionUpload,
    Student,
    User,
    UserRole,
)
from ..security import ensure_class_access, ensure_class_writable, get_current_user, require_owner, require_teacher
from ..schemas import ClassroomCreate, ClassroomOut, StudentOut, UserOut
from ..services.audit import log_audit
from ..services.excel import parse_roster_excel
from ..services.rate_limit import enforce_rate_limit
from ..services.upload_validation import (
    ALLOWED_EXCEL_EXTENSIONS,
    ALLOWED_EXCEL_MIME_TYPES,
    read_validated_upload,
)


router = APIRouter(prefix="/classes", tags=["classes"], dependencies=[Depends(require_teacher)])


def _archive_flags_for_classes(db: Session, class_ids: list[int]) -> dict[int, bool]:
    if not class_ids:
        return {}
    rows = db.execute(
        select(ClassArchiveState.class_id, ClassArchiveState.is_archived).where(
            ClassArchiveState.class_id.in_(class_ids)
        )
    ).all()
    return {row.class_id: bool(row.is_archived) for row in rows}


def _teacher_ids_for_classes(db: Session, class_ids: list[int]) -> dict[int, int | None]:
    if not class_ids:
        return {}
    rows = db.execute(
        select(ClassAccess.class_id, ClassAccess.user_id)
        .where(ClassAccess.class_id.in_(class_ids))
        .order_by(ClassAccess.class_id.asc(), ClassAccess.user_id.asc())
    ).all()
    teacher_map: dict[int, int | None] = {class_id: None for class_id in class_ids}
    for row in rows:
        if teacher_map.get(row.class_id) is None:
            teacher_map[row.class_id] = row.user_id
    return teacher_map


def _attach_archive_flags(db: Session, classes: list[Classroom]) -> list[Classroom]:
    archive_flags = _archive_flags_for_classes(db, [item.id for item in classes])
    teacher_ids = _teacher_ids_for_classes(db, [item.id for item in classes])
    for item in classes:
        setattr(item, "is_archived", archive_flags.get(item.id, False))
        setattr(item, "teacher_user_id", teacher_ids.get(item.id))
    return classes


def _attach_archive_flag(db: Session, classroom: Classroom) -> Classroom:
    setattr(classroom, "is_archived", _archive_flags_for_classes(db, [classroom.id]).get(classroom.id, False))
    setattr(classroom, "teacher_user_id", _teacher_ids_for_classes(db, [classroom.id]).get(classroom.id))
    return classroom


@router.post("", response_model=ClassroomOut, status_code=status.HTTP_201_CREATED)
def create_classroom(
    payload: ClassroomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Classroom:
    assigned_teacher_id = payload.teacher_user_id
    if current_user.role == UserRole.TEACHER and assigned_teacher_id and assigned_teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Teachers can only create classes for themselves.")
    if assigned_teacher_id is not None:
        teacher = db.get(User, assigned_teacher_id)
        if teacher is None or teacher.role != UserRole.TEACHER:
            raise HTTPException(status_code=400, detail="Assigned teacher not found.")
    elif current_user.role == UserRole.TEACHER:
        assigned_teacher_id = current_user.id

    classroom = Classroom(name=payload.name.strip(), subject=payload.subject, level=payload.level)
    db.add(classroom)
    db.flush()
    if assigned_teacher_id is not None:
        db.add(ClassAccess(class_id=classroom.id, user_id=assigned_teacher_id))
    log_audit(
        db,
        user=current_user,
        action="class.create",
        entity_type="class",
        entity_id=classroom.id,
        class_id=classroom.id,
        details={"name": classroom.name, "teacher_user_id": assigned_teacher_id},
    )
    db.commit()
    db.refresh(classroom)
    return _attach_archive_flag(db, classroom)


@router.get("", response_model=list[ClassroomOut])
def list_classes(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Classroom]:
    if current_user.role == UserRole.OWNER:
        classes = db.scalars(select(Classroom).order_by(Classroom.id.desc())).all()
        classes = _attach_archive_flags(db, classes)
        if include_archived:
            return classes
        return [item for item in classes if not getattr(item, "is_archived", False)]

    class_ids = db.scalars(select(ClassAccess.class_id).where(ClassAccess.user_id == current_user.id)).all()
    if not class_ids:
        return []
    unique_ids = sorted(set(class_ids))
    classes = db.scalars(select(Classroom).where(Classroom.id.in_(unique_ids)).order_by(Classroom.id.desc())).all()
    classes = _attach_archive_flags(db, classes)
    if include_archived:
        return classes
    return [item for item in classes if not getattr(item, "is_archived", False)]


@router.get("/by-teacher/{teacher_user_id}", response_model=list[ClassroomOut])
def list_classes_by_teacher(
    teacher_user_id: int,
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
) -> list[Classroom]:
    teacher = db.get(User, teacher_user_id)
    if teacher is None or teacher.role != UserRole.TEACHER:
        raise HTTPException(status_code=400, detail="Teacher not found.")
    class_ids = db.scalars(select(ClassAccess.class_id).where(ClassAccess.user_id == teacher_user_id)).all()
    if not class_ids:
        return []
    classes = db.scalars(select(Classroom).where(Classroom.id.in_(sorted(set(class_ids)))).order_by(Classroom.id.desc())).all()
    classes = _attach_archive_flags(db, classes)
    if include_archived:
        return classes
    return [item for item in classes if not getattr(item, "is_archived", False)]


@router.get("/owner-overview")
def owner_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
) -> dict:
    teachers = db.scalars(select(User).where(User.role == UserRole.TEACHER).order_by(User.full_name.asc())).all()
    all_classes = db.scalars(select(Classroom)).all()
    archive_flags = _archive_flags_for_classes(db, [row.id for row in all_classes])

    total_classes = len(all_classes)
    archived_classes = sum(1 for row in all_classes if archive_flags.get(row.id, False))
    active_classes = total_classes - archived_classes
    total_students = int(db.scalar(select(func.count(Student.id))) or 0)
    total_sessions = int(db.scalar(select(func.count(ClassSession.id))) or 0)
    total_exams = int(db.scalar(select(func.count(Exam.id))) or 0)

    teacher_rows: list[dict] = []
    for teacher in teachers:
        class_ids = sorted(set(db.scalars(select(ClassAccess.class_id).where(ClassAccess.user_id == teacher.id)).all()))
        if class_ids:
            student_count = int(db.scalar(select(func.count(Student.id)).where(Student.class_id.in_(class_ids))) or 0)
            session_count = int(db.scalar(select(func.count(ClassSession.id)).where(ClassSession.class_id.in_(class_ids))) or 0)
            exam_count = int(db.scalar(select(func.count(Exam.id)).where(Exam.class_id.in_(class_ids))) or 0)
            last_session_date = db.scalar(select(func.max(ClassSession.session_date)).where(ClassSession.class_id.in_(class_ids)))
        else:
            student_count = 0
            session_count = 0
            exam_count = 0
            last_session_date = None
        teacher_rows.append(
            {
                "teacher_id": teacher.id,
                "full_name": teacher.full_name,
                "email": teacher.email,
                "is_active": bool(teacher.is_active),
                "assigned_classes": len(class_ids),
                "students": student_count,
                "sessions": session_count,
                "exams": exam_count,
                "last_session_date": last_session_date.isoformat() if last_session_date else None,
            }
        )

    return {
        "counts": {
            "teachers": len(teachers),
            "classes_total": total_classes,
            "classes_active": active_classes,
            "classes_archived": archived_classes,
            "students": total_students,
            "sessions": total_sessions,
            "exams": total_exams,
        },
        "teachers": teacher_rows,
    }


@router.post("/{class_id}/assign-teacher/{teacher_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def assign_teacher_to_class(
    class_id: int,
    teacher_user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
) -> None:
    classroom = db.get(Classroom, class_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Class not found.")
    teacher = db.get(User, teacher_user_id)
    if teacher is None or teacher.role != UserRole.TEACHER:
        raise HTTPException(status_code=400, detail="Teacher not found.")
    existing_links = db.scalars(select(ClassAccess).where(ClassAccess.class_id == class_id)).all()
    existing_teacher_ids = {link.user_id for link in existing_links}
    for link in existing_links:
        if link.user_id != teacher_user_id:
            db.delete(link)
    if teacher_user_id not in existing_teacher_ids:
        db.add(ClassAccess(class_id=class_id, user_id=teacher_user_id))
    log_audit(
        db,
        user=_,
        action="class.assign_teacher",
        entity_type="class_access",
        entity_id=class_id,
        class_id=class_id,
        details={"teacher_user_id": teacher_user_id, "replaced_teacher_ids": sorted(existing_teacher_ids - {teacher_user_id})},
    )
    db.commit()


@router.get("/{class_id}/teachers", response_model=list[UserOut])
def list_class_teachers(
    class_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
) -> list[User]:
    classroom = db.get(Classroom, class_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Class not found.")
    teacher_ids = db.scalars(select(ClassAccess.user_id).where(ClassAccess.class_id == class_id)).all()
    if not teacher_ids:
        return []
    return db.scalars(
        select(User).where(User.id.in_(sorted(set(teacher_ids))), User.role == UserRole.TEACHER).order_by(User.full_name.asc())
    ).all()


@router.delete("/{class_id}/assign-teacher/{teacher_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_teacher_from_class(
    class_id: int,
    teacher_user_id: int,
    db: Session = Depends(get_db),
    owner_user: User = Depends(require_owner),
) -> None:
    classroom = db.get(Classroom, class_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Class not found.")
    teacher = db.get(User, teacher_user_id)
    if teacher is None or teacher.role != UserRole.TEACHER:
        raise HTTPException(status_code=400, detail="Teacher not found.")
    link = db.scalar(select(ClassAccess).where(ClassAccess.class_id == class_id, ClassAccess.user_id == teacher_user_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Teacher is not assigned to this class.")
    db.execute(delete(ClassAccess).where(ClassAccess.class_id == class_id, ClassAccess.user_id == teacher_user_id))
    log_audit(
        db,
        user=owner_user,
        action="class.unassign_teacher",
        entity_type="class_access",
        entity_id=class_id,
        class_id=class_id,
        details={"teacher_user_id": teacher_user_id},
    )
    db.commit()


@router.get("/{class_id}", response_model=ClassroomOut)
def get_classroom(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Classroom:
    return _attach_archive_flag(db, ensure_class_access(db, class_id, current_user))


@router.post("/{class_id}/archive")
def archive_class(
    class_id: int,
    reason: str | None = Query(default=None, max_length=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    now = datetime.now(UTC).replace(tzinfo=None)
    state = db.scalar(select(ClassArchiveState).where(ClassArchiveState.class_id == class_id))
    clean_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    if state is None:
        state = ClassArchiveState(
            class_id=class_id,
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
        action="class.archive",
        entity_type="class",
        entity_id=class_id,
        class_id=class_id,
        details={"reason": clean_reason},
    )
    db.commit()
    db.refresh(state)
    return {
        "class_id": class_id,
        "is_archived": state.is_archived,
        "archived_at": state.archived_at.isoformat() if state.archived_at else None,
        "reason": state.reason,
    }


@router.post("/{class_id}/restore")
def restore_class(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    state = db.scalar(select(ClassArchiveState).where(ClassArchiveState.class_id == class_id))
    if state is None:
        state = ClassArchiveState(class_id=class_id, is_archived=False, archived_at=None, reason=None)
        db.add(state)
    else:
        state.is_archived = False
        state.archived_at = None
        state.reason = None
    log_audit(
        db,
        user=current_user,
        action="class.restore",
        entity_type="class",
        entity_id=class_id,
        class_id=class_id,
        details=None,
    )
    db.commit()
    db.refresh(state)
    return {"class_id": class_id, "is_archived": state.is_archived, "archived_at": None, "reason": state.reason}


@router.get("/{class_id}/students", response_model=list[StudentOut])
def list_students(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[Student]:
    _ = ensure_class_access(db, class_id, current_user)
    return db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.full_name.asc())).all()


@router.get("/{class_id}/students/{student_id}/profile")
def student_profile(
    class_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    student = db.get(Student, student_id)
    if student is None or student.class_id != class_id:
        raise HTTPException(status_code=404, detail="Student not found in this class.")

    attendance_rows = db.execute(
        select(
            ClassSession.id.label("session_id"),
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
        .order_by(ClassSession.session_date.desc(), ClassSession.id.desc())
    ).all()
    attendance_counts = {"present": 0, "absent": 0, "late": 0, "excused": 0}
    for row in attendance_rows:
        attendance_counts[row.status.value] += 1

    exam_rows = db.execute(
        select(
            Exam.id.label("exam_id"),
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
        .order_by(Exam.exam_date.desc(), Exam.id.desc())
    ).all()
    scores = [float(row.score) for row in exam_rows]
    average_score = round(sum(scores) / len(scores), 2) if scores else None

    return {
        "student": {
            "id": student.id,
            "student_code": student.student_code,
            "external_id": student.external_id,
            "full_name": student.full_name,
            "birth_date": student.birth_date.isoformat() if student.birth_date else None,
            "class_id": student.class_id,
        },
        "attendance": {
            "counts": attendance_counts,
            "total_rows": len(attendance_rows),
            "records": [
                {
                    "session_id": row.session_id,
                    "session_date": row.session_date.isoformat(),
                    "status": row.status.value,
                    "minutes_late": row.minutes_late,
                    "comment": row.comment,
                }
                for row in attendance_rows
            ],
        },
        "exams": {
            "average_score": average_score,
            "count": len(exam_rows),
            "results": [
                {
                    "exam_id": row.exam_id,
                    "title": row.title,
                    "exam_date": row.exam_date.isoformat(),
                    "max_score": row.max_score,
                    "score": row.score,
                    "note": row.note,
                    "teacher_comment": row.teacher_comment,
                }
                for row in exam_rows
            ],
        },
    }


@router.get("/{class_id}/attendance-summary")
def attendance_summary(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.full_name.asc())).all()
    total_sessions = db.scalar(select(func.count(ClassSession.id)).where(ClassSession.class_id == class_id)) or 0

    rows = []
    for student in students:
        records = db.scalars(
            select(AttendanceRecord).join(ClassSession, AttendanceRecord.session_id == ClassSession.id).where(
                ClassSession.class_id == class_id,
                AttendanceRecord.student_id == student.id,
            )
        ).all()
        counts = {"present": 0, "absent": 0, "late": 0, "excused": 0}
        for record in records:
            counts[record.status.value] += 1
        attended = counts["present"] + counts["late"] + counts["excused"]
        rate = (attended / total_sessions * 100) if total_sessions else 0.0
        rows.append(
            {
                "student_id": student.id,
                "student_code": student.student_code,
                "full_name": student.full_name,
                **counts,
                "attendance_rate": round(rate, 2),
            }
        )
    return {"class_id": class_id, "total_sessions": total_sessions, "students": rows}


@router.get("/{class_id}/exam-summary")
def exam_summary(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    exams = db.scalars(select(Exam).where(Exam.class_id == class_id).order_by(Exam.exam_date.asc(), Exam.id.asc())).all()
    summary = []
    for exam in exams:
        scores = db.scalars(select(ExamResult.score).where(ExamResult.exam_id == exam.id)).all()
        avg_score = round(sum(scores) / len(scores), 2) if scores else None
        summary.append(
            {
                "exam_id": exam.id,
                "title": exam.title,
                "exam_date": exam.exam_date.isoformat(),
                "max_score": exam.max_score,
                "results_count": len(scores),
                "average_score": avg_score,
            }
        )
    return {"class_id": class_id, "exams": summary}


@router.get("/{class_id}/dashboard")
def class_dashboard(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    classroom = ensure_class_access(db, class_id, current_user)
    class_is_archived = _archive_flags_for_classes(db, [class_id]).get(class_id, False)
    student_count = db.scalar(select(func.count(Student.id)).where(Student.class_id == class_id)) or 0
    session_count = db.scalar(select(func.count(ClassSession.id)).where(ClassSession.class_id == class_id)) or 0
    exam_count = db.scalar(select(func.count(Exam.id)).where(Exam.class_id == class_id)) or 0

    recent_sessions = db.scalars(
        select(ClassSession).where(ClassSession.class_id == class_id).order_by(ClassSession.session_date.desc(), ClassSession.id.desc()).limit(5)
    ).all()
    recent_exams = db.scalars(
        select(Exam).where(Exam.class_id == class_id).order_by(Exam.exam_date.desc(), Exam.id.desc()).limit(5)
    ).all()

    attendance_rows = db.scalars(
        select(AttendanceRecord).join(ClassSession, AttendanceRecord.session_id == ClassSession.id).where(ClassSession.class_id == class_id)
    ).all()
    attendance_totals = {"present": 0, "absent": 0, "late": 0, "excused": 0}
    for row in attendance_rows:
        attendance_totals[row.status.value] += 1

    trend_sessions = db.scalars(
        select(ClassSession).where(ClassSession.class_id == class_id).order_by(ClassSession.session_date.desc(), ClassSession.id.desc()).limit(8)
    ).all()
    trend = []
    for session in reversed(trend_sessions):
        rows = db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id)).all()
        present_like = sum(1 for row in rows if row.status.value in {"present", "late", "excused"})
        rate = round((present_like / student_count * 100), 2) if student_count else 0.0
        trend.append({"session_id": session.id, "session_date": session.session_date.isoformat(), "attendance_rate": rate})

    uploads = db.scalars(
        select(SessionUpload).join(ClassSession, SessionUpload.session_id == ClassSession.id).where(ClassSession.class_id == class_id)
    ).all()
    confidence_values: list[float] = []
    latest_extraction_confidences: list[dict] = []
    for upload in uploads:
        ai_json = upload.ai_json if isinstance(upload.ai_json, dict) else None
        if not ai_json:
            continue
        confidence = ai_json.get("confidence")
        if isinstance(confidence, (int, float)):
            value = float(confidence)
            confidence_values.append(value)
            latest_extraction_confidences.append(
                {
                    "upload_id": upload.id,
                    "session_id": upload.session_id,
                    "confidence": value,
                    "reviewed": upload.reviewed,
                }
            )
    latest_extraction_confidences = sorted(
        latest_extraction_confidences,
        key=lambda row: row["upload_id"],
        reverse=True,
    )[:5]
    extraction_average = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None

    all_exams = db.scalars(select(Exam).where(Exam.class_id == class_id).order_by(Exam.exam_date.asc(), Exam.id.asc())).all()
    exam_trend = []
    for exam in all_exams[-8:]:
        scores = db.scalars(select(ExamResult.score).where(ExamResult.exam_id == exam.id)).all()
        average_score = round(sum(scores) / len(scores), 2) if scores else None
        exam_trend.append(
            {
                "exam_id": exam.id,
                "title": exam.title,
                "exam_date": exam.exam_date.isoformat(),
                "average_score": average_score,
                "results_count": len(scores),
            }
        )

    return {
        "classroom": {
            "id": classroom.id,
            "name": classroom.name,
            "subject": classroom.subject,
            "level": classroom.level,
            "is_archived": class_is_archived,
        },
        "counts": {
            "students": student_count,
            "sessions": session_count,
            "exams": exam_count,
            "attendance_rows": len(attendance_rows),
        },
        "attendance_totals": attendance_totals,
        "attendance_trend": trend,
        "extraction_metrics": {
            "average_confidence": extraction_average,
            "sample_size": len(confidence_values),
            "latest": latest_extraction_confidences,
        },
        "exam_trend": exam_trend,
        "recent_sessions": [
            {
                "id": session.id,
                "session_date": session.session_date.isoformat(),
                "start_time": session.start_time.isoformat() if session.start_time else None,
                "end_time": session.end_time.isoformat() if session.end_time else None,
                "note": session.note,
            }
            for session in recent_sessions
        ],
        "recent_exams": [
            {
                "id": exam.id,
                "title": exam.title,
                "exam_date": exam.exam_date.isoformat(),
                "max_score": exam.max_score,
            }
            for exam in recent_exams
        ],
    }


@router.get("/{class_id}/timeline")
def class_timeline(
    class_id: int,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    note_query: str | None = Query(default=None),
    has_progress: bool | None = Query(default=None),
    has_reviewed_upload: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    query = select(ClassSession).where(ClassSession.class_id == class_id)
    if date_from:
        query = query.where(ClassSession.session_date >= date_from)
    if date_to:
        query = query.where(ClassSession.session_date <= date_to)
    if note_query:
        pattern = f"%{note_query.strip()}%"
        query = query.where(ClassSession.note.ilike(pattern))
    sessions = db.scalars(query.order_by(ClassSession.session_date.desc(), ClassSession.id.desc())).all()
    session_ids = [session.id for session in sessions]
    if not session_ids:
        return {"class_id": class_id, "filters": {"date_from": date_from, "date_to": date_to, "note_query": note_query}, "sessions": []}

    progress_counts = {
        row.session_id: row.count_value
        for row in db.execute(
            select(ProgressItem.session_id, func.count(ProgressItem.id).label("count_value"))
            .where(ProgressItem.session_id.in_(session_ids))
            .group_by(ProgressItem.session_id)
        ).all()
    }
    attendance_counts = {
        row.session_id: row.count_value
        for row in db.execute(
            select(AttendanceRecord.session_id, func.count(AttendanceRecord.id).label("count_value"))
            .where(AttendanceRecord.session_id.in_(session_ids))
            .group_by(AttendanceRecord.session_id)
        ).all()
    }
    reviewed_upload_counts = {
        row.session_id: row.count_value
        for row in db.execute(
            select(SessionUpload.session_id, func.count(SessionUpload.id).label("count_value"))
            .where(SessionUpload.session_id.in_(session_ids), SessionUpload.reviewed.is_(True))
            .group_by(SessionUpload.session_id)
        ).all()
    }

    timeline_rows = [
        {
            "session_id": session.id,
            "session_date": session.session_date.isoformat(),
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
            "note": session.note,
            "attendance_rows": int(attendance_counts.get(session.id, 0)),
            "progress_items": int(progress_counts.get(session.id, 0)),
            "reviewed_uploads": int(reviewed_upload_counts.get(session.id, 0)),
        }
        for session in sessions
    ]
    if has_progress is not None:
        timeline_rows = [row for row in timeline_rows if (row["progress_items"] > 0) == has_progress]
    if has_reviewed_upload is not None:
        timeline_rows = [row for row in timeline_rows if (row["reviewed_uploads"] > 0) == has_reviewed_upload]

    return {
        "class_id": class_id,
        "filters": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "note_query": note_query,
            "has_progress": has_progress,
            "has_reviewed_upload": has_reviewed_upload,
        },
        "sessions": timeline_rows,
    }


@router.get("/{class_id}/attendance-export.csv")
def attendance_export_csv(
    class_id: int,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    mask_personal_data: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _ = ensure_class_access(db, class_id, current_user)
    enforce_rate_limit(
        scope="export",
        user_id=current_user.id,
        limit=app_config.EXPORT_RATE_LIMIT_COUNT,
        window_seconds=app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=class_id,
    )
    query = (
        select(
            ClassSession.session_date,
            ClassSession.id.label("session_id"),
            Student.id.label("student_id"),
            Student.student_code,
            Student.full_name,
            AttendanceRecord.status,
            AttendanceRecord.minutes_late,
            AttendanceRecord.comment,
        )
        .join(AttendanceRecord, AttendanceRecord.session_id == ClassSession.id)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .where(ClassSession.class_id == class_id)
    )
    if date_from:
        query = query.where(ClassSession.session_date >= date_from)
    if date_to:
        query = query.where(ClassSession.session_date <= date_to)
    rows = db.execute(query.order_by(ClassSession.session_date.asc(), Student.full_name.asc())).all()
    mask_map: dict[int, dict] = {}
    if mask_personal_data:
        students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.full_name.asc(), Student.id.asc())).all()
        mask_map = {
            student.id: {"student_code": f"ANON{idx:03d}", "full_name": f"Student {idx:03d}"}
            for idx, student in enumerate(students, start=1)
        }

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["session_date", "session_id", "student_code", "full_name", "status", "minutes_late", "comment"])
    for row in rows:
        student_code = row.student_code
        full_name = row.full_name
        comment = row.comment or ""
        if mask_personal_data:
            student_code = mask_map.get(row.student_id, {}).get("student_code", student_code)
            full_name = mask_map.get(row.student_id, {}).get("full_name", full_name)
            comment = ""
        writer.writerow(
            [
                row.session_date.isoformat(),
                row.session_id,
                student_code,
                full_name,
                row.status.value,
                row.minutes_late,
                comment,
            ]
        )
    csv_bytes = output.getvalue().encode("utf-8")
    suffix = "_masked" if mask_personal_data else ""
    return StreamingResponse(
        BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="class_{class_id}_attendance{suffix}.csv"'},
    )


@router.post("/{class_id}/students/import")
def import_students(
    class_id: int,
    file: UploadFile = File(...),
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
    content, _ = read_validated_upload(
        file,
        max_bytes=MAX_EXCEL_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_EXCEL_EXTENSIONS,
        allowed_mime_types=ALLOWED_EXCEL_MIME_TYPES,
        purpose="excel",
    )
    rows, errors = parse_roster_excel(content)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    existing_codes = set(
        db.scalars(select(Student.student_code).where(Student.class_id == class_id)).all()
    )
    duplicates_in_db: list[str] = []
    created = 0

    for row in rows:
        if row["student_code"] in existing_codes:
            duplicates_in_db.append(row["student_code"])
            continue
        db.add(
            Student(
                class_id=class_id,
                student_code=row["student_code"],
                external_id=row.get("external_id"),
                full_name=row["full_name"],
                birth_date=row.get("birth_date"),
            )
        )
        existing_codes.add(row["student_code"])
        created += 1

    log_audit(
        db,
        user=current_user,
        action="students.import",
        entity_type="student",
        class_id=class_id,
        details={"created": created, "duplicates_skipped": len(duplicates_in_db)},
    )
    db.commit()
    return {"created": created, "duplicates_skipped": duplicates_in_db}


@router.get("/{class_id}/students/template")
def download_roster_template(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _ = ensure_class_access(db, class_id, current_user)
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "students"
    sheet.append(("id", "name", "birth_date"))
    sheet.append(("A123456789", "Sample Student", "2011-03-23"))
    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="students_template.xlsx"'},
    )
