from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuthToken, ClassAccess, ClassArchiveState, Classroom, User, UserRole


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    token_value = credentials.credentials
    now = datetime.now(UTC).replace(tzinfo=None)
    token = db.scalar(
        select(AuthToken).where(
            AuthToken.token == token_value,
            AuthToken.expires_at > now,
        )
    )
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user.")
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=401, detail="User is temporarily locked.")
    return user


def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.OWNER, UserRole.TEACHER}:
        raise HTTPException(status_code=403, detail="Teacher access required.")
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Owner access required.")
    return user


def ensure_class_access(db: Session, class_id: int, user: User) -> Classroom:
    classroom = db.get(Classroom, class_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Class not found.")
    if user.role == UserRole.OWNER:
        return classroom
    link = db.scalar(select(ClassAccess).where(ClassAccess.class_id == class_id, ClassAccess.user_id == user.id))
    if link is None:
        raise HTTPException(status_code=403, detail="You do not have access to this class.")
    return classroom


def is_class_archived(db: Session, class_id: int) -> bool:
    state = db.scalar(select(ClassArchiveState).where(ClassArchiveState.class_id == class_id))
    return bool(state and state.is_archived)


def ensure_class_writable(db: Session, class_id: int, user: User) -> Classroom:
    classroom = ensure_class_access(db, class_id, user)
    if is_class_archived(db, class_id):
        raise HTTPException(status_code=409, detail="Class is archived and cannot be modified.")
    return classroom


def ensure_session_class_access(db: Session, class_id: int, user: User) -> None:
    ensure_class_access(db, class_id, user)
