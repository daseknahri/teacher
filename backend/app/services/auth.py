from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets

from sqlalchemy.orm import Session

from ..config import AUTH_TOKEN_TTL_HOURS
from ..models import AuthToken, User


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", maxsplit=1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return hmac.compare_digest(candidate, digest)


def create_access_token(db: Session, user: User) -> AuthToken:
    token_value = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=AUTH_TOKEN_TTL_HOURS)
    token = AuthToken(user_id=user.id, token=token_value, expires_at=expires_at)
    db.add(token)
    db.commit()
    db.refresh(token)
    return token

