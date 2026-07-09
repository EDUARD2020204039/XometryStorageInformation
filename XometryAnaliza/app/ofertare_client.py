from typing import Any
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
    if response.status_code == 202 and data.get("status_url"):
        return poll_automation_job(data["status_url"], headers)
    return data


def run_teczone_folder(project_path: str) -> dict[str, Any]:
    response = requests.post(
        f"{settings.OFERTARE_AUTOMATA_URL}/api/teczone/folder",
        json={"project_path": project_path},
        headers=_headers(),
        timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, settings.OFERTARE_AUTOMATA_READ_TIMEOUT),
    )
    response.raise_for_status()
    return response.json()


def poll_automation_job(status_url: str, headers: dict[str, str]) -> dict[str, Any]:
    deadline = time.time() + settings.OFERTARE_AUTOMATA_READ_TIMEOUT
    url = f"{settings.OFERTARE_AUTOMATA_URL}{status_url}"
    while time.time() < deadline:
        response = requests.get(
            url,
            headers=headers,
            timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, 30),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("result"):
            return data["result"]
        if data.get("error"):
            raise RuntimeError(data.get("error"))
        time.sleep(5)
    raise TimeoutError(f"Ofertare automation job did not finish before timeout: {status_url}")


def extract_geo_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    geo_items = []
    for item in result.get("trutops") or []:
        target = item.get("targetPath") or item.get("target_path")
        if target:
            geo_items.append(
                {
                    "part_name": item.get("partName") or item.get("part_name"),
                    "target_path": target,
                    "geo_exists": item.get("geo_exists"),
                    "status": item.get("status"),
                    "classification": item.get("classification"),
                    "bendable": item.get("bendable"),
                    "reason": item.get("reason") or item.get("message"),
                }
            )
    return geo_items
