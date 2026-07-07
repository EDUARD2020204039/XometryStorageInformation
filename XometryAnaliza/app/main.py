import html
from typing import Any
from pathlib import PureWindowsPath
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .agents import process_jobs
from .geo_files import read_remote_geo_file
from .store import find_job_by_offer_id, list_jobs, read_events


app = FastAPI(title="Xometry Analiza Agents", version="2.0.0")


class AgentJobsPayload(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "unknown"


def _run_jobs(payload: AgentJobsPayload) -> None:
    process_jobs(payload.jobs)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "xometry-analiza-agents"}


@app.post("/api/agents/jobs")
def submit_jobs(payload: AgentJobsPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    background_tasks.add_task(_run_jobs, payload)
    return {"ok": True, "queued": len(payload.jobs), "source": payload.source}


@app.get("/api/agents/logs")
def logs(limit: int = 50) -> dict[str, Any]:
    return {"items": read_events(limit)}


@app.get("/api/agents/jobs")
def jobs(limit: int = 100) -> dict[str, Any]:
    return {"items": list_jobs(limit)}


@app.get("/api/agents/geo/{offer_id}")
def geo_status(offer_id: str) -> dict[str, Any]:
    state = find_job_by_offer_id(offer_id)
    if not state:
        return {"ok": False, "offer_id": offer_id, "status": "not_found", "geo_items": []}
    sheet = state.get("sheet_metal_laser") or {}
    return {
        "ok": True,
        "offer_id": offer_id,
        "job_id": state.get("job_id"),
        "status": sheet.get("status") or "no_sheet_agent",
        "geo_items": sheet.get("geo_items") or [],
        "state": state,
    }


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


@app.get("/api/agents/geo/{offer_id}/files/{item_index}/view")
def geo_file_view(offer_id: str, item_index: int) -> HTMLResponse:
    state, target_path, content, filename = _read_geo_file(offer_id, item_index)
    job = state.get("job") or {}
    xometry_url = str(job.get("link") or job.get("url") or "")
    download_url = f"/api/agents/geo/{quote(offer_id, safe='')}/files/{item_index}"
    text = content.decode("utf-8", errors="replace")
    safe_title = html.escape(filename)
    safe_path = html.escape(str(target_path))
    safe_content = html.escape(text)
    safe_xometry_url = html.escape(xometry_url, quote=True)
    xometry_button = (
        f'<a class="button secondary" href="{safe_xometry_url}" target="_blank" rel="noreferrer">Deschide oferta Xometry</a>'
        if xometry_url
        else ""
    )

    return HTMLResponse(
        f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0;
      background: #f4f6f8;
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
    pre {{
      margin: 0;
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
  </style>
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
    <pre>{safe_content}</pre>
  </main>
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
