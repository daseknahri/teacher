from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging

import httpx

from .. import config as app_config
from .mailer import send_email, smtp_is_configured


logger = logging.getLogger("teacher_progress.alerts")
_last_alert_sent: dict[str, datetime] = {}


def alerting_enabled() -> bool:
    return bool(app_config.ALERT_WEBHOOK_URL or app_config.ALERT_EMAIL_TO)


def _alert_key(*, kind: str, method: str, path: str, status_code: int | None) -> str:
    return f"{kind}|{method}|{path}|{status_code if status_code is not None else '-'}"


def _should_send_alert(key: str, now: datetime | None = None) -> bool:
    at = now or datetime.now(UTC).replace(tzinfo=None)
    previous = _last_alert_sent.get(key)
    if previous is not None:
        wait = timedelta(seconds=app_config.ALERT_MIN_INTERVAL_SECONDS)
        if at - previous < wait:
            return False
    _last_alert_sent[key] = at
    return True


def reset_alert_state() -> None:
    _last_alert_sent.clear()


def _format_alert_subject(kind: str, method: str, path: str, status_code: int | None) -> str:
    code = str(status_code) if status_code is not None else "exception"
    return f"[TeacherProgress] {kind.upper()} {code} {method} {path}"


def _format_alert_body(payload: dict) -> str:
    return (
        f"kind: {payload.get('kind')}\n"
        f"time: {payload.get('utc_now')}\n"
        f"method: {payload.get('method')}\n"
        f"path: {payload.get('path')}\n"
        f"status_code: {payload.get('status_code')}\n"
        f"duration_ms: {payload.get('duration_ms')}\n"
        f"error: {payload.get('error')}\n"
    )


async def _send_webhook(payload: dict) -> None:
    if not app_config.ALERT_WEBHOOK_URL:
        return
    async with httpx.AsyncClient(timeout=app_config.ALERT_TIMEOUT_SECONDS) as client:
        response = await client.post(app_config.ALERT_WEBHOOK_URL, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"webhook_error_status={response.status_code}")


async def _send_email(payload: dict) -> None:
    if not app_config.ALERT_EMAIL_TO:
        return
    if not smtp_is_configured():
        raise RuntimeError("smtp_not_configured_for_alert_email")
    subject = _format_alert_subject(
        str(payload.get("kind") or "alert"),
        str(payload.get("method") or "-"),
        str(payload.get("path") or "-"),
        int(payload["status_code"]) if payload.get("status_code") is not None else None,
    )
    body = _format_alert_body(payload)
    await asyncio.to_thread(send_email, to_email=app_config.ALERT_EMAIL_TO, subject=subject, body_text=body)


async def send_request_alert(
    *,
    kind: str,
    method: str,
    path: str,
    status_code: int | None,
    duration_ms: float | None,
    error: str | None = None,
) -> None:
    if not alerting_enabled():
        return
    key = _alert_key(kind=kind, method=method, path=path, status_code=status_code)
    if not _should_send_alert(key):
        logger.info("alert.throttled", extra={"kind": kind, "method": method, "path": path, "status_code": status_code})
        return
    payload = {
        "kind": kind,
        "utc_now": datetime.now(UTC).isoformat(),
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "error": error,
    }
    try:
        await _send_webhook(payload)
    except Exception as exc:
        logger.warning("alert.webhook_failed", extra={"error": str(exc), "path": path, "kind": kind})
    try:
        await _send_email(payload)
    except Exception as exc:
        logger.warning("alert.email_failed", extra={"error": str(exc), "path": path, "kind": kind})
    logger.warning("alert.sent", extra={"kind": kind, "method": method, "path": path, "status_code": status_code})
