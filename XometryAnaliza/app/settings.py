import os
from pathlib import Path


DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
JOBS_DIR = DATA_DIR / "jobs"
EVENTS_PATH = DATA_DIR / "agent_events.jsonl"

OFERTARE_AUTOMATA_URL = os.getenv("OFERTARE_AUTOMATA_URL", "http://192.168.2.26:8585").rstrip("/")
OFERTARE_API_TOKEN = os.getenv("OFERTARE_API_TOKEN", "")
OFERTARE_AUTOMATA_ROOT = os.getenv(
    "OFERTARE_AUTOMATA_ROOT",
    r"C:\Users\Dorina\Desktop\Ofertare-Automata\XometryAuto",
)
OFERTARE_AUTOMATA_CONNECT_TIMEOUT = int(os.getenv("OFERTARE_AUTOMATA_CONNECT_TIMEOUT", "10"))
OFERTARE_AUTOMATA_READ_TIMEOUT = int(os.getenv("OFERTARE_AUTOMATA_READ_TIMEOUT", "600"))
OFERTARE_AUTOMATA_STALL_TIMEOUT = int(os.getenv("OFERTARE_AUTOMATA_STALL_TIMEOUT", "420"))
SHEET_AGENT_RETRY_SECONDS = int(os.getenv("SHEET_AGENT_RETRY_SECONDS", "3600"))
STALE_RUNNING_SECONDS = int(os.getenv("STALE_RUNNING_SECONDS", "300"))
AGENT_BUSY_MAX_RETRIES = int(os.getenv("AGENT_BUSY_MAX_RETRIES", "3"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://xometry-app:10000").rstrip("/")
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", os.getenv("BACKEND_URL", "http://86.123.232.23:10000")).rstrip("/")

XOMETRY_EMAIL = os.getenv("XOMETRY_EMAIL", "")
XOMETRY_PASSWORD = os.getenv("XOMETRY_PASSWORD", "")

GEO_SFTP_HOST = os.getenv("GEO_SFTP_HOST", "192.168.2.26")
GEO_SFTP_PORT = int(os.getenv("GEO_SFTP_PORT", "22"))
GEO_SFTP_USER = os.getenv("GEO_SFTP_USER", "Dorina")
GEO_SFTP_KEY_PATH = os.getenv("GEO_SFTP_KEY_PATH", "/app/data/ssh/id_ed25519")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() in ("1", "true", "yes")
TELEGRAM_SHEET_START_LOGS = os.getenv("TELEGRAM_SHEET_START_LOGS", "false").lower() in ("1", "true", "yes")
TELEGRAM_SHEET_FAILURE_LOGS = os.getenv("TELEGRAM_SHEET_FAILURE_LOGS", "false").lower() in ("1", "true", "yes")
TELEGRAM_GEO_LOGS = os.getenv("TELEGRAM_GEO_LOGS", "true").lower() in ("1", "true", "yes")
MCP_TOKEN = os.getenv("MCP_TOKEN", "")

WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
WATCHDOG_INTERVAL_SECONDS = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "300"))
WATCHDOG_XOMETRY_SESSION_MAX_AGE_SECONDS = int(os.getenv("WATCHDOG_XOMETRY_SESSION_MAX_AGE_SECONDS", "900"))
WATCHDOG_QUEUE_ACTIVE_STALE_SECONDS = int(
    os.getenv("WATCHDOG_QUEUE_ACTIVE_STALE_SECONDS", str(OFERTARE_AUTOMATA_READ_TIMEOUT + 300))
)
WATCHDOG_OFERTARE_HEALTH_TIMEOUT = int(os.getenv("WATCHDOG_OFERTARE_HEALTH_TIMEOUT", "8"))
WATCHDOG_RECENT_ERROR_SECONDS = int(os.getenv("WATCHDOG_RECENT_ERROR_SECONDS", "1800"))
WATCHDOG_TELEGRAM_ALERTS = os.getenv("WATCHDOG_TELEGRAM_ALERTS", "true").lower() in ("1", "true", "yes")

LOCAL_DOSAR_ROOT = os.getenv("LOCAL_DOSAR_ROOT", "/mnt/xLucru")
LOCAL_DOSAR_WINDOWS_ROOT = os.getenv("LOCAL_DOSAR_WINDOWS_ROOT", r"\\192.168.2.6\d\00 COTATII IN LUCRU")

HERMES_DIAGNOSTICS_ENABLED = os.getenv("HERMES_DIAGNOSTICS_ENABLED", "true").lower() in ("1", "true", "yes")
HERMES_AGENT_URL = os.getenv("HERMES_AGENT_URL", "").rstrip("/")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
HERMES_AGENT_MODEL = os.getenv("HERMES_AGENT_MODEL", "auto")
HERMES_DIAGNOSTIC_TIMEOUT_SECONDS = int(os.getenv("HERMES_DIAGNOSTIC_TIMEOUT_SECONDS", "45"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
