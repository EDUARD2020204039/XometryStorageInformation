from __future__ import annotations

import time
from typing import Any

from . import settings
from .ofertare_client import extract_geo_items, run_ofertare_automata
from .store import append_event, load_job_state, save_job_state
from .telegram_log import send_log


def _text(job: dict[str, Any]) -> str:
    fields = [
        job.get("id"),
        job.get("offer_id"),
        job.get("title"),
        job.get("job_name"),
        job.get("type"),
        job.get("material"),
        job.get("process"),
        job.get("remarks"),
        job.get("parts"),
    ]
    return " ".join(str(field or "") for field in fields).lower()


def _job_id(job: dict[str, Any]) -> str:
    return str(job.get("id") or job.get("job_id") or job.get("title") or job.get("offer_id") or "unknown")


class RouterAgent:
    def route(self, job: dict[str, Any]) -> list[str]:
        text = _text(job)
        agents = []
        if any(token in text for token in ("cnc", "milling", "turning", "machining")):
            agents.append("cnc")
        if any(token in text for token in ("sheet", "sheet metal", "metal sheet", "laser", "bending", "tabla")):
            agents.append("sheet_metal_laser")
        return agents


class CncAgent:
    name = "cnc"

    def run(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = _job_id(job)
        result = {
            "agent": self.name,
            "status": "classified",
            "message": "CNC job detected. Manual CNC analysis queue only for now.",
        }
        append_event("cnc.detected", f"CNC agent detected {job_id}", job_id=job_id, offer_id=job.get("offer_id"))
        return result


class SheetMetalLaserAgent:
    name = "sheet_metal_laser"

    def run(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = _job_id(job)
        offer_id = str(job.get("offer_id") or "")
        previous = load_job_state(job_id) or {}
        previous_sheet = previous.get("sheet_metal_laser") or {}
        previous_geo = previous_sheet.get("geo_items") or []
        if previous_geo:
            append_event("sheet.geo.cached", f"Sheet agent already has GEO for {job_id}", job_id=job_id, offer_id=offer_id)
            return {
                "agent": self.name,
                "status": "cached",
                "geo_items": previous_geo,
            }

        last_attempt_ts = previous_sheet.get("completed_ts") or previous_sheet.get("started_ts") or 0
        if last_attempt_ts and time.time() - float(last_attempt_ts) < settings.SHEET_AGENT_RETRY_SECONDS:
            retry_after = max(0, int(settings.SHEET_AGENT_RETRY_SECONDS - (time.time() - float(last_attempt_ts))))
            append_event("sheet.skip_recent", f"Sheet agent skipped recent attempt for {job_id}", job_id=job_id, offer_id=offer_id, retry_after_seconds=retry_after)
            return {
                **previous_sheet,
                "agent": self.name,
                "skipped": True,
                "retry_after_seconds": retry_after,
            }

        started_ts = time.time()
        running_state = {
            "agent": self.name,
            "status": "running",
            "started_ts": started_ts,
            "url": job.get("link") or job.get("url"),
        }
        save_job_state(
            job_id,
            {
                **previous,
                "job_id": job_id,
                "job": job,
                "offer_id": offer_id,
                self.name: running_state,
            },
        )
        append_event("sheet.start", f"Sheet agent started unfold for {job_id}", job_id=job_id, offer_id=offer_id, url=job.get("link") or job.get("url"))
        if settings.TELEGRAM_SHEET_START_LOGS:
            send_log(f"XometryAnaliza: SheetMetal/Laser agent pornit pentru {job_id}. Generez desfasurata GEO.")

        try:
            result = run_ofertare_automata(job)
            geo_items = extract_geo_items(result)
            status = "geo_ready" if any(item.get("geo_exists") for item in geo_items) else "geo_requested"
            output = {
                "agent": self.name,
                "status": status,
                "ofertare_result": result,
                "geo_items": geo_items,
                "completed_ts": time.time(),
            }
            append_event("sheet.done", f"Sheet agent finished {job_id}: {status}", job_id=job_id, offer_id=offer_id, geo_items=geo_items)
            if geo_items and settings.TELEGRAM_GEO_LOGS:
                first_geo = geo_items[0].get("target_path")
                send_log(f"XometryAnaliza: GEO pentru {job_id}: {first_geo}")
            return output
        except Exception as exc:
            output = {
                "agent": self.name,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "completed_ts": time.time(),
            }
            append_event("sheet.failed", f"Sheet agent failed {job_id}: {output['error']}", job_id=job_id, offer_id=offer_id)
            if settings.TELEGRAM_SHEET_FAILURE_LOGS:
                send_log(f"XometryAnaliza: EROARE SheetMetal/Laser pentru {job_id}: {output['error']}")
            return output


def process_job(job: dict[str, Any]) -> dict[str, Any]:
    router = RouterAgent()
    job_id = _job_id(job)
    agents = router.route(job)
    state = load_job_state(job_id) or {"job": job, "created_ts": time.time()}
    state["job_id"] = job_id
    state["job"] = job
    state["offer_id"] = job.get("offer_id")
    state["agents"] = agents

    append_event("router.route", f"Router selected {agents or ['none']} for {job_id}", job_id=job_id, offer_id=job.get("offer_id"), agents=agents)

    results = {}
    if "cnc" in agents:
        results["cnc"] = CncAgent().run(job)
    if "sheet_metal_laser" in agents:
        results["sheet_metal_laser"] = SheetMetalLaserAgent().run(job)

    state.update(results)
    save_job_state(job_id, state)
    return state


def process_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    processed = []
    for job in jobs:
        processed.append(process_job(job))
    return {
        "accepted": len(jobs),
        "processed": len(processed),
        "items": processed,
    }
