import os
from pathlib import Path


DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
JOBS_DIR = DATA_DIR / "jobs"
EVENTS_PATH = DATA_DIR / "agent_events.jsonl"

OFERTARE_AUTOMATA_URL = os.getenv("OFERTARE_AUTOMATA_URL", "http://192.168.2.26:8585").rstrip("/")
OFERTARE_AUTOMATA_ROOT = os.getenv("OFERTARE_AUTOMATA_ROOT", r"X:\\")
OFERTARE_AUTOMATA_CONNECT_TIMEOUT = int(os.getenv("OFERTARE_AUTOMATA_CONNECT_TIMEOUT", "10"))
OFERTARE_AUTOMATA_READ_TIMEOUT = int(os.getenv("OFERTARE_AUTOMATA_READ_TIMEOUT", "1800"))
SHEET_AGENT_RETRY_SECONDS = int(os.getenv("SHEET_AGENT_RETRY_SECONDS", "3600"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() in ("1", "true", "yes")
TELEGRAM_SHEET_START_LOGS = os.getenv("TELEGRAM_SHEET_START_LOGS", "false").lower() in ("1", "true", "yes")
TELEGRAM_SHEET_FAILURE_LOGS = os.getenv("TELEGRAM_SHEET_FAILURE_LOGS", "false").lower() in ("1", "true", "yes")
TELEGRAM_GEO_LOGS = os.getenv("TELEGRAM_GEO_LOGS", "true").lower() in ("1", "true", "yes")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
