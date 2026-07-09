import json
import os
import logging
import re
import time
import base64

import requests
from playwright.sync_api import Page, Locator

import config

# Use the logger defined in main.py
logger = logging.getLogger('xometry_bot')

GSH_JOB_OFFERS_QUERY = """query gshJobOffers($filter: OffersFilterType!, $offsetAttributes: OffsetAttributes) {
  gshJobOffers(filter: $filter, offsetAttributes: $offsetAttributes) {
    metadata { hasMore limit offset totalCount }
    offers {
      __typename
      ... on JobOffer {
        id
        code
        isUrgent
        cost { amount currencyCode }
        parts { quantity material processType }
      }
      ... on Offer {
        id
        isUrgent
        totalValueMoney { amount currencyCode }
        job {
          displayId
          positions { quantity material part { processType } }
        }
      }
    }
  }
}
"""

RFQ_OFFERS_QUERY = """query rfqOffers($filters: RfqOffersFilterType!, $offsetAttributes: OffsetAttributes) {
  rfqOffers(filters: $filters, offsetAttributes: $offsetAttributes) {
    metadata { limit offset total }
    offers {
      id
      responseState
      decisionState
      currency
      prices { quantity providerPrice { amount currencyCode } }
      rfq {
        xometryNumber
        positions {
          quantity
          material { name }
          process { name }
        }
      }
    }
  }
}
"""

def clean_price(price_str):
    """
    Extracts numerical value from price string like '€ 350.00' or '1.200 €'.
    """
    if not price_str:
        return 0.0
    # Remove currency symbol and whitespace
    cleaned = price_str.replace('€', '').strip()
    try:
        # Remove whitespace 
        cleaned = cleaned.replace(' ', '')
        if ',' in cleaned and '.' in cleaned:
            # Likely has both, assume standard EU '1.234,56' or EN '1,234.56'
            if cleaned.find(',') > cleaned.find('.'):
                # EU style: 1.234,56 -> 1234.56
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                # EN style: 1,234.56 -> 1234.56
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            # Single comma - might be decimal or thousands
            parts = cleaned.split(',')
            if len(parts[1]) == 3: # Thousands: 1,200
                cleaned = cleaned.replace(',', '')
            else: # Decimal: 1,20
                cleaned = cleaned.replace(',', '.')
        elif '.' in cleaned:
            # Single dot - might be decimal or thousands
            parts = cleaned.split('.')
            if len(parts[1]) == 3: # Thousands: 1.200
                cleaned = cleaned.replace('.', '')
            else:
                pass
        
        # Remove non-numeric characters except dot
        cleaned = re.sub(r'[^\d.]', '', cleaned)
        
        return float(cleaned)
    except Exception as e:
        logger.error(f"Price conversion error: {e} for {price_str}")
        return 0.0

def _get_auth_token(page: Page):
    try:
        token = page.evaluate("() => localStorage.getItem('authToken')")
        if token:
            return token
    except Exception as e:
        logger.error(f"Auth token not found: {e}")
    return None

def _graphql_request(token, operation_name, query, variables):
    url = f"https://api.xometry.eu/partners/graphql?{operation_name}"
    payload = {
        "operationName": operation_name,
        "query": query,
        "variables": variables,
    }
    try:
        resp = requests.post(
            url,
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "authorization": f"Bearer {token}",
            },
            data=json.dumps(payload),
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"GraphQL {operation_name} HTTP {resp.status_code}")
            return None
        data = resp.json()
        if data.get("errors"):
            logger.error(f"GraphQL {operation_name} errors: {data.get('errors')}")
            return None
        return data.get("data")
    except Exception as e:
        logger.error(f"GraphQL {operation_name} request failed: {e}")
        return None

def _parse_amount(value):
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        return clean_price(str(value))

def _join_unique(values):
    uniq = []
    for v in values:
        if not v:
            continue
        if v not in uniq:
            uniq.append(v)
    return ", ".join(uniq) if uniq else "Unknown"


CANONICAL_JOB_ID_RE = re.compile(r"\b(?:HJO|J)-\d+(?:-\d+)?\b", re.IGNORECASE)
CANONICAL_RFQ_ID_RE = re.compile(r"\bRFQ-\d+(?:-\d+)?\b", re.IGNORECASE)


def _extract_canonical_job_id(text):
    if not text:
        return None
    match = CANONICAL_JOB_ID_RE.search(text)
    if match:
        return match.group(0).upper()
    match = CANONICAL_RFQ_ID_RE.search(text)
    if match:
        return match.group(0).upper()
    return None


def _is_canonical_job_id(job_id):
    return bool(_extract_canonical_job_id(job_id))


def _is_gsh_job_id(job_id):
    return str(job_id or "").strip().upper().startswith(("HJO-", "J-"))


def _build_offer_link(offer_id=None, job_id=None, prefer_job_id=False):
    is_gsh_job = _is_gsh_job_id(job_id)
    canonical_job_id = _extract_canonical_job_id(job_id)
    if prefer_job_id and canonical_job_id:
        if canonical_job_id.startswith("RFQ-"):
            return f"https://partner.xometry.eu/rfqs/{canonical_job_id}"
        return f"https://partner.xometry.eu/offers/{canonical_job_id}"

    if offer_id:
        if is_gsh_job:
            return f"https://partner.xometry.eu/offers/{offer_id}?gsh=true&source=jobs&locale=en"
        return f"https://partner.xometry.eu/offers/{offer_id}?source=jobs&locale=en"

    if canonical_job_id:
        if canonical_job_id.startswith("RFQ-"):
            return f"https://partner.xometry.eu/rfqs/{canonical_job_id}"
        return f"https://partner.xometry.eu/offers/{canonical_job_id}"

    job_id = (job_id or "").strip()
    if job_id and job_id != "Unknown":
        return f"https://partner.xometry.eu/offers/{job_id}"
    return ""


def _extract_offer_display_id_from_page(page: Page):
    candidates = []

    try:
        candidates.append(page.title())
    except Exception:
        pass

    try:
        h1 = page.locator("h1").first
        if h1.count() > 0:
            candidates.append(h1.inner_text().strip())
    except Exception:
        pass

    try:
        body_text = page.evaluate(
            "() => document.body ? (document.body.innerText || '') : ''"
        )
        candidates.append(body_text)
    except Exception:
        pass

    for candidate in candidates:
        resolved = _extract_canonical_job_id(candidate)
        if resolved:
            return resolved
    return None


def _needs_offer_identity_resolution(job):
    job_id = str(job.get("id") or "").strip()
    if not job_id or job_id == "Unknown":
        return bool(job.get("offer_id"))
    if _is_gsh_job_id(job_id):
        return False
    return not _is_canonical_job_id(job_id)


def _resolve_offer_identity_from_page(page: Page, job):
    url = job.get("link") or _build_offer_link(
        offer_id=job.get("offer_id"),
        job_id=job.get("id"),
    )
    if not url:
        return None

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        logger.warning(f"Offer identity resolution failed for {url}: {e}")
        return None

    resolved_job_id = _extract_offer_display_id_from_page(page)
    if not resolved_job_id:
        return None

    return {
        "id": resolved_job_id,
        "link": _build_offer_link(
            offer_id=job.get("offer_id"),
            job_id=resolved_job_id,
            prefer_job_id=True,
        ),
    }


def _normalize_api_jobs(page: Page, jobs):
    suspicious_jobs = [job for job in jobs if _needs_offer_identity_resolution(job)]
    if not suspicious_jobs:
        return jobs

    logger.info(
        f"Resolving canonical job ids for {len(suspicious_jobs)} offers with non-standard ids..."
    )

    for job in suspicious_jobs:
        original_id = job.get("id")
        resolved = _resolve_offer_identity_from_page(page, job)
        if not resolved:
            continue

        job["id"] = resolved["id"]
        if resolved.get("link"):
            job["link"] = resolved["link"]

        if original_id != resolved["id"]:
            logger.info(f"Resolved job id {original_id} -> {resolved['id']}")

        time.sleep(0.5)

    return jobs

def _jobs_from_gsh_offers(offers, job_type_label):
    jobs = []
    for offer in offers:
        otype = offer.get("__typename")
        job_id = "Unknown"
        price = 0.0
        quantity = 0
        materials = []
        processes = []
        link = ""
        offer_id = None

        if otype == "Offer":
            job = offer.get("job") or {}
            job_id = job.get("displayId") or "Unknown"
            money = offer.get("totalValueMoney") or {}
            price = _parse_amount(money.get("amount"))
            positions = job.get("positions") or []
            offer_id = offer.get("id")
            for pos in positions:
                quantity += int(pos.get("quantity") or 0)
                materials.append(pos.get("material"))
                part = pos.get("part") or {}
                processes.append(part.get("processType"))
            link = _build_offer_link(offer_id=offer_id, job_id=job_id)
        elif otype == "JobOffer":
            job_id = offer.get("code") or "Unknown"
            money = offer.get("cost") or {}
            price = _parse_amount(money.get("amount"))
            parts = offer.get("parts") or []
            offer_id = offer.get("id")
            for part in parts:
                quantity += int(part.get("quantity") or 0)
                materials.append(part.get("material"))
                processes.append(part.get("processType"))
            link = _build_offer_link(offer_id=offer_id, job_id=job_id)

        material = _join_unique(materials)
        process = _join_unique(processes)

        if job_id == "Unknown" and price == 0.0:
            continue

        jobs.append({
            "id": job_id,
            "type": job_type_label,
            "price": price,
            "quantity": quantity,
            "material": material,
            "process": process,
            "link": link,
            "offer_id": offer_id,
            "raw_text": "api:gshJobOffers",
        })
    return jobs

def _jobs_from_rfq_offers(offers):
    jobs = []
    for offer in offers:
        rfq = offer.get("rfq") or {}
        job_id = rfq.get("xometryNumber") or "Unknown"

        # Price is often empty; use max providerPrice if present.
        prices = offer.get("prices") or []
        price_vals = []
        for p in prices:
            provider_price = (p or {}).get("providerPrice") or {}
            price_vals.append(_parse_amount(provider_price.get("amount")))
        price = max(price_vals) if price_vals else 0.0

        quantity = 0
        materials = []
        processes = []
        for pos in rfq.get("positions") or []:
            quantity += int(pos.get("quantity") or 0)
            material = (pos.get("material") or {}).get("name")
            process = (pos.get("process") or {}).get("name")
            materials.append(material)
            processes.append(process)

        material = _join_unique(materials)
        process = _join_unique(processes)

        link = f"https://partner.xometry.eu/rfqs/{job_id}" if job_id != "Unknown" else ""

        jobs.append({
            "id": job_id,
            "type": "RFQ",
            "price": price,
            "quantity": quantity,
            "material": material,
            "process": process,
            "link": link,
            "raw_text": "api:rfqOffers",
        })
    return jobs

def _fetch_gsh_job_offers(token, urgent=False):
    all_jobs = []
    seen_ids = set()
    limit = 4
    offset = 0
    max_pages = 200

    urgent_status = "only_urgent" if urgent else "without_urgent"

    for _ in range(max_pages):
        data = _graphql_request(
            token,
            "gshJobOffers",
            GSH_JOB_OFFERS_QUERY,
            {
                "filter": {"urgentStatus": urgent_status, "responseStatus": "empty"},
                "offsetAttributes": {"limit": limit, "offset": offset},
            },
        )
        if not data:
            break
        payload = data.get("gshJobOffers") or {}
        offers = payload.get("offers") or []
        jobs = _jobs_from_gsh_offers(offers, "Urgent" if urgent else "Standard")

        new_count = 0
        for job in jobs:
            jid = job.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(job)
                new_count += 1

        meta = payload.get("metadata") or {}
        has_more = meta.get("hasMore")
        if not offers or new_count == 0:
            if not has_more:
                break
        if not has_more:
            break

        offset += limit

    return all_jobs

def _fetch_rfq_offers(token):
    all_jobs = []
    seen_ids = set()
    limit = 10
    offset = 0
    max_pages = 200

    for _ in range(max_pages):
        data = _graphql_request(
            token,
            "rfqOffers",
            RFQ_OFFERS_QUERY,
            {
                "filters": {"responseState": "empty"},
                "offsetAttributes": {"limit": limit, "offset": offset},
            },
        )
        if not data:
            break
        payload = data.get("rfqOffers") or {}
        offers = payload.get("offers") or []
        jobs = _jobs_from_rfq_offers(offers)

        new_count = 0
        for job in jobs:
            jid = job.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(job)
                new_count += 1

        meta = payload.get("metadata") or {}
        total = meta.get("total")
        if not offers or new_count == 0:
            if total is None:
                break
        if total is not None and offset + limit >= total:
            break

        offset += limit

    return all_jobs

def scrape_all_via_api(page: Page):
    token = _get_auth_token(page)
    if not token:
        logger.error("API scrape skipped: missing auth token.")
        return None

    logger.info("Scraping via API (GraphQL)...")
    all_jobs = []
    try:
        all_jobs.extend(_fetch_gsh_job_offers(token, urgent=False))
        all_jobs.extend(_fetch_gsh_job_offers(token, urgent=True))
        all_jobs.extend(_fetch_rfq_offers(token))
    except Exception as e:
        logger.error(f"API scrape failed: {e}")
        return None

    _normalize_api_jobs(page, all_jobs)
    return all_jobs


def _extract_parts_from_page(page: Page):
    js = r"""
() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const txt = (el) => (el ? el.textContent.trim() : "");

  const findPartContainer = (element) => {
    let container = element.closest(".ant-card, [class*='_card_'], [class*='_info_'], div");
    if (!container || container === document.body) {
      container = element.closest("div");
      let current = element.parentElement;
      let depth = 0;
      const maxDepth = 8;
      while (current && current !== document.body && depth < maxDepth) {
        const t = txt(current);
        if (t.includes("Part ID:") &&
            (t.includes("pieces") || t.includes("piece") || t.includes("mm") || t.includes("Material:")) &&
            t.length > 100 &&
            current.offsetWidth > 200 &&
            current.offsetHeight > 100) {
          container = current;
          break;
        }
        current = current.parentElement;
        depth++;
      }
    }
    if (container && container !== document.body) {
      const t = txt(container);
      if (!t.includes("Job size") && !t.includes("Total:") && !t.includes("Lead time")) {
        return container;
      }
    }
    return null;
  };

  const findAllPartCards = () => {
    const partCards = [];

    const cards = $$(".ant-card");
    const withPartId = cards.filter(c => txt(c).includes("Part ID:"));
    if (withPartId.length > 0) {
      partCards.push(...withPartId);
    } else {
      const legacy = $$(".ant-card.ant-card-bordered._card_e2662_1");
      if (legacy.length > 0) {
        partCards.push(...legacy);
      } else {
        const partIdElements = $$("b").filter(b => /^Part ID:/i.test(txt(b)));
        partIdElements.forEach((partIdEl) => {
          const container = findPartContainer(partIdEl);
          if (container && !partCards.includes(container)) {
            partCards.push(container);
          }
        });
      }
    }
    return [...new Set(partCards)];
  };

  const extractPartDetails = (container) => {
    const details = {
      part_id: null,
      part_name: null,
      quantity: 1,
      dimensions: null,
      weight: null,
      volume: null,
      processes: [],
      material: null,
      finish: null,
      tolerance: null,
      image_url: null,
      production_remarks: null,
      price_per_unit: 0,
    };
    if (!container) return details;
    const text = txt(container);

    const partIdMatch = text.match(/Part ID:[^0-9]*(\d+)/i);
    if (partIdMatch) details.part_id = partIdMatch[1];

    const partNameElements = container.querySelectorAll('b');
    let partName = null;
    partNameElements.forEach((b) => {
      const t = b.textContent.trim();
      if (t.includes('.step') || (t.length > 10 && !t.includes('Part ID'))) {
        partName = t;
      }
    });
    if (partName) {
      details.part_name = partName;
    } else {
      const partNameMatch = text.match(/([A-Z0-9\\-_]+\\.step)/i);
      if (partNameMatch) details.part_name = partNameMatch[1];
    }

    const quantityMatch = text.match(/(\\d+)\\s*pieces?/i);
    if (quantityMatch) details.quantity = parseInt(quantityMatch[1]);

    const dimensionsMatch = text.match(/(\\d+\\.?\\d*)\\s*[x×]\\s*(\\d+\\.?\\d*)\\s*[x×]\\s*(\\d+\\.?\\d*)/i);
    if (dimensionsMatch) {
      details.dimensions = {
        length: parseFloat(dimensionsMatch[1]),
        width: parseFloat(dimensionsMatch[2]),
        height: parseFloat(dimensionsMatch[3]),
        unit: 'mm'
      };
    } else {
      const altDimensionsMatch = text.match(/(\\d+\\.?\\d*)\\s*[x×]\\s*(\\d+\\.?\\d*)\\s*[x×]\\s*(\\d+\\.?\\d*)\\s*mm?/i);
      if (altDimensionsMatch) {
        details.dimensions = {
          length: parseFloat(altDimensionsMatch[1]),
          width: parseFloat(altDimensionsMatch[2]),
          height: parseFloat(altDimensionsMatch[3]),
          unit: 'mm'
        };
      }
    }

    const weightMatch = text.match(/(\\d+\\.\\d{3})/);
    if (weightMatch) {
      details.weight = parseFloat(weightMatch[1]);
    } else {
      const altWeightMatch = text.match(/Weight[:\\s]*(\\d+\\.?\\d*)/i);
      if (altWeightMatch) details.weight = parseFloat(altWeightMatch[1]);
    }

    const volumeMatch = text.match(/(\\d+\\.?\\d*)\\s*cm3/i);
    if (volumeMatch) details.volume = parseFloat(volumeMatch[1]);

    const processSpans = container.querySelectorAll('.ant-tag');
    const processes = [];
    processSpans.forEach(span => {
      const processText = span.textContent.trim();
      if (processText &&
          !processText.includes('mm') &&
          !processText.includes('Custom') &&
          !processText.includes('Standard') &&
          !processText.includes('Aluminium') &&
          !processText.includes('Steel') &&
          !processText.includes('Plastic') &&
          processText.length > 2) {
        processes.push(processText);
      }
    });
    details.processes = processes;

    const materialSpan = container.querySelector('._notTag_u1abp_12');
    if (materialSpan) {
      details.material = materialSpan.textContent.trim();
    } else {
      const materialMatch = text.match(/Material:\\s*([^\\n]+)/i);
      if (materialMatch) {
        let val = materialMatch[1].trim();
        val = val.split("Other:")[0].split("Process:")[0].split("Production remarks:")[0].split("Tol.")[0].split("Ra:")[0].split("Material color:")[0];
        details.material = val.trim();
      } else {
        const lower = text.toLowerCase();
        const idx = lower.indexOf("material:");
        if (idx >= 0) {
          let val = text.slice(idx + "material:".length);
          val = val.split("Other:")[0].split("Process:")[0].split("Production remarks:")[0].split("Tol.")[0].split("Ra:")[0].split("Material color:")[0];
          details.material = val.trim();
        }
      }
    }

    const finishMatch = text.match(/Finish:\\s*([^\\n]+)/i);
    if (finishMatch) details.finish = finishMatch[1].trim();

    const toleranceMatch = text.match(/Tolerance:\\s*([^\\n]+)/i);
    if (toleranceMatch) details.tolerance = toleranceMatch[1].trim();

    const imgElement = container.querySelector(
      '.ant-image img, img[src*=\"s3.eu-central-1.amazonaws.com\"], img[src*=\"amazonaws.com\"], img[src*=\"s3.\"]'
    );
    if (imgElement && imgElement.src) {
      details.image_url = imgElement.src;
    } else {
      const candidates = Array.from(container.querySelectorAll('img[src]'))
        .map(i => i.src)
        .filter(src => src && !src.includes('logo') && !src.startsWith('data:'));
      if (candidates.length > 0) details.image_url = candidates[0];
    }

    const remarksMatch = text.match(/Production Remarks:\\s*([^\\n]+)/i);
    if (remarksMatch) details.production_remarks = remarksMatch[1].trim();

    return details;
  };

  const partCards = findAllPartCards();
  const parts = partCards.map((container, idx) => {
    const details = extractPartDetails(container);
    return {
      part_id: details.part_id || `part_${idx + 1}`,
      part_name: details.part_name || `Reper ${idx + 1}`,
      quantity: details.quantity || 1,
      dimensions: details.dimensions,
      weight: details.weight,
      volume: details.volume,
      processes: details.processes,
      material: details.material,
      finish: details.finish,
      tolerance: details.tolerance,
      image_url: details.image_url,
      production_remarks: details.production_remarks,
      price_per_unit: details.price_per_unit || 0
    };
  });

  const scorePart = (p) => {
    let s = 0;
    if (p.part_name) s += 1;
    if (p.dimensions) s += 2;
    if (p.weight) s += 1;
    if (p.volume) s += 1;
    if (p.material) s += 2;
    if (p.processes && p.processes.length) s += 1;
    if (p.image_url) s += 2;
    if (p.production_remarks) s += 1;
    return s;
  };

  const byId = {};
  for (const p of parts) {
    const key = String(p.part_id);
    if (!byId[key] || scorePart(p) > scorePart(byId[key])) {
      byId[key] = p;
    }
  }
  return Object.values(byId);
}
"""
    try:
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        try:
            page.wait_for_selector("text=Part ID", timeout=5000)
        except Exception:
            pass
        try:
            page.wait_for_selector("text=Material", timeout=5000)
        except Exception:
            pass
        return page.evaluate(js) or []
    except Exception as e:
        logger.error(f"Part extraction failed: {e}")
        return []


def _extract_part_fallbacks(page: Page):
    js = r"""
() => {
  const cards = Array.from(document.querySelectorAll(".ant-card"));
  const map = {};
  const dimRe = /(\\d+\\.?\\d*)\\s*[x×]\\s*(\\d+\\.?\\d*)\\s*[x×]\\s*(\\d+\\.?\\d*)/i;
  const qtyRe = /(\\d+)\\s*(?:pieces?|pcs|buc)/i;
  cards.forEach(c => {
    const text = (c.innerText || c.textContent || "");
    if (!text.includes("Part ID")) return;
    const idMatch = text.match(/Part ID:[^0-9]*(\\d+)/i);
    if (!idMatch) return;
    const pid = idMatch[1];
    const m = text.match(dimRe);
    const q = text.match(qtyRe);
    if (!map[pid]) map[pid] = {};
    if (m) {
      map[pid].dimensions = {
        length: parseFloat(m[1]),
        width: parseFloat(m[2]),
        height: parseFloat(m[3]),
        unit: "mm"
      };
    }
    if (q) {
      map[pid].quantity = parseInt(q[1]);
    }
  });
  return map;
}
"""
    try:
        return page.evaluate(js) or {}
    except Exception:
        return {}


def _extract_part_fallbacks_py(page: Page):
    fallback = {}
    try:
        cards = page.locator(".ant-card").all()
    except Exception:
        return fallback

    for card in cards:
        try:
            text = card.inner_text()
        except Exception:
            continue
        if "Part ID" not in text:
            continue
        id_match = re.search(r"Part ID:[^0-9]*(\d+)", text)
        if not id_match:
            continue
        pid = id_match.group(1)
        if pid not in fallback:
            fallback[pid] = {}

        dim_match = re.search(r"(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)", text)
        if dim_match:
            fallback[pid]["dimensions"] = {
                "length": float(dim_match.group(1)),
                "width": float(dim_match.group(2)),
                "height": float(dim_match.group(3)),
                "unit": "mm",
            }

        qty_match = re.search(r"(\d+)\s*(?:pieces?|pcs|buc)", text, re.IGNORECASE)
        if qty_match:
            fallback[pid]["quantity"] = int(qty_match.group(1))

    return fallback


def build_offer_payload(page: Page, job):
    offer_id = job.get("offer_id")
    if not offer_id:
        return None
    if job.get("id", "").startswith("RFQ-"):
        return None

    url = job.get("link") or _build_offer_link(offer_id=offer_id, job_id=job.get("id"))
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        logger.error(f"Offer page load failed for {offer_id}: {e}")
        return None

    resolved_job_id = _extract_offer_display_id_from_page(page) or job.get("id") or ""
    canonical_link = _build_offer_link(
        offer_id=offer_id,
        job_id=resolved_job_id,
        prefer_job_id=bool(_extract_canonical_job_id(resolved_job_id)),
    )

    parts = _extract_parts_from_page(page)
    fallbacks = _extract_part_fallbacks(page)
    if not fallbacks:
        fallbacks = _extract_part_fallbacks_py(page)
    if fallbacks:
        for part in parts:
            pid = str(part.get("part_id") or "")
            fb = fallbacks.get(pid)
            if not fb:
                continue
            if not part.get("dimensions") and fb.get("dimensions"):
                part["dimensions"] = fb["dimensions"]
            if (part.get("quantity") or 0) <= 1 and fb.get("quantity"):
                part["quantity"] = fb["quantity"]
    try:
        api_qty = int(job.get("quantity") or 0)
    except Exception:
        api_qty = 0

    if parts and api_qty > 1:
        all_one = all(int(p.get("quantity") or 0) <= 1 for p in parts)
        if all_one:
            if len(parts) == 1:
                parts[0]["quantity"] = api_qty
            elif api_qty % len(parts) == 0:
                per = api_qty // len(parts)
                for p in parts:
                    p["quantity"] = per
    parts_pricing = [{"part_index": i, "price_per_unit": 0} for i in range(len(parts))]
    payload = {
        "offer_id": str(offer_id),
        "title": resolved_job_id,
        "url": canonical_link or url,
        "parts": parts,
        "parts_pricing": parts_pricing,
        "total_price": 0,
    }
    return payload


def build_backend_payloads(page: Page, jobs, skip_offer_ids=None, max_offers=None):
    skip = {str(x) for x in (skip_offer_ids or set())}
    payloads = []
    processed = 0
    for job in jobs:
        offer_id = job.get("offer_id")
        if not offer_id:
            continue
        if str(offer_id) in skip:
            continue

        payload = build_offer_payload(page, job)
        if payload:
            payloads.append(payload)

        processed += 1
        if max_offers and processed >= max_offers:
            break
        time.sleep(1)

    return payloads


def _parse_dimensions_text(text):
    if not text:
        return None
    m = re.search(r"(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)", text)
    if not m:
        return None
    return {
        "length": float(m.group(1)),
        "width": float(m.group(2)),
        "height": float(m.group(3)),
        "unit": "mm",
    }


def _parse_date_text(text):
    if not text:
        return None
    m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if m:
        return m.group(0)
    m = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", text)
    if m:
        return m.group(0)
    return None


def _download_image_base64(url, request_context=None):
    if not url:
        return None
    try:
        if request_context is not None:
            try:
                resp = request_context.get(url, timeout=20000)
                if resp and resp.ok:
                    content_type = resp.headers.get("content-type") or "image/png"
                    body = resp.body()
                    if body:
                        b64 = base64.b64encode(body).decode("ascii")
                        return f"data:{content_type};base64,{b64}"
            except Exception:
                try:
                    logger.debug(f"Playwright request image failed: url={url}")
                except Exception:
                    pass
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200 or not resp.content:
            try:
                logger.debug(
                    f"Image download failed: status={resp.status_code} url={url}"
                )
            except Exception:
                pass
            return None
        content_type = resp.headers.get("content-type") or "image/png"
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception:
        try:
            logger.debug(f"Image download exception: url={url}")
        except Exception:
            pass
        return None


def _collect_order_links(page: Page, max_rounds=2):
    seen = set()
    current_round = 0
    while current_round < max_rounds:
        current_round += 1
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        try:
            links = page.evaluate(
                """() => {
                    const anchors = Array.from(document.querySelectorAll("a[href^='/orders/']"));
                    const out = [];
                    for (const a of anchors) {
                        const href = a.getAttribute("href") || "";
                        if (!href.startsWith("/orders/")) continue;
                        if (href.includes("orders?")) continue;
                        const clean = href.split("?")[0].split("#")[0];
                        const parts = clean.split("/").filter(Boolean);
                        if (parts.length === 2 && parts[0] === "orders" && parts[1]) {
                            out.push(`${location.origin}${clean}`);
                        }
                    }
                    return Array.from(new Set(out));
                }"""
            )
        except Exception:
            links = []
        for href in links or []:
            seen.add(href)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.6)
        except Exception:
            pass
    return list(seen)


def _get_orders_max_page(page: Page):
    try:
        return page.evaluate(
            """() => {
                const items = Array.from(document.querySelectorAll("li.ant-pagination-item a"));
                const nums = items.map(a => parseInt(a.textContent || "", 10)).filter(n => !isNaN(n));
                if (!nums.length) return 1;
                return Math.max(...nums);
            }"""
        )
    except Exception:
        return 1


def _goto_orders_page(page: Page, page_num: int):
    if page_num <= 1:
        return True
    try:
        selector = f"li.ant-pagination-item a:has-text('{page_num}')"
        link = page.locator(selector).first
        if link.count() == 0:
            return False
        before = page.locator("a[href^='/orders/']").first.get_attribute("href")
        link.click()
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        try:
            page.wait_for_selector("a[href^='/orders/']", timeout=10000)
        except Exception:
            pass
        after = page.locator("a[href^='/orders/']").first.get_attribute("href")
        return before != after or after is not None
    except Exception:
        return False


def _extract_order_details(page: Page):
    js = r"""
async () => {
  const txt = (el) => (el ? (el.textContent || "").replace(/\u00a0/g, " ").trim() : "");
  const bodyText = document.body ? (document.body.innerText || "") : "";

  const findInText = (re) => {
    const m = bodyText.match(re);
    return m ? (m[1] || m[0]) : null;
  };

  const orderId =
    txt(document.querySelector("._title_1of3e_1")) ||
    findInText(/\bPO-\d+\b/);

  let status = null;
  const statusEl = document.querySelector("._stateContainer_1of3e_39") || document.querySelector("._state_z5s0i_151");
  if (statusEl) {
    status = txt(statusEl);
  } else {
    status = findInText(/Need order confirmation|In production|Shipping|Delivered|Cancelled/i);
  }

  const leadTime = findInText(/Lead time:\s*(\d{2}\.\d{2}\.\d{4})/i);

  const getLabelValue = (root, label) => {
    const items = Array.from(root.querySelectorAll("div"));
    for (const el of items) {
      const b = el.querySelector(":scope > b");
      if (!b) continue;
      const btxt = txt(b).replace(/\s+/g, " ").trim();
      if (btxt.startsWith(label)) {
        let val = "";
        for (const node of el.childNodes) {
          if (node === b) continue;
          if (node.nodeType === Node.TEXT_NODE || node.nodeType === Node.ELEMENT_NODE) {
            val += node.textContent || "";
          }
        }
        val = val.replace(/\u00a0/g, " ").trim();
        if (val.startsWith(":")) val = val.slice(1).trim();
        if (!val) return null;
        if (val.includes("…") || val.includes("...")) {
          const titleEl = el.querySelector("[title]");
          if (titleEl && titleEl.getAttribute("title")) {
            return titleEl.getAttribute("title").trim();
          }
          const ariaEl = el.querySelector("[aria-label]");
          if (ariaEl && ariaEl.getAttribute("aria-label")) {
            return ariaEl.getAttribute("aria-label").trim();
          }
        }
        return val;
      }
    }
    return null;
  };

  const stripExt = (val) => {
    if (!val) return val;
    const trimmed = val.trim();
    const m = trimmed.match(/^(.*)\\.([A-Za-z0-9]{1,10})$/);
    if (!m) return trimmed;
    return m[1] || trimmed;
  };

  const findPartContainers = () => {
    const direct = Array.from(document.querySelectorAll("._container_1xtgm_1"));
    if (direct.length) return direct;
    const labels = Array.from(document.querySelectorAll("b")).filter((b) =>
      /Part ID/i.test(b.textContent || "")
    );
    const containers = new Set();
    for (const b of labels) {
      let el = b.closest("div");
      let hops = 0;
      while (el && hops < 8) {
        const text = txt(el);
        if (/Price per piece/i.test(text) || /Total price/i.test(text) || /Quantity/i.test(text)) {
          containers.add(el);
          break;
        }
        if (el.querySelector("img")) {
          containers.add(el);
          break;
        }
        el = el.parentElement;
        hops += 1;
      }
    }
    return Array.from(containers);
  };

  const blobToBase64 = (blob) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });

  const pickSignedUrl = (urls) => {
    if (!urls || !urls.length) return null;
    const prefer = urls.find((u) => u && (u.includes("X-Amz-") || u.includes("token=")));
    return prefer || urls[0];
  };

  const getImageUrl = (container) => {
    const imgs = Array.from(container.querySelectorAll("img"));
    const candidates = [];
    for (const im of imgs) {
      if (!im) continue;
      const current = im.currentSrc;
      if (current) candidates.push(current);
      const src = im.src || im.getAttribute("src");
      if (src) candidates.push(src);
      const dataSrc = im.getAttribute("data-src") || im.getAttribute("data-original");
      if (dataSrc) candidates.push(dataSrc);
      const srcset = im.getAttribute("srcset");
      if (srcset) {
        const first = srcset.split(",").map((s) => s.trim().split(" ")[0]).filter(Boolean);
        candidates.push(...first);
      }
    }
    const filtered = candidates.filter(Boolean);
    return pickSignedUrl(filtered);
  };

  const parts = [];
  const containers = findPartContainers();
  containers.forEach((container) => {
    const desc = container.querySelector("._description_1xtgm_70") || container;
    const otherInfo = container.querySelector("._otherInfoContainer_1xtgm_58") || desc;

    const partId = getLabelValue(desc, "Part ID") || container.getAttribute("id");
    let name = getLabelValue(desc, "Name") || null;
    if (!name || name.includes("…") || name.includes("...")) {
      const nameEl = Array.from(desc.querySelectorAll("div")).find((el) => {
        const b = el.querySelector(":scope > b");
        return b && /Name/i.test(txt(b));
      });
      if (nameEl) {
        const titleEl = nameEl.querySelector("[title]") || nameEl.querySelector("[aria-label]");
        if (titleEl) {
          const titleVal = titleEl.getAttribute("title") || titleEl.getAttribute("aria-label");
          if (titleVal && titleVal.length > 3) name = titleVal.trim();
        }
      }
    }
    if (!name || name.includes("…") || name.includes("...")) {
      const imgAlt = (container.querySelector("img[alt]") || {}).alt;
      if (imgAlt && imgAlt.length > 3) name = imgAlt;
    }
    if (!name || name.includes("…") || name.includes("...")) {
      const titleName = (desc.querySelector("[title]") || {}).title;
      if (titleName && titleName.length > 3) name = titleName;
    }
    if (!name) {
      name = (txt(desc).match(/([A-Z0-9\\-_]+\\.(?:step|stp|dxf|pdf|sldprt))/i) || [])[1] || null;
    }
    name = stripExt(name);
    const material = getLabelValue(desc, "Material");
    const dimsText = getLabelValue(desc, "Dimensions");

    const qtyEl = container.querySelector("._quantityTag_1xtgm_61") || otherInfo;
    const qtyText = qtyEl ? txt(qtyEl) : "";
    const qtyMatch = qtyText.match(/(\d+)\s*(pcs|pieces|buc)?/i);
    const quantity = qtyMatch ? parseInt(qtyMatch[1]) : null;

    const priceUnit = getLabelValue(otherInfo, "Price per piece");
    const priceTotal = getLabelValue(otherInfo, "Total price");

    const imageUrl = getImageUrl(container);

    if (partId || name || material || dimsText || quantity || priceUnit || priceTotal || imageUrl) {
      parts.push({
        part_id: partId,
        part_name: name,
        material: material,
        dimensions_text: dimsText,
        quantity: quantity,
        price_unit: priceUnit,
        price_total: priceTotal,
        image_url: imageUrl,
        image_data: null
      });
    }
  });

  let imageOk = 0;
  let imageFail = 0;
  await Promise.all(parts.map(async (p) => {
    if (!p.image_url) return;
    try {
      const resp = await fetch(p.image_url, { mode: "cors", credentials: "omit" });
      if (!resp.ok) {
        imageFail += 1;
        return;
      }
      const blob = await resp.blob();
      const dataUrl = await blobToBase64(blob);
      if (dataUrl) {
        p.image_data = dataUrl;
        imageOk += 1;
      } else {
        imageFail += 1;
      }
    } catch (e) {
      p.image_data = null;
      imageFail += 1;
    }
  }));

  return {
    order_id: orderId,
    status: status,
    date: leadTime,
    parts: parts,
    image_fetch_ok: imageOk,
    image_fetch_fail: imageFail
  };
}
"""
    try:
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        try:
            page.wait_for_selector("._container_1xtgm_1, text=Part ID", timeout=10000)
        except Exception:
            pass
        return page.evaluate(js) or {}
    except Exception as e:
        logger.error(f"Order detail extraction failed: {e}")
        return {}


def scrape_orders(
    page: Page,
    details_page: Page,
    max_orders=None,
    scroll_rounds=8,
    seen_order_ids=None,
    max_pages=0,
    stop_after_empty_pages=0,
    process_only_new=True,
):
    try:
        page.goto(config.ORDERS_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector("a[href^='/orders/']", timeout=15000)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Orders page load failed: {e}")
        return []

    seen_ids = set(seen_order_ids or [])
    order_links = []
    empty_pages = 0
    max_found = _get_orders_max_page(page)
    if max_pages and max_pages > 0:
        max_found = min(max_found, max_pages)

    for page_num in range(1, max_found + 1):
        if page_num > 1:
            _goto_orders_page(page, page_num)
        links = _collect_order_links(page, max_rounds=scroll_rounds)
        if not links:
            empty_pages += 1
        else:
            new_links = []
            for href in links:
                key = href.rstrip("/").split("/")[-1]
                if key not in seen_ids:
                    new_links.append(href)
                seen_ids.add(key)
            if new_links:
                empty_pages = 0
                order_links.extend(new_links if process_only_new else links)
            else:
                empty_pages += 1
        if stop_after_empty_pages and empty_pages >= stop_after_empty_pages:
            logger.info(
                f"Stopping orders pagination after {empty_pages} pages without new orders."
            )
            break

    if not order_links:
        logger.warning("No order links found.")
        return [], seen_ids

    orders = []
    image_data_count = 0
    total_links = len(order_links)
    start_ts = time.time()
    empty_parts_saved = 0
    extra_pages = []
    for idx, link in enumerate(order_links):
        if max_orders and idx >= max_orders:
            break
        try:
            details_page.goto(link, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            if "Page crashed" in str(e):
                try:
                    details_page.close()
                except Exception:
                    pass
                try:
                    details_page = page.context.new_page()
                    extra_pages.append(details_page)
                    details_page.goto(link, wait_until="domcontentloaded", timeout=30000)
                except Exception as e2:
                    logger.error(f"Order detail load failed: {link}: {e2}")
                    continue
            else:
                logger.error(f"Order detail load failed: {link}: {e}")
                continue

        data = _extract_order_details(details_page) or {}
        order_id = data.get("order_id")
        status = data.get("status")
        date = data.get("date")
        parts = data.get("parts") or []
        if not parts:
            try:
                logger.warning(
                    f"Order parts empty: {order_id} url={link} title={details_page.title()}"
                )
            except Exception:
                logger.warning(f"Order parts empty: {order_id} url={link}")
            if empty_parts_saved < 5:
                try:
                    os.makedirs("data/debug_orders", exist_ok=True)
                    safe_id = (order_id or f"order_{idx}").replace("/", "_")
                    path = os.path.join("data/debug_orders", f"{safe_id}.html")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(details_page.content())
                    empty_parts_saved += 1
                except Exception:
                    pass
        if data.get("image_fetch_ok") or data.get("image_fetch_fail"):
            logger.info(
                f"Order images fetch: ok={data.get('image_fetch_ok')}, "
                f"fail={data.get('image_fetch_fail')} ({order_id})"
            )

        for part in parts:
            dims = _parse_dimensions_text(part.get("dimensions_text") or "")
            if dims and not part.get("dimensions"):
                part["dimensions"] = dims
            part_entry = {
                "order_id": order_id,
                "order_url": link,
                "part_id": part.get("part_id"),
                "part_name": part.get("part_name"),
                "material": part.get("material"),
                "dimensions": part.get("dimensions"),
                "quantity": part.get("quantity"),
                "price_unit": part.get("price_unit"),
                "price_total": part.get("price_total"),
                "date": date,
                "status": status,
                "image_url": part.get("image_url"),
                "image_data": part.get("image_data"),
            }
            if not part_entry["image_data"] and part_entry.get("image_url"):
                try:
                    req_ctx = details_page.request
                except Exception:
                    req_ctx = None
                part_entry["image_data"] = _download_image_base64(
                    part_entry["image_url"], request_context=req_ctx
                )
            orders.append(part_entry)
            if part_entry.get("image_data"):
                image_data_count += 1
        time.sleep(1)

        if (idx + 1) % 5 == 0 or (idx + 1) == total_links:
            elapsed = max(1.0, time.time() - start_ts)
            rate = (idx + 1) / elapsed
            remaining = total_links - (idx + 1)
            eta = remaining / rate if rate > 0 else 0
            logger.info(
                f"Orders sync progress: {idx + 1}/{total_links} orders, "
                f"records={len(orders)}, images={image_data_count}, "
                f"eta={eta:.1f}s"
            )
        if (idx + 1) % 100 == 0:
            try:
                details_page.close()
            except Exception:
                pass
            try:
                details_page = page.context.new_page()
                extra_pages.append(details_page)
            except Exception:
                pass

    if image_data_count:
        logger.info(f"Orders sync images embedded: {image_data_count}")
    for p in extra_pages:
        try:
            p.close()
        except Exception:
            pass
    return orders, seen_ids

def extract_job_data(card: Locator, job_type="Standard"):
    """
    Extracts data from a single job card using robust text-based strategies
    compatible with Ant Design structure.
    """
    try:
        # 1. Get all text first for regex scanning
        card_text = card.inner_text()
        
        # 2. Extract ID
        job_id = "Unknown"
        try:
             # Try specific element first
             header = card.locator("h4").first
             if header.is_visible():
                 job_id = header.inner_text().strip()
             else:
                 # Fallback regex
                 match = re.search(r'((?:HJO|J)-\d+(?:-\d+)?|RFQ-\d+)', card_text)
                 if match:
                     job_id = match.group(1)
             
             # Clean ID: many RFQs have "RFQ-xxx / Offer xxx". Keep only the first part.
             if " / " in job_id:
                 job_id = job_id.split(" / ")[0].strip()
             # Replace non-breaking space and other junk
             job_id = job_id.replace('\u00a0', ' ').strip()
        except:
            pass

        # 3. Extract Price
        price = 0.0
        try:
            # More robust regex search for Total: followed by price, ignoring whitespace/newlines
            # Look for "Total:" then some whitespace/newlines then a price pattern
            price_match = re.search(r'Total:\s*.*?(\d[\d\.,]*\s?€|€\s?[\d\.,]*)', card_text, re.DOTALL | re.IGNORECASE)
            
            if price_match:
                price_str = price_match.group(1)
                price = clean_price(price_str)
            else:
                # Fallback: scan for any large price-looking string if Total is missing
                fallback_match = re.search(r'(€\s?[\d\.,]+|[\d\.,]+\s?€)', card_text)
                if fallback_match:
                    price = clean_price(fallback_match.group(1))
        except Exception as e:
            logger.debug(f"Price extract error: {e}")

        # 4. Process and Material
        process = "Unknown"
        material = "Unknown"
        
        try:
            if "Process:" in card_text:
                p_match = re.search(r'Process:\s*(.*?)(?=\nMaterial:|\nOther:|$)', card_text, re.DOTALL)
                if p_match:
                    raw = p_match.group(1).strip()
                    process = ", ".join([line.strip() for line in raw.split('\n') if line.strip()])
            
            if "Material:" in card_text:
                m_match = re.search(r'Material:\s*(.*?)(?=\nOther:|$)', card_text, re.DOTALL)
                if m_match:
                    raw = m_match.group(1).strip()
                    material = ", ".join([line.strip() for line in raw.split('\n') if line.strip()])
        except:
            pass

        # 4b. Extract Quantity
        quantity = 0
        try:
             # Look for "24 pcs" or "Job size: 2 parts (6 pcs)" -> we want 6 if possible, else 2
             # Regex for "X pcs"
             pcs_match = re.search(r'(\d+)\s*pcs', card_text, re.IGNORECASE)
             if pcs_match:
                 quantity = int(pcs_match.group(1))
             else:
                 # Fallback: "X parts"
                 parts_match = re.search(r'(\d+)\s*parts', card_text, re.IGNORECASE)
                 if parts_match:
                     quantity = int(parts_match.group(1))
        except:
             pass

        # 5. Extract Link
        link = ""
        try:
            # Priority: Links containing /offers/ or /rfqs/ 
            # AND NOT containing .zip or 'download'
            
            all_links = card.locator("a").all()
            for l in all_links:
                href = l.get_attribute("href")
                if not href:
                    continue
                
                href_lower = href.lower()
                # Filter out bad links
                if ".zip" in href_lower or "download" in href_lower:
                    continue
                    
                # Check for good links
                if "/offers/" in href or "/rfqs/" in href:
                    if href.startswith("/"):
                        link = f"https://partner.xometry.eu{href}"
                    else:
                        link = href
                    break # Found the best link
            
            # Fallback if no specific offer link found, but there is an ID
            if not link and job_id != "Unknown":
                # Construct link based on ID pattern
                if job_id.startswith(("HJO-", "J-")):
                     # Standard Job: https://partner.xometry.eu/offers/J-1736113-306487
                     link = f"https://partner.xometry.eu/offers/{job_id}"
                elif job_id.startswith("RFQ-"):
                     # RFQ: https://partner.xometry.eu/rfqs/RFQ-D14-0466
                     link = f"https://partner.xometry.eu/rfqs/{job_id}"
                
        except Exception as e:
            logger.debug(f"Link extract error: {e}")

        if job_id == "Unknown" and price == 0.0:
            return None # Not a valid job card

        return {
            "id": job_id,
            "type": job_type,
            "price": price,
            "quantity": quantity,
            "material": material,
            "process": process,
            "link": link,
            "raw_text": card_text[:100] # store snippet for debug
        }
    except Exception as e:
        logger.error(f"Error parsing card: {e}")
        return None

def get_jobs(page: Page, job_type="Standard"):
    """
    Scrapes jobs from the current active tab.
    """
    jobs = []
    
    # Force remove banner before looking for cards
    try:
        page.evaluate("() => { const el = document.getElementById('usercentrics-root'); if(el) el.remove(); }")
    except:
        pass

    # Wait for list to load
    try:
        page.wait_for_selector("text=Job Board", timeout=15000)
    except:
        logger.error(f"TIMEOUT waiting for Job Board on {page.url}")
        return []

    # Get all potential job cards
    cards = page.locator(".ant-card").all()
    
    logger.info(f"  [DEBUG] Found {len(cards)} .ant-card elements.")
    
    if len(cards) == 0:
        try:
            body_text = page.inner_text("body")
            logger.info(f"  [DEBUG] No cards. Page text sample: {body_text[:200]}...")
        except:
            pass
    
    for i, card in enumerate(cards):
        # We try to extract data from every card. Non-job cards will return None.
        job_data = extract_job_data(card, job_type=job_type)
        if job_data:
            logger.info(f"  [JOB] Found ID: {job_data['id']} | Price: {job_data['price']} | Mat: {job_data['material'][:20]}...")
            jobs.append(job_data)
        else:
            pass
            
    return jobs


def safe_click(page, selector):
    """
    Removes banner and performs a JS click.
    """
    try:
        page.evaluate("() => { const el = document.getElementById('usercentrics-root'); if(el) el.remove(); }")
        # Click element if it exists
        page.evaluate(f"() => {{ const el = document.querySelector('{selector}'); if(el) el.click(); }}")
        return True
    except Exception as e:
        logger.debug(f"JS Click failed for {selector}: {e}")
        return False

def remove_cookie_banner(page):
    try:
        page.evaluate("() => { const el = document.getElementById('usercentrics-root'); if(el) el.remove(); }")
    except:
        pass

def scrape_with_pagination(page, job_type="Standard", allow_infinite_scroll=True):
    """
    Scrapes the current page, tries to click 'Next', and repeats until no more pages.
    """
    # If pagination is missing, fall back to infinite scroll (unless disabled).
    if allow_infinite_scroll:
        try:
            pagination = page.locator(".ant-pagination").first
            if not pagination.is_visible():
                logger.info("  Pagination not visible. Switching to infinite scroll.")
                return scrape_with_infinite_scroll(page, job_type=job_type)
        except Exception:
            logger.info("  Pagination not detected. Switching to infinite scroll.")
            return scrape_with_infinite_scroll(page, job_type=job_type)

    all_jobs = []
    page_num = 1
    max_pages = 20 # Safety limit
    
    while page_num <= max_pages:
        logger.info(f"  [START] accessing Page {page_num}...")
        
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except:
            pass

        current_page_jobs = get_jobs(page, job_type=job_type)
        all_jobs.extend(current_page_jobs)
        logger.info(f"  [INFO] Found {len(current_page_jobs)} jobs on Page {page_num}.")
        
        # Look for the Next button
        try:
            next_btn = page.locator(".ant-pagination-next").first
            
            if not next_btn.is_visible():
                logger.info("  No pagination found (single page).")
                break
                
            class_attr = next_btn.get_attribute("class") or ""
            if "ant-pagination-disabled" in class_attr:
                logger.info("  Next button is disabled. Reached last page.")
                break
                
            logger.info("  Clicking Next page...")
            remove_cookie_banner(page)
            try:
                next_btn.evaluate("el => el.click()")
            except:
                next_btn.click(force=True)
            
            time.sleep(4) 
            page_num += 1
            
        except Exception as e:
            logger.error(f"  Error handling pagination: {e}")
            break
            
    return all_jobs

def _scroll_down(page):
    """
    Scrolls the main scrollable container if present, otherwise scrolls the window.
    Returns True if a scrollable container was used.
    """
    try:
        return page.evaluate("""
        () => {
            const root = document.querySelector('#root') || document.body;
            const els = Array.from(root.querySelectorAll('*'));
            const candidates = [];
            for (const el of els) {
                const style = window.getComputedStyle(el);
                const overflowY = style.overflowY;
                if ((overflowY === 'auto' || overflowY === 'scroll') &&
                    (el.scrollHeight > el.clientHeight + 100)) {
                    candidates.push(el);
                }
            }
            if (candidates.length > 0) {
                // Choose the tallest scrollable area.
                candidates.sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
                const target = candidates[0];
                target.scrollTop = target.scrollHeight;
                return true;
            }
            window.scrollTo(0, document.body.scrollHeight);
            return false;
        }
        """)
    except Exception as e:
        logger.debug(f"Scroll eval failed: {e}")
        return False

def scrape_with_infinite_scroll(page, job_type="Standard"):
    """
    Scrapes jobs by scrolling until no new items are loaded.
    """
    all_jobs = []
    seen_ids = set()
    max_scrolls = 30
    max_no_new_rounds = 3
    no_new_rounds = 0

    # Start at the top
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass

    last_seen_count = 0

    for _ in range(max_scrolls):
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        current_jobs = get_jobs(page, job_type=job_type)
        new_found = 0
        for job in current_jobs:
            jid = job.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(job)
                new_found += 1

        if len(all_jobs) == last_seen_count and new_found == 0:
            no_new_rounds += 1
        else:
            no_new_rounds = 0
            last_seen_count = len(all_jobs)

        if no_new_rounds >= max_no_new_rounds:
            logger.info("  No new jobs after scrolling. Stopping.")
            break

        remove_cookie_banner(page)
        _scroll_down(page)
        time.sleep(2)

    return all_jobs

def scrape_all(page: Page):
    api_jobs = scrape_all_via_api(page)
    if api_jobs is not None and len(api_jobs) > 0:
        return api_jobs
    if api_jobs is not None and len(api_jobs) == 0:
        logger.warning("API returned 0 jobs. Falling back to UI scrape.")

    all_opportunities = []
    
    # Wait for tabs to load
    try:
        page.wait_for_selector(".ant-tabs-tab", timeout=15000)
    except:
        logger.error("Timeout: Tab bar not found on page.")
    
    # 1. Urgent Jobs
    logger.info("Scraping Urgent Jobs...")
    try:
        # Match "Urgent" anywhere in key (case-insensitive)
        urgent_tab = page.get_by_role("tab", name=re.compile("Urgent", re.IGNORECASE)).first
        if urgent_tab.is_visible():
            remove_cookie_banner(page)
            urgent_tab.click()
            time.sleep(3) 
            all_opportunities.extend(scrape_with_pagination(page, job_type="Urgent"))
        else:
            logger.error("Urgent tab (role) not found")
    except Exception as e:
        logger.error(f"Error scraping Urgent tab: {e}")

    # 2. RFQs
    logger.info("Scraping RFQs...")
    try:
        rfq_tab = page.get_by_role("tab", name=re.compile("RFQ", re.IGNORECASE)).first
        if rfq_tab.is_visible():
            remove_cookie_banner(page)
            rfq_tab.click()
            time.sleep(3)
            all_opportunities.extend(scrape_with_pagination(page, job_type="RFQ", allow_infinite_scroll=False))
        else:
            logger.error("RFQ tab (role) not found")
    except Exception as e:
        logger.error(f"Error scraping RFQ tab: {e}")
        
    # 3. Standard Jobs
    logger.info("Scraping Standard Jobs...")
    try:
        # Usually checking for "Job Board" or "Offers" or "Standard"
        # Let's try matching "Offers" but exclude Urgent if possible, or just click the first tab that says "Offers" 
        # that ISN'T the urgent one? 
        # Actually in AnT design, the tabs might be named "Job Board" and "Urgent Offers".
        # Let's try a broader regex for the main offers tab.
        # Often the main tab is just "Job Board" or "All Offers"
        # Let's try searching for "Job" or "Board" or "Standard"
        
        # Taking a guess based on Xometry UI: "Job board" is the header. The tab likely says "Offers" or "Live Offers".
        # We will try a few likely candidates.
        std_tab = page.get_by_role("tab", name=re.compile("Offer|Job", re.IGNORECASE)).first
        
        # If it finds "Urgent Offers" first, we might be in trouble. 
        # If we iterate we can skip "Urgent".
        tabs = page.get_by_role("tab").all()
        found_std = False
        for t in tabs:
            txt = t.inner_text().lower()
            if "urgent" not in txt and "rfq" not in txt:
                # This is likely the standard tab
                if t.is_visible():
                    remove_cookie_banner(page)
                    t.click()
                    time.sleep(3)
                    all_opportunities.extend(scrape_with_pagination(page, job_type="Standard"))
                    found_std = True
                    break
        
        if not found_std:
             logger.error("Standard/Offers tab (role) not found via exclusion")

    except Exception as e:
        logger.error(f"Error scraping Standard tab: {e}")

    # Final Deduplication
    unique_jobs = {}
    for job in all_opportunities:
        jid = job.get('id')
        if jid and jid != "Unknown":
            if jid not in unique_jobs:
                unique_jobs[jid] = job
            else:
                # If we already have it, maybe prioritize one with link
                if not unique_jobs[jid].get('link') and job.get('link'):
                    unique_jobs[jid] = job

    return list(unique_jobs.values())
