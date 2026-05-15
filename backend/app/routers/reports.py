from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..config import EXPORTS_DIR
from ..database import get_db
from ..models import Exam, ExamResult, ExportArtifact, Student, User
from ..security import ensure_class_access, get_current_user, require_teacher
from ..services.audit import log_audit
from ..services.excel import build_principal_export
from ..services.rate_limit import enforce_rate_limit
from ..services.report import build_class_pdf_report, build_student_profile_pdf


router = APIRouter(tags=["reports"], dependencies=[Depends(require_teacher)])


def _class_student_masks(db: Session, class_id: int) -> dict[int, dict]:
    students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.full_name.asc(), Student.id.asc())).all()
    return {
        student.id: {
            "student_code": f"ANON{idx:03d}",
            "external_id": f"ANON{idx:03d}",
            "full_name": f"Student {idx:03d}",
        }
        for idx, student in enumerate(students, start=1)
    }


def _persist_export(
    db: Session,
    *,
    class_id: int,
    current_user: User,
    export_type: str,
    filename: str,
    content: bytes,
) -> ExportArtifact:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    class_dir = EXPORTS_DIR / f"class_{class_id}"
    class_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_name = filename.replace(" ", "_")
    target = class_dir / f"{stamp}_{safe_name}"
    target.write_bytes(content)

    artifact = ExportArtifact(
        class_id=class_id,
        export_type=export_type,
        file_name=target.name,
        file_path=str(target),
        file_size=len(content),
        created_by_user_id=current_user.id,
    )
    db.add(artifact)
    db.flush()
    log_audit(
        db,
        user=current_user,
        action="report.export",
        entity_type="export_artifact",
        entity_id=artifact.id,
        class_id=class_id,
        details={"export_type": export_type, "file_name": artifact.file_name, "file_size": artifact.file_size},
    )
    db.commit()
    db.refresh(artifact)
    return artifact


@router.get("/classes/{class_id}/reports/full.pdf")
def export_full_pdf(
    class_id: int,
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
    content = build_class_pdf_report(db, class_id, mask_personal_data=mask_personal_data)
    suffix = "_masked" if mask_personal_data else ""
    artifact = _persist_export(
        db,
        class_id=class_id,
        current_user=current_user,
        export_type=f"class_full_pdf{suffix}",
        filename=f"class_{class_id}_report{suffix}.pdf",
        content=content,
    )
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="class_{class_id}_report{suffix}.pdf"',
            "X-Export-Artifact-Id": str(artifact.id),
        },
    )


@router.get("/classes/{class_id}/students/{student_id}/reports/profile.pdf")
def export_student_profile_pdf(
    class_id: int,
    student_id: int,
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
    masks = _class_student_masks(db, class_id) if mask_personal_data else {}
    try:
        content = build_student_profile_pdf(
            db,
            class_id,
            student_id,
            mask_personal_data=mask_personal_data,
            masked_student_code=masks.get(student_id, {}).get("student_code"),
            masked_full_name=masks.get(student_id, {}).get("full_name"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    suffix = "_masked" if mask_personal_data else ""
    artifact = _persist_export(
        db,
        class_id=class_id,
        current_user=current_user,
        export_type=f"student_profile_pdf{suffix}",
        filename=f"class_{class_id}_student_{student_id}_profile{suffix}.pdf",
        content=content,
    )
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="class_{class_id}_student_{student_id}_profile{suffix}.pdf"',
            "X-Export-Artifact-Id": str(artifact.id),
        },
    )


@router.get("/classes/{class_id}/reports/official-notes.xlsx")
@router.get("/classes/{class_id}/reports/principal-notes.xlsx")
def export_official_notes(
    class_id: int,
    mask_personal_data: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    classroom = ensure_class_access(db, class_id, current_user)
    enforce_rate_limit(
        scope="export",
        user_id=current_user.id,
        limit=app_config.EXPORT_RATE_LIMIT_COUNT,
        window_seconds=app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=class_id,
    )
    exams = db.scalars(select(Exam).where(Exam.class_id == class_id).order_by(Exam.exam_date.asc(), Exam.id.asc())).all()
    if not exams:
        raise HTTPException(status_code=404, detail="No exam found for this class.")
    selected_exams = exams[-3:]
    selected_exam_ids = [exam.id for exam in selected_exams]

    raw_results = db.execute(
        select(
            Student.id.label("student_id"),
            Student.student_code,
            Student.full_name,
            ExamResult.exam_id,
            ExamResult.score,
            ExamResult.note,
            ExamResult.teacher_comment,
        )
        .join(Student, Student.id == ExamResult.student_id)
        .where(ExamResult.exam_id.in_(selected_exam_ids))
    ).all()

    students = db.scalars(select(Student).where(Student.class_id == class_id).order_by(Student.full_name.asc())).all()
    masks = _class_student_masks(db, class_id) if mask_personal_data else {}
    by_student_exam = {
        (row.student_id, row.exam_id): {
            "score": row.score,
            "note": row.note,
            "teacher_comment": row.teacher_comment,
        }
        for row in raw_results
    }

    rows: list[dict] = []
    for student in students:
        scores = []
        for exam in selected_exams:
            value = by_student_exam.get((student.id, exam.id))
            scores.append(value["score"] if value else None)
        latest_value = by_student_exam.get((student.id, selected_exams[-1].id), {})
        student_code = student.student_code
        external_id = student.external_id
        full_name = student.full_name
        if mask_personal_data:
            student_code = masks.get(student.id, {}).get("student_code", student_code)
            external_id = masks.get(student.id, {}).get("external_id", external_id)
            full_name = masks.get(student.id, {}).get("full_name", full_name)
        rows.append(
            {
                "student_code": student_code,
                "external_id": external_id,
                "full_name": full_name,
                "birth_date": student.birth_date,
                "score": latest_value.get("score"),
                "note": latest_value.get("note"),
                "teacher_comment": latest_value.get("teacher_comment"),
                "scores": scores,
            }
        )

    content = build_principal_export(
        exam_title=selected_exams[-1].title,
        rows=rows,
        class_name=classroom.name,
        subject=classroom.subject,
    )
    suffix = "_masked" if mask_personal_data else ""
    artifact = _persist_export(
        db,
        class_id=class_id,
        current_user=current_user,
        export_type=f"official_notes_xlsx{suffix}",
        filename=f"class_{class_id}_official_notes{suffix}.xlsx",
        content=content,
    )
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="class_{class_id}_official_notes{suffix}.xlsx"',
            "X-Export-Artifact-Id": str(artifact.id),
        },
    )


@router.get("/classes/{class_id}/exports/history")
def list_export_history(
    class_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    rows = db.scalars(
        select(ExportArtifact)
        .where(ExportArtifact.class_id == class_id)
        .order_by(ExportArtifact.created_at.desc(), ExportArtifact.id.desc())
        .limit(limit)
    ).all()
    return {
        "class_id": class_id,
        "count": len(rows),
        "items": [
            {
                "id": row.id,
                "export_type": row.export_type,
                "file_name": row.file_name,
                "file_size": row.file_size,
                "created_by_user_id": row.created_by_user_id,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/exports/{export_id}/download")
def download_export_by_id(
    export_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    artifact = db.get(ExportArtifact, export_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    _ = ensure_class_access(db, artifact.class_id, current_user)
    enforce_rate_limit(
        scope="export",
        user_id=current_user.id,
        limit=app_config.EXPORT_RATE_LIMIT_COUNT,
        window_seconds=app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS,
        resource_id=artifact.class_id,
    )

    target = Path(artifact.file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Export file not found on disk.")
    content = target.read_bytes()

    media_type = (
        "application/pdf"
        if artifact.file_name.lower().endswith(".pdf")
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return StreamingResponse(
        BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.file_name}"'},
    )
