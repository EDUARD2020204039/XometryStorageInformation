from typing import Any

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from .agents import process_jobs
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
