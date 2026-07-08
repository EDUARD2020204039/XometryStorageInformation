from typing import Any

import requests

from . import settings


def _part_ids(job: dict[str, Any]) -> list[str]:
    values = []
    for part in job.get("parts") or []:
        part_id = part.get("part_id") if isinstance(part, dict) else None
        if part_id:
            values.append(str(part_id))
    return values


def lookup_dosar_references(job: dict[str, Any]) -> dict[str, Any]:
    offer_id = str(job.get("offer_id") or "")
    if not offer_id:
        return {"success": False, "error": "missing offer_id"}

    params = {}
    job_id = job.get("job_name") or job.get("title") or job.get("id")
    if job_id:
        params["job_id"] = str(job_id)
    part_ids = _part_ids(job)
    if part_ids:
        params["part_ids"] = ",".join(part_ids)

    response = requests.get(
        f"{settings.BACKEND_URL}/api/xometry/dosar/{offer_id}",
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
