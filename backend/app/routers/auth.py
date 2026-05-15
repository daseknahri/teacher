from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..database import get_db
from ..models import AuthToken, User, UserRole
from ..schemas import (
    InviteSendIn,
    InviteSendOut,
    LoginIn,
    OwnerBootstrapIn,
    PasswordChangeIn,
    PasswordResetIn,
    TokenOut,
    UserCreate,
    UserOut,
    UserStatusUpdateIn,
)
from ..security import bearer_scheme, get_current_user, require_owner
from ..services.audit import log_audit
from ..services.auth import create_access_token, hash_password, verify_password
from ..services.mailer import send_email, smtp_is_configured


router = APIRouter(prefix="/auth", tags=["auth"])


def _invite_message(*, app_url: str, email: str, temporary_password: str | None) -> str:
    lines = [
        "Teacher account invitation",
        "",
        f"Login URL: {app_url}",
        f"Email: {email}",
    ]
    if temporary_password:
        lines.append(f"Temporary password: {temporary_password}")
        lines.append("Please change your password after first login.")
    else:
        lines.append("Password: ask owner to provide or reset temporary password.")
    return "\n".join(lines)


@router.post("/bootstrap-owner", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def bootstrap_owner(payload: OwnerBootstrapIn, db: Session = Depends(get_db)) -> User:
    existing_owner = db.scalar(select(User).where(User.role == UserRole.OWNER))
    if existing_owner:
        raise HTTPException(status_code=400, detail="Owner already exists.")

    user = User(
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=UserRole.OWNER,
        is_active=True,
    )
    db.add(user)
    db.flush()
    log_audit(
        db,
        user=user,
        action="auth.bootstrap_owner",
        entity_type="user",
        entity_id=user.id,
        details={"email": user.email},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    now = datetime.now(UTC).replace(tzinfo=None)
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.locked_until and user.locked_until > now:
        raise HTTPException(
            status_code=423,
            detail=f"Account is temporarily locked until {user.locked_until.isoformat()}",
        )
    if user is None or not verify_password(payload.password, user.password_hash):
        if user is not None:
            user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
            if (
                app_config.MAX_FAILED_LOGIN_ATTEMPTS > 0
                and user.failed_login_attempts >= app_config.MAX_FAILED_LOGIN_ATTEMPTS
            ):
                lock_minutes = max(1, int(app_config.LOGIN_LOCKOUT_MINUTES))
                user.locked_until = now + timedelta(minutes=lock_minutes)
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive.")
    user.failed_login_attempts = 0
    user.locked_until = None

    token = create_access_token(db, user)
    return TokenOut(access_token=token.token, expires_at=token.expires_at.isoformat())


@router.post("/refresh", response_model=TokenOut)
def refresh_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> TokenOut:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    now = datetime.now(UTC).replace(tzinfo=None)
    current_token = db.scalar(
        select(AuthToken).where(
            AuthToken.token == credentials.credentials,
            AuthToken.expires_at > now,
        )
    )
    if current_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = db.get(User, current_token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user.")

    db.delete(current_token)
    db.commit()
    token = create_access_token(db, user)
    log_audit(
        db,
        user=user,
        action="auth.refresh_token",
        entity_type="auth_token",
        entity_id=token.id,
        details=None,
    )
    db.commit()
    return TokenOut(access_token=token.token, expires_at=token.expires_at.isoformat())


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    db.execute(
        delete(AuthToken).where(
            AuthToken.user_id == current_user.id,
            AuthToken.expires_at > now,
        )
    )
    db.commit()
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, owner_user: User = Depends(require_owner), db: Session = Depends(get_db)) -> User:
    if payload.role == UserRole.OWNER:
        raise HTTPException(status_code=400, detail="Only one owner is allowed.")
    existing = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists.")
    user = User(
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    log_audit(
        db,
        user=owner_user,
        action="auth.create_user",
        entity_type="user",
        entity_id=user.id,
        details={"email": user.email, "role": user.role.value},
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_owner), db: Session = Depends(get_db)) -> list[User]:
    return db.scalars(select(User).order_by(User.role.asc(), User.full_name.asc())).all()


@router.post("/users/{user_id}/send-invite", response_model=InviteSendOut)
def send_user_invite(
    user_id: int,
    payload: InviteSendIn,
    owner_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> InviteSendOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role != UserRole.TEACHER:
        raise HTTPException(status_code=400, detail="Invites are only supported for teacher accounts.")
    if not smtp_is_configured():
        raise HTTPException(status_code=400, detail="SMTP is not configured.")

    app_url = (payload.app_url or "").strip() or "http://127.0.0.1:8000/app"
    message = _invite_message(
        app_url=app_url,
        email=user.email,
        temporary_password=payload.temporary_password,
    )
    subject = "Teacher Platform Login Details"
    try:
        send_email(to_email=user.email, subject=subject, body_text=message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Invite email failed: {type(exc).__name__}") from exc

    log_audit(
        db,
        user=owner_user,
        action="auth.send_invite",
        entity_type="user",
        entity_id=user.id,
        details={
            "email": user.email,
            "app_url": app_url,
            "included_temporary_password": bool(payload.temporary_password),
        },
    )
    db.commit()
    return InviteSendOut(
        sent=True,
        to_email=user.email,
        app_url=app_url,
        included_temporary_password=bool(payload.temporary_password),
    )


@router.patch("/users/{user_id}/status", response_model=UserOut)
def update_user_status(
    user_id: int,
    payload: UserStatusUpdateIn,
    owner_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role == UserRole.OWNER and not payload.is_active:
        raise HTTPException(status_code=400, detail="Owner cannot be deactivated.")
    user.is_active = payload.is_active
    if payload.is_active:
        user.failed_login_attempts = 0
        user.locked_until = None
    if not payload.is_active:
        db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    log_audit(
        db,
        user=owner_user,
        action="auth.update_user_status",
        entity_type="user",
        entity_id=user.id,
        details={"is_active": payload.is_active},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/reset-password", response_model=UserOut)
def reset_user_password(
    user_id: int,
    payload: PasswordResetIn,
    owner_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role == UserRole.OWNER:
        raise HTTPException(status_code=400, detail="Use /auth/change-password for owner password changes.")
    user.password_hash = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    log_audit(
        db,
        user=owner_user,
        action="auth.reset_password",
        entity_type="user",
        entity_id=user.id,
        details=None,
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/change-password", response_model=UserOut)
def change_password(
    payload: PasswordChangeIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different.")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.failed_login_attempts = 0
    current_user.locked_until = None
    db.execute(delete(AuthToken).where(AuthToken.user_id == current_user.id))
    log_audit(
        db,
        user=current_user,
        action="auth.change_password",
        entity_type="user",
        entity_id=current_user.id,
        details=None,
    )
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/users/{user_id}/unlock", response_model=UserOut)
def unlock_user(
    user_id: int,
    owner_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    user.failed_login_attempts = 0
    user.locked_until = None
    log_audit(
        db,
        user=owner_user,
        action="auth.unlock_user",
        entity_type="user",
        entity_id=user.id,
        details=None,
    )
    db.commit()
    db.refresh(user)
    return user
