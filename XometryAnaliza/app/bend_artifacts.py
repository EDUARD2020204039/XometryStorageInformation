from __future__ import annotations

import html
import json
import textwrap
import time
from pathlib import Path
from typing import Any

from . import settings


def _artifact_dir(offer_id: str) -> Path:
    settings.ensure_dirs()
    path = settings.DATA_DIR / "artifacts" / str(offer_id or "unknown") / "bend"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_issue(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    classification = str(item.get("classification") or "").lower()
    reason = str(item.get("reason") or item.get("message") or "")
    if status and status not in ("ok", "success", "geo_ready", "done"):
        return True
    if item.get("bendable") is False:
        return True
    if classification and classification not in ("ok", "success", "bendable", "ready"):
        return True
    return bool(reason and any(token in reason.lower() for token in ("eroare", "failed", "nu accepta", "problem", "unsupported")))


def build_bend_artifacts(job_id: str, offer_id: str, result: dict[str, Any], geo_items: list[dict[str, Any]]) -> dict[str, Any]:
    trutops = result.get("trutops") or []
    warnings = result.get("warnings") or []
    issues = [item for item in trutops if isinstance(item, dict) and _is_issue(item)]
    has_issues = bool(issues or warnings)
    folder = _artifact_dir(offer_id)

    summary = {
        "ok": True,
        "job_id": job_id,
        "offer_id": offer_id,
        "has_bend_issues": has_issues,
        "status": "probleme la indoire" if has_issues else "fara probleme la indoire",
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "created_ts": time.time(),
        "artifacts": [],
    }

    payload = {
        **summary,
        "issues": issues,
        "warnings": warnings,
        "geo_items": geo_items,
    }
    (folder / "bend_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cards = []
    for index, item in enumerate(issues, start=1):
        controls = item.get("ui_controls") or []
        control_lines = "".join(
            f"<li><strong>{html.escape(str(ctrl.get('control_type') or ''))}</strong> {html.escape(str(ctrl.get('text') or ''))}</li>"
            for ctrl in controls[:80] if isinstance(ctrl, dict)
        )
        steps = "".join(f"<li>{html.escape(str(step))}</li>" for step in (item.get("steps") or [])[:60])
        cards.append(f"""
        <section class="card issue">
          <h2>{index}. {html.escape(str(item.get('partName') or item.get('part_name') or 'Reper'))}</h2>
          <div class="meta">status: {html.escape(str(item.get('status')))} &middot; clasificare: {html.escape(str(item.get('classification')))}</div>
          <p>{html.escape(str(item.get('reason') or item.get('message') or 'Problema detectata la indoire.'))}</p>
          <h3>Pasi</h3><ol>{steps or '<li>Nu sunt pasi raportati.</li>'}</ol>
          <h3>Controale TecZone vazute</h3><ul>{control_lines or '<li>Nu sunt controale capturate.</li>'}</ul>
        </section>
        """)

    if not cards:
        cards.append('<section class="card ok"><h2>Fara probleme la indoire</h2><p>Agentul nu a raportat erori de indoire pentru fisierele procesate.</p></section>')

    report_html = f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bend report - {html.escape(job_id)}</title>
  <style>
    body{{margin:0;background:#f4f7fb;color:#172033;font-family:Arial,sans-serif}}
    header{{padding:18px 22px;background:#111827;color:white}}
    h1{{margin:0;font-size:22px}} .sub{{margin-top:5px;color:#cbd5e1}}
    main{{display:grid;gap:14px;padding:18px 22px}}
    .card{{border:1px solid #d8e0ea;border-radius:8px;background:white;padding:14px 16px;box-shadow:0 8px 24px rgba(15,23,42,.08)}}
    .issue{{border-left:5px solid #f5222d}} .ok{{border-left:5px solid #52c41a}}
    h2{{margin:0 0 6px;font-size:17px}} h3{{font-size:13px;margin:12px 0 6px;color:#334155}}
    .meta{{font-size:12px;color:#64748b}} li{{margin:3px 0}} p{{line-height:1.45}}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(summary['status'])}</h1>
    <div class="sub">{html.escape(job_id)} &middot; oferta {html.escape(str(offer_id))} &middot; {len(issues)} probleme &middot; {len(warnings)} avertizari</div>
  </header>
  <main>{''.join(cards)}</main>
</body>
</html>"""
    (folder / "bend_report.html").write_text(report_html, encoding="utf-8")
    _write_bend_png(folder / "bend_report.png", summary, issues, warnings)
    summary["artifacts"] = [
        {
            "type": "bend_report",
            "name": "bend_report.html",
            "url": f"/api/agents/bend/{offer_id}/artifacts/bend_report.html",
        },
        {
            "type": "bend_report_json",
            "name": "bend_report.json",
            "url": f"/api/agents/bend/{offer_id}/artifacts/bend_report.json",
        },
        {
            "type": "bend_screenshot",
            "name": "bend_report.png",
            "url": f"/api/agents/bend/{offer_id}/artifacts/bend_report.png",
        },
    ]
    return summary


def _write_bend_png(path: Path, summary: dict[str, Any], issues: list[dict[str, Any]], warnings: list[Any]) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return

    width, height = 1280, 760
    image = Image.new("RGB", (width, height), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("arial.ttf", 34)
        head_font = ImageFont.truetype("arial.ttf", 22)
        text_font = ImageFont.truetype("arial.ttf", 18)
        small_font = ImageFont.truetype("arial.ttf", 15)
    except Exception:
        title_font = head_font = text_font = small_font = ImageFont.load_default()

    accent = "#ef4444" if summary.get("has_bend_issues") else "#22c55e"
    draw.rectangle((0, 0, width, 96), fill="#111827")
    draw.text((28, 24), str(summary.get("status") or "Bend report"), fill="#ffffff", font=title_font)
    draw.text((28, 64), f"{summary.get('job_id')} | oferta {summary.get('offer_id')}", fill="#cbd5e1", font=small_font)

    draw.rounded_rectangle((28, 126, width - 28, height - 28), radius=12, fill="#ffffff", outline="#d8e0ea", width=2)
    draw.rectangle((28, 126, 38, height - 28), fill=accent)
    y = 154
    draw.text((58, y), f"Probleme: {len(issues)}    Avertizari: {len(warnings)}", fill="#172033", font=head_font)
    y += 44

    lines: list[str] = []
    if issues:
        for index, issue in enumerate(issues[:8], start=1):
            name = issue.get("partName") or issue.get("part_name") or "Reper"
            reason = issue.get("reason") or issue.get("message") or "Problema detectata la indoire."
            lines.append(f"{index}. {name}: {reason}")
    else:
        lines.append("Agentul nu a raportat probleme de indoire pentru fisierele procesate.")
    if warnings:
        lines.append("")
        lines.append("Avertizari:")
        lines.extend(str(item) for item in warnings[:6])

    for raw in lines:
        for line in textwrap.wrap(str(raw), width=118) or [""]:
            draw.text((58, y), line, fill="#334155", font=text_font)
            y += 28
            if y > height - 70:
                draw.text((58, y), "...", fill="#334155", font=text_font)
                image.save(path)
                return
    image.save(path)


def read_bend_summary(offer_id: str) -> dict[str, Any] | None:
    path = _artifact_dir(offer_id) / "bend_report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def artifact_path(offer_id: str, filename: str) -> Path:
    safe = Path(filename).name
    path = _artifact_dir(offer_id) / safe
    if not path.exists():
        raise FileNotFoundError(safe)
    return path


def copy_bend_artifacts_to_dosar(offer_id: str, dosar_path: str) -> dict[str, Any]:
    target_root = Path(str(dosar_path).replace("\\", "/"))
    if str(target_root).startswith("X:/"):
        target_root = Path("/mnt/xLucru") / target_root.name
    target = target_root / "INDOIRE"
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in ("bend_report.html", "bend_report.json", "bend_report.png"):
        src = _artifact_dir(offer_id) / name
        if not src.exists():
            continue
        dest = target / name
        dest.write_bytes(src.read_bytes())
        copied.append(str(dest))
    return {"ok": True, "copied": copied, "target": str(target)}
