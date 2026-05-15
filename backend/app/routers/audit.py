from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta
from io import StringIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..database import get_db
from ..models import AuditLog, User
from ..security import ensure_class_access, get_current_user, require_owner, require_teacher
from ..services.rate_limit import enforce_rate_limit


router = APIRouter(tags=["audit"], dependencies=[Depends(require_teacher)])


def _serialize_log(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "class_id": row.class_id,
        "details": row.details,
        "created_at": row.created_at.isoformat(),
    }


def _filtered_owner_logs_query(
    *,
    action: str | None,
    class_id: int | None,
    user_id: int | None,
    date_from: date | None,
    date_to: date | None,
):
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action.strip())
    if class_id is not None:
        query = query.where(AuditLog.class_id == class_id)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if date_from is not None:
        start_dt = datetime.combine(date_from, time.min)
        query = query.where(AuditLog.created_at >= start_dt)
    if date_to is not None:
        end_exclusive = datetime.combine(date_to + timedelta(days=1), time.min)
        query = query.where(AuditLog.created_at < end_exclusive)
    return query


@router.get("/classes/{class_id}/audit-logs")
def list_class_audit_logs(
    class_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = ensure_class_access(db, class_id, current_user)
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.class_id == class_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()
    return {"class_id": class_id, "count": len(rows), "items": [_serialize_log(row) for row in rows]}


@router.get("/audit/logs")
def list_audit_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    action: str | None = Query(default=None),
    class_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
) -> dict:
    query = _filtered_owner_logs_query(
        action=action,
        class_id=class_id,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    rows = db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)).all()
    return {"count": len(rows), "items": [_serialize_log(row) for row in rows]}


@router.get("/audit/logs.csv")
def export_audit_logs_csv(
    limit: int = Query(default=200, ge=1, le=5000),
    action: str | None = Query(default=None),
    class_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
) -> StreamingResponse:
    enforce_rate_limit(
        scope="export",
        user_id=_.id,
        limit=app_config.EXPORT_RATE_LIMIT_COUNT,
        window_seconds=app_config.EXPORT_RATE_LIMIT_WINDOW_SECONDS,
    )
    query = _filtered_owner_logs_query(
        action=action,
        class_id=class_id,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )
    rows = db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "user_id", "action", "entity_type", "entity_id", "class_id", "details"])
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.created_at.isoformat(),
                row.user_id,
                row.action,
                row.entity_type,
                row.entity_id,
                row.class_id,
                row.details or {},
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'},
    )
