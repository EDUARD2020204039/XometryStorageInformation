from typing import Any
from pathlib import PureWindowsPath
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import Response
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
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Geo-Path": str(target_path),
        },
    )
