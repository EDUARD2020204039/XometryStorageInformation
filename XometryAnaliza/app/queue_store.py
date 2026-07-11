from __future__ import annotations

import threading
import time
from typing import Any

from .agents import process_job
from .ofertare_client import find_project_folder_for_job
from .store import append_event, load_job_state, safe_id, save_job_state
from . import settings


_LOCK = threading.RLock()
_WORKER: threading.Thread | None = None
POST_SAVE_DELAY_SECONDS = 120
AGENT_BUSY_RETRY_SECONDS = 120
SHEET_KEYWORDS = (
    "sheet",
    "sheet metal",
    "metal sheet",
    "laser",
    "laser cutting",
    "bending",
    "tabla",
)


def _queue_path():
    settings.ensure_dirs()
    return settings.DATA_DIR / "agent_queue.json"


def _default_state() -> dict[str, Any]:
    return {"active": None, "queued": [], "completed": [], "seen_job_ids": [], "seen_offer_ids": [], "paused_until": 0, "pause_reason": "", "paused_item": None}


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


def _offer_id(job: dict[str, Any]) -> str:
    return str(job.get("offer_id") or job.get("offerId") or "").strip()


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
    if job.get("manual"):
        return True

    parts = [part for part in job.get("parts") or [] if isinstance(part, dict)]
    if parts:
        return any(
            any(keyword in _part_process_text(part) for keyword in SHEET_KEYWORDS)
            for part in parts
        )

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


def _has_recent_attempt(job_id: str) -> bool:
    state = load_job_state(job_id) or {}
    sheet = state.get("sheet_metal_laser") or {}
    completed_ts = float(sheet.get("completed_ts") or sheet.get("started_ts") or 0)
    return bool(completed_ts and time.time() - completed_ts < settings.SHEET_AGENT_RETRY_SECONDS)


def _geo_counts(sheet: dict[str, Any]) -> tuple[int, int]:
    ready = 0
    requested = 0
    for item in sheet.get("geo_items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("target_path"):
            requested += 1
        if item.get("geo_exists") is True and item.get("target_path"):
            ready += 1
    return ready, requested


def enqueue_jobs(jobs: list[dict[str, Any]], source: str = "unknown", force: bool = False, front: bool = False) -> dict[str, Any]:
    now = time.time()
    added = 0
    skipped = 0
    skipped_non_sheet = 0
    skipped_cached = 0
    skipped_recent = 0
    skipped_active = 0
    with _LOCK:
        data = _read()
        known = {item["job_id"] for item in data.get("queued") or []}
        known_offers = {str(item.get("offer_id")) for item in data.get("queued") or [] if item.get("offer_id")}
        active = data.get("active") or {}
        if active.get("job_id"):
            known.add(active["job_id"])
        if active.get("offer_id"):
            known_offers.add(str(active["offer_id"]))
        known.update(item.get("job_id") for item in data.get("completed") or [] if item.get("job_id"))
        known_offers.update(str(item.get("offer_id")) for item in data.get("completed") or [] if item.get("offer_id"))
        known.update(str(item) for item in data.get("seen_job_ids") or [])
        known_offers.update(str(item) for item in data.get("seen_offer_ids") or [])

        for job in jobs:
            job_id = _job_id(job)
            offer_id = _offer_id(job)
            active_job_id = str(active.get("job_id") or "")
            active_offer_id = str(active.get("offer_id") or "")
            if active and (job_id == active_job_id or (offer_id and offer_id == active_offer_id)):
                skipped += 1
                skipped_active += 1
                continue
            if not _is_sheet_laser_job(job):
                skipped += 1
                skipped_non_sheet += 1
                continue
            if not force and _has_ready_geo(job_id):
                skipped += 1
                skipped_cached += 1
                continue
            if not force and _has_recent_attempt(job_id):
                skipped += 1
                skipped_recent += 1
                continue
            if force:
                data["queued"] = [
                    item for item in data.get("queued") or []
                    if item.get("job_id") != job_id and (not offer_id or str(item.get("offer_id") or "") != offer_id)
                ]
            elif job_id in known or (offer_id and offer_id in known_offers):
                skipped += 1
                continue
            priority = len(data.get("queued") or []) + added + 1
            item = {
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
                "force": force,
            }
            if front:
                data["queued"].insert(added, item)
            else:
                data["queued"].append(item)
            known.add(job_id)
            if offer_id:
                known_offers.add(offer_id)
            seen = set(str(item) for item in data.get("seen_job_ids") or [])
            seen.add(job_id)
            data["seen_job_ids"] = sorted(seen)
            if offer_id:
                seen_offers = set(str(item) for item in data.get("seen_offer_ids") or [])
                seen_offers.add(offer_id)
                data["seen_offer_ids"] = sorted(seen_offers)
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
            skipped_recent=skipped_recent,
            skipped_active=skipped_active,
            force=force,
            front=front,
        )
        ensure_worker()
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "skipped_non_sheet": skipped_non_sheet,
        "skipped_cached": skipped_cached,
        "skipped_recent": skipped_recent,
        "skipped_active": skipped_active,
        "force": force,
        "front": front,
        "queued": len(data.get("queued") or []),
    }


def _sort_queue(data: dict[str, Any]) -> None:
    data["queued"] = sorted(
        data.get("queued") or [],
        key=lambda item: (float(item.get("available_after") or 0), int(item.get("priority") or 999999), float(item.get("queued_ts") or 0)),
    )
    _renumber_queue(data)


def _renumber_queue(data: dict[str, Any]) -> None:
    for index, item in enumerate(data.get("queued") or []):
        item["priority"] = index + 1
        item["manual_order"] = index


def _dedupe_queue(data: dict[str, Any]) -> None:
    completed_ids = {item.get("job_id") for item in data.get("completed") or [] if item.get("job_id")}
    completed_offers = {str(item.get("offer_id")) for item in data.get("completed") or [] if item.get("offer_id")}
    seen: set[str] = set()
    seen_offers: set[str] = set()
    deduped = []
    for item in data.get("queued") or []:
        job_id = item.get("job_id")
        offer_id = str(item.get("offer_id") or "")
        forced = bool(item.get("force"))
        if not job_id or job_id in seen or (not forced and job_id in completed_ids):
            continue
        if offer_id and (offer_id in seen_offers or (not forced and offer_id in completed_offers)):
            continue
        seen.add(job_id)
        if offer_id:
            seen_offers.add(offer_id)
        deduped.append(item)
    data["queued"] = deduped


def _item_with_state(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    enriched = dict(item)
    state = load_job_state(str(item.get("job_id") or "")) or {}
    sheet = state.get("sheet_metal_laser") or {}
    result = sheet.get("ofertare_result") or {}
    project_root = result.get("projectRoot") or result.get("project_root")
    if not project_root and str(sheet.get("status") or "").lower() == "running":
        found = find_project_folder_for_job(str(item.get("job_id") or ""))
        if found and found.get("path"):
            project_root = found.get("path")
            sheet = {
                **sheet,
                "ofertare_result": {
                    **result,
                    "projectRoot": project_root,
                    "projectName": found.get("name"),
                    "discoveredWhileRunning": True,
                },
            }
            state["sheet_metal_laser"] = sheet
            save_job_state(str(item.get("job_id") or ""), state)
    if project_root:
        enriched["project_root"] = project_root
        enriched["project_name"] = str(project_root).replace("\\", "/").rstrip("/").split("/")[-1]
    enriched["agent_status"] = sheet.get("status")
    ready_count, requested_count = _geo_counts(sheet)
    started_ts = float(sheet.get("started_ts") or item.get("started_ts") or 0)
    completed_ts = float(sheet.get("completed_ts") or 0)
    enriched["identified_parts_count"] = int(sheet.get("identified_parts_count") or 0)
    enriched["processed_parts_count"] = int(sheet.get("processed_parts_count") or ready_count)
    enriched["geo_ready_count"] = int(sheet.get("geo_ready_count") or ready_count)
    enriched["geo_requested_count"] = int(sheet.get("geo_requested_count") or requested_count)
    enriched["analysis_started_ts"] = started_ts
    enriched["analysis_completed_ts"] = completed_ts
    enriched["analysis_elapsed_seconds"] = max(0, (completed_ts or time.time()) - started_ts) if started_ts else 0
    enriched["process_duration_seconds"] = float(sheet.get("process_duration_seconds") or 0)
    return enriched


def get_queue_state() -> dict[str, Any]:
    with _LOCK:
        data = _read()
        paused_item = data.get("paused_item")
        if not paused_item and float(data.get("paused_until") or 0) > time.time():
            reason = str(data.get("pause_reason") or "")
            paused_item = next((item for item in data.get("queued") or [] if item.get("job_id") and item.get("job_id") in reason), None)
        return {
            **data,
            "active": _item_with_state(data.get("active")),
            "paused_item": _item_with_state(paused_item),
            "running": bool(data.get("active")),
            "worker_alive": bool(_WORKER and _WORKER.is_alive()),
            "queued_count": len(data.get("queued") or []),
            "completed_count": len(data.get("completed") or []),
            "paused": float(data.get("paused_until") or 0) > time.time(),
        }


def reorder(job_ids: list[str]) -> dict[str, Any]:
    with _LOCK:
        data = _read()
        queued = data.get("queued") or []
        by_id = {item["job_id"]: item for item in queued}
        reordered = [by_id[job_id] for job_id in job_ids if job_id in by_id]
        rest = [item for item in queued if item["job_id"] not in set(job_ids)]
        data["queued"] = reordered + rest
        _renumber_queue(data)
        _write(data)
    append_event("queue.reorder", "Queue reordered", job_ids=job_ids)
    return get_queue_state()


def set_priority(job_id: str, priority: int) -> dict[str, Any]:
    with _LOCK:
        data = _read()
        queued = data.get("queued") or []
        index = next((i for i, item in enumerate(queued) if item["job_id"] == job_id), -1)
        if index >= 0:
            item = queued.pop(index)
            target = max(0, min(int(priority) - 1, len(queued)))
            queued.insert(target, item)
            data["queued"] = queued
            _renumber_queue(data)
        _write(data)
    append_event("queue.position", f"Queue position changed for {job_id}", job_id=job_id, position=priority)
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
            _renumber_queue(data)
            _write(data)
    append_event("queue.move", f"Moved {job_id} {direction}", job_id=job_id, direction=direction)
    return get_queue_state()


def _pop_next() -> dict[str, Any] | None:
    with _LOCK:
        data = _read()
        if data.get("active") or not data.get("queued"):
            return None
        if float(data.get("paused_until") or 0) > time.time():
            return None
        _sort_queue(data)
        if float((data["queued"][0] or {}).get("available_after") or 0) > time.time():
            _write(data)
            return None
        item = data["queued"].pop(0)
        item["status"] = "running"
        item["started_ts"] = time.time()
        data["active"] = item
        data["paused_item"] = None
        _write(data)
        return item


def _sheet_status(result: dict[str, Any] | None) -> str | None:
    return (result or {}).get("sheet_metal_laser", {}).get("status") if result else None


def _process_seconds(item: dict[str, Any]) -> float:
    started = float(item.get("started_ts") or 0)
    return max(0, time.time() - started) if started else 0


def _pause_remaining() -> float:
    with _LOCK:
        data = _read()
        if data.get("active") or not data.get("queued"):
            return 0
        return max(0, float(data.get("paused_until") or 0) - time.time())


def _finish(item: dict[str, Any], result: dict[str, Any] | None = None, error: str | None = None) -> int:
    with _LOCK:
        data = _read()
        status = _sheet_status(result)
        process_seconds = _process_seconds(item)
        if process_seconds:
            data["last_process_seconds"] = process_seconds
        if status == "agent_busy":
            retry_seconds = AGENT_BUSY_RETRY_SECONDS
            item["status"] = "queued"
            item["available_after"] = time.time() + retry_seconds
            item["busy_retries"] = int(item.get("busy_retries") or 0) + 1
            data["active"] = None
            data["paused_until"] = item["available_after"]
            data["pause_reason"] = f"TecZone Dorina ocupat; reincerc {item.get('job_id')} dupa pauza calculata"
            data["paused_item"] = dict(item)
            data["queued"] = [item] + (data.get("queued") or [])
            _sort_queue(data)
            _write(data)
            return retry_seconds

        done = {
            **item,
            "status": "failed" if error else "done",
            "completed_ts": time.time(),
            "error": error,
            "result_status": status,
            "process_seconds": process_seconds,
        }
        data["active"] = None
        cooldown_seconds = POST_SAVE_DELAY_SECONDS if status == "geo_ready" and not error else 0
        if cooldown_seconds and data.get("queued"):
            data["paused_until"] = time.time() + cooldown_seconds
            data["pause_reason"] = f"Pauza 2 minute dupa salvarea GEO pentru {item.get('job_id')}"
            data["paused_item"] = dict(item)
        else:
            data["pause_reason"] = ""
            data["paused_until"] = 0
            data["paused_item"] = None
        data["completed"] = [done] + (data.get("completed") or [])[:49]
        seen = set(str(value) for value in data.get("seen_job_ids") or [])
        if item.get("job_id"):
            seen.add(str(item["job_id"]))
        data["seen_job_ids"] = sorted(seen)
        seen_offers = set(str(value) for value in data.get("seen_offer_ids") or [])
        if item.get("offer_id"):
            seen_offers.add(str(item["offer_id"]))
        data["seen_offer_ids"] = sorted(seen_offers)
        _write(data)
        return cooldown_seconds


def _worker_loop() -> None:
    while True:
        item = _pop_next()
        if not item:
            pause_seconds = _pause_remaining()
            if pause_seconds:
                time.sleep(pause_seconds)
                continue
            return
        job_id = item["job_id"]
        append_event("queue.start", f"Started queued job {job_id}", job_id=job_id, offer_id=item.get("offer_id"))
        try:
            result = process_job(item["job"])
            delay_seconds = _finish(item, result=result)
            if _sheet_status(result) == "agent_busy":
                append_event("queue.agent_busy", f"TecZone busy; paused queue for {job_id}", job_id=job_id, offer_id=item.get("offer_id"), retry_seconds=delay_seconds)
                time.sleep(delay_seconds)
                continue
            append_event("queue.done", f"Finished queued job {job_id}", job_id=job_id, offer_id=item.get("offer_id"))
            if delay_seconds:
                append_event("queue.cooldown", f"Paused queue after {job_id} for {delay_seconds}s", job_id=job_id, offer_id=item.get("offer_id"), retry_seconds=delay_seconds)
                time.sleep(delay_seconds)
                continue
        except Exception as exc:
            _finish(item, error=f"{type(exc).__name__}: {exc}")
            append_event("queue.failed", f"Queued job failed {job_id}: {exc}", job_id=job_id, offer_id=item.get("offer_id"))

        pause_seconds = _pause_remaining()
        if pause_seconds:
            time.sleep(pause_seconds)


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
        seen_offers = set(str(value) for value in data.get("seen_offer_ids") or [])
        for bucket in ("queued", "completed"):
            for item in data.get(bucket) or []:
                if item.get("job_id"):
                    seen.add(str(item["job_id"]))
                if item.get("offer_id"):
                    seen_offers.add(str(item["offer_id"]))
        data["seen_job_ids"] = sorted(seen)
        data["seen_offer_ids"] = sorted(seen_offers)
        _dedupe_queue(data)
        _sort_queue(data)
        _write(data)
        should_start = bool(data.get("queued"))

    if should_start:
        ensure_worker()
    return get_queue_state()
