import os

import requests
import time

import config


def send_to_backend(jobs):
    if not config.BACKEND_ENABLED:
        return False, "Backend disabled"
    if not config.BACKEND_URL:
        return False, "Missing BACKEND_URL"

    url = f"{config.BACKEND_URL.rstrip('/')}/api/scrape"
    headers = {"content-type": "application/json"}
    if config.BACKEND_API_KEY:
        headers["authorization"] = f"Bearer {config.BACKEND_API_KEY}"

    offers = []
    for job in jobs:
        offer_id = job.get("offer_id")
        job_id = job.get("id")
        if not offer_id:
            continue
        if job_id and str(job_id).startswith("RFQ-"):
            continue
        job_id_text = str(job_id or "")
        if job_id_text.startswith(("HJO-", "J-")):
            url_fallback = f"https://partner.xometry.eu/offers/{offer_id}?gsh=true&source=jobs&locale=en"
        else:
            url_fallback = f"https://partner.xometry.eu/offers/{offer_id}?source=jobs&locale=en"
        offers.append({
            "offer_id": str(offer_id),
            "title": job_id,
            "url": job.get("link") or url_fallback,
            "price": job.get("price"),
            "currency": config.MIN_PRICE_CURRENCY,
            "quantity": job.get("quantity"),
            "material": job.get("material"),
            "process": job.get("process"),
        })

    if not offers:
        return False, "No offers with offer_id to send"

    return send_payloads(offers)


def fetch_existing_offer_ids():
    if not config.BACKEND_ENABLED:
        return set()
    if not config.BACKEND_URL:
        return set()

    url = f"{config.BACKEND_URL.rstrip('/')}/api/offers"
    headers = {}
    if config.BACKEND_API_KEY:
        headers["authorization"] = f"Bearer {config.BACKEND_API_KEY}"
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return set()
        data = resp.json() or []
        return {str(o.get("offer_id")) for o in data if o.get("offer_id")}
    except Exception:
        return set()


def _synced_file():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "data", "backend_synced.txt")


def load_synced_offer_ids():
    path = _synced_file()
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception:
        return set()


def mark_synced(offer_ids):
    if not offer_ids:
        return
    os.makedirs("data", exist_ok=True)
    path = _synced_file()
    try:
        with open(path, "a") as f:
            for oid in offer_ids:
                f.write(f"{oid}\n")
    except Exception:
        pass


def send_payloads(payloads):
    if not config.BACKEND_ENABLED:
        return False, "Backend disabled"
    if not config.BACKEND_URL:
        return False, "Missing BACKEND_URL"

    if not payloads:
        return True, None

    url = f"{config.BACKEND_URL.rstrip('/')}/api/scrape"
    headers = {"content-type": "application/json"}
    if config.BACKEND_API_KEY:
        headers["authorization"] = f"Bearer {config.BACKEND_API_KEY}"

    ok = 0
    ok_ids = []
    failed = []
    for payload in payloads:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                failed.append(f"{payload.get('offer_id')}: HTTP {resp.status_code}")
            else:
                ok += 1
                ok_ids.append(str(payload.get("offer_id")))
        except Exception as e:
            failed.append(f"{payload.get('offer_id')}: {e}")

    if failed:
        return False, f"{ok}/{len(payloads)} ok; failed: {', '.join(failed[:3])}", ok_ids
    return True, None, ok_ids


def send_orders_sync(orders):
    if not config.BACKEND_ENABLED:
        return False, "Backend disabled"
    if not config.BACKEND_URL:
        return False, "Missing BACKEND_URL"
    if not orders:
        return True, None

    url = f"{config.BACKEND_URL.rstrip('/')}/api/orders/sync"
    headers = {"content-type": "application/json"}
    if config.BACKEND_API_KEY:
        headers["authorization"] = f"Bearer {config.BACKEND_API_KEY}"

    batch_size = max(1, int(config.BACKEND_ORDERS_BATCH_SIZE))
    timeout = max(30, int(config.BACKEND_ORDERS_TIMEOUT))
    retries = max(0, int(config.BACKEND_ORDERS_RETRY))
    total = len(orders)
    ok_batches = 0
    failed = []

    for i in range(0, total, batch_size):
        batch = orders[i:i + batch_size]
        attempt = 0
        last_err = None
        while attempt <= retries:
            attempt += 1
            try:
                resp = requests.post(
                    url, headers=headers, json={"orders": batch}, timeout=timeout
                )
                if resp.status_code == 200:
                    ok_batches += 1
                    last_err = None
                    break
                last_err = f"HTTP {resp.status_code}"
            except Exception as e:
                last_err = str(e)
            time.sleep(0.5)
        if last_err:
            failed.append(f"{i}-{i+len(batch)-1}: {last_err}")

    if failed:
        return False, f"{ok_batches} batches ok; failed: {', '.join(failed[:3])}"
    return True, None
