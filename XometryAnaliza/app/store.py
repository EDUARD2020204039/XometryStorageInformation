import json
import time
from pathlib import Path
from typing import Any

from . import settings


def safe_id(value: Any) -> str:
    raw = str(value or "unknown").strip()
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)[:120] or "unknown"


def append_event(event_type: str, message: str, **data: Any) -> dict[str, Any]:
    settings.ensure_dirs()
    event = {
        "ts": time.time(),
        "type": event_type,
        "message": message,
        **data,
    }
    with settings.EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events(limit: int = 50) -> list[dict[str, Any]]:
    if not settings.EVENTS_PATH.exists():
        return []
    lines = settings.EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def job_path(job_id: str) -> Path:
    return settings.JOBS_DIR / f"{safe_id(job_id)}.json"


def save_job_state(job_id: str, state: dict[str, Any]) -> dict[str, Any]:
    settings.ensure_dirs()
    path = job_path(job_id)
    state = {**state, "job_id": job_id, "updated_ts": time.time()}
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def load_job_state(job_id: str) -> dict[str, Any] | None:
    path = job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_job_by_offer_id(offer_id: str) -> dict[str, Any] | None:
    target = str(offer_id)
    for path in settings.JOBS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        job = data.get("job") or {}
        if str(job.get("offer_id") or data.get("offer_id") or "") == target:
            return data
    return None


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    items = []
    for path in sorted(settings.JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items
