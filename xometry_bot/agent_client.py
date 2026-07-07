import requests
import config


def submit_jobs(jobs, source="scraper"):
    agent_url = getattr(config, "AGENT_URL", "")
    timeout = getattr(config, "AGENT_TIMEOUT", 10)
    if not agent_url:
        return False, "AGENT_URL missing"
    try:
        resp = requests.post(
            f"{agent_url.rstrip('/')}/api/agents/jobs",
            json={"source": source, "jobs": jobs},
            timeout=timeout,
        )
        if not resp.ok:
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        return True, resp.json()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def fetch_logs(limit=20):
    agent_url = getattr(config, "AGENT_URL", "")
    timeout = getattr(config, "AGENT_TIMEOUT", 10)
    if not agent_url:
        return False, "AGENT_URL missing", []
    try:
        resp = requests.get(f"{agent_url.rstrip('/')}/api/agents/logs", params={"limit": limit}, timeout=timeout)
        if not resp.ok:
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}", []
        return True, None, resp.json().get("items", [])
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", []


def fetch_geo_status(offer_id):
    agent_url = getattr(config, "AGENT_URL", "")
    timeout = getattr(config, "AGENT_TIMEOUT", 10)
    if not agent_url:
        return False, "AGENT_URL missing", None
    if not offer_id:
        return False, "offer_id missing", None
    try:
        resp = requests.get(
            f"{agent_url.rstrip('/')}/api/agents/geo/{offer_id}",
            timeout=timeout,
        )
        if not resp.ok:
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}", None
        return True, None, resp.json()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", None
