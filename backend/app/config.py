from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "storage"))
UPLOADS_DIR = STORAGE_DIR / "uploads"
EXPORTS_DIR = STORAGE_DIR / "exports"
LOGS_DIR = STORAGE_DIR / "logs"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
AUTH_TOKEN_TTL_HOURS = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "24"))
MAX_FAILED_LOGIN_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "7"))
LOG_JSON = _env_bool("LOG_JSON", True)
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "").strip()
ALERT_ON_5XX = _env_bool("ALERT_ON_5XX", True)
ALERT_ON_EXCEPTION = _env_bool("ALERT_ON_EXCEPTION", True)
ALERT_SLOW_MS = int(os.getenv("ALERT_SLOW_MS", "2500"))
ALERT_MIN_INTERVAL_SECONDS = int(os.getenv("ALERT_MIN_INTERVAL_SECONDS", "300"))
ALERT_TIMEOUT_SECONDS = int(os.getenv("ALERT_TIMEOUT_SECONDS", "10"))

MAX_EXCEL_UPLOAD_BYTES = int(os.getenv("MAX_EXCEL_UPLOAD_BYTES", str(5 * 1024 * 1024)))
MAX_SCREENSHOT_UPLOAD_BYTES = int(os.getenv("MAX_SCREENSHOT_UPLOAD_BYTES", str(10 * 1024 * 1024)))
UPLOAD_RATE_LIMIT_COUNT = int(os.getenv("UPLOAD_RATE_LIMIT_COUNT", "10"))
UPLOAD_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("UPLOAD_RATE_LIMIT_WINDOW_SECONDS", "60"))
EXPORT_RATE_LIMIT_COUNT = int(os.getenv("EXPORT_RATE_LIMIT_COUNT", "20"))
EXPORT_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("EXPORT_RATE_LIMIT_WINDOW_SECONDS", "60"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
OCR_LANG = os.getenv("OCR_LANG", "fra+eng").strip() or "fra+eng"
UNIT_PLANNER_PROVIDER = os.getenv("UNIT_PLANNER_PROVIDER", "openai").strip().lower() or "openai"
SESSION_WRITER_PROVIDER = os.getenv("SESSION_WRITER_PROVIDER", "fallback").strip().lower() or "fallback"
NOTEBOOKLM_HOME = os.getenv("NOTEBOOKLM_HOME", "").strip()
NOTEBOOKLM_AUTH_PATH = os.getenv("NOTEBOOKLM_AUTH_PATH", "").strip()
NOTEBOOKLM_PROFILE = os.getenv("NOTEBOOKLM_PROFILE", "").strip() or None
NOTEBOOKLM_TIMEOUT_SECONDS = int(os.getenv("NOTEBOOKLM_TIMEOUT_SECONDS", "45"))
NOTEBOOKLM_KEEPALIVE_SECONDS = int(os.getenv("NOTEBOOKLM_KEEPALIVE_SECONDS", "0"))
NOTEBOOKLM_NOTEBOOK_PREFIX = os.getenv("NOTEBOOKLM_NOTEBOOK_PREFIX", "Teacher Progress - ").strip()


SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
SMTP_USE_SSL = _env_bool("SMTP_USE_SSL", False)
SMTP_USE_STARTTLS = _env_bool("SMTP_USE_STARTTLS", True)
