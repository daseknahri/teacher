from __future__ import annotations

from email.message import EmailMessage
import smtplib

from .. import config as app_config


def smtp_is_configured() -> bool:
    return bool(app_config.SMTP_HOST and app_config.SMTP_FROM_EMAIL)


def send_email(*, to_email: str, subject: str, body_text: str) -> None:
    if not smtp_is_configured():
        raise RuntimeError("SMTP is not configured.")

    message = EmailMessage()
    message["From"] = app_config.SMTP_FROM_EMAIL
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body_text)

    if app_config.SMTP_USE_SSL:
        with smtplib.SMTP_SSL(app_config.SMTP_HOST, app_config.SMTP_PORT, timeout=30) as client:
            if app_config.SMTP_USERNAME:
                client.login(app_config.SMTP_USERNAME, app_config.SMTP_PASSWORD)
            client.send_message(message)
        return

    with smtplib.SMTP(app_config.SMTP_HOST, app_config.SMTP_PORT, timeout=30) as client:
        if app_config.SMTP_USE_STARTTLS:
            client.starttls()
        if app_config.SMTP_USERNAME:
            client.login(app_config.SMTP_USERNAME, app_config.SMTP_PASSWORD)
        client.send_message(message)
