from typing import Any
from urllib.parse import quote
import time

import requests

from . import settings


def _headers() -> dict[str, str]:
    headers = {}
    if settings.OFERTARE_API_TOKEN:
        headers["X-Ofertare-Token"] = settings.OFERTARE_API_TOKEN
    return headers


def run_ofertare_automata(job: dict[str, Any]) -> dict[str, Any]:
    url = job.get("link") or job.get("url")
    if not url:
        raise ValueError("Job has no Xometry offer URL.")

    payload = {
        "url": url,
        "root": settings.OFERTARE_AUTOMATA_ROOT,
        "headless": True,
        "run_trutops": True,
    }
    if settings.XOMETRY_EMAIL:
        payload["email"] = settings.XOMETRY_EMAIL
    if settings.XOMETRY_PASSWORD:
        payload["password"] = settings.XOMETRY_PASSWORD
    headers = _headers()
    endpoint = "/api/automation/offers" if settings.OFERTARE_API_TOKEN else "/api/offers"
    response = requests.post(
        f"{settings.OFERTARE_AUTOMATA_URL}{endpoint}",
        json=payload,
        headers=headers,
        timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, settings.OFERTARE_AUTOMATA_READ_TIMEOUT),
    )
    response.raise_for_status()
    data = response.json()
    if data.get("result"):
        return data["result"]
    if data.get("status_url"):
        return poll_automation_job(data["status_url"], headers)
    return data


def run_teczone_folder(project_path: str) -> dict[str, Any]:
    headers = _headers()
    response = requests.post(
        f"{settings.OFERTARE_AUTOMATA_URL}/api/teczone/folder",
        json={"project_path": project_path},
        headers=headers,
        timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, settings.OFERTARE_AUTOMATA_READ_TIMEOUT),
    )
    response.raise_for_status()
    data = response.json()
    if data.get("result"):
        return data["result"]
    if data.get("status_url"):
        return poll_automation_job(data["status_url"], headers)
    return data


def find_project_folder_for_job(job_id: str) -> dict[str, Any] | None:
    if not job_id:
        return None
    try:
        response = requests.get(
            f"{settings.OFERTARE_AUTOMATA_URL}/api/project-folder-for-job/{quote(str(job_id), safe='')}",
            headers=_headers(),
            timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, 8),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if data.get("path"):
            return data
    except Exception:
        return None
    return None


def fetch_automation_jobs() -> dict[str, Any]:
    response = requests.get(
        f"{settings.OFERTARE_AUTOMATA_URL}/api/automation/jobs",
        headers=_headers(),
        timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, 8),
    )
    response.raise_for_status()
    return response.json()


def poll_automation_job(status_url: str, headers: dict[str, str]) -> dict[str, Any]:
    deadline = time.time() + settings.OFERTARE_AUTOMATA_READ_TIMEOUT
    stall_deadline = time.time() + settings.OFERTARE_AUTOMATA_STALL_TIMEOUT if settings.OFERTARE_AUTOMATA_STALL_TIMEOUT > 0 else 0
    url = f"{settings.OFERTARE_AUTOMATA_URL}{status_url}"
    last_status = ""
    while time.time() < deadline:
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, 30),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ConnectionError(
                f"Ofertare API status check failed for {status_url}: {type(exc).__name__}: {exc}"
            ) from exc
        data = response.json()
        if data.get("result"):
            return data["result"]
        if data.get("error"):
            raise RuntimeError(data.get("error"))
        last_status = str(data.get("status") or last_status or "running")
        if stall_deadline and time.time() >= stall_deadline:
            raise TimeoutError(
                f"Ofertare automation job is still {last_status} after "
                f"{settings.OFERTARE_AUTOMATA_STALL_TIMEOUT}s: {status_url}. "
                "Dorina desktop/browser automation may be stuck."
            )
        time.sleep(5)
    raise TimeoutError(f"Ofertare automation job did not finish before timeout: {status_url}; last status={last_status or 'unknown'}")


def extract_geo_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    geo_items = []
    for item in result.get("trutops") or []:
        target = item.get("targetPath") or item.get("target_path")
        if target:
            geo_items.append(
                {
                    "part_name": item.get("partName") or item.get("part_name"),
                    "source_path": item.get("sourcePath") or item.get("source_path"),
                    "original_source_path": item.get("originalSourcePath") or item.get("original_source_path"),
                    "target_path": target,
                    "original_target_path": item.get("originalTargetPath") or item.get("original_target_path"),
                    "geo_exists": item.get("geo_exists"),
                    "status": item.get("status"),
                    "classification": item.get("classification"),
                    "bendable": item.get("bendable"),
                    "reason": item.get("reason") or item.get("message"),
                }
            )
    return geo_items
