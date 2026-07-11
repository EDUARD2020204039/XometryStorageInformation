from __future__ import annotations

import time
from collections import Counter
from typing import Any

from . import queue_store
from .store import list_jobs, read_events


def _sheet(state: dict[str, Any]) -> dict[str, Any]:
    sheet = state.get("sheet_metal_laser")
    return sheet if isinstance(sheet, dict) else {}


def _job(state: dict[str, Any]) -> dict[str, Any]:
    job = state.get("job")
    return job if isinstance(job, dict) else {}


def _job_id(state: dict[str, Any]) -> str:
    job = _job(state)
    return str(state.get("job_id") or job.get("id") or job.get("job_id") or "").strip()


def _offer_id(state: dict[str, Any]) -> str:
    job = _job(state)
    return str(state.get("offer_id") or job.get("offer_id") or "").strip()


def _status(state: dict[str, Any]) -> str:
    sheet = _sheet(state)
    status = str(sheet.get("status") or state.get("status") or "unknown").strip().lower()
    return status or "unknown"


def _geo_counts(state: dict[str, Any]) -> tuple[int, int]:
    geo_items = _sheet(state).get("geo_items") or []
    requested = 0
    ready = 0
    for item in geo_items:
        if not isinstance(item, dict):
            continue
        if item.get("target_path"):
            requested += 1
        if item.get("geo_exists") is True and item.get("target_path"):
            ready += 1
    return ready, requested


def _project_name(state: dict[str, Any]) -> str:
    result = _sheet(state).get("ofertare_result") or {}
    if not isinstance(result, dict):
        return ""
    root = str(result.get("projectRoot") or result.get("project_root") or "")
    return str(result.get("projectName") or root.replace("\\", "/").rstrip("/").split("/")[-1] or "")


def _recent_jobs(limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for state in list_jobs(limit):
        sheet = _sheet(state)
        if not sheet:
            continue
        ready, requested = _geo_counts(state)
        items.append(
            {
                "job_id": _job_id(state),
                "offer_id": _offer_id(state),
                "status": _status(state),
                "geo_ready_count": ready,
                "geo_requested_count": requested,
                "project_name": _project_name(state),
                "updated_ts": float(state.get("updated_ts") or sheet.get("completed_ts") or sheet.get("started_ts") or 0),
                "started_ts": float(sheet.get("started_ts") or 0),
                "completed_ts": float(sheet.get("completed_ts") or 0),
                "error": str(sheet.get("error") or ""),
            }
        )
    return sorted(items, key=lambda item: float(item.get("updated_ts") or 0), reverse=True)


def observability_summary(job_limit: int = 10000, event_limit: int = 500) -> dict[str, Any]:
    queue = queue_store.get_queue_state()
    jobs = _recent_jobs(job_limit)
    status_counts = Counter(str(item.get("status") or "unknown") for item in jobs)
    event_counts = Counter(str(item.get("type") or "unknown") for item in read_events(event_limit))
    geo_ready_total = sum(int(item.get("geo_ready_count") or 0) for item in jobs)
    geo_requested_total = sum(int(item.get("geo_requested_count") or 0) for item in jobs)
    now = time.time()
    paused_until = float(queue.get("paused_until") or 0)
    active = queue.get("active") or {}

    return {
        "ok": True,
        "generated_ts": now,
        "storage": {
            "type": "json_files",
            "jobs": "/app/data/jobs/*.json",
            "queue": "/app/data/agent_queue.json",
            "events": "/app/data/agent_events.jsonl",
        },
        "queue": {
            "queued_count": int(queue.get("queued_count") or 0),
            "completed_count": int(queue.get("completed_count") or 0),
            "running": bool(queue.get("running")),
            "paused": bool(queue.get("paused")),
            "worker_alive": bool(queue.get("worker_alive")),
            "paused_seconds_remaining": max(0.0, paused_until - now),
            "last_process_seconds": float(queue.get("last_process_seconds") or 0),
            "active_job_id": str(active.get("job_id") or ""),
            "active_offer_id": str(active.get("offer_id") or ""),
        },
        "jobs": {
            "total": len(jobs),
            "by_status": dict(sorted(status_counts.items())),
            "geo_ready_files_total": geo_ready_total,
            "geo_requested_files_total": geo_requested_total,
            "recent": jobs[:50],
        },
        "events": {
            "sample_size": event_limit,
            "by_type": dict(sorted(event_counts.items())),
        },
    }


def _label(value: Any) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric(name: str, value: int | float, labels: dict[str, Any] | None = None) -> str:
    if labels:
        label_text = ",".join(f'{key}="{_label(val)}"' for key, val in sorted(labels.items()))
        return f"{name}{{{label_text}}} {float(value)}"
    return f"{name} {float(value)}"


def prometheus_metrics() -> str:
    summary = observability_summary()
    queue = summary["queue"]
    jobs = summary["jobs"]
    events = summary["events"]

    lines = [
        "# HELP xometryanaliza_up Service health flag.",
        "# TYPE xometryanaliza_up gauge",
        _metric("xometryanaliza_up", 1),
        "# HELP xometryanaliza_queue_jobs Current queue sizes and worker state.",
        "# TYPE xometryanaliza_queue_jobs gauge",
        _metric("xometryanaliza_queue_jobs", queue["queued_count"], {"state": "queued"}),
        _metric("xometryanaliza_queue_jobs", queue["completed_count"], {"state": "completed_recent"}),
        _metric("xometryanaliza_queue_running", 1 if queue["running"] else 0),
        _metric("xometryanaliza_queue_paused", 1 if queue["paused"] else 0),
        _metric("xometryanaliza_queue_worker_alive", 1 if queue["worker_alive"] else 0),
        _metric("xometryanaliza_queue_paused_seconds_remaining", queue["paused_seconds_remaining"]),
        _metric("xometryanaliza_queue_last_process_seconds", queue["last_process_seconds"]),
        "# HELP xometryanaliza_jobs_total Processed sheet/laser jobs by status.",
        "# TYPE xometryanaliza_jobs_total gauge",
    ]

    for status, count in (jobs.get("by_status") or {}).items():
        lines.append(_metric("xometryanaliza_jobs_total", int(count), {"status": status}))

    lines.extend(
        [
            _metric("xometryanaliza_geo_files_total", jobs["geo_ready_files_total"], {"state": "ready"}),
            _metric("xometryanaliza_geo_files_total", jobs["geo_requested_files_total"], {"state": "requested"}),
            "# HELP xometryanaliza_events_recent_total Recent event counts by type.",
            "# TYPE xometryanaliza_events_recent_total gauge",
        ]
    )

    for event_type, count in (events.get("by_type") or {}).items():
        lines.append(_metric("xometryanaliza_events_recent_total", int(count), {"type": event_type}))

    lines.extend(
        [
            "# HELP xometryanaliza_recent_job_status Latest processed jobs, capped at 50 to avoid excessive label cardinality.",
            "# TYPE xometryanaliza_recent_job_status gauge",
        ]
    )
    for item in jobs.get("recent") or []:
        labels = {
            "job_id": item.get("job_id"),
            "offer_id": item.get("offer_id"),
            "status": item.get("status"),
            "project": item.get("project_name"),
        }
        lines.append(_metric("xometryanaliza_recent_job_status", 1, labels))
        if item.get("updated_ts"):
            lines.append(_metric("xometryanaliza_recent_job_updated_timestamp", item["updated_ts"], labels))

    return "\n".join(lines) + "\n"
