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
    AttendanceStatus,
    ClassAccess,
    ClassTimetableRule,
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
    WorkflowChecklistItem,
    WorkflowSessionChecklistAction,
    WorkflowUnit,
    WorkflowUnitStatus,
)
from ..security import ensure_class_access, ensure_class_writable, get_current_user, require_owner, require_teacher
from ..schemas import ClassroomCreate, ClassroomOut, ClassroomUpdate, StudentOut, UserOut
from ..services.audit import log_audit
from ..services.excel import parse_roster_excel
from ..services.rate_limit import enforce_rate_limit
from ..services.school_time import school_today
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


def _set_class_teacher_assignment(
    db: Session,
    class_id: int,
    teacher_user_id: int | None,
) -> list[int]:
    existing_links = db.scalars(select(ClassAccess).where(ClassAccess.class_id == class_id)).all()
    existing_teacher_ids = sorted({link.user_id for link in existing_links})
    for link in existing_links:
        if teacher_user_id is None or link.user_id != teacher_user_id:
            db.delete(link)
    if teacher_user_id is not None and teacher_user_id not in existing_teacher_ids:
        db.add(ClassAccess(class_id=class_id, user_id=teacher_user_id))
    return [tid for tid in existing_teacher_ids if tid != teacher_user_id]


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
    open_sessions = int(db.scalar(select(func.count(ClassSession.id)).where(ClassSession.end_time.is_(None))) or 0)
    active_units = int(
        db.scalar(select(func.count(WorkflowUnit.id)).where(WorkflowUnit.status == WorkflowUnitStatus.ACTIVE)) or 0
    )
    closed_units = int(
        db.scalar(select(func.count(WorkflowUnit.id)).where(WorkflowUnit.status == WorkflowUnitStatus.CLOSED)) or 0
    )
    completed_checklist_items = int(
        db.scalar(select(func.count(WorkflowChecklistItem.id)).where(WorkflowChecklistItem.is_completed.is_(True))) or 0
    )
    checked_session_rows = int(
        db.scalar(
            select(func.count(WorkflowSessionChecklistAction.id)).where(
                WorkflowSessionChecklistAction.checked.is_(True)
            )
        )
        or 0
    )
    exam_results = int(db.scalar(select(func.count(ExamResult.id))) or 0)
    classes_by_id = {row.id: row for row in all_classes}
    teachers_by_id = {row.id: row for row in teachers}
    teacher_ids_by_class = _teacher_ids_for_classes(db, [row.id for row in all_classes])
    recent_session_rows: list[dict] = []
    recent_sessions = db.scalars(
        select(ClassSession)
        .order_by(ClassSession.session_date.desc(), ClassSession.created_at.desc(), ClassSession.id.desc())
        .limit(20)
    ).all()
    for session in recent_sessions:
        classroom = classes_by_id.get(session.class_id)
        teacher_id = teacher_ids_by_class.get(session.class_id)
        assigned_teacher = teachers_by_id.get(teacher_id) if teacher_id else None
        attendance_rows = int(
            db.scalar(select(func.count(AttendanceRecord.id)).where(AttendanceRecord.session_id == session.id)) or 0
        )
        absent_rows = int(
            db.scalar(
                select(func.count(AttendanceRecord.id)).where(
                    AttendanceRecord.session_id == session.id,
                    AttendanceRecord.status == AttendanceStatus.ABSENT,
                )
            )
            or 0
        )
        recent_session_rows.append(
            {
                "session_id": session.id,
                "class_id": session.class_id,
                "class_name": classroom.name if classroom else f"Class #{session.class_id}",
                "teacher_user_id": teacher_id,
                "teacher_name": assigned_teacher.full_name if assigned_teacher else None,
                "teacher_email": assigned_teacher.email if assigned_teacher else None,
                "session_date": session.session_date.isoformat(),
                "start_time": session.start_time.isoformat(timespec="minutes") if session.start_time else None,
                "end_time": session.end_time.isoformat(timespec="minutes") if session.end_time else None,
                "is_open": session.end_time is None,
                "unit_session_number": session.unit_session_number,
                "attendance_rows": attendance_rows,
                "absent_rows": absent_rows,
                "progress_items": int(
                    db.scalar(select(func.count(ProgressItem.id)).where(ProgressItem.session_id == session.id)) or 0
                ),
                "checked_session_rows": int(
                    db.scalar(
                        select(func.count(WorkflowSessionChecklistAction.id)).where(
                            WorkflowSessionChecklistAction.session_id == session.id,
                            WorkflowSessionChecklistAction.checked.is_(True),
                        )
                    )
                    or 0
                ),
                "note_preview": (session.note or "")[:160] if session.note else None,
            }
        )

    overview_class_rows: list[dict] = []
    for classroom in sorted(all_classes, key=lambda row: row.name.lower()):
        teacher_id = teacher_ids_by_class.get(classroom.id)
        assigned_teacher = teachers_by_id.get(teacher_id) if teacher_id else None
        class_last_session_date = db.scalar(
            select(func.max(ClassSession.session_date)).where(ClassSession.class_id == classroom.id)
        )
        overview_class_rows.append(
            {
                "class_id": classroom.id,
                "name": classroom.name,
                "subject": classroom.subject,
                "level": classroom.level,
                "is_archived": bool(archive_flags.get(classroom.id, False)),
                "teacher_user_id": teacher_id,
                "teacher_name": assigned_teacher.full_name if assigned_teacher else None,
                "teacher_email": assigned_teacher.email if assigned_teacher else None,
                "teacher_is_active": bool(assigned_teacher.is_active) if assigned_teacher else None,
                "students": int(db.scalar(select(func.count(Student.id)).where(Student.class_id == classroom.id)) or 0),
                "sessions": int(
                    db.scalar(select(func.count(ClassSession.id)).where(ClassSession.class_id == classroom.id)) or 0
                ),
                "open_sessions": int(
                    db.scalar(
                        select(func.count(ClassSession.id)).where(
                            ClassSession.class_id == classroom.id,
                            ClassSession.end_time.is_(None),
                        )
                    )
                    or 0
                ),
                "active_units": int(
                    db.scalar(
                        select(func.count(WorkflowUnit.id)).where(
                            WorkflowUnit.class_id == classroom.id,
                            WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
                        )
                    )
                    or 0
                ),
                "exams": int(db.scalar(select(func.count(Exam.id)).where(Exam.class_id == classroom.id)) or 0),
                "last_session_date": class_last_session_date.isoformat() if class_last_session_date else None,
            }
        )

    teacher_rows: list[dict] = []
    for teacher in teachers:
        class_ids = sorted(set(db.scalars(select(ClassAccess.class_id).where(ClassAccess.user_id == teacher.id)).all()))
        if class_ids:
            active_class_ids = [class_id for class_id in class_ids if not archive_flags.get(class_id, False)]
            archived_class_ids = [class_id for class_id in class_ids if archive_flags.get(class_id, False)]
            student_count = int(db.scalar(select(func.count(Student.id)).where(Student.class_id.in_(class_ids))) or 0)
            session_count = int(db.scalar(select(func.count(ClassSession.id)).where(ClassSession.class_id.in_(class_ids))) or 0)
            open_session_count = int(
                db.scalar(
                    select(func.count(ClassSession.id)).where(
                        ClassSession.class_id.in_(class_ids),
                        ClassSession.end_time.is_(None),
                    )
                )
                or 0
            )
            exam_count = int(db.scalar(select(func.count(Exam.id)).where(Exam.class_id.in_(class_ids))) or 0)
            last_session_date = db.scalar(select(func.max(ClassSession.session_date)).where(ClassSession.class_id.in_(class_ids)))
            attendance_rows = int(
                db.scalar(
                    select(func.count(AttendanceRecord.id))
                    .join(ClassSession, AttendanceRecord.session_id == ClassSession.id)
                    .where(ClassSession.class_id.in_(class_ids))
                )
                or 0
            )
            progress_items = int(
                db.scalar(
                    select(func.count(ProgressItem.id))
                    .join(ClassSession, ProgressItem.session_id == ClassSession.id)
                    .where(ClassSession.class_id.in_(class_ids))
                )
                or 0
            )
            active_unit_count = int(
                db.scalar(
                    select(func.count(WorkflowUnit.id)).where(
                        WorkflowUnit.class_id.in_(class_ids),
                        WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
                    )
                )
                or 0
            )
            closed_unit_count = int(
                db.scalar(
                    select(func.count(WorkflowUnit.id)).where(
                        WorkflowUnit.class_id.in_(class_ids),
                        WorkflowUnit.status == WorkflowUnitStatus.CLOSED,
                    )
                )
                or 0
            )
            checklist_items = int(
                db.scalar(
                    select(func.count(WorkflowChecklistItem.id))
                    .join(WorkflowUnit, WorkflowChecklistItem.unit_id == WorkflowUnit.id)
                    .where(WorkflowUnit.class_id.in_(class_ids))
                )
                or 0
            )
            completed_items = int(
                db.scalar(
                    select(func.count(WorkflowChecklistItem.id))
                    .join(WorkflowUnit, WorkflowChecklistItem.unit_id == WorkflowUnit.id)
                    .where(
                        WorkflowUnit.class_id.in_(class_ids),
                        WorkflowChecklistItem.is_completed.is_(True),
                    )
                )
                or 0
            )
            checked_actions = int(
                db.scalar(
                    select(func.count(WorkflowSessionChecklistAction.id))
                    .join(ClassSession, WorkflowSessionChecklistAction.session_id == ClassSession.id)
                    .where(
                        ClassSession.class_id.in_(class_ids),
                        WorkflowSessionChecklistAction.checked.is_(True),
                    )
                )
                or 0
            )
            exam_result_stats = db.execute(
                select(func.count(ExamResult.id), func.avg(ExamResult.score))
                .join(Exam, ExamResult.exam_id == Exam.id)
                .where(Exam.class_id.in_(class_ids))
            ).one()
            exam_result_count = int(exam_result_stats[0] or 0)
            average_exam_score = float(exam_result_stats[1]) if exam_result_stats[1] is not None else None
            teacher_class_rows = []
            for class_id in class_ids:
                classroom = classes_by_id.get(class_id)
                if classroom is None:
                    continue
                class_last_session_date = db.scalar(
                    select(func.max(ClassSession.session_date)).where(ClassSession.class_id == class_id)
                )
                teacher_class_rows.append(
                    {
                        "class_id": class_id,
                        "name": classroom.name,
                        "subject": classroom.subject,
                        "level": classroom.level,
                        "is_archived": bool(archive_flags.get(class_id, False)),
                        "students": int(
                            db.scalar(select(func.count(Student.id)).where(Student.class_id == class_id)) or 0
                        ),
                        "sessions": int(
                            db.scalar(select(func.count(ClassSession.id)).where(ClassSession.class_id == class_id))
                            or 0
                        ),
                        "open_sessions": int(
                            db.scalar(
                                select(func.count(ClassSession.id)).where(
                                    ClassSession.class_id == class_id,
                                    ClassSession.end_time.is_(None),
                                )
                            )
                            or 0
                        ),
                        "active_units": int(
                            db.scalar(
                                select(func.count(WorkflowUnit.id)).where(
                                    WorkflowUnit.class_id == class_id,
                                    WorkflowUnit.status == WorkflowUnitStatus.ACTIVE,
                                )
                            )
                            or 0
                        ),
                        "last_session_date": class_last_session_date.isoformat() if class_last_session_date else None,
                    }
                )
            teacher_sessions = db.scalars(
                select(ClassSession)
                .where(ClassSession.class_id.in_(class_ids))
                .order_by(ClassSession.session_date.desc(), ClassSession.start_time.desc(), ClassSession.id.desc())
                .limit(24)
            ).all()
            teacher_session_ids = [int(session.id) for session in teacher_sessions]
            checked_items_by_session: dict[int, list[str]] = {session_id: [] for session_id in teacher_session_ids}
            if teacher_session_ids:
                checked_rows = db.execute(
                    select(WorkflowSessionChecklistAction.session_id, WorkflowChecklistItem.title)
                    .join(WorkflowChecklistItem, WorkflowSessionChecklistAction.item_id == WorkflowChecklistItem.id)
                    .where(
                        WorkflowSessionChecklistAction.session_id.in_(teacher_session_ids),
                        WorkflowSessionChecklistAction.checked.is_(True),
                    )
                    .order_by(
                        WorkflowSessionChecklistAction.session_id.asc(),
                        WorkflowChecklistItem.position.asc(),
                        WorkflowChecklistItem.id.asc(),
                    )
                ).all()
                for session_id, title in checked_rows:
                    clean_title = str(title or "").strip()
                    if clean_title:
                        checked_items_by_session.setdefault(int(session_id), []).append(clean_title)
            teacher_session_rows = []
            for session in teacher_sessions:
                classroom = classes_by_id.get(session.class_id)
                unit = session.unit
                checked_item_titles = checked_items_by_session.get(int(session.id), [])
                teacher_session_rows.append(
                    {
                        "session_id": session.id,
                        "class_id": session.class_id,
                        "class_name": classroom.name if classroom else f"Class #{session.class_id}",
                        "session_date": session.session_date.isoformat(),
                        "start_time": session.start_time.isoformat(timespec="minutes") if session.start_time else None,
                        "end_time": session.end_time.isoformat(timespec="minutes") if session.end_time else None,
                        "is_open": session.end_time is None,
                        "unit_id": session.unit_id,
                        "unit_title": unit.title if unit else None,
                        "unit_type": unit.unit_type.value if unit else None,
                        "unit_session_number": session.unit_session_number,
                        "checked_session_rows": len(checked_item_titles),
                        "checked_items": checked_item_titles,
                        "progress_items": int(
                            db.scalar(select(func.count(ProgressItem.id)).where(ProgressItem.session_id == session.id))
                            or 0
                        ),
                    }
                )
            timetable_rules = db.scalars(
                select(ClassTimetableRule)
                .where(
                    ClassTimetableRule.class_id.in_(class_ids),
                    (ClassTimetableRule.effective_to.is_(None)) | (ClassTimetableRule.effective_to >= school_today()),
                )
                .order_by(ClassTimetableRule.weekday.asc(), ClassTimetableRule.start_time.asc())
                .limit(40)
            ).all()
            timetable_rule_rows = []
            for rule in timetable_rules:
                classroom = classes_by_id.get(rule.class_id)
                timetable_rule_rows.append(
                    {
                        "rule_id": rule.id,
                        "class_id": rule.class_id,
                        "class_name": classroom.name if classroom else f"Class #{rule.class_id}",
                        "weekday": rule.weekday,
                        "start_time": rule.start_time.isoformat(timespec="minutes"),
                        "end_time": rule.end_time.isoformat(timespec="minutes"),
                        "subject": rule.subject,
                        "room": rule.room,
                        "group_name": rule.group_name,
                        "effective_from": rule.effective_from.isoformat(),
                        "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
                    }
                )
        else:
            active_class_ids = []
            archived_class_ids = []
            student_count = 0
            session_count = 0
            open_session_count = 0
            exam_count = 0
            last_session_date = None
            attendance_rows = 0
            progress_items = 0
            active_unit_count = 0
            closed_unit_count = 0
            checklist_items = 0
            completed_items = 0
            checked_actions = 0
            exam_result_count = 0
            average_exam_score = None
            teacher_class_rows = []
            teacher_session_rows = []
            timetable_rule_rows = []
        class_names = [classes_by_id[class_id].name for class_id in class_ids if class_id in classes_by_id]
        teacher_rows.append(
            {
                "teacher_id": teacher.id,
                "full_name": teacher.full_name,
                "email": teacher.email,
                "is_active": bool(teacher.is_active),
                "assigned_classes": len(class_ids),
                "active_classes": len(active_class_ids),
                "archived_classes": len(archived_class_ids),
                "class_names": class_names,
                "classes": teacher_class_rows,
                "students": student_count,
                "sessions": session_count,
                "open_sessions": open_session_count,
                "exams": exam_count,
                "exam_results": exam_result_count,
                "average_exam_score": average_exam_score,
                "attendance_rows": attendance_rows,
                "progress_items": progress_items,
                "active_units": active_unit_count,
                "closed_units": closed_unit_count,
                "checklist_items": checklist_items,
                "completed_checklist_items": completed_items,
                "checked_session_rows": checked_actions,
                "last_session_date": last_session_date.isoformat() if last_session_date else None,
                "recent_sessions": teacher_session_rows,
                "timetable_rules": timetable_rule_rows,
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
            "open_sessions": open_sessions,
            "exams": total_exams,
            "exam_results": exam_results,
            "active_units": active_units,
            "closed_units": closed_units,
            "completed_checklist_items": completed_checklist_items,
            "checked_session_rows": checked_session_rows,
        },
        "teachers": teacher_rows,
        "classes": overview_class_rows,
        "recent_sessions": recent_session_rows,
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
    replaced_teacher_ids = _set_class_teacher_assignment(db, class_id, teacher_user_id)
    log_audit(
        db,
        user=_,
        action="class.assign_teacher",
        entity_type="class_access",
        entity_id=class_id,
        class_id=class_id,
        details={"teacher_user_id": teacher_user_id, "replaced_teacher_ids": replaced_teacher_ids},
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


@router.patch("/{class_id}", response_model=ClassroomOut)
def update_classroom(
    class_id: int,
    payload: ClassroomUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Classroom:
    classroom = ensure_class_writable(db, class_id, current_user)
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required.")

    details: dict[str, object] = {}
    if payload.name is not None:
        clean_name = payload.name.strip()
        classroom.name = clean_name
        details["name"] = clean_name
    if payload.subject is not None:
        classroom.subject = payload.subject
        details["subject"] = payload.subject
    if payload.level is not None:
        classroom.level = payload.level
        details["level"] = payload.level
    if payload.teacher_user_id is not None:
        teacher = db.get(User, payload.teacher_user_id)
        if teacher is None or teacher.role != UserRole.TEACHER:
            raise HTTPException(status_code=400, detail="Assigned teacher not found.")
        details["teacher_user_id"] = payload.teacher_user_id
        details["replaced_teacher_ids"] = _set_class_teacher_assignment(db, class_id, payload.teacher_user_id)
    elif "teacher_user_id" in payload.model_fields_set:
        details["teacher_user_id"] = None
        details["replaced_teacher_ids"] = _set_class_teacher_assignment(db, class_id, None)

    if details:
        log_audit(
            db,
            user=current_user,
            action="class.update",
            entity_type="class",
            entity_id=class_id,
            class_id=class_id,
            details=details,
        )
    db.commit()
    db.refresh(classroom)
    return _attach_archive_flag(db, classroom)


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
