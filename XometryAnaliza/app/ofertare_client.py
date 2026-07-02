from typing import Any

import requests

from . import settings


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
    response = requests.post(
        f"{settings.OFERTARE_AUTOMATA_URL}/api/offers",
        json=payload,
        timeout=(settings.OFERTARE_AUTOMATA_CONNECT_TIMEOUT, settings.OFERTARE_AUTOMATA_READ_TIMEOUT),
    )
    response.raise_for_status()
    return response.json()


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
