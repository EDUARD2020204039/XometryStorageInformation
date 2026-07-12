from typing import Any

import requests

from . import settings


def _is_fallback_part_id(value: str, job_id: str = "") -> bool:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return True
    if job_id and normalized == str(job_id or "").strip().upper():
        return True
    return normalized.startswith(("HJO-", "J-", "RFQ-"))


def _part_ids(job: dict[str, Any]) -> list[str]:
    values = []
    job_id = str(job.get("job_name") or job.get("title") or job.get("id") or job.get("job_id") or "")
    for part in job.get("parts") or []:
        part_id = part.get("part_id") if isinstance(part, dict) else None
        if part_id and not _is_fallback_part_id(str(part_id), job_id):
            values.append(str(part_id))
    return list(dict.fromkeys(values))


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
