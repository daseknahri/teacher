"""Retention policy + cleanup for stored artifacts (uploads, exports, logs).

Each category has a configurable max age in days (0 disables it). Cleanup deletes the
on-disk file and, for DB-tracked artifacts, the owning row. Everything is reported back so
the action is auditable, and a dry run can preview what would be removed without touching
anything. File deletions are constrained to the configured storage directories as a guard
against path traversal from stored paths.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config as app_config
from ..models import ExportArtifact, SessionUpload


def _utcnow_naive() -> datetime:
    from datetime import UTC

    return datetime.now(UTC).replace(tzinfo=None)


def _resolve_within(base_dir: Path, raw_path: str) -> Path | None:
    """Resolve a stored path and confirm it lives under base_dir; else None."""
    if not raw_path:
        return None
    try:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        resolved = candidate.resolve()
        base = base_dir.resolve()
        if resolved == base or base in resolved.parents:
            return resolved
    except (OSError, ValueError):
        return None
    return None


def _delete_file(path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    try:
        size = path.stat().st_size
        path.unlink()
        return int(size)
    except OSError:
        return 0


def _cleanup_db_artifacts(
    db: Session,
    *,
    model,
    base_dir: Path,
    cutoff: datetime,
    dry_run: bool,
) -> dict:
    rows = db.scalars(select(model).where(model.created_at < cutoff)).all()
    deleted = 0
    freed_bytes = 0
    for row in rows:
        resolved = _resolve_within(base_dir, str(getattr(row, "file_path", "") or ""))
        if dry_run:
            if resolved is not None and resolved.is_file():
                try:
                    freed_bytes += int(resolved.stat().st_size)
                except OSError:
                    pass
            deleted += 1
            continue
        freed_bytes += _delete_file(resolved)
        db.delete(row)
        deleted += 1
    return {"deleted": deleted, "freed_bytes": freed_bytes}


def _cleanup_log_files(*, base_dir: Path, cutoff: datetime, dry_run: bool) -> dict:
    deleted = 0
    freed_bytes = 0
    if not base_dir.exists():
        return {"deleted": 0, "freed_bytes": 0}
    cutoff_ts = cutoff.timestamp()
    for entry in base_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime >= cutoff_ts:
                continue
        except OSError:
            continue
        if dry_run:
            try:
                freed_bytes += int(entry.stat().st_size)
            except OSError:
                pass
            deleted += 1
            continue
        freed_bytes += _delete_file(entry)
        deleted += 1
    return {"deleted": deleted, "freed_bytes": freed_bytes}


def _category(name: str, days: int, *, enabled: bool) -> dict:
    return {"category": name, "retention_days": int(days), "enabled": bool(enabled)}


def run_retention_cleanup(db: Session, *, dry_run: bool = False, now: datetime | None = None) -> dict:
    """Delete artifacts older than the configured retention window. Returns a per-category report."""
    now = now or _utcnow_naive()
    uploads_days = int(app_config.RETENTION_UPLOADS_DAYS)
    exports_days = int(app_config.RETENTION_EXPORTS_DAYS)
    logs_days = int(app_config.RETENTION_LOGS_DAYS)

    report: dict = {"dry_run": bool(dry_run), "ran_at": now.isoformat(), "categories": {}}

    if uploads_days > 0:
        res = _cleanup_db_artifacts(
            db, model=SessionUpload, base_dir=app_config.UPLOADS_DIR, cutoff=now - timedelta(days=uploads_days), dry_run=dry_run
        )
        report["categories"]["uploads"] = {**_category("uploads", uploads_days, enabled=True), **res}
    else:
        report["categories"]["uploads"] = _category("uploads", uploads_days, enabled=False)

    if exports_days > 0:
        res = _cleanup_db_artifacts(
            db, model=ExportArtifact, base_dir=app_config.EXPORTS_DIR, cutoff=now - timedelta(days=exports_days), dry_run=dry_run
        )
        report["categories"]["exports"] = {**_category("exports", exports_days, enabled=True), **res}
    else:
        report["categories"]["exports"] = _category("exports", exports_days, enabled=False)

    if logs_days > 0:
        res = _cleanup_log_files(base_dir=app_config.LOGS_DIR, cutoff=now - timedelta(days=logs_days), dry_run=dry_run)
        report["categories"]["logs"] = {**_category("logs", logs_days, enabled=True), **res}
    else:
        report["categories"]["logs"] = _category("logs", logs_days, enabled=False)

    if not dry_run:
        db.commit()

    report["total_deleted"] = sum(int(c.get("deleted", 0)) for c in report["categories"].values())
    report["total_freed_bytes"] = sum(int(c.get("freed_bytes", 0)) for c in report["categories"].values())
    return report


def _dir_usage(base_dir: Path) -> dict:
    file_count = 0
    total_bytes = 0
    if base_dir.exists():
        for entry in base_dir.rglob("*"):
            if entry.is_file():
                file_count += 1
                try:
                    total_bytes += int(entry.stat().st_size)
                except OSError:
                    pass
    return {"file_count": file_count, "total_bytes": total_bytes}


def get_retention_status(db: Session) -> dict:
    """Current retention configuration plus current storage usage per category."""
    return {
        "policy": {
            "uploads_days": int(app_config.RETENTION_UPLOADS_DAYS),
            "exports_days": int(app_config.RETENTION_EXPORTS_DAYS),
            "logs_days": int(app_config.RETENTION_LOGS_DAYS),
            "run_on_startup": bool(app_config.RETENTION_RUN_ON_STARTUP),
        },
        "usage": {
            "uploads": _dir_usage(app_config.UPLOADS_DIR),
            "exports": _dir_usage(app_config.EXPORTS_DIR),
            "logs": _dir_usage(app_config.LOGS_DIR),
        },
    }
