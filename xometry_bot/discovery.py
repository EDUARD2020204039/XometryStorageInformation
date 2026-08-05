import json
import os
from datetime import datetime, timezone


REGISTRY_VERSION = 1


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _job_key(job):
    offer_id = str(job.get("offer_id") or "").strip()
    if offer_id:
        return f"offer:{offer_id}"
    job_id = str(job.get("id") or job.get("job_id") or "").strip()
    return f"job:{job_id}" if job_id else ""


def _load_registry(path):
    if not os.path.exists(path):
        return {"version": REGISTRY_VERSION, "jobs": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
            raise ValueError("invalid discovery registry")
        return data
    except Exception:
        return {"version": REGISTRY_VERSION, "jobs": {}}


def _save_registry(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary_path = f"{path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary_path, path)


def stamp_discovered_jobs(jobs, registry_path, detected_at=None):
    """Attach immutable first-seen and current last-seen timestamps to scraped jobs."""
    now = detected_at or _utc_now_iso()
    registry = _load_registry(registry_path)
    records = registry.setdefault("jobs", {})
    new_count = 0

    for job in jobs:
        key = _job_key(job)
        if not key:
            continue
        record = records.get(key)
        if not isinstance(record, dict):
            record = {
                "first_seen_at": now,
                "seen_count": 0,
            }
            records[key] = record
            new_count += 1

        record["last_seen_at"] = now
        record["seen_count"] = int(record.get("seen_count") or 0) + 1
        record["job_id"] = str(job.get("id") or job.get("job_id") or "")
        record["offer_id"] = str(job.get("offer_id") or "")

        job["first_seen_at"] = record["first_seen_at"]
        job["last_seen_at"] = record["last_seen_at"]
        job["seen_count"] = record["seen_count"]

    registry["version"] = REGISTRY_VERSION
    registry["updated_at"] = now
    _save_registry(registry_path, registry)
    return new_count, now
