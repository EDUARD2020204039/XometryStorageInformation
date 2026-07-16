from __future__ import annotations

import json
import threading
import time
from typing import Any

import requests

from . import queue_store, settings
from .store import append_event, list_jobs, read_events
from .telegram_log import send_log


_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_LAST_ALERT_SIGNATURE = ""


def _status_path():
    settings.ensure_dirs()
    return settings.DATA_DIR / "watchdog_status.json"


def _history_path():
    settings.ensure_dirs()
    return settings.DATA_DIR / "watchdog_history.jsonl"


def _xometry_session_path():
    settings.ensure_dirs()
    return settings.DATA_DIR / "xometry_session.json"


def _read_json(path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_latest(payload: dict[str, Any]) -> None:
    _status_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with _history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def latest_status() -> dict[str, Any]:
    return _read_json(_status_path(), {
        "ok": False,
        "status": "unknown",
        "checked_at": 0,
        "summary": "Watchdog nu a rulat inca.",
        "scenarios": [],
    })


def history(limit: int = 50) -> list[dict[str, Any]]:
    path = _history_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _scenario(name: str, ok: bool, summary: str, details: dict[str, Any] | None = None, severity: str = "error") -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "status": "ok" if ok else severity,
        "summary": summary,
        "details": details or {},
    }


def _check_xometry_session() -> dict[str, Any]:
    data = _read_json(_xometry_session_path(), {})
    checked_at = float(data.get("checked_at") or 0)
    age = max(0, time.time() - checked_at) if checked_at else None
    details = {
        "reason": data.get("reason") or "never_checked",
        "phase": data.get("phase") or "",
        "age_seconds": int(age) if age is not None else None,
        "api_ok": bool(data.get("api_ok")),
        "api_reason": data.get("api_reason") or "",
        "job_board": bool(data.get("job_board")),
        "auth_token_present": bool(data.get("auth_token_present")),
        "jobs_count": data.get("jobs_count"),
        "url": data.get("url") or "",
    }
    if not data:
        return _scenario("xometry_session", False, "Nu exista inca un status de login Xometry.", details)
    if not data.get("ok"):
        return _scenario("xometry_session", False, f"Sesiune Xometry invalida: {details['reason']}", details)
    if age is not None and age > settings.WATCHDOG_XOMETRY_SESSION_MAX_AGE_SECONDS:
        return _scenario(
            "xometry_session",
            False,
            f"Sesiunea Xometry nu a mai fost verificata de {int(age)}s.",
            details,
            severity="warning",
        )
    jobs_count = data.get("jobs_count")
    if data.get("phase") == "scrape" and isinstance(jobs_count, int) and jobs_count <= 0:
        return _scenario("xometry_session", False, "Scrape Xometry a returnat 0 joburi.", details)
    if not data.get("api_ok"):
        api_reason = str(data.get("api_reason") or "")
        ui_session_ok = bool(data.get("job_board") or data.get("total_order_value"))
        scrape_has_jobs = data.get("phase") == "scrape" and isinstance(jobs_count, int) and jobs_count > 0
        transient_api_reasons = ("graphql_errors", "timeout", "temporarily unavailable", "connection")
        if ui_session_ok and data.get("auth_token_present") and (
            scrape_has_jobs or any(marker in api_reason.lower() for marker in transient_api_reasons)
        ):
            return _scenario(
                "xometry_session",
                True,
                f"Login Xometry si scrape validate; API GraphQL temporar instabil: {api_reason or 'unknown'}.",
                details,
            )
        return _scenario("xometry_session", False, f"Tokenul/API Xometry nu este valid: {api_reason}", details)
    return _scenario("xometry_session", True, "Login Xometry, token si API validate.", details)


def _check_queue_worker() -> dict[str, Any]:
    queue = queue_store.get_queue_state()
    active = queue.get("active") or {}
    queued = queue.get("queued") or []
    paused = bool(queue.get("paused"))
    worker_alive = bool(queue.get("worker_alive"))
    problems: list[str] = []

    job_ids = [str(item.get("job_id") or "") for item in queued if item.get("job_id")]
    offer_ids = [str(item.get("offer_id") or "") for item in queued if item.get("offer_id")]
    if len(job_ids) != len(set(job_ids)):
        problems.append("exista joburi duplicate in coada")
    if len(offer_ids) != len(set(offer_ids)):
        problems.append("exista offer_id duplicate in coada")

    if queued and not active and not paused and not worker_alive:
        problems.append("exista joburi in asteptare, dar workerul nu ruleaza")

    active_age = 0
    if active:
        active_age = max(0, time.time() - float(active.get("started_ts") or 0))
        if active_age > settings.WATCHDOG_QUEUE_ACTIVE_STALE_SECONDS:
            problems.append(f"job activ prea vechi: {int(active_age)}s")

    protected = {str(item.get("job_id") or "") for item in [active, *queued] if isinstance(item, dict)}
    stale_running = []
    for state in list_jobs(limit=10000):
        job_id = str(state.get("job_id") or "")
        if not job_id or job_id in protected:
            continue
        sheet = state.get("sheet_metal_laser") or {}
        if str(sheet.get("status") or "").lower() != "running":
            continue
        started = float(sheet.get("started_ts") or state.get("updated_ts") or 0)
        if started and time.time() - started > settings.STALE_RUNNING_SECONDS:
            stale_running.append(job_id)
    if stale_running:
        problems.append(f"joburi ramase running in istoric: {', '.join(stale_running[:5])}")

    details = {
        "queued_count": len(queued),
        "active_job_id": active.get("job_id") or "",
        "active_age_seconds": int(active_age),
        "paused": paused,
        "worker_alive": worker_alive,
        "stale_running_count": len(stale_running),
    }
    if problems:
        return _scenario("queue_worker", False, "; ".join(problems), details)
    return _scenario("queue_worker", True, "Coada si workerul sunt consistente.", details)


def _check_ofertare_api() -> dict[str, Any]:
    url = f"{settings.OFERTARE_AUTOMATA_URL}/health"
    try:
        response = requests.get(url, timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, settings.WATCHDOG_OFERTARE_HEALTH_TIMEOUT))
        body = response.text[:300]
        details = {"url": url, "status_code": response.status_code, "body": body}
        if not response.ok:
            return _scenario("ofertare_api", False, f"Ofertare API raspunde HTTP {response.status_code}.", details)
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if payload and payload.get("status") not in (None, "ok") and payload.get("ok") is not True:
            details["json"] = payload
            return _scenario("ofertare_api", False, "Ofertare API health nu este OK.", details)
        return _scenario("ofertare_api", True, "Ofertare/TecZone API raspunde la health.", details)
    except Exception as exc:
        return _scenario(
            "ofertare_api",
            False,
            f"Nu pot accesa Ofertare API: {type(exc).__name__}: {exc}",
            {"url": url},
        )


def _check_hermes_api() -> dict[str, Any]:
    if not settings.HERMES_DIAGNOSTICS_ENABLED:
        return _scenario("hermes_api", True, "Hermes diagnostics este dezactivat.", {"enabled": False})
    if not settings.HERMES_AGENT_URL:
        return _scenario("hermes_api", True, "Hermes diagnostics nu are URL configurat.", {"enabled": True})

    base = settings.HERMES_AGENT_URL.rstrip("/")
    url = f"{base}/health"
    details = {"enabled": True, "url": url, "model": settings.HERMES_AGENT_MODEL}
    try:
        response = requests.get(url, timeout=(3, 6))
        details["status_code"] = response.status_code
        details["body"] = response.text[:300]
        if response.ok:
            return _scenario("hermes_api", True, "Hermes raspunde la health.", details)
        return _scenario("hermes_api", False, f"Hermes health raspunde HTTP {response.status_code}.", details, severity="warning")
    except Exception as exc:
        details["error"] = f"{type(exc).__name__}: {exc}"
        return _scenario("hermes_api", False, f"Hermes nu raspunde: {type(exc).__name__}: {exc}", details, severity="warning")


def _check_recent_flow_errors() -> dict[str, Any]:
    cutoff = time.time() - settings.WATCHDOG_RECENT_ERROR_SECONDS
    events = [item for item in read_events(300) if float(item.get("ts") or 0) >= cutoff]
    hits = []
    ignored_markers = (
        "login=no",
        "xometry_error=no",
        "session ok",
        "scrape_ok",
        "graphql_ok",
        "ui_ok_api_warning:graphql_errors",
    )
    markers = (
        "login=yes",
        "xometry_error=yes",
        "blocked_login",
        "blocked_documentation",
        "timeout",
        "failed",
        "eroare",
        "error",
    )
    for item in events:
        event_type = str(item.get("type") or "")
        if event_type.startswith("watchdog."):
            continue
        message = str(item.get("message") or "")
        lowered = f"{event_type} {message}".lower()
        if any(marker in lowered for marker in ignored_markers):
            continue
        if any(marker in lowered for marker in markers):
            hits.append({
                "ts": item.get("ts"),
                "type": event_type,
                "message": message[:260],
                "job_id": item.get("job_id"),
                "offer_id": item.get("offer_id"),
            })
    details = {
        "window_seconds": settings.WATCHDOG_RECENT_ERROR_SECONDS,
        "hit_count": len(hits),
        "examples": hits[-8:],
    }
    if hits:
        return _scenario(
            "recent_flow_errors",
            False,
            f"Am gasit {len(hits)} evenimente recente cu login/eroare/timeout.",
            details,
            severity="warning",
        )
    return _scenario("recent_flow_errors", True, "Nu exista erori recente in fluxul de ofertare.", details)


def run_checks(source: str = "manual") -> dict[str, Any]:
    scenarios = [
        _check_xometry_session(),
        _check_queue_worker(),
        _check_ofertare_api(),
        _check_hermes_api(),
        _check_recent_flow_errors(),
    ]
    failed = [item for item in scenarios if not item.get("ok")]
    status = "ok" if not failed else ("warning" if all(item.get("status") == "warning" for item in failed) else "error")
    payload = {
        "ok": not failed,
        "status": status,
        "checked_at": time.time(),
        "source": source,
        "summary": "Toate scenariile watchdog sunt OK." if not failed else f"{len(failed)} scenarii au probleme.",
        "scenarios": scenarios,
    }
    _write_latest(payload)
    _emit_alert_if_changed(payload)
    return payload


def _alert_signature(payload: dict[str, Any]) -> str:
    failed = [item for item in payload.get("scenarios") or [] if not item.get("ok")]
    return "|".join(f"{item.get('name')}:{item.get('status')}" for item in failed)


def _emit_alert_if_changed(payload: dict[str, Any]) -> None:
    global _LAST_ALERT_SIGNATURE
    signature = _alert_signature(payload)
    if signature == _LAST_ALERT_SIGNATURE:
        return
    _LAST_ALERT_SIGNATURE = signature
    if payload.get("ok"):
        append_event("watchdog.ok", "Watchdog: toate scenariile sunt OK")
        if settings.WATCHDOG_TELEGRAM_ALERTS:
            send_log("XometryAnaliza watchdog: toate scenariile sunt OK.")
        return

    failed = [item for item in payload.get("scenarios") or [] if not item.get("ok")]
    message = "XometryAnaliza watchdog: probleme detectate\n" + "\n".join(
        f"- {item.get('name')}: {item.get('summary')}" for item in failed
    )
    append_event("watchdog.failed", message)
    if settings.WATCHDOG_TELEGRAM_ALERTS:
        send_log(message)


def _loop() -> None:
    while True:
        try:
            run_checks(source="periodic")
        except Exception as exc:
            append_event("watchdog.error", f"Watchdog crashed during checks: {type(exc).__name__}: {exc}")
        time.sleep(max(30, settings.WATCHDOG_INTERVAL_SECONDS))


def start() -> bool:
    global _THREAD
    if not settings.WATCHDOG_ENABLED:
        return False
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return False
        _THREAD = threading.Thread(target=_loop, name="xometry-watchdog", daemon=True)
        _THREAD.start()
        return True
