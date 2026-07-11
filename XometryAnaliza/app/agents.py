from __future__ import annotations

import time
from typing import Any

from . import settings
from .ofertare_client import extract_geo_items, run_ofertare_automata, run_teczone_folder
from .geo_files import read_remote_file
from .store import append_event, load_job_state, save_job_state
from .telegram_log import send_log
from .xometry_backend_client import lookup_dosar_references
from .bend_artifacts import build_bend_artifacts, copy_bend_artifacts_to_dosar

SHEET_KEYWORDS = (
    "sheet",
    "sheet metal",
    "metal sheet",
    "laser",
    "laser cutting",
    "bending",
    "tabla",
    "tablă",
)


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


def _sheet_part_ids(job: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for part in job.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if not any(keyword in _part_process_text(part) for keyword in SHEET_KEYWORDS):
            continue
        part_id = str(part.get("part_id") or part.get("id") or "").strip()
        if part_id:
            ids.add(part_id.lower())
            digits = "".join(ch for ch in part_id if ch.isdigit())
            if digits:
                ids.add(digits.lower())
    return ids


def _sheet_part_count(job: dict[str, Any]) -> int:
    parts = [part for part in job.get("parts") or [] if isinstance(part, dict)]
    sheet_parts = [part for part in parts if any(keyword in _part_process_text(part) for keyword in SHEET_KEYWORDS)]
    return len(sheet_parts) or len(_sheet_part_ids(job)) or len(parts)


def _geo_item_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("part_id", "part_name", "partName", "target_path", "targetPath")
    ).lower()


def _filter_geo_items_for_sheet_parts(job: dict[str, Any], geo_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sheet_ids = _sheet_part_ids(job)
    if not sheet_ids:
        return geo_items

    filtered = []
    for item in geo_items:
        text = _geo_item_text(item)
        matched = [part_id for part_id in sheet_ids if part_id and part_id in text]
        if matched:
            filtered.append({**item, "sheet_relevant": True, "matched_sheet_part_ids": sorted(set(matched))})
    return filtered


def _result_text(result: dict[str, Any]) -> str:
    warnings = [str(item or "") for item in result.get("warnings") or []]
    trutops = []
    for item in result.get("trutops") or []:
        if isinstance(item, dict):
            trutops.extend(str(item.get(key) or "") for key in ("classification", "reason", "message", "status"))
    return "\n".join(warnings + trutops).lower()


def _ofertare_log_lines(result: dict[str, Any], limit: int = 80) -> list[str]:
    lines: list[str] = []
    for item in result.get("warnings") or []:
        for line in str(item or "").splitlines():
            line = line.strip()
            if not line:
                continue
            lowered = line.lower()
            if "password" in lowered or "token" in lowered:
                continue
            lines.append(line[:600])
            if len(lines) >= limit:
                return lines
    return lines


def _read_capture_hint(result: dict[str, Any]) -> str:
    for file_path in result.get("files") or []:
        path = str(file_path or "")
        if not path.lower().endswith(".body.txt"):
            continue
        try:
            return read_remote_file(path).decode("utf-8", "replace")[:12000].lower()
        except Exception:
            return ""
    return ""


def _classify_ofertare_failure(result: dict[str, Any]) -> dict[str, Any]:
    text = _result_text(result)
    capture_hint = ""
    login_tokens = (
        "pagina de login",
        "xometry_email/xometry_password",
        "basic_email",
        "basic_password",
        "sign in",
        "log in",
    )
    if any(token in text for token in login_tokens):
        return {
            "status": "blocked_login",
            "failure_type": "xometry_login_required",
            "message": "Ofertare a ajuns la login Xometry; verifica sesiunea sau credentialele Xometry pe laptopul de ofertare.",
            "action": "Deschide Ofertare-Automata pe laptop, refa login-ul Xometry si retrimite jobul manual.",
        }

    document_tokens = (
        "nu am descarcat automat fisierele",
        "nu am gasit nicio piesa",
        "nu exista piese/step",
        "xometry_parts_missing",
        "source_missing",
    )
    if any(token in text for token in document_tokens):
        capture_hint = _read_capture_hint(result)
        if "something went wrong" in capture_hint or "we couldn" in capture_hint:
            message = "Xometry a returnat pagina de eroare in loc de documentatie; nu am de unde sa extrag STEP/GEO."
        elif "back to rfqs" in capture_hint and "not a partner" in capture_hint:
            message = "RFQ-ul nu a incarcat documentatia pentru partener; captura nu contine fisiere STEP."
        else:
            message = "Nu s-au descarcat fisierele Xometry/STEP; TecZone nu poate porni fara documentatie."
        return {
            "status": "blocked_documentation",
            "failure_type": "xometry_documentation_unavailable",
            "message": message,
            "action": "Verifica pagina Xometry si folderul DOC al proiectului; daca fisierele apar manual, retrimite jobul din dashboard.",
            "capture_hint": capture_hint[:500],
        }

    for item in result.get("trutops") or []:
        classification = str(item.get("classification") or "").lower()
        reason = str(item.get("reason") or item.get("message") or "")
        if classification in {"xometry_parts_missing", "source_missing"}:
            return {
                "status": "blocked_documentation",
                "failure_type": classification,
                "message": reason or "Ofertare nu a gasit piese/STEP pentru TecZone.",
                "action": "Verifica documentatia descarcata si retrimite jobul dupa ce exista STEP in DOC.",
            }
    return {}


class RouterAgent:
    def route(self, job: dict[str, Any]) -> list[str]:
        if job.get("manual"):
            return ["sheet_metal_laser"]

        text = _text(job)
        agents = []
        parts = [part for part in job.get("parts") or [] if isinstance(part, dict)]
        if parts:
            if _sheet_part_ids(job):
                agents.append("sheet_metal_laser")
        elif any(token in text for token in SHEET_KEYWORDS):
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
        url = str(job.get("link") or job.get("url") or "")
        previous = load_job_state(job_id) or {}
        previous_sheet = previous.get("sheet_metal_laser") or {}
        previous_geo = previous_sheet.get("geo_items") or []
        previous_ready_geo = _filter_geo_items_for_sheet_parts(
            job,
            [item for item in previous_geo if item.get("geo_exists") is True and item.get("target_path")],
        )
        if previous_ready_geo:
            completed_ts = time.time()
            append_event("sheet.geo.cached", f"Sheet agent already has GEO for {job_id}", job_id=job_id, offer_id=offer_id)
            return {
                "agent": self.name,
                "status": "cached",
                "geo_items": previous_ready_geo,
                "matched_sheet_part_ids": sorted(_sheet_part_ids(job)),
                "identified_parts_count": _sheet_part_count(job),
                "processed_parts_count": len(previous_ready_geo),
                "geo_ready_count": len(previous_ready_geo),
                "geo_requested_count": len(previous_ready_geo),
                "started_ts": completed_ts,
                "completed_ts": completed_ts,
                "process_duration_seconds": 0,
            }

        is_rfq_without_offer = job_id.upper().startswith("RFQ-") and not url
        if is_rfq_without_offer:
            message = "RFQ sheet/laser job skipped: no RFQ URL/files available for automatic GEO extraction."
            append_event("sheet.skip_rfq", f"{message} {job_id}", job_id=job_id, offer_id=offer_id, url=url)
            return {
                "agent": self.name,
                "status": "skipped_rfq",
                "reason": message,
                "url": url,
                "completed_ts": time.time(),
            }

        last_status = str(previous_sheet.get("status") or "").lower()
        last_attempt_ts = previous_sheet.get("completed_ts") or previous_sheet.get("started_ts") or 0
        if (
            last_status != "agent_busy"
            and last_attempt_ts
            and time.time() - float(last_attempt_ts) < settings.SHEET_AGENT_RETRY_SECONDS
        ):
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
            "url": url,
            "identified_parts_count": _sheet_part_count(job),
            "processed_parts_count": 0,
            "geo_ready_count": 0,
            "geo_requested_count": 0,
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
        append_event("sheet.start", f"Sheet agent started unfold for {job_id}", job_id=job_id, offer_id=offer_id, url=url)
        if settings.TELEGRAM_SHEET_START_LOGS:
            send_log(f"XometryAnaliza: SheetMetal/Laser agent pornit pentru {job_id}. Generez desfasurata GEO.")

        try:
            previous_project = (previous_sheet.get("ofertare_result") or {}).get("projectRoot")
            if last_status == "agent_busy" and previous_project:
                result = run_teczone_folder(str(previous_project))
                append_event("sheet.retry_folder", f"Retrying TecZone on existing folder for {job_id}", job_id=job_id, offer_id=offer_id, project_root=previous_project)
            else:
                result = run_ofertare_automata(job)
            for log_line in _ofertare_log_lines(result):
                append_event("ofertare.log", log_line, job_id=job_id, offer_id=offer_id)
            raw_geo_items = extract_geo_items(result)
            geo_items = _filter_geo_items_for_sheet_parts(job, raw_geo_items)
            failure = _classify_ofertare_failure(result)
            failure_reason = str(failure.get("message") or "")
            bend_report = build_bend_artifacts(job_id, offer_id, result, geo_items) if offer_id and not failure else None
            agent_busy_items = geo_items or raw_geo_items
            agent_busy = bool(agent_busy_items) and all(
                str(item.get("classification") or "").lower() == "agent_busy"
                or "agent is already processing" in str(item.get("reason") or "").lower()
                for item in agent_busy_items
            )
            status = (
                "agent_busy"
                if agent_busy
                else str(failure.get("status") or "")
                if failure
                else "geo_ready"
                if any(item.get("geo_exists") for item in geo_items)
                else "geo_requested"
            )
            completed_ts = time.time()
            geo_requested_count = len([item for item in geo_items if item.get("target_path")])
            geo_ready_count = len([item for item in geo_items if item.get("geo_exists") is True and item.get("target_path")])
            output = {
                "agent": self.name,
                "status": status,
                "ofertare_result": result,
                "geo_items": geo_items,
                "bend_report": bend_report,
                "error": failure_reason,
                "matched_sheet_part_ids": sorted(_sheet_part_ids(job)),
                "identified_parts_count": _sheet_part_count(job),
                "processed_parts_count": geo_ready_count,
                "geo_ready_count": geo_ready_count,
                "geo_requested_count": geo_requested_count,
                "started_ts": started_ts,
                "completed_ts": completed_ts,
                "process_duration_seconds": max(0, completed_ts - started_ts),
            }
            if failure:
                output.update(
                    {
                        "failure_type": failure.get("failure_type"),
                        "failure_action": failure.get("action"),
                        "can_retry": True,
                    }
                )
                append_event(
                    "sheet.blocked",
                    f"Sheet agent blocked {job_id}: {failure_reason}",
                    job_id=job_id,
                    offer_id=offer_id,
                    status=status,
                    failure_type=failure.get("failure_type"),
                    action=failure.get("action"),
                )
            append_event("sheet.done", f"Sheet agent finished {job_id}: {status}", job_id=job_id, offer_id=offer_id, geo_items=geo_items)
            if geo_items and settings.TELEGRAM_GEO_LOGS:
                first_geo = geo_items[0].get("target_path")
                send_log(f"XometryAnaliza: GEO pentru {job_id}: {first_geo}")
            return output
        except Exception as exc:
            completed_ts = time.time()
            output = {
                "agent": self.name,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "identified_parts_count": _sheet_part_count(job),
                "processed_parts_count": 0,
                "geo_ready_count": 0,
                "geo_requested_count": 0,
                "started_ts": started_ts,
                "completed_ts": completed_ts,
                "process_duration_seconds": max(0, completed_ts - started_ts),
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

    try:
        dosar_lookup = lookup_dosar_references(job)
        state["dosar_lookup"] = dosar_lookup
        reference_count = len(dosar_lookup.get("references_with_dosar") or [])
        append_event(
            "dosar.lookup",
            f"Dosar lookup found {reference_count} references for {job_id}",
            job_id=job_id,
            offer_id=job.get("offer_id"),
            references_with_dosar=dosar_lookup.get("references_with_dosar") or [],
        )
    except Exception as exc:
        state["dosar_lookup"] = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        append_event("dosar.lookup_failed", f"Dosar lookup failed for {job_id}: {exc}", job_id=job_id, offer_id=job.get("offer_id"))

    results = {}
    if "cnc" in agents:
        results["cnc"] = CncAgent().run(job)
    if "sheet_metal_laser" in agents:
        results["sheet_metal_laser"] = SheetMetalLaserAgent().run(job)
        bend_report = (results["sheet_metal_laser"] or {}).get("bend_report") or {}
        current_dosar = (state.get("dosar_lookup") or {}).get("current") or {}
        if bend_report and current_dosar.get("has_dosar") and current_dosar.get("dosar_path"):
            try:
                bend_report["dosar_copy"] = copy_bend_artifacts_to_dosar(str(job.get("offer_id") or ""), current_dosar["dosar_path"])
            except Exception as exc:
                bend_report["dosar_copy"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

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
