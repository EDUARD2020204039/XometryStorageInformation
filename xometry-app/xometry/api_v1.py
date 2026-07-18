"""Versioned API contracts introduced during the architecture refactor."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, func, or_
from sqlalchemy.orm import Session

from .db import get_db
from .models import Offer, Order, Part
from .part_history import best_name_from_details, match_part, part_tokens


router = APIRouter(tags=["API v1"])


@router.get("/api/v1/orders/summary")
async def order_summary(db: Session = Depends(get_db)):
    total_rows = db.query(func.count(Order.id)).scalar() or 0
    total_orders = db.query(func.count(func.distinct(Order.order_id))).scalar() or 0
    status_rows = db.query(Order.status, func.count(Order.id)).group_by(Order.status).all()
    status_orders = (
        db.query(Order.status, func.count(func.distinct(Order.order_id)))
        .group_by(Order.status)
        .all()
    )
    return {
        "total_orders": total_orders,
        "total_rows": total_rows,
        "by_status": {
            str(status or "unknown"): {
                "orders": dict(status_orders).get(status, 0),
                "rows": rows,
            }
            for status, rows in status_rows
        },
    }


def _offer_url(offer: Offer | None) -> str | None:
    if not offer:
        return None
    return offer.url or f"https://partner.xometry.eu/offers/{offer.offer_id}"


@router.get("/api/parts/history", deprecated=True)
@router.get("/api/v1/parts/history")
async def part_history(
    part_id: Optional[str] = None,
    part_name: Optional[str] = None,
    material: Optional[str] = None,
    length: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    current_offer_id: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    if not part_id and not part_name:
        raise HTTPException(status_code=400, detail="part_id or part_name is required")

    tokens = part_tokens(part_name)[:5]
    part_filters = [Part.part_id.ilike(str(part_id))] if part_id else []
    order_filters = [Order.part_id.ilike(str(part_id))] if part_id else []
    for token in tokens:
        term = f"%{token}%"
        part_filters.append(Part.name.ilike(term))
        order_filters.append(Order.details.cast(String).ilike(term))

    parts = db.query(Part).filter(or_(*part_filters)).limit(250).all() if part_filters else []
    orders = db.query(Order).filter(or_(*order_filters)).limit(250).all() if order_filters else []
    query_dimensions = (length, width, height)
    matches: list[dict] = []

    for candidate in parts:
        offer = candidate.offer
        if current_offer_id and offer and str(offer.offer_id) == str(current_offer_id):
            continue
        verdict = match_part(
            query_part_id=part_id,
            query_name=part_name,
            candidate_part_id=candidate.part_id,
            candidate_name=candidate.name,
            query_material=material,
            candidate_material=candidate.material,
            query_dimensions=query_dimensions,
            candidate_dimensions=(candidate.length, candidate.width, candidate.height),
        )
        if verdict["score"] < 60:
            continue
        matches.append({
            "source": "job",
            "score": verdict["score"],
            "reasons": verdict["reasons"],
            "part_id": candidate.part_id,
            "part_name": candidate.name,
            "material": candidate.material,
            "dimensions": [candidate.length, candidate.width, candidate.height],
            "quantity": candidate.quantity,
            "unit_price": candidate.unit_price,
            "id": offer.id if offer else None,
            "offer_id": offer.offer_id if offer else None,
            "title": offer.title if offer else None,
            "date": offer.created_at.isoformat() if offer and offer.created_at else None,
            "url": _offer_url(offer),
        })

    for candidate in orders:
        details = candidate.details if isinstance(candidate.details, dict) else {}
        candidate_name = best_name_from_details(details)
        dimensions = details.get("dimensions") or {}
        candidate_dimensions = (
            dimensions.get("length", dimensions.get("l")),
            dimensions.get("width", dimensions.get("w")),
            dimensions.get("height", dimensions.get("h")),
        ) if isinstance(dimensions, dict) else ()
        verdict = match_part(
            query_part_id=part_id,
            query_name=part_name,
            candidate_part_id=candidate.part_id,
            candidate_name=candidate_name,
            query_material=material,
            candidate_material=details.get("material"),
            query_dimensions=query_dimensions,
            candidate_dimensions=candidate_dimensions,
        )
        if verdict["score"] < 60:
            continue
        matches.append({
            "source": "po",
            "score": verdict["score"],
            "reasons": verdict["reasons"],
            "part_id": candidate.part_id,
            "part_name": candidate_name,
            "material": details.get("material"),
            "dimensions": list(candidate_dimensions),
            "id": candidate.id,
            "order_id": candidate.order_id,
            "title": f"PO {candidate.order_id}",
            "status": candidate.status,
            "date": candidate.order_date,
            "price": candidate.price,
            "url": details.get("order_url") or details.get("url"),
        })

    matches.sort(key=lambda item: item["score"], reverse=True)
    matches = matches[: max(1, min(limit, 50))]
    return {
        "found": bool(matches),
        "query": {"part_id": part_id, "part_name": part_name, "tokens": tokens},
        "jobs_count": sum(item["source"] == "job" for item in matches),
        "po_count": sum(item["source"] == "po" for item in matches),
        "matches": matches,
    }
