from __future__ import annotations

from datetime import UTC, datetime
import json
from importlib.util import find_spec
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from ..config import (
    ALERT_EMAIL_TO,
    ALERT_MIN_INTERVAL_SECONDS,
    ALERT_ON_5XX,
    ALERT_ON_EXCEPTION,
    ALERT_SLOW_MS,
    ALERT_WEBHOOK_URL,
    DATABASE_URL,
    EXPORTS_DIR,
    LOGIN_LOCKOUT_MINUTES,
    LOGS_DIR,
    MAX_FAILED_LOGIN_ATTEMPTS,
    NOTEBOOKLM_AUTH_PATH,
    NOTEBOOKLM_HOME,
    NOTEBOOKLM_KEEPALIVE_SECONDS,
    NOTEBOOKLM_PROFILE,
    NOTEBOOKLM_TIMEOUT_SECONDS,
    STORAGE_DIR,
    UPLOADS_DIR,
)
from ..models import User
from ..security import require_owner
from ..services.workflow_generation import notebooklm_smoke_test


router = APIRouter(prefix="/ops", tags=["ops"])


def _safe_dir_stats(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "files": 0, "bytes": 0}
    files = 0
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            files += 1
            try:
                total += file_path.stat().st_size
            except OSError:
                pass
    return {"path": str(path), "exists": True, "files": files, "bytes": total}


def _resolve_notebooklm_home() -> Path:
    if NOTEBOOKLM_HOME:
        return Path(NOTEBOOKLM_HOME).expanduser()
    return Path.home() / ".notebooklm"


def _resolve_notebooklm_storage_path() -> Path:
    if NOTEBOOKLM_AUTH_PATH:
        return Path(NOTEBOOKLM_AUTH_PATH).expanduser()
    profile = NOTEBOOKLM_PROFILE or "default"
    home_dir = _resolve_notebooklm_home()
    profile_path = home_dir / "profiles" / profile / "storage_state.json"
    legacy_path = home_dir / "storage_state.json"
    if profile == "default" and legacy_path.exists() and not profile_path.exists():
        return legacy_path
    return profile_path


def _resolve_notebooklm_context_path() -> Path:
    profile = NOTEBOOKLM_PROFILE or "default"
    home_dir = _resolve_notebooklm_home()
    profile_path = home_dir / "profiles" / profile / "context.json"
    legacy_path = home_dir / "context.json"
    if profile == "default" and legacy_path.exists() and not profile_path.exists():
        return legacy_path
    return profile_path


def _notebooklm_status_payload() -> dict:
    home_dir = _resolve_notebooklm_home()
    storage_path = _resolve_notebooklm_storage_path()
    context_path = _resolve_notebooklm_context_path()
    package_installed = find_spec("notebooklm") is not None

    storage_valid = False
    storage_error = None
    cookies_count = 0
    if storage_path.exists():
        try:
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
            cookies = payload.get("cookies") if isinstance(payload, dict) else None
            origins = payload.get("origins") if isinstance(payload, dict) else None
            cookies_count = len(cookies) if isinstance(cookies, list) else 0
            storage_valid = isinstance(cookies, list) and isinstance(origins, list)
        except Exception as exc:
            storage_error = f"{exc.__class__.__name__}: {exc}"

    context_present = context_path.exists()
    context_notebook_id = None
    if context_present:
        try:
            payload = json.loads(context_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                raw = payload.get("notebook_id") or payload.get("current_notebook_id")
                context_notebook_id = str(raw).strip() if raw else None
        except Exception:
            context_notebook_id = None

    ready = bool(package_installed and storage_path.exists() and storage_valid)
    return {
        "installed": bool(package_installed),
        "ready": ready,
        "profile": NOTEBOOKLM_PROFILE or "default",
        "home_dir": str(home_dir),
        "auth_path": str(storage_path),
        "auth_file_exists": storage_path.exists(),
        "auth_file_valid": storage_valid,
        "auth_file_error": storage_error,
        "cookies_count": cookies_count,
        "context_path": str(context_path),
        "context_file_exists": context_present,
        "context_notebook_id": context_notebook_id,
        "timeout_seconds": NOTEBOOKLM_TIMEOUT_SECONDS,
        "keepalive_seconds": NOTEBOOKLM_KEEPALIVE_SECONDS,
    }


@router.get("/status")
def ops_status(
    request: Request,
    _: User = Depends(require_owner),
) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    started_at = getattr(request.app.state, "started_at", None)
    uptime_seconds = None
    if isinstance(started_at, datetime):
        uptime_seconds = max(0, int((now - started_at).total_seconds()))

    backups_dir = STORAGE_DIR / "backups"
    backups = sorted(backups_dir.glob("*.sql"), key=lambda p: p.stat().st_mtime, reverse=True) if backups_dir.exists() else []
    latest_backup = backups[0] if backups else None

    db_scheme = DATABASE_URL.split("://", maxsplit=1)[0] if "://" in DATABASE_URL else DATABASE_URL
    return {
        "status": "ok",
        "utc_now": now.isoformat(),
        "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
        "uptime_seconds": uptime_seconds,
        "database_scheme": db_scheme,
        "storage": {
            "root": _safe_dir_stats(STORAGE_DIR),
            "uploads": _safe_dir_stats(UPLOADS_DIR),
            "exports": _safe_dir_stats(EXPORTS_DIR),
            "logs": _safe_dir_stats(LOGS_DIR),
        },
        "backups": {
            "directory": str(backups_dir),
            "count": len(backups),
            "latest_file": latest_backup.name if latest_backup else None,
            "latest_mtime": datetime.fromtimestamp(latest_backup.stat().st_mtime, UTC).isoformat()
            if latest_backup
            else None,
            "latest_size_bytes": latest_backup.stat().st_size if latest_backup else None,
        },
        "alerts": {
            "enabled": bool(ALERT_WEBHOOK_URL or ALERT_EMAIL_TO),
            "webhook_configured": bool(ALERT_WEBHOOK_URL),
            "email_configured": bool(ALERT_EMAIL_TO),
            "on_5xx": bool(ALERT_ON_5XX),
            "on_exception": bool(ALERT_ON_EXCEPTION),
            "slow_ms": ALERT_SLOW_MS,
            "min_interval_seconds": ALERT_MIN_INTERVAL_SECONDS,
        },
        "security": {
            "max_failed_login_attempts": MAX_FAILED_LOGIN_ATTEMPTS,
            "login_lockout_minutes": LOGIN_LOCKOUT_MINUTES,
        },
    }


@router.get("/notebooklm/status")
def notebooklm_status(_: User = Depends(require_owner)) -> dict:
    return _notebooklm_status_payload()


@router.post("/notebooklm/smoke-test")
def notebooklm_smoke_test_endpoint(_: User = Depends(require_owner)) -> dict:
    status_payload = _notebooklm_status_payload()
    smoke = notebooklm_smoke_test()
    return {
        "ready": bool(status_payload.get("ready")),
        "status": status_payload,
        "smoke": smoke,
    }


@router.post("/notebooklm/auth/upload")
async def upload_notebooklm_auth_file(
    file: UploadFile = File(...),
    _: User = Depends(require_owner),
) -> dict:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Auth file is required.")
    try:
        raw = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to read auth file: {exc}") from exc
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded auth file is empty.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Auth file is not valid JSON: {exc}") from exc
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    origins = payload.get("origins") if isinstance(payload, dict) else None
    if not isinstance(cookies, list) or not isinstance(origins, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth file must contain Playwright storage_state JSON with cookies and origins arrays.",
        )

    storage_path = _resolve_notebooklm_storage_path()
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if storage_path.exists() and storage_path.is_file():
        try:
            if storage_path.parent.exists():
                storage_path.parent.chmod(0o700)
            storage_path.chmod(0o600)
        except Exception:
            pass
    return _notebooklm_status_payload()


@router.post("/notebooklm/auth/clear")
def clear_notebooklm_auth_file(_: User = Depends(require_owner)) -> dict:
    storage_path = _resolve_notebooklm_storage_path()
    context_path = _resolve_notebooklm_context_path()
    for path in (storage_path, context_path):
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except Exception:
            pass
    return _notebooklm_status_payload()
