from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from . import settings
from .store import append_event, safe_id


def _compact(value: Any, limit: int = 4000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...truncated..."


def _evidence_text(result: dict[str, Any], output: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("error", "status", "failure_type", "failure_action"):
        if output.get(key):
            chunks.append(str(output.get(key)))
    for item in result.get("warnings") or []:
        chunks.append(str(item))
    for item in result.get("trutops") or []:
        if isinstance(item, dict):
            chunks.extend(
                str(item.get(key) or "")
                for key in ("status", "classification", "reason", "message", "sourcePath", "targetPath")
            )
    return "\n".join(chunks).lower()


def _classify(text: str, output: dict[str, Any]) -> tuple[str, str, str]:
    status = str(output.get("status") or "").lower()
    if status == "agent_busy" or "agent is already processing" in text or "ocupat" in text:
        return (
            "agent_busy",
            "TecZone/Ofertare proceseaza deja alt job.",
            "Pastreaza jobul in coada si reincerca dupa pauza calculata; nu porni o a doua automatizare manual.",
        )
    if "401" in text or "unauthorized" in text or "forbidden" in text:
        return (
            "ofertare_auth",
            "Ofertare API a respins cererea din cauza autentificarii.",
            "Verifica tokenul X-Ofertare-Token dintre XometryAnaliza si Ofertare-Automata.",
        )
    if "pagina de login" in text or "xometry_email" in text or "basic_email" in text or "sign in" in text:
        return (
            "xometry_login",
            "Automatizarea a ajuns pe login Xometry in loc de oferta.",
            "Refa sesiunea Xometry pe laptopul de ofertare si ruleaza testul de sesiune din QA.",
        )
    if "nu am descarcat automat fisierele" in text or "nu am gasit nicio piesa" in text or "source_missing" in text:
        return (
            "documentation_missing",
            "Documentatia/STEP nu a fost descarcata sau nu a fost gasita.",
            "Deschide oferta in browser, verifica download-ul documentatiei si apoi retrimite jobul.",
        )
    if "x:\\" in text or "winerror 3" in text or "cannot find the path" in text or "file not found" in text:
        return (
            "path_mapping",
            "TecZone/Ofertare nu vede calea proiectului.",
            "Verifica maparea UNC/drive si foloseste calea de retea, nu litera X: in serviciile rulate ca background.",
        )
    if "polygon" in text or "mesh" in text or "faceted" in text or "not bendable" in text:
        return (
            "invalid_geometry",
            "Piesa pare modelata ca mesh/fatete sau nu poate fi desfasurata corect.",
            "Trimite captura si fisierul STEP catre proiectant; jobul necesita verificare manuala in TecZoneBEND.",
        )
    if "bend" in text or "indoir" in text or "trutops" in text or "teczone" in text:
        return (
            "teczone_unfold",
            "TecZone a intampinat o problema la desfasurare/indoire/export.",
            "Verifica screenshot-urile din EROARE si reia doar dupa confirmarea geometriei.",
        )
    return (
        "unknown",
        "Nu am putut clasifica sigur eroarea pe baza datelor primite.",
        "Uita-te in raportul complet si in logul Ofertare-Automata pentru pasul exact unde s-a blocat.",
    )


def _project_error_dir(job: dict[str, Any]) -> Path | None:
    linux_path = str(job.get("project_path_linux") or "").strip()
    if linux_path:
        base = Path(linux_path)
        if base.exists():
            return base / "EROARE" / "AI_DIAG"
    return None


def _fallback_error_dir(job_id: str) -> Path:
    return settings.DATA_DIR / "diagnostics" / safe_id(job_id)


def _write_report(job: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("id") or job.get("job_id") or "unknown")
    folder = _project_error_dir(job) or _fallback_error_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = folder / f"{stamp}_{safe_id(job_id)}_diagnostic"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return {
        **report,
        "report_path": str(json_path),
        "report_markdown_path": str(md_path),
    }


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Diagnostic {report.get('job_id')}",
            "",
            f"- Categorie: {report.get('category')}",
            f"- Rezumat: {report.get('summary')}",
            f"- Actiune recomandata: {report.get('recommended_action')}",
            f"- Hermes: {(report.get('hermes') or {}).get('status')}",
            "",
            "## Evidenta",
            "",
            "```json",
            _compact(report.get("evidence") or {}, 12000),
            "```",
            "",
        ]
    )


def _hermes_endpoint() -> str:
    base = settings.HERMES_AGENT_URL
    if not base:
        return ""
    if base.endswith("/v1/chat/completions"):
        return base
    return f"{base.rstrip('/')}/v1/chat/completions"


def _ask_hermes(report: dict[str, Any]) -> dict[str, Any]:
    endpoint = _hermes_endpoint()
    if not settings.HERMES_DIAGNOSTICS_ENABLED:
        return {"status": "disabled"}
    if not endpoint or not settings.HERMES_API_KEY:
        return {"status": "missing_config"}

    prompt = (
        "Analizeaza eroarea TecZone/Xometry de mai jos. Raspunde concis in romana cu: "
        "cauza probabila, pas de verificare, pas de remediere. Nu inventa date lipsa.\n\n"
        f"{_compact(report, 9000)}"
    )
    headers = {
        "Authorization": f"Bearer {settings.HERMES_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.HERMES_AGENT_MODEL,
        "messages": [
            {"role": "system", "content": "Esti un agent de diagnoza pentru automatizarea TecZoneBEND/Xometry."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=(8, settings.HERMES_DIAGNOSTIC_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        data = response.json()
        text = ""
        choices = data.get("choices") or []
        if choices:
            text = str(((choices[0] or {}).get("message") or {}).get("content") or "")
        return {"status": "sent", "endpoint": endpoint, "response": text[:5000]}
    except Exception as exc:
        return {"status": "failed", "endpoint": endpoint, "error": f"{type(exc).__name__}: {exc}"}


def diagnose_teczone_failure(job: dict[str, Any], result: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("id") or job.get("job_id") or "unknown")
    offer_id = str(job.get("offer_id") or "")
    text = _evidence_text(result, output)
    category, summary, action = _classify(text, output)
    evidence = {
        "job": {
            "id": job_id,
            "offer_id": offer_id,
            "link": job.get("link") or job.get("url"),
            "project_path": job.get("project_path"),
            "project_path_linux": job.get("project_path_linux"),
            "source": job.get("source") or job.get("queue_source"),
        },
        "status": output.get("status"),
        "error": output.get("error"),
        "failure_type": output.get("failure_type"),
        "geo_items": output.get("geo_items") or [],
        "ofertare_logs": (result.get("warnings") or [])[-40:],
        "trutops": (result.get("trutops") or [])[-40:],
    }
    report = {
        "created_ts": time.time(),
        "job_id": job_id,
        "offer_id": offer_id,
        "category": category,
        "summary": summary,
        "recommended_action": action,
        "evidence": evidence,
    }
    report["hermes"] = _ask_hermes(report)
    saved = _write_report(job, report)
    append_event(
        "diagnostic.created",
        f"Diagnostic {category} pentru {job_id}: {summary}",
        job_id=job_id,
        offer_id=offer_id,
        category=category,
        report_path=saved.get("report_path"),
        hermes_status=(saved.get("hermes") or {}).get("status"),
    )
    return saved
