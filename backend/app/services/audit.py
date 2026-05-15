from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def log_audit(
    db: Session,
    *,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    class_id: int | None = None,
    details: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        class_id=class_id,
        details=details,
    )
    db.add(row)
    return row
