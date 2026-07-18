"""Stable part-name normalization and confidence scoring."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePath
from typing import Any, Iterable


_GENERIC_TOKENS = {
    "2d", "3d", "ad", "cad", "converted", "drawing", "file", "final",
    "model", "part", "pdf", "step", "stp", "sldprt", "revision", "rev",
}


def _ascii(value: Any) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()


def normalize_part_name(value: Any) -> str:
    text = _ascii(value).lower().replace("…", " ")
    text = re.sub(r"\.{3,}", " ", text)
    text = PurePath(text).name
    text = re.sub(r"\.(pdf|step|stp|sldprt|x_t|iges|igs|stl|dwg|dxf)$", "", text)
    text = re.sub(r"(?:[_\- ]+converted)?[_\- ]*20\d{12}$", "", text)
    text = re.sub(r"[_\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def part_tokens(value: Any) -> list[str]:
    output: list[str] = []
    for token in re.findall(r"[a-z0-9]+", normalize_part_name(value)):
        if token in _GENERIC_TOKENS or len(token) < 4:
            continue
        if token.isdigit() and len(token) >= 8:
            continue
        if token not in output:
            output.append(token)
    return output


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def best_name_from_details(details: Any) -> str:
    if isinstance(details, dict):
        for key in ("part_name", "partName", "filename", "file_name", "drawing", "name"):
            value = details.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    values = list(_strings(details))
    return next(
        (value for value in values if re.search(r"\.(pdf|step|stp|dwg|dxf)(?:\?.*)?$", value, re.I)),
        "",
    )


def _dimension_bonus(expected: Iterable[Any], actual: Iterable[Any]) -> int:
    try:
        left = sorted(float(value) for value in expected if value is not None)
        right = sorted(float(value) for value in actual if value is not None)
    except (TypeError, ValueError):
        return 0
    if len(left) != 3 or len(right) != 3:
        return 0
    return 12 if all(abs(a - b) <= max(0.2, a * 0.005) for a, b in zip(left, right)) else 0


def match_part(
    *,
    query_part_id: Any,
    query_name: Any,
    candidate_part_id: Any,
    candidate_name: Any,
    query_material: Any = None,
    candidate_material: Any = None,
    query_dimensions: Iterable[Any] = (),
    candidate_dimensions: Iterable[Any] = (),
) -> dict[str, Any]:
    qid, cid = str(query_part_id or "").strip(), str(candidate_part_id or "").strip()
    qname, cname = normalize_part_name(query_name), normalize_part_name(candidate_name)
    common = sorted(
        set(part_tokens(query_name)) & set(part_tokens(candidate_name)),
        key=lambda item: (-len(item), item),
    )
    score = 0
    reasons: list[str] = []
    if qid and cid and qid.lower() == cid.lower():
        score = 100
        reasons.append("acelasi Part ID")
    elif qname and cname and qname == cname:
        score = 92
        reasons.append("acelasi nume complet")
    elif common and (max(map(len, common)) >= 7 or len(common) >= 2):
        score = 62 + min(18, sum(min(len(token), 9) for token in common) // 2)
        reasons.append("cod comun: " + ", ".join(common[:3]))
    if not score:
        return {"score": 0, "reasons": [], "tokens": common}

    material_a, material_b = _ascii(query_material).lower(), _ascii(candidate_material).lower()
    if material_a and material_b and (material_a in material_b or material_b in material_a):
        score += 5
        reasons.append("material compatibil")
    if _dimension_bonus(query_dimensions, candidate_dimensions):
        score += 12
        reasons.append("dimensiuni identice")
    return {"score": min(score, 100), "reasons": reasons, "tokens": common}
