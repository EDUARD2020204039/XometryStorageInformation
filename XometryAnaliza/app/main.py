import html
import json
import re
import time
from typing import Any
from pathlib import PureWindowsPath
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, HTTPException, Body, Header
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .agents import process_jobs
from .bend_artifacts import artifact_path, read_bend_summary
from .geo_files import read_remote_file, read_remote_geo_file
from .metrics import observability_summary, prometheus_metrics
from .store import find_job_by_offer_id, list_jobs, read_events
from . import queue_store, settings


app = FastAPI(title="Xometry Analiza Agents", version="2.0.0")

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#0f172a"/>
  <path d="M15 15l34 34M49 15L15 49" stroke="#38bdf8" stroke-width="8" stroke-linecap="round"/>
  <path d="M12 44h40" stroke="#f97316" stroke-width="3" stroke-linecap="round"/>
  <circle cx="50" cy="44" r="5" fill="#facc15"/>
  <path d="M47 44h10" stroke="#f97316" stroke-width="2" stroke-linecap="round"/>
</svg>"""

@app.on_event("startup")
def start_queue_worker() -> None:
    queue_store.recover_and_start()


class AgentJobsPayload(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "unknown"


class ManualJobPayload(BaseModel):
    identifier: str = ""
    job_id: str = ""
    offer_id: str = ""
    url: str = ""
    source: str = "manual"
    force: bool = True
    front: bool = True


class XometrySessionPayload(BaseModel):
    ok: bool = False
    reason: str = ""
    phase: str = ""
    source: str = ""
    url: str = ""
    title: str = ""
    body_length: int = 0
    body_sample: str = ""
    login_form: bool = False
    job_board: bool = False
    total_order_value: bool = False
    auth_token_present: bool = False
    api_ok: bool = False
    api_reason: str = ""
    api_detail: str = ""
    api_sample_count: int | None = None
    jobs_count: int | None = None
    checked_at: float = 0


def _run_jobs(payload: AgentJobsPayload) -> None:
    process_jobs(payload.jobs)


JOB_ID_RE = re.compile(r"\b(?:HJO|J|RFQ)-\d+(?:-\d+)?\b", re.IGNORECASE)
OFFER_URL_RE = re.compile(r"/offers/(\d+)", re.IGNORECASE)
RFQ_URL_RE = re.compile(r"/rfqs/([^/?#]+)", re.IGNORECASE)


def _xometry_offer_url(offer_id: str = "", job_id: str = "") -> str:
    value = str(offer_id or job_id or "").strip()
    if not value:
        return ""
    if str(job_id or "").upper().startswith("RFQ-"):
        rfq_value = str(job_id).strip()
        rfq_slug = rfq_value[4:] if rfq_value.upper().startswith("RFQ-") else rfq_value
        return f"https://partner.xometry.eu/rfqs/{quote(rfq_slug, safe='')}?source=rfqs"
    suffix = "?gsh=true&source=jobs&locale=en" if str(job_id or "").upper().startswith(("HJO-", "J-")) else "?source=jobs&locale=en"
    return f"https://partner.xometry.eu/offers/{quote(value, safe='')}{suffix}"


def _xometry_session_path():
    settings.ensure_dirs()
    return settings.DATA_DIR / "xometry_session.json"


def _read_xometry_session() -> dict[str, Any]:
    path = _xometry_session_path()
    if not path.exists():
        return {
            "ok": False,
            "reason": "never_checked",
            "phase": "",
            "source": "",
            "checked_at": 0,
            "age_seconds": 0,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {"ok": False, "reason": "status_file_invalid", "checked_at": 0}
    checked_at = float(data.get("checked_at") or 0)
    data["age_seconds"] = max(0, int(time.time() - checked_at)) if checked_at else 0
    return data


def _write_xometry_session(payload: dict[str, Any]) -> dict[str, Any]:
    settings.ensure_dirs()
    data = {**payload, "checked_at": float(payload.get("checked_at") or time.time())}
    _xometry_session_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    append_message = (
        f"Xometry session {('OK' if data.get('ok') else 'INVALID')} "
        f"phase={data.get('phase') or '-'} reason={data.get('reason') or '-'}"
    )
    from .store import append_event
    append_event("xometry.session", append_message, ok=bool(data.get("ok")), reason=data.get("reason") or "")
    return _read_xometry_session()


def _find_known_job(job_id: str = "", offer_id: str = "") -> dict[str, Any] | None:
    job_id_norm = str(job_id or "").strip().lower()
    offer_id_norm = str(offer_id or "").strip()
    for state in list_jobs(1000):
        job = state.get("job") or {}
        current_job_id = str(state.get("job_id") or job.get("id") or job.get("job_id") or "").strip()
        current_offer_id = str(state.get("offer_id") or job.get("offer_id") or "").strip()
        if job_id_norm and current_job_id.lower() == job_id_norm:
            return {**job, "id": current_job_id, "offer_id": current_offer_id or job.get("offer_id")}
        if offer_id_norm and current_offer_id == offer_id_norm:
            return {**job, "id": current_job_id or job.get("id"), "offer_id": current_offer_id}
    return None


def _manual_job_from_payload(payload: ManualJobPayload) -> dict[str, Any]:
    identifier = str(payload.identifier or "").strip()
    url = str(payload.url or "").strip()
    offer_id = str(payload.offer_id or "").strip()
    job_id = str(payload.job_id or "").strip()

    source_text = " ".join(value for value in (identifier, url, offer_id, job_id) if value)
    if not url and identifier.lower().startswith(("http://", "https://")):
        url = identifier
    offer_match = OFFER_URL_RE.search(url or identifier)
    if offer_match and not offer_id:
        offer_id = offer_match.group(1)
    rfq_match = RFQ_URL_RE.search(url or identifier)
    if rfq_match:
        rfq_slug = rfq_match.group(1).strip()
        if not job_id:
            job_id = rfq_slug.upper() if rfq_slug.upper().startswith("RFQ-") else f"RFQ-{rfq_slug}"
        if not offer_id:
            offer_id = rfq_slug
    job_match = JOB_ID_RE.search(source_text)
    if job_match and not job_id:
        job_id = job_match.group(0).upper()
    if not offer_id and identifier.isdigit():
        offer_id = identifier

    known = _find_known_job(job_id=job_id, offer_id=offer_id) or {}
    if not job_id:
        job_id = str(known.get("id") or known.get("job_id") or offer_id or "manual")
    if not offer_id:
        offer_id = str(known.get("offer_id") or "")
    if not url:
        url = str(known.get("link") or known.get("url") or _xometry_offer_url(offer_id, job_id))

    job = {
        **known,
        "id": job_id,
        "job_id": job_id,
        "offer_id": offer_id,
        "title": known.get("title") or known.get("job_name") or job_id,
        "job_name": known.get("job_name") or job_id,
        "link": url,
        "url": url,
        "process": known.get("process") or "sheet metal, laser cutting, bending",
        "raw_text": f"{known.get('raw_text') or ''} manual sheet metal laser cutting bending".strip(),
        "manual": True,
    }
    if not job.get("parts"):
        job["parts"] = [{"process": "Sheet", "processType": "Laser Cutting", "part_id": job_id}]
    return job


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "xometry-analiza-agents"}


@app.get("/favicon.svg")
def favicon_svg() -> Response:
    return Response(FAVICON_SVG, media_type="image/svg+xml")


@app.get("/favicon.ico")
def favicon_ico() -> Response:
    return Response(FAVICON_SVG, media_type="image/svg+xml")


@app.get("/metrics")
def metrics() -> Response:
    return Response(
        prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/api/observability/summary")
def observability_summary_api(limit: int = 10000) -> dict[str, Any]:
    return observability_summary(job_limit=limit)


@app.get("/api/observability/jobs")
def observability_jobs_api(limit: int = 200) -> dict[str, Any]:
    return {"items": observability_summary(job_limit=limit)["jobs"]["recent"][:limit]}


@app.post("/api/agents/jobs")
def submit_jobs(payload: AgentJobsPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    result = queue_store.enqueue_jobs(payload.jobs, payload.source)
    return {"ok": True, "queued": result["queued"], "added": result["added"], "skipped": result["skipped"], "source": payload.source}


@app.post("/api/queue/manual")
def submit_manual_job(payload: ManualJobPayload) -> dict[str, Any]:
    job = _manual_job_from_payload(payload)
    if not (job.get("link") or job.get("url")):
        raise HTTPException(status_code=400, detail="Nu pot construi URL Xometry pentru acest job.")
    result = queue_store.enqueue_jobs([job], payload.source or "manual", force=payload.force, front=payload.front)
    return {"ok": True, "job": job, "result": result}


@app.get("/api/agents/logs")
def logs(limit: int = 50) -> dict[str, Any]:
    return {"items": read_events(limit)}


@app.get("/api/agents/jobs")
def jobs(limit: int = 100) -> dict[str, Any]:
    return {"items": list_jobs(limit)}


def _history_items(limit: int = 300) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for state in list_jobs(limit):
        sheet = state.get("sheet_metal_laser") or {}
        if not sheet:
            continue
        job = state.get("job") or {}
        result = sheet.get("ofertare_result") or {}
        geo_items = sheet.get("geo_items") or []
        ready_geo_count = len([item for item in geo_items if item.get("geo_exists") is True])
        requested_geo_count = len([item for item in geo_items if item.get("target_path")])
        started_ts = float(sheet.get("started_ts") or 0)
        completed_ts = float(sheet.get("completed_ts") or 0)
        duration_seconds = float(sheet.get("process_duration_seconds") or 0)
        if not duration_seconds and started_ts and completed_ts:
            duration_seconds = max(0, completed_ts - started_ts)
        project_root = str(result.get("projectRoot") or result.get("project_root") or "")
        project_name = str(result.get("projectName") or project_root.replace("\\", "/").rstrip("/").split("/")[-1] or "")
        offer_id = str(state.get("offer_id") or job.get("offer_id") or "")
        job_id = str(state.get("job_id") or job.get("id") or offer_id or "")
        items.append(
            {
                "job_id": job_id,
                "offer_id": offer_id,
                "title": job.get("title") or job.get("job_name") or job_id,
                "url": job.get("link") or job.get("url") or "",
                "status": sheet.get("status") or "",
                "project_root": project_root,
                "project_name": project_name,
                "identified_parts_count": int(sheet.get("identified_parts_count") or 0),
                "processed_parts_count": int(sheet.get("processed_parts_count") or ready_geo_count),
                "geo_count": requested_geo_count,
                "ready_geo_count": ready_geo_count,
                "updated_ts": state.get("updated_ts") or sheet.get("completed_ts") or sheet.get("started_ts") or 0,
                "started_ts": started_ts,
                "completed_ts": completed_ts,
                "duration_seconds": duration_seconds,
                "error": sheet.get("error") or "",
                "failure_action": sheet.get("failure_action") or "",
                "failure_type": sheet.get("failure_type") or "",
            }
        )
    return sorted(items, key=lambda item: float(item.get("updated_ts") or 0), reverse=True)


@app.get("/api/agents/history")
def agent_history(limit: int = 300) -> dict[str, Any]:
    return {"items": _history_items(limit)}


def _xometry_log_path(result: dict[str, Any]) -> str:
    for file_path in result.get("files") or []:
        path = str(file_path or "")
        if path.replace("\\", "/").lower().endswith("/doc/xometry_steps.log") or path.lower().endswith("\\doc\\xometry_steps.log"):
            return path
    project_root = str(result.get("projectRoot") or result.get("project_root") or "").rstrip("\\/")
    if project_root:
        return f"{project_root}\\DOC\\xometry_steps.log"
    return ""


def _xometry_log_lines_from_state(state: dict[str, Any]) -> tuple[list[str], str]:
    sheet = state.get("sheet_metal_laser") or {}
    result = sheet.get("ofertare_result") or {}
    log_path = _xometry_log_path(result)
    if log_path:
        try:
            text = read_remote_file(log_path).decode("utf-8", "replace")
            lines = [line.rstrip() for line in text.splitlines() if line.strip()]
            if lines:
                return lines, log_path
        except Exception:
            pass
    fallback_lines: list[str] = []
    for item in result.get("warnings") or []:
        for raw_line in str(item or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("XometryLog:"):
                line = line[len("XometryLog:"):].strip()
            if any(marker in line for marker in ("start:", "login.", "navigate.", "capture.", "download.", "finish:")):
                fallback_lines.append(line)
    return fallback_lines, log_path


@app.get("/api/agents/history/view", response_class=HTMLResponse)
def agent_history_view(limit: int = 300) -> HTMLResponse:
    rows = []
    for item in _history_items(limit):
        offer_id = str(item.get("offer_id") or "")
        job_id = str(item.get("job_id") or "")
        xometry_url = str(item.get("url") or "")
        if not xometry_url and offer_id:
            xometry_url = f"https://partner.xometry.eu/offers/{quote(offer_id, safe='')}?gsh=true&source=jobs&locale=en"
        project_name = str(item.get("project_name") or "")
        project_root = str(item.get("project_root") or "")
        status = str(item.get("status") or "")
        error = str(item.get("error") or "")
        failure_action = str(item.get("failure_action") or "")
        geo_count = int(item.get("geo_count") or 0)
        ready_geo_count = int(item.get("ready_geo_count") or 0)
        completed_ts = float(item.get("completed_ts") or item.get("updated_ts") or 0)
        identified_parts = int(item.get("identified_parts_count") or 0)
        processed_parts = int(item.get("processed_parts_count") or ready_geo_count)
        duration_seconds = float(item.get("duration_seconds") or 0)
        xometry_link = (
            f'<a href="{html.escape(xometry_url, quote=True)}" target="_blank" rel="noreferrer">{html.escape(job_id)}</a>'
            if xometry_url
            else html.escape(job_id)
        )
        dosar_link = (
            f'<a class="button green" href="/api/agents/project/{quote(offer_id, safe="")}" target="_blank" rel="noreferrer">{html.escape(project_name or "Dosar")}</a>'
            if offer_id and project_root
            else '<span class="muted">-</span>'
        )
        xometry_log_link = (
            f'<a class="button secondary" href="/api/agents/xometry-log/{quote(offer_id, safe="")}/view" target="_blank" rel="noreferrer">Log Xometry</a>'
            if offer_id and project_root
            else ""
        )
        geo_link = (
            f'<a class="button" href="/api/agents/geo/{quote(offer_id, safe="")}/view" target="_blank" rel="noreferrer">GEO {ready_geo_count}</a>'
            if offer_id and ready_geo_count
            else '<span class="muted">-</span>'
        )
        geo_note = f"cerute: {geo_count} / gata: {ready_geo_count}" if geo_count else f"gata: {ready_geo_count}"
        error_html = html.escape(error)
        if failure_action:
            error_html += f'<div class="muted">{html.escape(failure_action)}</div>'
        repeat_identifier = xometry_url or job_id or offer_id
        repeat_button = (
            f'<button type="button" class="button repeat" data-repeat="{html.escape(repeat_identifier, quote=True)}">Repeta</button>'
            if repeat_identifier
            else '<span class="muted">-</span>'
        )
        rows.append(
            f"<tr>"
            f"<td><strong>{xometry_link}</strong><div class=\"muted\">{html.escape(offer_id)}</div></td>"
            f"<td><span class=\"status {html.escape(status)}\">{html.escape(status or '-')}</span></td>"
            f"<td>{dosar_link} {xometry_log_link}<div class=\"muted path\">{html.escape(project_root)}</div></td>"
            f"<td>{geo_link}<div class=\"muted\">{html.escape(geo_note)}</div></td>"
            f"<td><strong>{processed_parts}/{identified_parts or '-'}</strong><div class=\"muted\">procesate / identificate</div></td>"
            f"<td data-duration=\"{duration_seconds}\"></td>"
            f"<td data-ts=\"{completed_ts}\"></td>"
            f"<td class=\"err\">{error_html}</td>"
            f"<td>{repeat_button}</td>"
            f"</tr>"
        )
    table_rows = "".join(rows) or '<tr><td colspan="9">Nu exista istoric inca.</td></tr>'
    return HTMLResponse(f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Istoric XometryAnaliza</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body{{margin:0;background:#f3f6f9;color:#172033;font-family:Arial,sans-serif}}
    header{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 26px;background:#111827;color:white}}
    h1{{margin:0;font-size:24px}} .sub{{margin-top:6px;color:#cbd5e1}}
    main{{padding:18px 22px}}
    .top-actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}
    .qa-link{{display:inline-flex;align-items:center;min-height:34px;padding:0 12px;border:1px solid white;border-radius:5px;background:white;color:#0958d9;text-decoration:none;font-weight:700}}
    .result{{margin:0 0 12px;padding:10px 12px;border:1px solid #d9e2ec;border-radius:6px;background:white;font-size:13px;font-weight:700;display:none}}
    .result.ok{{display:block;color:#166534;border-color:#86efac;background:#f0fdf4}}
    .result.bad{{display:block;color:#991b1b;border-color:#fecaca;background:#fff1f2}}
    table{{width:100%;border-collapse:collapse;background:white;border:1px solid #d9e2ec;border-radius:8px;overflow:hidden}}
    th,td{{padding:10px 12px;border-bottom:1px solid #e5eaf0;text-align:left;vertical-align:top;font-size:14px}}
    th{{background:#f8fafc;font-size:12px;text-transform:uppercase;color:#52606d}}
    a{{color:#0958d9;text-decoration:none;font-weight:700}} a:hover{{text-decoration:underline}}
    .button{{display:inline-flex;align-items:center;min-height:28px;padding:0 9px;border:1px solid #1677ff;border-radius:4px;background:white;color:#0958d9;text-decoration:none;font-weight:700}}
    button.button{{cursor:pointer;font:inherit}}
    .repeat{{border-color:#0f766e;color:#0f766e;background:#f0fdfa}}
    .green{{border-color:#16a34a;background:#ecfdf3;color:#166534}}
    .secondary{{border-color:#64748b;color:#334155}}
    .muted{{margin-top:4px;color:#64748b;font-size:12px}} .path{{max-width:520px;word-break:break-all}}
    .status{{display:inline-flex;min-height:22px;align-items:center;border-radius:999px;padding:0 8px;background:#e2e8f0;color:#334155;font-size:12px;font-weight:700}}
    .geo_ready,.cached{{background:#dcfce7;color:#166534}} .running{{background:#dbeafe;color:#1d4ed8}} .failed,.blocked_login,.blocked_documentation{{background:#fee2e2;color:#991b1b}} .geo_requested{{background:#fef3c7;color:#92400e}}
    .err{{max-width:360px;color:#991b1b;font-size:12px;word-break:break-word}}
  </style>
</head>
<body>
  <header>
    <div><h1>Istoric XometryAnaliza</h1><div class="sub">Oferte procesate de agentul sheet/laser</div></div>
    <div class="top-actions"><a class="qa-link" href="/">Inapoi la QA</a></div>
  </header>
  <main>
    <div id="repeatResult" class="result"></div>
    <table>
      <thead><tr><th>Oferta</th><th>Status</th><th>Dosar</th><th>GEO</th><th>Piese</th><th>Durata</th><th>Finalizat</th><th>Eroare</th><th>Actiuni</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </main>
  <script>
    const fmtDuration = seconds => {{
      seconds = Math.max(0, Math.round(Number(seconds || 0)));
      if (!seconds) return '-';
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = seconds % 60;
      if (h) return `${{h}}h ${{m}}m`;
      if (m) return `${{m}}m ${{s}}s`;
      return `${{s}}s`;
    }};
    document.querySelectorAll('td[data-duration]').forEach(td => {{
      td.textContent = fmtDuration(td.dataset.duration);
    }});
    document.querySelectorAll('td[data-ts]').forEach(td => {{
      const ts = Number(td.dataset.ts || 0);
      td.textContent = ts ? new Date(ts * 1000).toLocaleString() : '-';
    }});
    async function repeatJob(identifier) {{
      const result = document.getElementById('repeatResult');
      result.className = 'result';
      result.textContent = 'Trimit jobul in coada...';
      try {{
        const response = await fetch('/api/queue/manual', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{identifier, force: true, front: true, source: 'history-repeat'}})
        }});
        const data = await response.json();
        const added = data?.result?.added || 0;
        result.className = 'result ' + (added ? 'ok' : 'bad');
        result.textContent = added
          ? `Retrimis primul in coada: ${{data.job?.id || identifier}}`
          : `Nu l-am putut retrimite: ${{data?.detail || 'verifica daca este sheet/laser sau deja activ'}}`;
      }} catch (err) {{
        result.className = 'result bad';
        result.textContent = 'Eroare la retrimitere.';
      }}
    }}
    document.querySelectorAll('[data-repeat]').forEach(button => {{
      button.addEventListener('click', () => repeatJob(button.dataset.repeat || ''));
    }});
  </script>
</body>
</html>""")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse("""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>XometryAnaliza Queue</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body{margin:0;background:#f3f6f9;color:#172033;font-family:Arial,sans-serif}
    header{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:16px 20px;background:#111827;color:white}
    h1{margin:0;font-size:20px} .sub{color:#cbd5e1;font-size:12px;margin-top:3px}
    .top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}
    .toplink{display:inline-flex;align-items:center;height:30px;padding:0 10px;border-radius:999px;background:white;color:#0958d9;text-decoration:none;font-size:12px;font-weight:700}
    main{display:grid;grid-template-columns:360px 1fr;gap:16px;padding:16px}
    section{background:white;border:1px solid #d9e2ec;border-radius:8px;overflow:hidden}
    h2{margin:0;padding:12px 14px;border-bottom:1px solid #e5eaf0;font-size:15px;background:#f8fafc}
    .panel{padding:12px 14px}.active{border-left:5px solid #1677ff}.idle{border-left:5px solid #94a3b8}
    .job{display:grid;grid-template-columns:1fr auto;gap:10px;padding:10px;border-bottom:1px solid #eef2f7}
    .job:last-child{border-bottom:0}.id{font-weight:700}.id a{color:#0f172a;text-decoration:none}.id a:hover{color:#0958d9;text-decoration:underline}.meta{font-size:12px;color:#52606d;margin-top:4px}
    .pill{display:inline-flex;align-items:center;min-height:22px;padding:0 8px;border-radius:999px;background:#e6f4ff;color:#0958d9;font-size:12px;font-weight:700}
    .button{display:inline-flex;align-items:center;justify-content:center;height:30px;padding:0 10px;border:1px solid #16a34a;border-radius:4px;background:#ecfdf3;color:#166534;text-decoration:none;font-size:12px;font-weight:700}
    button,input{height:30px;border:1px solid #cbd5e1;border-radius:4px;background:white;font-weight:700}
    button{cursor:pointer;padding:0 9px} input{width:62px;padding:0 6px}
    .actions{display:flex;align-items:center;gap:6px}.log{font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap}
    .manual{display:flex;gap:8px;align-items:center}.manual input{width:100%;min-width:0}.manual button{white-space:nowrap;background:#1677ff;color:white;border-color:#1677ff}
    .hint{margin-top:8px;font-size:12px;color:#52606d}.result{margin-top:8px;font-size:12px;font-weight:700}.ok{color:#166534}.bad{color:#991b1b}
    .session{border-left:5px solid #94a3b8}.session.ok{border-left-color:#16a34a}.session.bad{border-left-color:#dc2626}
    .session .state{font-size:18px;font-weight:800}.session .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:8px}
    .session .check{font-size:12px;border:1px solid #d9e2ec;border-radius:4px;padding:6px;background:#f8fafc}
    .session .check.yes{border-color:#86efac;background:#f0fdf4;color:#166534}.session .check.no{border-color:#fecaca;background:#fff1f2;color:#991b1b}
    @media(max-width:900px){main{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <header><div><h1>XometryAnaliza</h1><div class="sub">TecZone laptop queue, GEO, bend status</div></div><div class="top"><a class="toplink" href="/api/agents/history/view" target="_blank" rel="noreferrer">Istoric</a><a class="toplink" href="/metrics" target="_blank" rel="noreferrer">Metrics</a><div id="summary"></div></div></header>
  <main>
    <div>
      <section>
        <h2>Trimite job manual</h2>
        <div class="panel">
          <form class="manual" onsubmit="submitManual(event)">
            <input id="manualJob" placeholder="URL, offer id, HJO-..., J-... sau RFQ URL" autocomplete="off">
            <button type="submit">Trimite job</button>
          </form>
          <div class="hint">Il pune primul in coada si forteaza refacerea daca a mai fost vazut.</div>
          <div id="manualResult" class="result"></div>
        </div>
      </section>
      <section id="xometrySession" style="margin-top:16px"></section>
      <section id="active" style="margin-top:16px"></section>
      <section style="margin-top:16px"><h2>Logs</h2><div id="logs" class="panel log"></div></section>
    </div>
    <section><h2>Urmatoarele pentru laptop</h2><div id="queue"></div></section>
  </main>
  <script>
    const api = async (url, options={}) => (await fetch(url,{headers:{'Content-Type':'application/json'},...options})).json();
    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    const fmtDuration = (seconds) => {
      seconds = Math.max(0, Math.round(Number(seconds || 0)));
      if (!seconds) return '-';
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = seconds % 60;
      if (h) return `${h}h ${m}m`;
      if (m) return `${m}m ${s}s`;
      return `${s}s`;
    };
    const xometryUrl = (item) => item?.url || (item?.offer_id ? `https://partner.xometry.eu/offers/${encodeURIComponent(item.offer_id)}?gsh=true&source=jobs&locale=en` : '');
    function jobName(item, prefix=''){
      const url = xometryUrl(item);
      const label = esc(item?.job_id || item?.title || item?.offer_id || 'oferta');
      const text = `${prefix}${label}`;
      return url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${text}</a>` : text;
    }
    function progressHtml(item){
      if (!item) return '';
      const identified = Number(item.identified_parts_count || 0);
      const processed = Number(item.processed_parts_count || item.geo_ready_count || 0);
      const ready = Number(item.geo_ready_count || 0);
      const requested = Number(item.geo_requested_count || 0);
      const elapsed = Number(item.analysis_elapsed_seconds || 0);
      const duration = Number(item.process_duration_seconds || 0);
      const diagnostic = item.error ? `<div class="meta bad">${esc(item.error)}</div>` : '';
      const action = item.failure_action ? `<div class="meta">${esc(item.failure_action)}</div>` : '';
      return `<div class="meta">piese: ${processed}/${identified || '-'} procesate - GEO: ${ready}/${requested} gata - in analiza: ${fmtDuration(elapsed)}${duration ? ` - durata finala: ${fmtDuration(duration)}` : ''}</div>${diagnostic}${action}`;
    }
    function projectButton(item){
      if (!item?.offer_id) return '';
      if (!item?.project_root) return `<div style="margin-top:10px"><a class="button" href="http://192.168.2.26:8585" target="_blank" rel="noreferrer">Deschide Ofertare</a></div>`;
      return `<div style="margin-top:10px"><a class="button" href="/api/agents/project/${encodeURIComponent(item.offer_id)}" target="_blank" rel="noreferrer">Dosar activ: ${esc(item.project_name || item.project_root)}</a></div>`;
    }
    function fmtAge(seconds){
      seconds = Math.max(0, Math.round(Number(seconds || 0)));
      if (!seconds) return 'niciodata';
      const m = Math.floor(seconds / 60);
      if (m < 1) return `${seconds}s in urma`;
      const h = Math.floor(m / 60);
      if (!h) return `${m}m in urma`;
      return `${h}h ${m % 60}m in urma`;
    }
    function renderXometrySession(session){
      session = session || {};
      const ok = !!session.ok;
      const age = fmtAge(session.age_seconds || 0);
      const reason = session.reason || 'never_checked';
      const phase = session.phase || '-';
      const url = session.url || '';
      const checks = [
        ['Token', session.auth_token_present],
        ['API', session.api_ok],
        ['Job Board', session.job_board],
        ['Login form', !session.login_form],
      ].map(([label, value]) => `<div class="check ${value ? 'yes' : 'no'}">${esc(label)}: ${value ? 'OK' : 'NU'}</div>`).join('');
      const details = [
        `faza: ${phase}`,
        `motiv: ${reason}`,
        `verificat: ${age}`,
        session.jobs_count != null ? `joburi scrape: ${session.jobs_count}` : '',
        session.api_reason ? `api: ${session.api_reason}` : '',
      ].filter(Boolean).map(esc).join(' · ');
      document.getElementById('xometrySession').innerHTML =
        `<h2>Sesiune Xometry</h2><div class="panel session ${ok ? 'ok' : 'bad'}">` +
        `<div class="state">${ok ? 'Conectat valid' : 'Problema login/sesiune'}</div>` +
        `<div class="meta">${details}</div>` +
        (url ? `<div class="meta"><a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a></div>` : '') +
        `<div class="grid">${checks}</div>` +
        (session.body_sample && !ok ? `<div class="meta bad">${esc(session.body_sample).slice(0,260)}</div>` : '') +
        `</div>`;
    }
    async function move(id, direction){ await api('/api/queue/'+encodeURIComponent(id)+'/move',{method:'POST',body:JSON.stringify({direction})}); refresh(); }
    async function position(id, el){ await api('/api/queue/'+encodeURIComponent(id)+'/priority',{method:'POST',body:JSON.stringify({priority:Number(el.value||1)})}); refresh(); }
    async function submitManual(event){
      event.preventDefault();
      const input = document.getElementById('manualJob');
      const result = document.getElementById('manualResult');
      const value = input.value.trim();
      if (!value) return;
      result.className = 'result';
      result.textContent = 'Trimit...';
      try {
        const data = await api('/api/queue/manual',{method:'POST',body:JSON.stringify({identifier:value,force:true,front:true})});
        const added = data?.result?.added || 0;
        const skippedActive = data?.result?.skipped_active || 0;
        result.className = 'result ' + (added ? 'ok' : 'bad');
        result.textContent = added ? `Adaugat primul in coada: ${data.job?.id || value}` : (skippedActive ? 'Jobul este deja activ pe laptop.' : 'Nu a fost adaugat. Verifica daca este sheet/laser sau URL valid.');
        if (added) input.value = '';
        refresh();
      } catch (err) {
        result.className = 'result bad';
        result.textContent = 'Eroare la trimitere.';
      }
    }
    function jobHtml(item, i){
      const title = esc(item.title || item.job_id);
      const id = esc(item.job_id);
      return `<div class="job"><div><div class="id">${jobName(item, `${i+1}. `)}</div><div class="meta">${title}</div><div class="meta">${esc(item.offer_id||'')} ${esc(item.source||'')}</div></div><div class="actions"><input type="number" min="1" value="${i+1}" onchange="position('${id}',this)"><button onclick="move('${id}','up')">Up</button><button onclick="move('${id}','down')">Down</button></div></div>`;
    }
    function renderDashboard(data, logs, xometrySession){
      renderXometrySession(xometrySession || {});
      const paused = data.paused;
      const pauseUntil = data.paused_until ? new Date(data.paused_until * 1000).toLocaleTimeString() : '';
      document.getElementById('summary').innerHTML = `<span class="pill">${data.running?'laptop lucreaza':paused?'Dorina ocupata':'idle'}</span> <span class="pill">${data.queued_count} sheet/laser in coada</span>`;
      const active = data.active;
      const pausedItem = data.paused_item;
      const idleText = paused ? `Dorina este ocupata in TecZone. Reiau coada la ${pauseUntil}.<div class="meta">${data.pause_reason||''}</div>` : 'Laptopul nu proceseaza desfasurata acum.';
      const pausedHtml = pausedItem ? `<div class="id">${jobName(pausedItem)}</div><div class="meta">${esc(data.pause_reason||'')}</div>${progressHtml(pausedItem)}${projectButton(pausedItem)}` : idleText;
      document.getElementById('active').innerHTML = `<h2>Laptop TecZone activ</h2><div class="panel ${active?'active':paused?'active':'idle'}">${active?`<div class="id">${jobName(active)}</div><div class="meta">${esc(active.title||'')}</div><div class="meta">pornit: ${new Date((active.started_ts||0)*1000).toLocaleString()}</div>${progressHtml(active)}${projectButton(active)}`:pausedHtml}</div>`;
      document.getElementById('queue').innerHTML = (data.queued||[]).map(jobHtml).join('') || '<div class="panel">Nu sunt joburi sheet/laser in asteptare.</div>';
      document.getElementById('logs').textContent = (logs.items||[]).reverse().map(x => `${new Date((x.ts||0)*1000).toLocaleTimeString()} ${x.type}: ${x.message}`).join('\\n');
    }
    async function refresh(){
      const payload = await api('/api/queue/live');
      renderDashboard(payload.queue || payload, {items: payload.logs || []}, payload.xometry_session || {});
    }
    let fallbackTimer = null;
    function startFallback(){
      if (!fallbackTimer) fallbackTimer = setInterval(refresh, 5000);
    }
    function stopFallback(){
      if (fallbackTimer) {
        clearInterval(fallbackTimer);
        fallbackTimer = null;
      }
    }
    function startLiveStream(){
      if (!window.EventSource) {
        refresh();
        startFallback();
        return;
      }
      const source = new EventSource('/api/queue/stream');
      source.addEventListener('snapshot', event => {
        try {
          const payload = JSON.parse(event.data);
          renderDashboard(payload.queue || {}, {items: payload.logs || []}, payload.xometry_session || {});
          stopFallback();
        } catch (err) {
          startFallback();
        }
      });
      source.onerror = () => {
        startFallback();
      };
      refresh();
    }
    startLiveStream();
  </script>
</body>
</html>""")


@app.get("/api/queue")
def queue_status() -> dict[str, Any]:
    return queue_store.get_queue_state()


@app.get("/api/xometry/session")
def xometry_session() -> dict[str, Any]:
    return _read_xometry_session()


@app.post("/api/xometry/session")
def update_xometry_session(payload: XometrySessionPayload) -> dict[str, Any]:
    return {"session": _write_xometry_session(payload.dict())}


def _compact_queue_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    keys = (
        "job_id",
        "offer_id",
        "title",
        "url",
        "source",
        "priority",
        "status",
        "started_ts",
        "project_root",
        "project_name",
        "agent_status",
        "error",
        "failure_action",
        "failure_type",
        "identified_parts_count",
        "processed_parts_count",
        "geo_ready_count",
        "geo_requested_count",
        "analysis_started_ts",
        "analysis_completed_ts",
        "analysis_elapsed_seconds",
        "process_duration_seconds",
    )
    return {key: item.get(key) for key in keys if key in item}


def _queue_live_state() -> dict[str, Any]:
    state = queue_store.get_queue_state()
    return {
        "active": _compact_queue_item(state.get("active")),
        "paused_item": _compact_queue_item(state.get("paused_item")),
        "queued": [_compact_queue_item(item) for item in state.get("queued") or []],
        "running": bool(state.get("running")),
        "worker_alive": bool(state.get("worker_alive")),
        "queued_count": int(state.get("queued_count") or 0),
        "completed_count": int(state.get("completed_count") or 0),
        "paused": bool(state.get("paused")),
        "paused_until": state.get("paused_until") or 0,
        "pause_reason": state.get("pause_reason") or "",
        "last_process_seconds": state.get("last_process_seconds") or 0,
        "active_analysis_elapsed_seconds": (state.get("active") or {}).get("analysis_elapsed_seconds") or 0,
        "active_identified_parts_count": (state.get("active") or {}).get("identified_parts_count") or 0,
        "active_processed_parts_count": (state.get("active") or {}).get("processed_parts_count") or 0,
        "active_geo_ready_count": (state.get("active") or {}).get("geo_ready_count") or 0,
    }


def _compact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ts": item.get("ts"),
            "type": item.get("type"),
            "message": item.get("message"),
            "job_id": item.get("job_id"),
            "offer_id": item.get("offer_id"),
        }
        for item in events
    ]


@app.get("/api/queue/live")
def queue_live() -> dict[str, Any]:
    return {"queue": _queue_live_state(), "logs": _compact_events(read_events(20)), "xometry_session": _read_xometry_session()}


@app.get("/api/queue/stream")
def queue_stream() -> StreamingResponse:
    def events():
        last_payload = ""
        while True:
            snapshot = {
                "queue": _queue_live_state(),
                "logs": _compact_events(read_events(20)),
                "xometry_session": _read_xometry_session(),
            }
            text = json.dumps(snapshot, ensure_ascii=False, default=str)
            if text != last_payload:
                payload = {"ts": time.time(), **snapshot}
                yield f"event: snapshot\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                last_payload = text
            else:
                yield f": heartbeat {int(time.time())}\n\n"
            time.sleep(2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/queue/{job_id}/priority")
def queue_priority(job_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return queue_store.set_priority(job_id, int(payload.get("priority") or 1))


@app.post("/api/queue/{job_id}/move")
def queue_move(job_id: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return queue_store.move(job_id, str(payload.get("direction") or "up"))


@app.post("/api/queue/reorder")
def queue_reorder(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return queue_store.reorder([str(item) for item in payload.get("job_ids") or []])


def _bend_summary_from_geo_items(offer_id: str, job_id: str | None, geo_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not geo_items:
        return None
    issues = []
    warnings = []
    for item in geo_items:
        status = str(item.get("status") or "").lower()
        classification = str(item.get("classification") or "").lower()
        reason = str(item.get("reason") or item.get("message") or "")
        is_issue = False
        if status and status not in ("ok", "success", "geo_ready", "done", "cached"):
            is_issue = True
        if item.get("bendable") is False:
            is_issue = True
        if classification and classification not in ("ok", "success", "bendable", "ready"):
            is_issue = True
        if reason and any(token in reason.lower() for token in ("eroare", "failed", "nu accepta", "problem", "unsupported")):
            is_issue = True
        if is_issue:
            issues.append(item)
        elif reason:
            warnings.append(reason)

    has_issues = bool(issues)
    return {
        "ok": True,
        "job_id": job_id,
        "offer_id": offer_id,
        "has_bend_issues": has_issues,
        "status": "probleme la indoire" if has_issues else "fara probleme la indoire",
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "source": "geo_items",
        "artifacts": [],
    }


def _check_mcp_token(x_mcp_token: str | None) -> None:
    token = getattr(settings, "MCP_TOKEN", "")
    if token and x_mcp_token != token:
        raise HTTPException(status_code=401, detail="Invalid MCP token")


@app.get("/mcp/tools")
def mcp_tools(x_mcp_token: str | None = Header(default=None)) -> dict[str, Any]:
    _check_mcp_token(x_mcp_token)
    return {
        "server": "xometryanaliza",
        "endpoint": "/mcp",
        "methods": {
            "queue.status": {},
            "queue.set_priority": {"job_id": "HJO-... or J-...", "priority": 2},
            "queue.move": {"job_id": "HJO-... or J-...", "direction": "up|down"},
            "queue.reorder": {"job_ids": ["HJO-1", "J-2"]},
            "queue.submit": {"source": "hermes", "jobs": []},
            "queue.submit_manual": {"identifier": "URL, offer id, HJO-..., J-... or RFQ URL", "force": True, "front": True},
        },
    }


@app.post("/mcp")
def mcp(payload: dict[str, Any] = Body(default_factory=dict), x_mcp_token: str | None = Header(default=None)) -> dict[str, Any]:
    _check_mcp_token(x_mcp_token)
    method = payload.get("method")
    params = payload.get("params") or {}
    if method == "queue.status":
        result = queue_store.get_queue_state()
    elif method == "queue.set_priority":
        result = queue_store.set_priority(str(params.get("job_id")), int(params.get("priority") or 1))
    elif method == "queue.move":
        result = queue_store.move(str(params.get("job_id")), str(params.get("direction") or "up"))
    elif method == "queue.reorder":
        result = queue_store.reorder([str(item) for item in params.get("job_ids") or []])
    elif method == "queue.submit":
        result = queue_store.enqueue_jobs(params.get("jobs") or [], params.get("source") or "hermes")
    elif method == "queue.submit_manual":
        manual = ManualJobPayload(
            identifier=str(params.get("identifier") or ""),
            job_id=str(params.get("job_id") or ""),
            offer_id=str(params.get("offer_id") or ""),
            url=str(params.get("url") or ""),
            source=str(params.get("source") or "hermes"),
            force=bool(params.get("force", True)),
            front=bool(params.get("front", True)),
        )
        job = _manual_job_from_payload(manual)
        result = {"job": job, **queue_store.enqueue_jobs([job], manual.source, force=manual.force, front=manual.front)}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown MCP method: {method}")
    return {"jsonrpc": "2.0", "id": payload.get("id"), "result": result}


@app.get("/api/agents/geo/{offer_id}")
def geo_status(offer_id: str) -> dict[str, Any]:
    state = find_job_by_offer_id(offer_id)
    if not state:
        return {"ok": False, "offer_id": offer_id, "status": "not_found", "geo_items": []}
    sheet = state.get("sheet_metal_laser") or {}
    geo_items = sheet.get("geo_items") or []
    bend_report = sheet.get("bend_report") or read_bend_summary(offer_id) or _bend_summary_from_geo_items(
        offer_id,
        state.get("job_id"),
        geo_items,
    )
    return {
        "ok": True,
        "offer_id": offer_id,
        "job_id": state.get("job_id"),
        "status": sheet.get("status") or "no_sheet_agent",
        "geo_items": geo_items,
        "bend_report": bend_report,
        "state": state,
    }


@app.get("/api/agents/xometry-log/{offer_id}")
def xometry_log_raw(offer_id: str) -> Response:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer state not found")
    lines, log_path = _xometry_log_lines_from_state(state)
    if not lines:
        raise HTTPException(status_code=404, detail="No Xometry automation log found for this offer yet.")
    header = f"# {log_path}\n" if log_path else "# warnings fallback\n"
    return Response(header + "\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")


@app.get("/api/agents/xometry-log/{offer_id}/view", response_class=HTMLResponse)
def xometry_log_view(offer_id: str) -> HTMLResponse:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer state not found")
    job = state.get("job") or {}
    job_id = str(state.get("job_id") or job.get("id") or offer_id)
    sheet = state.get("sheet_metal_laser") or {}
    status = str(sheet.get("status") or "")
    lines, log_path = _xometry_log_lines_from_state(state)
    raw_url = f"/api/agents/xometry-log/{quote(offer_id, safe='')}"
    project_url = f"/api/agents/project/{quote(offer_id, safe='')}"
    xometry_url = str(job.get("link") or job.get("url") or "")

    def line_class(line: str) -> str:
        lowered = line.lower()
        if "failed" in lowered or "timeout" in lowered or "error" in lowered or "nu am descarcat" in lowered:
            return "bad"
        if "download.saved" in lowered or "download.extracted" in lowered or "login.after_submit" in lowered:
            return "good"
        if "skip" in lowered or "not_visible" in lowered or "xometry_error=yes" in lowered or "login=yes" in lowered:
            return "warn"
        if "download." in lowered:
            return "download"
        if "login." in lowered:
            return "login"
        if "navigate." in lowered:
            return "nav"
        if "capture." in lowered:
            return "capture"
        return "info"

    if lines:
        rows = "".join(
            f'<div class="event {line_class(line)}"><div class="dot"></div><pre>{html.escape(line)}</pre></div>'
            for line in lines
        )
        empty = ""
    else:
        rows = ""
        empty = '<section class="empty">Nu exista inca log Xometry pentru aceasta oferta. La urmatoarea rulare va aparea DOC/xometry_steps.log.</section>'
    xometry_link = (
        f'<a class="button secondary" href="{html.escape(xometry_url, quote=True)}" target="_blank" rel="noreferrer">Oferta Xometry</a>'
        if xometry_url
        else ""
    )
    return HTMLResponse(f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Log Xometry - {html.escape(job_id)}</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body{{margin:0;background:#f4f7fb;color:#172033;font-family:Arial,sans-serif}}
    header{{padding:20px 24px;background:#111827;color:white}}
    h1{{margin:0;font-size:24px}} .sub{{margin-top:6px;color:#cbd5e1}}
    main{{padding:18px 22px;display:grid;gap:14px}}
    .actions{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
    .button{{display:inline-flex;align-items:center;min-height:34px;padding:0 12px;border:1px solid #1677ff;border-radius:5px;background:#1677ff;color:white;text-decoration:none;font-weight:700}}
    .secondary{{background:white;color:#0958d9}}
    .path{{color:#52606d;font-size:13px;word-break:break-all}}
    .timeline{{background:white;border:1px solid #d9e2ec;border-radius:8px;overflow:hidden}}
    .event{{display:grid;grid-template-columns:18px 1fr;gap:10px;padding:10px 14px;border-bottom:1px solid #eef2f7;align-items:start}}
    .event:last-child{{border-bottom:0}}
    .dot{{width:10px;height:10px;border-radius:50%;margin-top:5px;background:#64748b}}
    pre{{margin:0;white-space:pre-wrap;font:13px/1.45 Consolas,monospace;color:#172033}}
    .good .dot{{background:#16a34a}} .bad .dot{{background:#dc2626}} .warn .dot{{background:#f59e0b}}
    .login .dot{{background:#7c3aed}} .download .dot{{background:#0ea5e9}} .nav .dot{{background:#2563eb}} .capture .dot{{background:#0891b2}}
    .bad{{background:#fff1f2}} .warn{{background:#fffbeb}} .good{{background:#f0fdf4}}
    .empty{{background:white;border:1px solid #d9e2ec;border-radius:8px;padding:16px;color:#52606d}}
  </style>
</head>
<body>
  <header>
    <h1>Log Xometry - {html.escape(job_id)}</h1>
    <div class="sub">Status: {html.escape(status or "necunoscut")} &middot; Oferta {html.escape(str(offer_id))}</div>
  </header>
  <main>
    <div class="actions">
      <a class="button" href="{raw_url}" target="_blank" rel="noreferrer">Text raw</a>
      <a class="button secondary" href="{project_url}" target="_blank" rel="noreferrer">Dosar / fisiere</a>
      {xometry_link}
    </div>
    <div class="path">{html.escape(log_path or "fallback din warnings")}</div>
    {empty}
    <section class="timeline">{rows}</section>
  </main>
</body>
</html>""")


@app.get("/api/agents/project/{offer_id}", response_class=HTMLResponse)
def project_status_view(offer_id: str) -> HTMLResponse:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer state not found")
    job = state.get("job") or {}
    sheet = state.get("sheet_metal_laser") or {}
    result = sheet.get("ofertare_result") or {}
    project_root = str(result.get("projectRoot") or result.get("project_root") or "")
    files = [str(item) for item in result.get("files") or []]
    warnings = [str(item) for item in result.get("warnings") or []]
    error = str(sheet.get("error") or "")
    failure_action = str(sheet.get("failure_action") or "")
    geo_items = sheet.get("geo_items") or []
    job_id = str(state.get("job_id") or job.get("id") or offer_id)
    xometry_url = str(job.get("link") or job.get("url") or "")
    geo_url = f"/api/agents/geo/{quote(offer_id, safe='')}/view"
    xometry_log_url = f"/api/agents/xometry-log/{quote(offer_id, safe='')}/view"
    rows = "".join(f"<li><code>{html.escape(path)}</code></li>" for path in files) or "<li>Nu exista fisiere raportate inca.</li>"
    warning_rows = "".join(f"<li>{html.escape(text)}</li>" for text in warnings) or "<li>Nu sunt warning-uri raportate.</li>"
    error_block = (
        f"""<section>
      <h2>Diagnostic</h2>
      <p class="err">{html.escape(error)}</p>
      <p>{html.escape(failure_action)}</p>
    </section>"""
        if error or failure_action
        else ""
    )
    geo_rows = "".join(
        f"<li>{html.escape(str(item.get('part_name') or item.get('partName') or 'part'))}: "
        f"<code>{html.escape(str(item.get('target_path') or item.get('targetPath') or ''))}</code></li>"
        for item in geo_items
    ) or "<li>Nu exista GEO salvat inca.</li>"
    xometry_link = (
        f'<a class="button secondary" href="{html.escape(xometry_url, quote=True)}" target="_blank" rel="noreferrer">Deschide oferta Xometry</a>'
        if xometry_url
        else ""
    )
    return HTMLResponse(f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dosar activ - {html.escape(job_id)}</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body{{margin:0;background:#f3f6f9;color:#172033;font-family:Arial,sans-serif}}
    header{{padding:22px 26px;background:#111827;color:white}}
    h1{{margin:0;font-size:24px}} .sub{{margin-top:6px;color:#cbd5e1}}
    main{{padding:20px 26px;display:grid;gap:16px}}
    section{{background:white;border:1px solid #d9e2ec;border-radius:8px;padding:16px}}
    h2{{margin:0 0 10px;font-size:16px}} code{{background:#f1f5f9;padding:2px 5px;border-radius:4px}}
    ul{{margin:8px 0 0;padding-left:22px}} li{{margin:6px 0}}
    .button{{display:inline-flex;align-items:center;justify-content:center;height:34px;padding:0 12px;border:1px solid #1677ff;border-radius:5px;background:#1677ff;color:white;text-decoration:none;font-weight:700;margin-right:8px}}
    .secondary{{background:white;color:#0958d9}}
    .err{{color:#991b1b;font-weight:700}}
  </style>
</head>
<body>
  <header>
    <h1>Dosar activ - {html.escape(job_id)}</h1>
    <div class="sub">Status: {html.escape(str(sheet.get("status") or "necunoscut"))} &middot; Oferta {html.escape(str(offer_id))}</div>
  </header>
  <main>
    <section>
      <h2>Actiuni</h2>
      {xometry_link}
      <a class="button secondary" href="{geo_url}" target="_blank" rel="noreferrer">Desfasurate GEO</a>
      <a class="button secondary" href="{xometry_log_url}" target="_blank" rel="noreferrer">Log Xometry</a>
    </section>
    {error_block}
    <section>
      <h2>Folder Ofertare</h2>
      <code>{html.escape(project_root or "Nu exista projectRoot inca.")}</code>
    </section>
    <section>
      <h2>GEO</h2>
      <ul>{geo_rows}</ul>
    </section>
    <section>
      <h2>Warning-uri</h2>
      <ul>{warning_rows}</ul>
    </section>
    <section>
      <h2>Fisiere</h2>
      <ul>{rows}</ul>
    </section>
  </main>
</body>
</html>""")


@app.get("/api/agents/bend/{offer_id}")
def bend_status(offer_id: str) -> dict[str, Any]:
    summary = read_bend_summary(offer_id)
    if not summary:
        state = find_job_by_offer_id(offer_id)
        sheet = (state or {}).get("sheet_metal_laser") or {}
        summary = _bend_summary_from_geo_items(offer_id, (state or {}).get("job_id"), sheet.get("geo_items") or [])
    if not summary:
        return {"ok": False, "offer_id": offer_id, "status": "not_found", "has_bend_issues": None, "artifacts": []}
    return {"ok": True, **summary}


@app.get("/api/agents/bend/{offer_id}/artifacts/{filename}")
def bend_artifact(offer_id: str, filename: str) -> Response:
    try:
        path = artifact_path(offer_id, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    if path.suffix.lower() == ".html":
        media_type = "text/html; charset=utf-8"
    elif path.suffix.lower() == ".png":
        media_type = "image/png"
    else:
        media_type = "application/json"
    return Response(path.read_bytes(), media_type=media_type)


@app.get("/api/agents/geo/{offer_id}/view")
def geo_all_view(offer_id: str) -> HTMLResponse:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer not found in XometryAnaliza.")

    job = state.get("job") or {}
    job_id = str(state.get("job_id") or job.get("id") or offer_id)
    xometry_url = str(job.get("link") or job.get("url") or "")
    sheet = state.get("sheet_metal_laser") or {}
    geo_items = sheet.get("geo_items") or []
    ready_indexes = [
        index for index, item in enumerate(geo_items)
        if item.get("geo_exists") is True and item.get("target_path")
    ]

    if not ready_indexes:
        xometry_link = (
            f'<a class="button secondary" href="{html.escape(xometry_url, quote=True)}" target="_blank" rel="noreferrer">Deschide oferta Xometry</a>'
            if xometry_url
            else ""
        )
        requested_count = len([item for item in geo_items if item.get("target_path")])
        return HTMLResponse(f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Desfasurate GEO - {html.escape(job_id)}</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body{{margin:0;background:#f3f6f9;color:#172033;font-family:Arial,sans-serif}}
    header{{padding:28px 32px;background:#111827;color:white}}
    h1{{margin:0;font-size:26px}} .sub{{margin-top:8px;color:#cbd5e1}}
    main{{padding:24px 32px}}
    .card{{background:white;border:1px solid #d9e2ec;border-radius:8px;padding:18px;max-width:760px}}
    .button{{display:inline-flex;align-items:center;justify-content:center;min-height:38px;padding:0 14px;border:1px solid #1677ff;border-radius:4px;background:white;color:#0958d9;text-decoration:none;font-weight:700}}
  </style>
</head>
<body>
  <header><h1>Desfasurate GEO - {html.escape(job_id)}</h1><div class="sub">Oferta {html.escape(str(offer_id))}</div></header>
  <main>
    <section class="card">
      <h2>Nu exista GEO gata pentru afisare</h2>
      <p>Au fost cerute {requested_count} desfasurate, dar niciun fisier nu este confirmat ca salvat pe disc.</p>
      {xometry_link}
    </section>
  </main>
</body>
</html>""", status_code=404)

    cards = []
    for display_index, item_index in enumerate(ready_indexes, start=1):
        try:
            _, target_path, content, filename = _read_geo_file(offer_id, item_index)
        except Exception as exc:
            cards.append(
                f"""
                <section class="viewer error">
                  <h2>GEO {display_index}</h2>
                  <p>{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</p>
                </section>
                """
            )
            continue

        text = _decode_geo_text(content)
        preview_svg, preview_stats = _geo_preview_svg(text)
        dimensions = preview_stats.get("dimensions") or "necunoscut"
        thickness = preview_stats.get("thickness") or "necunoscuta"
        cut_count = preview_stats.get("cut_segments", 0)
        bend_count = preview_stats.get("bend_segments", 0)
        hole_count = preview_stats.get("holes", 0)
        point_count = preview_stats.get("points", 0)
        download_url = f"/api/agents/geo/{quote(offer_id, safe='')}/files/{item_index}"
        view_url = f"/api/agents/geo/{quote(offer_id, safe='')}/files/{item_index}/view"
        cards.append(
            f"""
            <section class="viewer">
              <div class="viewer-head">
                <div class="viewer-info">
                  <h2>{display_index}. {html.escape(filename)}</h2>
                  <div class="path">{html.escape(str(target_path))}</div>
                  <div class="stats-grid">
                    <div class="stat-box"><strong>{html.escape(dimensions)}</strong><span>Dimensiuni</span></div>
                    <div class="stat-box"><strong>{html.escape(thickness)}</strong><span>Grosime</span></div>
                    <div class="stat-box"><strong>{cut_count}</strong><span>Contururi</span></div>
                    <div class="stat-box"><strong>{hole_count}</strong><span>Gauri</span></div>
                    <div class="stat-box"><strong>{bend_count}</strong><span>Indoituri</span></div>
                    <div class="stat-box"><strong>{point_count}</strong><span>Puncte</span></div>
                  </div>
                  <div class="viewer-meta">{html.escape(dimensions)} · {cut_count} contururi · {hole_count} gauri · {bend_count} indoituri · {point_count} puncte</div>
                </div>
                <div class="viewer-actions">
                  <a class="button" href="{view_url}" target="_blank" rel="noreferrer">2D + 3D</a>
                  <a class="button secondary" href="{download_url}">Descarca .geo</a>
                </div>
              </div>
              <div class="cad-frame">{preview_svg}</div>
            </section>
            """
        )

    xometry_button = (
        f'<a class="button secondary" href="{html.escape(xometry_url, quote=True)}" target="_blank" rel="noreferrer">Deschide oferta Xometry</a>'
        if xometry_url
        else ""
    )

    return HTMLResponse(
        f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Desfasurate GEO - {html.escape(job_id)}</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body {{
      margin: 0;
      background: #eef2f5;
      color: #111827;
      font-family: Arial, sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 3;
      background: #ffffff;
      border-bottom: 1px solid #d9e2ec;
      padding: 14px 22px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 22px;
    }}
    h2 {{
      margin: 0 0 5px;
      font-size: 16px;
    }}
    .sub {{
      color: #52606d;
      font-size: 13px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 4px;
      background: #1677ff;
      color: #ffffff;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }}
    .button.secondary {{
      background: #ffffff;
      border: 1px solid #b8c2cc;
      color: #1f2937;
    }}
    main {{
      display: grid;
      gap: 18px;
      padding: 18px 22px 32px;
    }}
    .viewer {{
      overflow: hidden;
      border: 1px solid #cfd8e3;
      border-radius: 8px;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .viewer.error {{
      padding: 16px;
      border-color: #ffa39e;
      background: #fff1f0;
    }}
    .viewer-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 16px;
      border-bottom: 1px solid #d9e2ec;
      background: #f8fafc;
    }}
    .viewer-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .viewer-info {{
      flex: 1;
      min-width: 0;
    }}
    .viewer-meta {{
      display: none;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(96px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .stat-box {{
      min-height: 52px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #ffffff;
      padding: 8px 10px;
      box-sizing: border-box;
    }}
    .stat-box strong {{
      display: block;
      color: #0f172a;
      font-size: 19px;
      line-height: 22px;
      white-space: nowrap;
    }}
    .stat-box span {{
      display: block;
      margin-top: 4px;
      color: #52606d;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .path {{
      color: #52606d;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .cad-frame {{
      height: 520px;
      min-height: 420px;
      background: #0b1120;
    }}
    .cad-empty {{
      display: flex;
      height: 100%;
      align-items: center;
      justify-content: center;
      color: #dbeafe;
      font-size: 15px;
    }}
    .geo-svg {{
      display: block;
      width: 100%;
      height: 100%;
      background:
        radial-gradient(circle at 25% 18%, rgba(59, 130, 246, 0.18) 0, rgba(12, 18, 34, 0) 35%),
        linear-gradient(145deg, #101827 0%, #070b14 100%);
    }}
    .geo-grid {{ stroke: rgba(148, 163, 184, 0.17); stroke-width: 0.25; }}
    .geo-axis {{ stroke: rgba(148, 163, 184, 0.35); stroke-width: 0.45; }}
    .geo-build-plate {{ fill: rgba(15, 23, 42, 0.18); stroke: rgba(148, 163, 184, 0.22); stroke-width: 0.5; vector-effect: non-scaling-stroke; }}
    .geo-cut-shadow {{ fill: none; stroke: rgba(2, 6, 23, 0.80); stroke-width: 5.5; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }}
    .geo-cut,
    .geo-arc {{ fill: none; stroke: #f8fafc; stroke-width: 2.1; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }}
    .geo-hole {{ fill: rgba(15, 23, 42, 0.68); stroke: #93c5fd; stroke-width: 1.5; vector-effect: non-scaling-stroke; }}
    .geo-bend {{ fill: none; stroke: #fbbf24; stroke-width: 1.7; stroke-dasharray: 6 5; stroke-linecap: round; vector-effect: non-scaling-stroke; }}
    .geo-node {{ fill: #38bdf8; stroke: #0f172a; stroke-width: 0.8; vector-effect: non-scaling-stroke; }}
    .geo-dim {{ stroke: #94a3b8; stroke-width: 0.8; vector-effect: non-scaling-stroke; }}
    .geo-dim-text {{ fill: #cbd5e1; font-family: Arial, sans-serif; font-size: 4px; font-weight: 700; text-anchor: middle; dominant-baseline: middle; }}
    .geo-watermark {{ fill: rgba(226, 232, 240, 0.42); font-family: Arial, sans-serif; font-size: 5px; font-weight: 700; letter-spacing: 0; }}
    @media (max-width: 900px) {{
      .viewer-head {{
        flex-direction: column;
      }}
      .stats-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Desfasurate GEO - {html.escape(job_id)}</h1>
    <div class="sub">{len(ready_indexes)} fisiere GEO generate pentru aceasta oferta</div>
    <div class="actions">{xometry_button}</div>
  </header>
  <main>
    {"".join(cards)}
  </main>
</body>
</html>"""
    )


@app.get("/api/agents/geo/{offer_id}/files/{item_index}")
def geo_file(offer_id: str, item_index: int) -> Response:
    _, target_path, content, filename = _read_geo_file(offer_id, item_index)
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


def _norm_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _base_name_without_suffix(value: Any) -> str:
    name = PureWindowsPath(str(value or "").replace("/", "\\")).name
    return re.sub(r"\.(?:geo|stp|step)$", "", name, flags=re.IGNORECASE).lower()


def _step_path_for_geo_item(state: dict[str, Any], item_index: int) -> str:
    sheet = state.get("sheet_metal_laser") or {}
    geo_items = sheet.get("geo_items") or []
    if item_index < 0 or item_index >= len(geo_items):
        raise HTTPException(status_code=404, detail="GEO item not found.")

    item = geo_items[item_index]
    target_path = str(item.get("target_path") or item.get("targetPath") or "")
    part_name = str(item.get("part_name") or item.get("partName") or "")
    target_norm = _norm_path(target_path)
    target_base = _base_name_without_suffix(target_path)
    part_base = _base_name_without_suffix(part_name)

    result = sheet.get("ofertare_result") or {}
    trutops = [entry for entry in result.get("trutops") or [] if isinstance(entry, dict)]
    for entry in trutops:
        entry_target = _norm_path(entry.get("targetPath") or entry.get("target_path") or entry.get("originalTargetPath") or entry.get("original_target_path"))
        entry_part = _base_name_without_suffix(entry.get("partName") or entry.get("part_name") or "")
        if not (
            entry_target == target_norm
            or (target_base and target_base == entry_part)
            or (part_base and part_base == entry_part)
        ):
            continue
        source_path = str(
            entry.get("sourcePath")
            or entry.get("source_path")
            or entry.get("originalSourcePath")
            or entry.get("original_source_path")
            or ""
        )
        if source_path.lower().endswith((".stp", ".step")):
            return source_path

    for candidate in (item.get("source_path"), item.get("sourcePath"), item.get("original_source_path"), item.get("originalSourcePath")):
        candidate = str(candidate or "")
        if candidate.lower().endswith((".stp", ".step")):
            return candidate

    files = [str(path) for path in result.get("files") or []]
    step_files = [path for path in files if path.lower().endswith((".stp", ".step"))]
    if not step_files:
        raise HTTPException(status_code=404, detail="No STEP file found for this GEO item.")

    def score(path: str) -> tuple[int, int]:
        base = _base_name_without_suffix(path)
        value = 0
        if target_base and (target_base in base or base in target_base):
            value += 20
        if part_base and (part_base in base or base in part_base):
            value += 20
        lowered = _norm_path(path)
        if "/doc/" in lowered:
            value += 5
        if "/oferta/" in lowered:
            value += 2
        return value, -len(path)

    best = max(step_files, key=score)
    if score(best)[0] <= 0 and len(step_files) > 1:
        raise HTTPException(status_code=404, detail="Could not match a STEP file to this GEO item.")
    return best


def _read_step_file(offer_id: str, item_index: int) -> tuple[str, bytes, str]:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer not found in XometryAnaliza.")
    step_path = _step_path_for_geo_item(state, item_index)
    try:
        content = read_remote_file(step_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Remote STEP file was not found.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read remote STEP file: {type(exc).__name__}: {exc}") from exc
    filename = PureWindowsPath(str(step_path)).name or f"{offer_id}-{item_index}.stp"
    return step_path, content, filename


@app.get("/api/agents/geo/{offer_id}/files/{item_index}/step")
def geo_step_file(offer_id: str, item_index: int) -> Response:
    _, content, filename = _read_step_file(offer_id, item_index)
    return Response(
        content,
        media_type="model/step",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
        },
    )


@app.get("/api/agents/geo/{offer_id}/files/{item_index}/view")
def geo_file_view(offer_id: str, item_index: int) -> HTMLResponse:
    state, target_path, content, filename = _read_geo_file(offer_id, item_index)
    job = state.get("job") or {}
    xometry_url = str(job.get("link") or job.get("url") or "")
    download_url = f"/api/agents/geo/{quote(offer_id, safe='')}/files/{item_index}"
    text = _decode_geo_text(content)
    preview_svg, preview_stats = _geo_preview_svg(text)
    safe_title = html.escape(filename)
    safe_path = html.escape(str(target_path))
    safe_content = html.escape(text)
    safe_preview_svg = preview_svg
    safe_xometry_url = html.escape(xometry_url, quote=True)
    dimensions = preview_stats.get("dimensions") or "necunoscut"
    thickness = preview_stats.get("thickness") or "necunoscuta"
    cut_count = preview_stats.get("cut_segments", 0)
    bend_count = preview_stats.get("bend_segments", 0)
    hole_count = preview_stats.get("holes", 0)
    point_count = preview_stats.get("points", 0)
    xometry_button = (
        f'<a class="button secondary" href="{safe_xometry_url}" target="_blank" rel="noreferrer">Deschide oferta Xometry</a>'
        if xometry_url
        else ""
    )
    try:
        step_path = _step_path_for_geo_item(state, item_index)
        step_url = f"/api/agents/geo/{quote(offer_id, safe='')}/files/{item_index}/step"
        step_status = "Se incarca modelul STEP..."
    except HTTPException as exc:
        step_path = ""
        step_url = ""
        step_status = str(exc.detail)
    safe_step_path = html.escape(step_path or "Nu am gasit fisier STEP pentru aceasta piesa.")
    safe_step_url = html.escape(step_url, quote=True)
    safe_step_status = html.escape(step_status)

    return HTMLResponse(
        f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body {{
      margin: 0;
      background: #eef2f5;
      color: #111827;
      font-family: Arial, sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      background: #ffffff;
      border-bottom: 1px solid #d9e2ec;
      padding: 14px 22px;
      z-index: 1;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.25;
    }}
    .path {{
      color: #4b5563;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 4px;
      background: #1677ff;
      color: #ffffff;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
    }}
    .button.secondary {{
      background: #ffffff;
      border: 1px solid #b8c2cc;
      color: #1f2937;
    }}
    main {{
      padding: 18px 22px;
    }}
    .viewer {{
      border: 1px solid #cfd8e3;
      border-radius: 8px;
      overflow: hidden;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .viewer-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 16px;
      border-bottom: 1px solid #d9e2ec;
      background: #f8fafc;
    }}
    .viewer-title {{
      font-size: 15px;
      font-weight: 700;
    }}
    .viewer-meta {{
      margin-top: 4px;
      color: #52606d;
      font-size: 12px;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
      gap: 12px;
      color: #52606d;
      font-size: 12px;
    }}
    .legend span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }}
    .swatch {{
      width: 18px;
      height: 3px;
      border-radius: 999px;
      display: inline-block;
    }}
    .swatch.cut {{
      background: #22d3ee;
    }}
    .swatch.bend {{
      background: #f59e0b;
    }}
    .swatch.hole {{
      background: #93c5fd;
    }}
    .tool-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 12px;
      border-bottom: 1px solid #d9e2ec;
      background: #f8fafc;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(88px, 1fr));
      gap: 8px;
      color: #475569;
      font-size: 12px;
    }}
    .metric {{
      border: 1px solid #d7dee8;
      border-radius: 4px;
      background: #ffffff;
      padding: 5px 8px;
    }}
    .metric strong {{
      display: block;
      color: #0f172a;
      font-size: 13px;
    }}
    .tool-buttons {{
      display: flex;
      gap: 6px;
    }}
    .icon-button {{
      min-width: 32px;
      height: 30px;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      background: #ffffff;
      color: #0f172a;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }}
    .icon-button.wide {{
      min-width: 58px;
    }}
    .icon-button.active {{
      border-color: #f59e0b;
      background: #fff7ed;
      color: #9a3412;
    }}
    .cad-frame {{
      height: calc(100vh - 285px);
      min-height: 520px;
      background: #0b1120;
    }}
    .viewer-split {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      min-height: 520px;
    }}
    .viewer-pane {{
      min-width: 0;
      border-right: 1px solid #1e293b;
      background: #0b1120;
    }}
    .viewer-pane:last-child {{
      border-right: 0;
    }}
    .pane-label {{
      height: 34px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 12px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.20);
      background: #111827;
      color: #e5e7eb;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .step-path {{
      color: #94a3b8;
      font-size: 11px;
      font-weight: 400;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 58%;
    }}
    .step-frame {{
      position: relative;
      height: calc(100vh - 285px);
      min-height: 520px;
      background:
        radial-gradient(circle at 70% 25%, rgba(14, 165, 233, 0.18) 0, rgba(14, 165, 233, 0) 32%),
        linear-gradient(145deg, #0f172a 0%, #050816 100%);
    }}
    .step-frame canvas {{
      display: block;
      width: 100%;
      height: 100%;
    }}
    .step-status {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 18px;
      color: #dbeafe;
      font-size: 14px;
      text-align: center;
      z-index: 2;
      pointer-events: none;
    }}
    .measure-readout {{
      position: absolute;
      left: 12px;
      bottom: 12px;
      z-index: 3;
      min-width: 190px;
      border: 1px solid rgba(251, 191, 36, 0.55);
      border-radius: 6px;
      background: rgba(15, 23, 42, 0.86);
      color: #fde68a;
      padding: 8px 10px;
      font-size: 13px;
      font-weight: 700;
      pointer-events: none;
      box-shadow: 0 8px 22px rgba(0, 0, 0, 0.22);
    }}
    .cad-empty {{
      display: flex;
      height: 100%;
      align-items: center;
      justify-content: center;
      color: #dbeafe;
      font-size: 15px;
    }}
    .geo-svg {{
      display: block;
      width: 100%;
      height: 100%;
      cursor: grab;
      background:
        radial-gradient(circle at 25% 18%, rgba(59, 130, 246, 0.18) 0, rgba(12, 18, 34, 0) 35%),
        linear-gradient(145deg, #101827 0%, #070b14 100%);
    }}
    .geo-svg:active {{
      cursor: grabbing;
    }}
    .geo-grid {{
      stroke: rgba(148, 163, 184, 0.17);
      stroke-width: 0.25;
    }}
    .geo-axis {{
      stroke: rgba(148, 163, 184, 0.35);
      stroke-width: 0.45;
    }}
    .geo-build-plate {{
      fill: rgba(15, 23, 42, 0.18);
      stroke: rgba(148, 163, 184, 0.22);
      stroke-width: 0.5;
      vector-effect: non-scaling-stroke;
    }}
    .geo-cut-shadow {{
      fill: none;
      stroke: rgba(2, 6, 23, 0.80);
      stroke-width: 5.5;
      stroke-linecap: round;
      stroke-linejoin: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-cut {{
      fill: none;
      stroke: #f8fafc;
      stroke-width: 2.1;
      stroke-linecap: round;
      stroke-linejoin: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-arc {{
      fill: none;
      stroke: #f8fafc;
      stroke-width: 2.1;
      stroke-linecap: round;
      stroke-linejoin: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-hole {{
      fill: rgba(15, 23, 42, 0.68);
      stroke: #93c5fd;
      stroke-width: 1.5;
      vector-effect: non-scaling-stroke;
    }}
    .geo-bend {{
      fill: none;
      stroke: #fbbf24;
      stroke-width: 1.7;
      stroke-dasharray: 6 5;
      stroke-linecap: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-node {{
      fill: #38bdf8;
      stroke: #0f172a;
      stroke-width: 0.8;
      vector-effect: non-scaling-stroke;
    }}
    .geo-dim {{
      stroke: #94a3b8;
      stroke-width: 0.8;
      vector-effect: non-scaling-stroke;
    }}
    .geo-dim-text {{
      fill: #cbd5e1;
      font-family: Arial, sans-serif;
      font-size: 4px;
      font-weight: 700;
      text-anchor: middle;
      dominant-baseline: middle;
    }}
    .geo-watermark {{
      fill: rgba(226, 232, 240, 0.42);
      font-family: Arial, sans-serif;
      font-size: 5px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    details {{
      margin-top: 14px;
    }}
    summary {{
      cursor: pointer;
      color: #334155;
      font-weight: 700;
      font-size: 13px;
    }}
    pre {{
      margin: 12px 0 0;
      padding: 16px;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      background: #ffffff;
      color: #111827;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    @media (max-width: 1100px) {{
      .viewer-split {{
        grid-template-columns: 1fr;
      }}
      .viewer-pane {{
        border-right: 0;
        border-bottom: 1px solid #1e293b;
      }}
      .viewer-pane:last-child {{
        border-bottom: 0;
      }}
    }}
  </style>
  <script type="importmap">
    {{
      "imports": {{
        "three": "https://cdn.jsdelivr.net/npm/three@0.185.1/build/three.module.js",
        "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.185.1/examples/jsm/"
      }}
    }}
  </script>
  <script src="https://cdn.jsdelivr.net/npm/occt-import-js@0.0.23/dist/occt-import-js.js"></script>
</head>
<body>
  <header>
    <h1>{safe_title}</h1>
    <div class="path">{safe_path}</div>
    <div class="actions">
      <a class="button" href="{download_url}">Descarca .geo</a>
      {xometry_button}
    </div>
  </header>
  <main>
    <section class="viewer">
      <div class="viewer-head">
        <div>
          <div class="viewer-title">Preview desfasurata GEO</div>
          <div class="viewer-meta">{html.escape(dimensions)} · {cut_count} contururi · {bend_count} indoituri · {point_count} puncte</div>
        </div>
        <div class="legend">
          <span><i class="swatch cut"></i> Contur</span>
          <span><i class="swatch hole"></i> Gauri</span>
          <span><i class="swatch bend"></i> Indoire</span>
        </div>
      </div>
      <div class="tool-row">
        <div class="metric-grid">
          <div class="metric"><strong>{html.escape(dimensions)}</strong>Dimensiuni</div>
          <div class="metric"><strong>{html.escape(thickness)}</strong>Grosime</div>
          <div class="metric"><strong>{cut_count}</strong>Contururi</div>
          <div class="metric"><strong>{hole_count}</strong>Gauri</div>
          <div class="metric"><strong>{bend_count}</strong>Indoituri</div>
        </div>
        <div class="tool-buttons">
          <button class="icon-button" type="button" data-geo-zoom="in" title="Zoom in">+</button>
          <button class="icon-button" type="button" data-geo-zoom="out" title="Zoom out">-</button>
          <button class="icon-button" type="button" data-geo-zoom="fit" title="Fit">Fit</button>
          <button class="icon-button wide" type="button" id="step-measure-toggle" title="Masoara pe 3D">Masura</button>
          <button class="icon-button wide" type="button" id="step-measure-clear" title="Sterge masurarea">Clear</button>
        </div>
      </div>
      <div class="viewer-split">
        <div class="viewer-pane">
          <div class="pane-label"><span>Desfasurata GEO 2D</span></div>
          <div class="cad-frame">{safe_preview_svg}</div>
        </div>
        <div class="viewer-pane">
          <div class="pane-label"><span>Vedere 3D STEP</span><span class="step-path" title="{safe_step_path}">{safe_step_path}</span></div>
          <div id="step-viewer" class="step-frame" data-step-url="{safe_step_url}">
            <div id="step-status" class="step-status">{safe_step_status}</div>
            <div id="step-measure-readout" class="measure-readout">Masura: click pe doua puncte</div>
          </div>
        </div>
      </div>
    </section>
    <details>
      <summary>Arata continut raw .geo</summary>
      <pre>{safe_content}</pre>
    </details>
  </main>
  <script>
    (() => {{
      const svg = document.getElementById('geo-render');
      if (!svg) return;
      const original = (svg.dataset.viewbox || svg.getAttribute('viewBox')).split(/\\s+/).map(Number);
      let box = [...original];
      let dragging = false;
      let start = null;
      const setBox = () => svg.setAttribute('viewBox', box.map(v => Number(v.toFixed(3))).join(' '));
      const zoomAt = (factor, cx = box[0] + box[2] / 2, cy = box[1] + box[3] / 2) => {{
        const nextW = box[2] * factor;
        const nextH = box[3] * factor;
        box[0] = cx - (cx - box[0]) * factor;
        box[1] = cy - (cy - box[1]) * factor;
        box[2] = nextW;
        box[3] = nextH;
        setBox();
      }};
      const svgPoint = event => {{
        const pt = svg.createSVGPoint();
        pt.x = event.clientX;
        pt.y = event.clientY;
        return pt.matrixTransform(svg.getScreenCTM().inverse());
      }};
      svg.addEventListener('wheel', event => {{
        event.preventDefault();
        const pt = svgPoint(event);
        zoomAt(event.deltaY < 0 ? 0.86 : 1.16, pt.x, pt.y);
      }}, {{ passive: false }});
      svg.addEventListener('pointerdown', event => {{
        dragging = true;
        start = {{ clientX: event.clientX, clientY: event.clientY, box: [...box] }};
        svg.setPointerCapture(event.pointerId);
      }});
      svg.addEventListener('pointermove', event => {{
        if (!dragging || !start) return;
        const scaleX = box[2] / Math.max(svg.clientWidth, 1);
        const scaleY = box[3] / Math.max(svg.clientHeight, 1);
        box[0] = start.box[0] - (event.clientX - start.clientX) * scaleX;
        box[1] = start.box[1] - (event.clientY - start.clientY) * scaleY;
        setBox();
      }});
      svg.addEventListener('pointerup', event => {{
        dragging = false;
        start = null;
        try {{ svg.releasePointerCapture(event.pointerId); }} catch (_) {{}}
      }});
      document.querySelectorAll('[data-geo-zoom]').forEach(button => {{
        button.addEventListener('click', () => {{
          const mode = button.dataset.geoZoom;
          if (mode === 'fit') {{
            box = [...original];
            setBox();
          }} else {{
            zoomAt(mode === 'in' ? 0.82 : 1.22);
          }}
        }});
      }});
    }})();
  </script>
  <script type="module">
    import * as THREE from 'three';
    import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

    const container = document.getElementById('step-viewer');
    const status = document.getElementById('step-status');
    const measureReadout = document.getElementById('step-measure-readout');
    const measureButton = document.getElementById('step-measure-toggle');
    const clearMeasureButton = document.getElementById('step-measure-clear');
    const stepUrl = container?.dataset.stepUrl || '';
    let measureEnabled = false;

    const setStatus = (text, persistent = false) => {{
      if (!status) return;
      status.textContent = text;
      status.style.display = persistent ? 'flex' : 'none';
    }};

    const flatten = (array) => {{
      if (!Array.isArray(array)) return [];
      return Array.isArray(array[0]) ? array.flat() : array;
    }};

    async function loadStepViewer() {{
      if (!container || !status || !stepUrl) {{
        setStatus(status?.textContent || 'Nu exista STEP pentru acest reper.', true);
        return;
      }}
      try {{
        setStatus('Incarc STEP si convertesc in 3D...', true);
        const [occt, response] = await Promise.all([
          window.occtimportjs({{
            locateFile: (file) => `https://cdn.jsdelivr.net/npm/occt-import-js@0.0.23/dist/${{file}}`
          }}),
          fetch(stepUrl)
        ]);
        if (!response.ok) {{
          throw new Error(`STEP HTTP ${{response.status}}`);
        }}
        const buffer = await response.arrayBuffer();
        const result = occt.ReadStepFile(new Uint8Array(buffer), {{
          linearUnit: 'millimeter',
          linearDeflectionType: 'bounding_box_ratio',
          linearDeflection: 0.0015,
          angularDeflection: 0.4
        }});
        if (!result?.success || !Array.isArray(result.meshes) || !result.meshes.length) {{
          throw new Error('STEP-ul nu a produs mesh 3D.');
        }}

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x08111f);
        const renderer = new THREE.WebGLRenderer({{ antialias: true }});
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        container.appendChild(renderer.domElement);

        const camera = new THREE.PerspectiveCamera(35, container.clientWidth / Math.max(container.clientHeight, 1), 0.1, 100000);
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;

        scene.add(new THREE.HemisphereLight(0xdbeafe, 0x0f172a, 1.15));
        const keyLight = new THREE.DirectionalLight(0xffffff, 1.8);
        keyLight.position.set(2, 3, 4);
        scene.add(keyLight);
        const rimLight = new THREE.DirectionalLight(0x60a5fa, 0.65);
        rimLight.position.set(-4, 2, -2);
        scene.add(rimLight);

        const group = new THREE.Group();
        scene.add(group);
        const solidMeshes = [];
        for (const mesh of result.meshes) {{
          const geometry = new THREE.BufferGeometry();
          const positions = flatten(mesh?.attributes?.position?.array);
          if (!positions.length) continue;
          geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
          const normals = flatten(mesh?.attributes?.normal?.array);
          if (normals.length === positions.length) {{
            geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
          }}
          const indices = flatten(mesh?.index?.array);
          if (indices.length) {{
            geometry.setIndex(indices);
          }}
          geometry.computeVertexNormals();
          const color = Array.isArray(mesh.color) ? new THREE.Color(mesh.color[0], mesh.color[1], mesh.color[2]) : new THREE.Color(0xb8c7d9);
          const material = new THREE.MeshStandardMaterial({{
            color,
            metalness: 0.18,
            roughness: 0.52,
            side: THREE.DoubleSide
          }});
          const solid = new THREE.Mesh(geometry, material);
          group.add(solid);
          solidMeshes.push(solid);
          const edges = new THREE.LineSegments(
            new THREE.EdgesGeometry(geometry, 35),
            new THREE.LineBasicMaterial({{ color: 0x1e293b, transparent: true, opacity: 0.42 }})
          );
          group.add(edges);
        }}

        const box = new THREE.Box3().setFromObject(group);
        const size = new THREE.Vector3();
        const center = new THREE.Vector3();
        box.getSize(size);
        box.getCenter(center);
        group.position.sub(center);
        const maxDim = Math.max(size.x, size.y, size.z, 1);
        camera.position.set(maxDim * 0.9, -maxDim * 1.25, maxDim * 0.75);
        camera.near = maxDim / 1000;
        camera.far = maxDim * 20;
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();

        const grid = new THREE.GridHelper(maxDim * 1.8, 16, 0x334155, 0x1e293b);
        grid.rotation.x = Math.PI / 2;
        grid.position.z = -size.z / 2 - maxDim * 0.04;
        scene.add(grid);

        const raycaster = new THREE.Raycaster();
        const pointer = new THREE.Vector2();
        const measurePoints = [];
        const measureMarkers = [];
        let measureLine = null;
        const markerGeometry = new THREE.SphereGeometry(maxDim * 0.012, 18, 12);
        const markerMaterial = new THREE.MeshBasicMaterial({{ color: 0xfbbf24 }});
        const lineMaterial = new THREE.LineBasicMaterial({{ color: 0xfbbf24, linewidth: 2 }});

        const formatMm = (value) => `${{value.toFixed(2)}} mm`;
        const setMeasureText = (text) => {{
          if (measureReadout) measureReadout.textContent = text;
        }};
        const clearMeasure = () => {{
          measurePoints.length = 0;
          for (const marker of measureMarkers.splice(0)) {{
            scene.remove(marker);
          }}
          if (measureLine) {{
            scene.remove(measureLine);
            measureLine.geometry.dispose();
            measureLine = null;
          }}
          setMeasureText(measureEnabled ? 'Masura: click primul punct' : 'Masura: click pe doua puncte');
        }};
        const setMeasureEnabled = (enabled) => {{
          measureEnabled = enabled;
          controls.enabled = !enabled;
          renderer.domElement.style.cursor = enabled ? 'crosshair' : 'grab';
          measureButton?.classList.toggle('active', enabled);
          setMeasureText(enabled ? 'Masura: click primul punct' : 'Masura: click pe doua puncte');
        }};
        const addMeasurePoint = (point) => {{
          if (measurePoints.length >= 2) clearMeasure();
          const localPoint = point.clone();
          measurePoints.push(localPoint);
          const marker = new THREE.Mesh(markerGeometry, markerMaterial);
          marker.position.copy(localPoint);
          scene.add(marker);
          measureMarkers.push(marker);
          if (measurePoints.length === 1) {{
            setMeasureText('Masura: click al doilea punct');
            return;
          }}
          const distance = measurePoints[0].distanceTo(measurePoints[1]);
          const geometry = new THREE.BufferGeometry().setFromPoints(measurePoints);
          measureLine = new THREE.Line(geometry, lineMaterial);
          scene.add(measureLine);
          setMeasureText(`Masura: ${{formatMm(distance)}}`);
        }};
        measureButton?.addEventListener('click', () => {{
          setMeasureEnabled(!measureEnabled);
          if (measureEnabled) clearMeasure();
        }});
        clearMeasureButton?.addEventListener('click', clearMeasure);
        renderer.domElement.addEventListener('pointerdown', (event) => {{
          renderer.domElement.dataset.measureStartX = String(event.clientX);
          renderer.domElement.dataset.measureStartY = String(event.clientY);
        }});
        renderer.domElement.addEventListener('pointerup', (event) => {{
          if (!measureEnabled) return;
          const startX = Number(renderer.domElement.dataset.measureStartX || event.clientX);
          const startY = Number(renderer.domElement.dataset.measureStartY || event.clientY);
          if (Math.hypot(event.clientX - startX, event.clientY - startY) > 4) return;
          const rect = renderer.domElement.getBoundingClientRect();
          pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
          pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
          raycaster.setFromCamera(pointer, camera);
          const hits = raycaster.intersectObjects(solidMeshes, false);
          if (!hits.length) {{
            setMeasureText('Masura: click pe suprafata piesei');
            return;
          }}
          addMeasurePoint(hits[0].point);
        }});

        setStatus('', false);
        const resize = () => {{
          const width = Math.max(container.clientWidth, 1);
          const height = Math.max(container.clientHeight, 1);
          camera.aspect = width / height;
          camera.updateProjectionMatrix();
          renderer.setSize(width, height);
        }};
        window.addEventListener('resize', resize);
        const animate = () => {{
          controls.update();
          renderer.render(scene, camera);
          requestAnimationFrame(animate);
        }};
        animate();
      }} catch (error) {{
        setStatus(`Nu pot afisa 3D: ${{error?.message || error}}`, true);
      }}
    }}

    loadStepViewer();
  </script>
</body>
</html>"""
    )


def _read_geo_file(offer_id: str, item_index: int) -> tuple[dict[str, Any], str, bytes, str]:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer not found in XometryAnaliza.")

    sheet = state.get("sheet_metal_laser") or {}
    geo_items = sheet.get("geo_items") or []
    if item_index < 0 or item_index >= len(geo_items):
        raise HTTPException(status_code=404, detail="GEO item not found.")

    item = geo_items[item_index]
    target_path = item.get("target_path")
    if not target_path:
        raise HTTPException(status_code=404, detail="GEO item has no target path.")

    try:
        content = read_remote_geo_file(str(target_path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Remote GEO file was not found.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read remote GEO file: {type(exc).__name__}: {exc}") from exc

    filename = PureWindowsPath(str(target_path)).name or f"{offer_id}-{item_index}.geo"
    return state, str(target_path), content, filename


def _decode_geo_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _ints_from_line(value: str) -> list[int]:
    return [int(match) for match in re.findall(r"-?\d+", value)]


def _point_from_line(value: str) -> tuple[float, float] | None:
    parts = value.split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _format_mm(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") + " mm"


def _geo_thickness_from_lines(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line.upper() != "NONE":
            continue
        for next_line in lines[index + 1:index + 7]:
            parts = next_line.split()
            if not parts:
                continue
            try:
                value = float(parts[0])
            except ValueError:
                continue
            if 0 < value <= 100:
                return _format_mm(value)
    return "necunoscuta"


def _geo_preview_svg(text: str) -> tuple[str, dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines()]
    points: dict[int, tuple[float, float]] = {}
    cut_segments: list[tuple[str, tuple[int, ...]]] = []
    cut_circles: list[tuple[int, float]] = []
    bend_segments: list[tuple[str, tuple[int, ...]]] = []
    block = ""

    for index, line in enumerate(lines):
        if line.startswith("#~"):
            block = line

        if line == "P" and index + 2 < len(lines):
            point_ids = _ints_from_line(lines[index + 1])
            coords = _point_from_line(lines[index + 2])
            if len(point_ids) == 1 and coords:
                points[point_ids[0]] = coords
            continue

        if line not in {"LIN", "ARC", "CIR"} or index + 2 >= len(lines):
            continue

        refs = tuple(_ints_from_line(lines[index + 2]))
        if line == "LIN" and len(refs) >= 2:
            target = bend_segments if block == "#~371" else cut_segments if block == "#~331" else None
            if target is not None:
                target.append(("line", refs[:2]))
        elif line == "ARC" and len(refs) >= 3 and block == "#~331":
            cut_segments.append(("arc", refs[:3]))
        elif line == "CIR" and refs and index + 3 < len(lines) and block == "#~331":
            try:
                radius = float(lines[index + 3].split()[0])
            except (ValueError, IndexError):
                radius = 0.0
            if radius > 0:
                cut_circles.append((refs[0], radius))

    used_ids = set()
    for _, refs in [*cut_segments, *bend_segments]:
        used_ids.update(refs)
    for center_id, _ in cut_circles:
        used_ids.add(center_id)
    used_points = [points[point_id] for point_id in used_ids if point_id in points]

    stats: dict[str, Any] = {
        "points": len(points),
        "cut_segments": len(cut_segments),
        "bend_segments": len(bend_segments),
        "holes": len(cut_circles),
        "dimensions": "necunoscut",
        "thickness": _geo_thickness_from_lines(lines),
    }

    if not used_points:
        return '<div class="cad-empty">Nu am putut reconstrui geometria din acest fisier GEO.</div>', stats

    min_x = min(point[0] for point in used_points)
    max_x = max(point[0] for point in used_points)
    min_y = min(point[1] for point in used_points)
    max_y = max(point[1] for point in used_points)
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad = max(max(width, height) * 0.10, 18.0)
    view_w = width + pad * 2
    view_h = height + pad * 2
    stats["dimensions"] = f"{width:.1f} x {height:.1f} mm"

    def point(point_id: int) -> tuple[float, float] | None:
        raw = points.get(point_id)
        if raw is None:
            return None
        x, y = raw
        return x - min_x + pad, max_y - y + pad

    def fmt(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".")

    grid = []
    grid_step = _nice_grid_step(max(width, height))
    grid_start_x = int(min_x // grid_step) * grid_step
    grid_end_x = int(max_x // grid_step + 2) * grid_step
    grid_start_y = int(min_y // grid_step) * grid_step
    grid_end_y = int(max_y // grid_step + 2) * grid_step

    gx = grid_start_x
    while gx <= grid_end_x:
        x = gx - min_x + pad
        cls = "geo-axis" if abs(gx) < 0.0001 else "geo-grid"
        grid.append(f'<line class="{cls}" x1="{fmt(x)}" y1="0" x2="{fmt(x)}" y2="{fmt(view_h)}" />')
        gx += grid_step

    gy = grid_start_y
    while gy <= grid_end_y:
        y = max_y - gy + pad
        cls = "geo-axis" if abs(gy) < 0.0001 else "geo-grid"
        grid.append(f'<line class="{cls}" x1="0" y1="{fmt(y)}" x2="{fmt(view_w)}" y2="{fmt(y)}" />')
        gy += grid_step

    left = pad
    right = pad + width
    top = pad
    bottom = pad + height
    dim_y = bottom + pad * 0.45
    dim_x = left - pad * 0.45
    dim_arrow = (
        '<defs>'
        '<marker id="geo-arrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">'
        '<path d="M0,0 L6,3 L0,6 Z" fill="#94a3b8" />'
        '</marker>'
        '</defs>'
    )

    cut_svg = []
    cut_shadow_svg = []
    for kind, refs in cut_segments:
        if kind == "line":
            a = point(refs[0])
            b = point(refs[1])
            if not a or not b:
                continue
            cut_shadow_svg.append(
                f'<line class="geo-cut-shadow" x1="{fmt(a[0])}" y1="{fmt(a[1])}" x2="{fmt(b[0])}" y2="{fmt(b[1])}" />'
            )
            cut_svg.append(
                f'<line class="geo-cut" x1="{fmt(a[0])}" y1="{fmt(a[1])}" x2="{fmt(b[0])}" y2="{fmt(b[1])}" />'
            )
        elif kind == "arc":
            a = point(refs[0])
            b = point(refs[1])
            c = point(refs[2])
            if not a or not b or not c:
                continue
            cut_shadow_svg.append(
                f'<path class="geo-cut-shadow" d="M {fmt(a[0])} {fmt(a[1])} Q {fmt(b[0])} {fmt(b[1])} {fmt(c[0])} {fmt(c[1])}" />'
            )
            cut_svg.append(
                f'<path class="geo-arc" d="M {fmt(a[0])} {fmt(a[1])} Q {fmt(b[0])} {fmt(b[1])} {fmt(c[0])} {fmt(c[1])}" />'
            )

    hole_svg = []
    node_svg = []
    for center_id, radius in cut_circles:
        center = point(center_id)
        if not center:
            continue
        hole_svg.append(
            f'<circle class="geo-hole" cx="{fmt(center[0])}" cy="{fmt(center[1])}" r="{fmt(radius)}" />'
        )

    for point_id in sorted(used_ids):
        rendered = point(point_id)
        if rendered:
            node_svg.append(f'<circle class="geo-node" cx="{fmt(rendered[0])}" cy="{fmt(rendered[1])}" r="0.9" />')

    bend_svg = []
    for _, refs in bend_segments:
        a = point(refs[0])
        b = point(refs[1])
        if not a or not b:
            continue
        bend_svg.append(
            f'<line class="geo-bend" x1="{fmt(a[0])}" y1="{fmt(a[1])}" x2="{fmt(b[0])}" y2="{fmt(b[1])}" />'
        )

    dimensions_svg = (
        f'<g>'
        f'<line class="geo-dim" x1="{fmt(left)}" y1="{fmt(dim_y)}" x2="{fmt(right)}" y2="{fmt(dim_y)}" '
        f'marker-start="url(#geo-arrow)" marker-end="url(#geo-arrow)" />'
        f'<line class="geo-dim" x1="{fmt(left)}" y1="{fmt(bottom)}" x2="{fmt(left)}" y2="{fmt(dim_y)}" />'
        f'<line class="geo-dim" x1="{fmt(right)}" y1="{fmt(bottom)}" x2="{fmt(right)}" y2="{fmt(dim_y)}" />'
        f'<text class="geo-dim-text" x="{fmt((left + right) / 2)}" y="{fmt(dim_y + pad * 0.22)}">{width:.1f} mm</text>'
        f'<line class="geo-dim" x1="{fmt(dim_x)}" y1="{fmt(top)}" x2="{fmt(dim_x)}" y2="{fmt(bottom)}" '
        f'marker-start="url(#geo-arrow)" marker-end="url(#geo-arrow)" />'
        f'<line class="geo-dim" x1="{fmt(dim_x)}" y1="{fmt(top)}" x2="{fmt(left)}" y2="{fmt(top)}" />'
        f'<line class="geo-dim" x1="{fmt(dim_x)}" y1="{fmt(bottom)}" x2="{fmt(left)}" y2="{fmt(bottom)}" />'
        f'<text class="geo-dim-text" transform="translate({fmt(dim_x - pad * 0.24)} {fmt((top + bottom) / 2)}) rotate(-90)">{height:.1f} mm</text>'
        f'</g>'
    )

    return (
        f'<svg id="geo-render" class="geo-svg" viewBox="0 0 {fmt(view_w)} {fmt(view_h)}" '
        f'data-viewbox="0 0 {fmt(view_w)} {fmt(view_h)}" role="img" aria-label="GEO preview">'
        f'{dim_arrow}'
        f'<g>{"".join(grid)}</g>'
        f'<rect class="geo-build-plate" x="{fmt(left)}" y="{fmt(top)}" width="{fmt(width)}" height="{fmt(height)}" rx="1.5" />'
        f'{dimensions_svg}'
        f'<text class="geo-watermark" x="{fmt(left)}" y="{fmt(top - pad * 0.35)}">BUILD123 STYLE RENDER</text>'
        f'<g transform="translate(1.4 1.6)">{"".join(cut_shadow_svg)}</g>'
        f'<g>{"".join(cut_svg)}</g>'
        f'<g>{"".join(hole_svg)}</g>'
        f'<g>{"".join(bend_svg)}</g>'
        f'<g>{"".join(node_svg)}</g>'
        "</svg>",
        stats,
    )


def _nice_grid_step(span: float) -> float:
    if span <= 50:
        return 5.0
    if span <= 150:
        return 10.0
    if span <= 500:
        return 25.0
    return 50.0
