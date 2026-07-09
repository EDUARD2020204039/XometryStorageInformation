from __future__ import annotations

import threading
import time
from typing import Any

from .agents import process_job
from .store import append_event, load_job_state, safe_id
from . import settings


_LOCK = threading.RLock()
_WORKER: threading.Thread | None = None
SHEET_KEYWORDS = (
    "sheet",
    "sheet metal",
    "metal sheet",
    "laser",
    "laser cutting",
    "bending",
    "tabla",
    "tablÄƒ",
)


def _queue_path():
    settings.ensure_dirs()
    return settings.DATA_DIR / "agent_queue.json"


def _default_state() -> dict[str, Any]:
    return {"active": None, "queued": [], "completed": [], "seen_job_ids": []}


def _read() -> dict[str, Any]:
    path = _queue_path()
    if not path.exists():
        return _default_state()
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**_default_state(), **data}
    except Exception:
        return _default_state()


def _write(data: dict[str, Any]) -> dict[str, Any]:
    import json
    path = _queue_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _job_id(job: dict[str, Any]) -> str:
    return str(job.get("id") or job.get("job_id") or job.get("title") or job.get("offer_id") or "unknown")


def _part_process_text(part: dict[str, Any]) -> str:
    values = [
        part.get("process"),
        part.get("processType"),
        part.get("process_type"),
        part.get("material"),
        part.get("part_name"),
        part.get("name"),
    ]
    processes = part.get("processes")
    if isinstance(processes, list):
        values.extend(processes)
    elif processes:
        values.append(processes)
    return " ".join(str(value or "") for value in values).lower()


def _is_sheet_laser_job(job: dict[str, Any]) -> bool:
    for part in job.get("parts") or []:
        if isinstance(part, dict) and any(keyword in _part_process_text(part) for keyword in SHEET_KEYWORDS):
            return True

    haystack = " ".join(
        str(job.get(key) or "")
        for key in ("id", "title", "job_name", "material", "process", "remarks", "raw_text")
    ).lower()
    return any(keyword in haystack for keyword in SHEET_KEYWORDS)


def _has_ready_geo(job_id: str) -> bool:
    state = load_job_state(job_id) or {}
    sheet = state.get("sheet_metal_laser") or {}
    return any(item.get("geo_exists") is True and item.get("target_path") for item in sheet.get("geo_items") or [])


def enqueue_jobs(jobs: list[dict[str, Any]], source: str = "unknown") -> dict[str, Any]:
    now = time.time()
    added = 0
    skipped = 0
    skipped_non_sheet = 0
    skipped_cached = 0
    with _LOCK:
        data = _read()
        known = {item["job_id"] for item in data.get("queued") or []}
        active = data.get("active") or {}
        if active.get("job_id"):
            known.add(active["job_id"])
        known.update(item.get("job_id") for item in data.get("completed") or [] if item.get("job_id"))
        known.update(str(item) for item in data.get("seen_job_ids") or [])

        for job in jobs:
            job_id = _job_id(job)
            if not _is_sheet_laser_job(job):
                skipped += 1
                skipped_non_sheet += 1
                continue
            if _has_ready_geo(job_id):
                skipped += 1
                skipped_cached += 1
                continue
            if job_id in known:
                skipped += 1
                continue
            priority = int(job.get("priority") or 100)
            data["queued"].append({
                "job_id": job_id,
                "safe_id": safe_id(job_id),
                "offer_id": job.get("offer_id"),
                "title": job.get("title") or job.get("job_name") or job_id,
                "url": job.get("link") or job.get("url"),
                "source": source,
                "priority": priority,
                "status": "queued",
                "queued_ts": now,
                "job": job,
            })
            known.add(job_id)
            seen = set(str(item) for item in data.get("seen_job_ids") or [])
            seen.add(job_id)
            data["seen_job_ids"] = sorted(seen)
            added += 1

        _dedupe_queue(data)
        _sort_queue(data)
        _write(data)
    if added:
        append_event(
            "queue.enqueue",
            f"Queued {added} sheet/laser jobs from {source}",
            source=source,
            added=added,
            skipped=skipped,
            skipped_non_sheet=skipped_non_sheet,
            skipped_cached=skipped_cached,
        )
        ensure_worker()
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "skipped_non_sheet": skipped_non_sheet,
        "skipped_cached": skipped_cached,
        "queued": len(data.get("queued") or []),
    }


def _sort_queue(data: dict[str, Any]) -> None:
    data["queued"] = sorted(
        data.get("queued") or [],
        key=lambda item: (-int(item.get("priority") or 0), float(item.get("queued_ts") or 0)),
    )


def _dedupe_queue(data: dict[str, Any]) -> None:
    completed_ids = {item.get("job_id") for item in data.get("completed") or [] if item.get("job_id")}
    seen: set[str] = set()
    deduped = []
    for item in data.get("queued") or []:
        job_id = item.get("job_id")
        if not job_id or job_id in seen or job_id in completed_ids:
            continue
        seen.add(job_id)
        deduped.append(item)
    data["queued"] = deduped


def get_queue_state() -> dict[str, Any]:
    with _LOCK:
        data = _read()
        return {
            **data,
            "running": bool(data.get("active")),
            "worker_alive": bool(_WORKER and _WORKER.is_alive()),
            "queued_count": len(data.get("queued") or []),
            "completed_count": len(data.get("completed") or []),
        }


def reorder(job_ids: list[str]) -> dict[str, Any]:
    with _LOCK:
        data = _read()
        queued = data.get("queued") or []
        by_id = {item["job_id"]: item for item in queued}
        reordered = [by_id[job_id] for job_id in job_ids if job_id in by_id]
        rest = [item for item in queued if item["job_id"] not in set(job_ids)]
        data["queued"] = reordered + rest
        for index, item in enumerate(data["queued"]):
            item["manual_order"] = index
            item["priority"] = max(0, 1000 - index)
        _write(data)
    append_event("queue.reorder", "Queue reordered", job_ids=job_ids)
    return get_queue_state()


def set_priority(job_id: str, priority: int) -> dict[str, Any]:
    with _LOCK:
        data = _read()
        for item in data.get("queued") or []:
            if item["job_id"] == job_id:
                item["priority"] = int(priority)
                break
        _sort_queue(data)
        _write(data)
    append_event("queue.priority", f"Priority changed for {job_id}", job_id=job_id, priority=priority)
    return get_queue_state()


def move(job_id: str, direction: str) -> dict[str, Any]:
    with _LOCK:
        data = _read()
        queued = data.get("queued") or []
        index = next((i for i, item in enumerate(queued) if item["job_id"] == job_id), -1)
        if index >= 0:
            target = index - 1 if direction == "up" else index + 1
            target = max(0, min(target, len(queued) - 1))
            queued[index], queued[target] = queued[target], queued[index]
            data["queued"] = queued
            for order, item in enumerate(data["queued"]):
                item["priority"] = max(0, 1000 - order)
            _write(data)
    append_event("queue.move", f"Moved {job_id} {direction}", job_id=job_id, direction=direction)
    return get_queue_state()


def _pop_next() -> dict[str, Any] | None:
    with _LOCK:
        data = _read()
        if data.get("active") or not data.get("queued"):
            return None
        item = data["queued"].pop(0)
        item["status"] = "running"
        item["started_ts"] = time.time()
        data["active"] = item
        _write(data)
        return item


def _finish(item: dict[str, Any], result: dict[str, Any] | None = None, error: str | None = None) -> None:
    with _LOCK:
        data = _read()
        done = {
            **item,
            "status": "failed" if error else "done",
            "completed_ts": time.time(),
            "error": error,
            "result_status": (result or {}).get("sheet_metal_laser", {}).get("status") if result else None,
        }
        data["active"] = None
        data["completed"] = [done] + (data.get("completed") or [])[:49]
        seen = set(str(value) for value in data.get("seen_job_ids") or [])
        if item.get("job_id"):
            seen.add(str(item["job_id"]))
        data["seen_job_ids"] = sorted(seen)
        _write(data)


def _worker_loop() -> None:
    while True:
        item = _pop_next()
        if not item:
            return
        job_id = item["job_id"]
        append_event("queue.start", f"Started queued job {job_id}", job_id=job_id, offer_id=item.get("offer_id"))
        try:
            result = process_job(item["job"])
            _finish(item, result=result)
            append_event("queue.done", f"Finished queued job {job_id}", job_id=job_id, offer_id=item.get("offer_id"))
        except Exception as exc:
            _finish(item, error=f"{type(exc).__name__}: {exc}")
            append_event("queue.failed", f"Queued job failed {job_id}: {exc}", job_id=job_id, offer_id=item.get("offer_id"))


def ensure_worker() -> bool:
    global _WORKER
    with _LOCK:
        if _WORKER and _WORKER.is_alive():
            return False
        _WORKER = threading.Thread(target=_worker_loop, name="xometry-agent-queue", daemon=True)
        _WORKER.start()
        return True


def recover_and_start() -> dict[str, Any]:
    with _LOCK:
        data = _read()
        active = data.get("active")
        if active:
            active["status"] = "queued"
            active.pop("started_ts", None)
            data["queued"] = [active] + (data.get("queued") or [])
            data["active"] = None
            _write(data)
            append_event("queue.recover", f"Recovered stale active job {active.get('job_id')}", job_id=active.get("job_id"))

        seen = set(str(value) for value in data.get("seen_job_ids") or [])
        for bucket in ("queued", "completed"):
            for item in data.get(bucket) or []:
                if item.get("job_id"):
                    seen.add(str(item["job_id"]))
        data["seen_job_ids"] = sorted(seen)
        _dedupe_queue(data)
        _write(data)
        should_start = bool(data.get("queued"))

    if should_start:
        ensure_worker()
    return get_queue_state()
