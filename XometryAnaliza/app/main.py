import html
import re
from typing import Any
from pathlib import PureWindowsPath
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .agents import process_jobs
from .geo_files import read_remote_geo_file
from .store import find_job_by_offer_id, list_jobs, read_events


app = FastAPI(title="Xometry Analiza Agents", version="2.0.0")


class AgentJobsPayload(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "unknown"


def _run_jobs(payload: AgentJobsPayload) -> None:
    process_jobs(payload.jobs)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "xometry-analiza-agents"}


@app.post("/api/agents/jobs")
def submit_jobs(payload: AgentJobsPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    background_tasks.add_task(_run_jobs, payload)
    return {"ok": True, "queued": len(payload.jobs), "source": payload.source}


@app.get("/api/agents/logs")
def logs(limit: int = 50) -> dict[str, Any]:
    return {"items": read_events(limit)}


@app.get("/api/agents/jobs")
def jobs(limit: int = 100) -> dict[str, Any]:
    return {"items": list_jobs(limit)}


@app.get("/api/agents/geo/{offer_id}")
def geo_status(offer_id: str) -> dict[str, Any]:
    state = find_job_by_offer_id(offer_id)
    if not state:
        return {"ok": False, "offer_id": offer_id, "status": "not_found", "geo_items": []}
    sheet = state.get("sheet_metal_laser") or {}
    return {
        "ok": True,
        "offer_id": offer_id,
        "job_id": state.get("job_id"),
        "status": sheet.get("status") or "no_sheet_agent",
        "geo_items": sheet.get("geo_items") or [],
        "state": state,
    }


@app.get("/api/agents/geo/{offer_id}/view")
def geo_all_view(offer_id: str) -> HTMLResponse:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer not found in XometryAnaliza.")

    job = state.get("job") or {}
    job_id = str(state.get("job_id") or job.get("id") or offer_id)
    xometry_url = str(job.get("link") or job.get("url") or "")
    sheet = state.get("sheet_metal_laser") or {}
    geo_items = sheet.get("geo_items") or []
    ready_indexes = [
        index for index, item in enumerate(geo_items)
        if item.get("geo_exists") is True and item.get("target_path")
    ]

    if not ready_indexes:
        raise HTTPException(status_code=404, detail="No ready GEO files found for this offer.")

    cards = []
    for display_index, item_index in enumerate(ready_indexes, start=1):
        try:
            _, target_path, content, filename = _read_geo_file(offer_id, item_index)
        except Exception as exc:
            cards.append(
                f"""
                <section class="viewer error">
                  <h2>GEO {display_index}</h2>
                  <p>{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</p>
                </section>
                """
            )
            continue

        text = _decode_geo_text(content)
        preview_svg, preview_stats = _geo_preview_svg(text)
        dimensions = preview_stats.get("dimensions") or "necunoscut"
        thickness = preview_stats.get("thickness") or "necunoscuta"
        cut_count = preview_stats.get("cut_segments", 0)
        bend_count = preview_stats.get("bend_segments", 0)
        hole_count = preview_stats.get("holes", 0)
        point_count = preview_stats.get("points", 0)
        download_url = f"/api/agents/geo/{quote(offer_id, safe='')}/files/{item_index}"
        cards.append(
            f"""
            <section class="viewer">
              <div class="viewer-head">
                <div class="viewer-info">
                  <h2>{display_index}. {html.escape(filename)}</h2>
                  <div class="path">{html.escape(str(target_path))}</div>
                  <div class="stats-grid">
                    <div class="stat-box"><strong>{html.escape(dimensions)}</strong><span>Dimensiuni</span></div>
                    <div class="stat-box"><strong>{html.escape(thickness)}</strong><span>Grosime</span></div>
                    <div class="stat-box"><strong>{cut_count}</strong><span>Contururi</span></div>
                    <div class="stat-box"><strong>{hole_count}</strong><span>Gauri</span></div>
                    <div class="stat-box"><strong>{bend_count}</strong><span>Indoituri</span></div>
                    <div class="stat-box"><strong>{point_count}</strong><span>Puncte</span></div>
                  </div>
                  <div class="viewer-meta">{html.escape(dimensions)} · {cut_count} contururi · {hole_count} gauri · {bend_count} indoituri · {point_count} puncte</div>
                </div>
                <a class="button" href="{download_url}">Descarca .geo</a>
              </div>
              <div class="cad-frame">{preview_svg}</div>
            </section>
            """
        )

    xometry_button = (
        f'<a class="button secondary" href="{html.escape(xometry_url, quote=True)}" target="_blank" rel="noreferrer">Deschide oferta Xometry</a>'
        if xometry_url
        else ""
    )

    return HTMLResponse(
        f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Desfasurate GEO - {html.escape(job_id)}</title>
  <style>
    body {{
      margin: 0;
      background: #eef2f5;
      color: #111827;
      font-family: Arial, sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 3;
      background: #ffffff;
      border-bottom: 1px solid #d9e2ec;
      padding: 14px 22px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 22px;
    }}
    h2 {{
      margin: 0 0 5px;
      font-size: 16px;
    }}
    .sub {{
      color: #52606d;
      font-size: 13px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 4px;
      background: #1677ff;
      color: #ffffff;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }}
    .button.secondary {{
      background: #ffffff;
      border: 1px solid #b8c2cc;
      color: #1f2937;
    }}
    main {{
      display: grid;
      gap: 18px;
      padding: 18px 22px 32px;
    }}
    .viewer {{
      overflow: hidden;
      border: 1px solid #cfd8e3;
      border-radius: 8px;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .viewer.error {{
      padding: 16px;
      border-color: #ffa39e;
      background: #fff1f0;
    }}
    .viewer-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 16px;
      border-bottom: 1px solid #d9e2ec;
      background: #f8fafc;
    }}
    .viewer-info {{
      flex: 1;
      min-width: 0;
    }}
    .viewer-meta {{
      display: none;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(6, minmax(96px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .stat-box {{
      min-height: 52px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #ffffff;
      padding: 8px 10px;
      box-sizing: border-box;
    }}
    .stat-box strong {{
      display: block;
      color: #0f172a;
      font-size: 19px;
      line-height: 22px;
      white-space: nowrap;
    }}
    .stat-box span {{
      display: block;
      margin-top: 4px;
      color: #52606d;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .path {{
      color: #52606d;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .cad-frame {{
      height: 520px;
      min-height: 420px;
      background: #0b1120;
    }}
    .cad-empty {{
      display: flex;
      height: 100%;
      align-items: center;
      justify-content: center;
      color: #dbeafe;
      font-size: 15px;
    }}
    .geo-svg {{
      display: block;
      width: 100%;
      height: 100%;
      background:
        radial-gradient(circle at 25% 18%, rgba(59, 130, 246, 0.18) 0, rgba(12, 18, 34, 0) 35%),
        linear-gradient(145deg, #101827 0%, #070b14 100%);
    }}
    .geo-grid {{ stroke: rgba(148, 163, 184, 0.17); stroke-width: 0.25; }}
    .geo-axis {{ stroke: rgba(148, 163, 184, 0.35); stroke-width: 0.45; }}
    .geo-build-plate {{ fill: rgba(15, 23, 42, 0.18); stroke: rgba(148, 163, 184, 0.22); stroke-width: 0.5; vector-effect: non-scaling-stroke; }}
    .geo-cut-shadow {{ fill: none; stroke: rgba(2, 6, 23, 0.80); stroke-width: 5.5; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }}
    .geo-cut,
    .geo-arc {{ fill: none; stroke: #f8fafc; stroke-width: 2.1; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }}
    .geo-hole {{ fill: rgba(15, 23, 42, 0.68); stroke: #93c5fd; stroke-width: 1.5; vector-effect: non-scaling-stroke; }}
    .geo-bend {{ fill: none; stroke: #fbbf24; stroke-width: 1.7; stroke-dasharray: 6 5; stroke-linecap: round; vector-effect: non-scaling-stroke; }}
    .geo-node {{ fill: #38bdf8; stroke: #0f172a; stroke-width: 0.8; vector-effect: non-scaling-stroke; }}
    .geo-dim {{ stroke: #94a3b8; stroke-width: 0.8; vector-effect: non-scaling-stroke; }}
    .geo-dim-text {{ fill: #cbd5e1; font-family: Arial, sans-serif; font-size: 4px; font-weight: 700; text-anchor: middle; dominant-baseline: middle; }}
    .geo-watermark {{ fill: rgba(226, 232, 240, 0.42); font-family: Arial, sans-serif; font-size: 5px; font-weight: 700; letter-spacing: 0; }}
    @media (max-width: 900px) {{
      .viewer-head {{
        flex-direction: column;
      }}
      .stats-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Desfasurate GEO - {html.escape(job_id)}</h1>
    <div class="sub">{len(ready_indexes)} fisiere GEO generate pentru aceasta oferta</div>
    <div class="actions">{xometry_button}</div>
  </header>
  <main>
    {"".join(cards)}
  </main>
</body>
</html>"""
    )


@app.get("/api/agents/geo/{offer_id}/files/{item_index}")
def geo_file(offer_id: str, item_index: int) -> Response:
    _, target_path, content, filename = _read_geo_file(offer_id, item_index)
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@app.get("/api/agents/geo/{offer_id}/files/{item_index}/view")
def geo_file_view(offer_id: str, item_index: int) -> HTMLResponse:
    state, target_path, content, filename = _read_geo_file(offer_id, item_index)
    job = state.get("job") or {}
    xometry_url = str(job.get("link") or job.get("url") or "")
    download_url = f"/api/agents/geo/{quote(offer_id, safe='')}/files/{item_index}"
    text = _decode_geo_text(content)
    preview_svg, preview_stats = _geo_preview_svg(text)
    safe_title = html.escape(filename)
    safe_path = html.escape(str(target_path))
    safe_content = html.escape(text)
    safe_preview_svg = preview_svg
    safe_xometry_url = html.escape(xometry_url, quote=True)
    dimensions = preview_stats.get("dimensions") or "necunoscut"
    thickness = preview_stats.get("thickness") or "necunoscuta"
    cut_count = preview_stats.get("cut_segments", 0)
    bend_count = preview_stats.get("bend_segments", 0)
    hole_count = preview_stats.get("holes", 0)
    point_count = preview_stats.get("points", 0)
    xometry_button = (
        f'<a class="button secondary" href="{safe_xometry_url}" target="_blank" rel="noreferrer">Deschide oferta Xometry</a>'
        if xometry_url
        else ""
    )

    return HTMLResponse(
        f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0;
      background: #eef2f5;
      color: #111827;
      font-family: Arial, sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      background: #ffffff;
      border-bottom: 1px solid #d9e2ec;
      padding: 14px 22px;
      z-index: 1;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.25;
    }}
    .path {{
      color: #4b5563;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 4px;
      background: #1677ff;
      color: #ffffff;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
    }}
    .button.secondary {{
      background: #ffffff;
      border: 1px solid #b8c2cc;
      color: #1f2937;
    }}
    main {{
      padding: 18px 22px;
    }}
    .viewer {{
      border: 1px solid #cfd8e3;
      border-radius: 8px;
      overflow: hidden;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .viewer-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 16px;
      border-bottom: 1px solid #d9e2ec;
      background: #f8fafc;
    }}
    .viewer-title {{
      font-size: 15px;
      font-weight: 700;
    }}
    .viewer-meta {{
      margin-top: 4px;
      color: #52606d;
      font-size: 12px;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: flex-end;
      gap: 12px;
      color: #52606d;
      font-size: 12px;
    }}
    .legend span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }}
    .swatch {{
      width: 18px;
      height: 3px;
      border-radius: 999px;
      display: inline-block;
    }}
    .swatch.cut {{
      background: #22d3ee;
    }}
    .swatch.bend {{
      background: #f59e0b;
    }}
    .swatch.hole {{
      background: #93c5fd;
    }}
    .tool-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 12px;
      border-bottom: 1px solid #d9e2ec;
      background: #f8fafc;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(88px, 1fr));
      gap: 8px;
      color: #475569;
      font-size: 12px;
    }}
    .metric {{
      border: 1px solid #d7dee8;
      border-radius: 4px;
      background: #ffffff;
      padding: 5px 8px;
    }}
    .metric strong {{
      display: block;
      color: #0f172a;
      font-size: 13px;
    }}
    .tool-buttons {{
      display: flex;
      gap: 6px;
    }}
    .icon-button {{
      min-width: 32px;
      height: 30px;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      background: #ffffff;
      color: #0f172a;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }}
    .cad-frame {{
      height: calc(100vh - 245px);
      min-height: 520px;
      background: #0b1120;
    }}
    .cad-empty {{
      display: flex;
      height: 100%;
      align-items: center;
      justify-content: center;
      color: #dbeafe;
      font-size: 15px;
    }}
    .geo-svg {{
      display: block;
      width: 100%;
      height: 100%;
      cursor: grab;
      background:
        radial-gradient(circle at 25% 18%, rgba(59, 130, 246, 0.18) 0, rgba(12, 18, 34, 0) 35%),
        linear-gradient(145deg, #101827 0%, #070b14 100%);
    }}
    .geo-svg:active {{
      cursor: grabbing;
    }}
    .geo-grid {{
      stroke: rgba(148, 163, 184, 0.17);
      stroke-width: 0.25;
    }}
    .geo-axis {{
      stroke: rgba(148, 163, 184, 0.35);
      stroke-width: 0.45;
    }}
    .geo-build-plate {{
      fill: rgba(15, 23, 42, 0.18);
      stroke: rgba(148, 163, 184, 0.22);
      stroke-width: 0.5;
      vector-effect: non-scaling-stroke;
    }}
    .geo-cut-shadow {{
      fill: none;
      stroke: rgba(2, 6, 23, 0.80);
      stroke-width: 5.5;
      stroke-linecap: round;
      stroke-linejoin: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-cut {{
      fill: none;
      stroke: #f8fafc;
      stroke-width: 2.1;
      stroke-linecap: round;
      stroke-linejoin: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-arc {{
      fill: none;
      stroke: #f8fafc;
      stroke-width: 2.1;
      stroke-linecap: round;
      stroke-linejoin: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-hole {{
      fill: rgba(15, 23, 42, 0.68);
      stroke: #93c5fd;
      stroke-width: 1.5;
      vector-effect: non-scaling-stroke;
    }}
    .geo-bend {{
      fill: none;
      stroke: #fbbf24;
      stroke-width: 1.7;
      stroke-dasharray: 6 5;
      stroke-linecap: round;
      vector-effect: non-scaling-stroke;
    }}
    .geo-node {{
      fill: #38bdf8;
      stroke: #0f172a;
      stroke-width: 0.8;
      vector-effect: non-scaling-stroke;
    }}
    .geo-dim {{
      stroke: #94a3b8;
      stroke-width: 0.8;
      vector-effect: non-scaling-stroke;
    }}
    .geo-dim-text {{
      fill: #cbd5e1;
      font-family: Arial, sans-serif;
      font-size: 4px;
      font-weight: 700;
      text-anchor: middle;
      dominant-baseline: middle;
    }}
    .geo-watermark {{
      fill: rgba(226, 232, 240, 0.42);
      font-family: Arial, sans-serif;
      font-size: 5px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    details {{
      margin-top: 14px;
    }}
    summary {{
      cursor: pointer;
      color: #334155;
      font-weight: 700;
      font-size: 13px;
    }}
    pre {{
      margin: 12px 0 0;
      padding: 16px;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      background: #ffffff;
      color: #111827;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_title}</h1>
    <div class="path">{safe_path}</div>
    <div class="actions">
      <a class="button" href="{download_url}">Descarca .geo</a>
      {xometry_button}
    </div>
  </header>
  <main>
    <section class="viewer">
      <div class="viewer-head">
        <div>
          <div class="viewer-title">Preview desfasurata GEO</div>
          <div class="viewer-meta">{html.escape(dimensions)} · {cut_count} contururi · {bend_count} indoituri · {point_count} puncte</div>
        </div>
        <div class="legend">
          <span><i class="swatch cut"></i> Contur</span>
          <span><i class="swatch hole"></i> Gauri</span>
          <span><i class="swatch bend"></i> Indoire</span>
        </div>
      </div>
      <div class="tool-row">
        <div class="metric-grid">
          <div class="metric"><strong>{html.escape(dimensions)}</strong>Dimensiuni</div>
          <div class="metric"><strong>{html.escape(thickness)}</strong>Grosime</div>
          <div class="metric"><strong>{cut_count}</strong>Contururi</div>
          <div class="metric"><strong>{hole_count}</strong>Gauri</div>
          <div class="metric"><strong>{bend_count}</strong>Indoituri</div>
        </div>
        <div class="tool-buttons">
          <button class="icon-button" type="button" data-geo-zoom="in" title="Zoom in">+</button>
          <button class="icon-button" type="button" data-geo-zoom="out" title="Zoom out">-</button>
          <button class="icon-button" type="button" data-geo-zoom="fit" title="Fit">Fit</button>
        </div>
      </div>
      <div class="cad-frame">{safe_preview_svg}</div>
    </section>
    <details>
      <summary>Arata continut raw .geo</summary>
      <pre>{safe_content}</pre>
    </details>
  </main>
  <script>
    (() => {{
      const svg = document.getElementById('geo-render');
      if (!svg) return;
      const original = (svg.dataset.viewbox || svg.getAttribute('viewBox')).split(/\\s+/).map(Number);
      let box = [...original];
      let dragging = false;
      let start = null;
      const setBox = () => svg.setAttribute('viewBox', box.map(v => Number(v.toFixed(3))).join(' '));
      const zoomAt = (factor, cx = box[0] + box[2] / 2, cy = box[1] + box[3] / 2) => {{
        const nextW = box[2] * factor;
        const nextH = box[3] * factor;
        box[0] = cx - (cx - box[0]) * factor;
        box[1] = cy - (cy - box[1]) * factor;
        box[2] = nextW;
        box[3] = nextH;
        setBox();
      }};
      const svgPoint = event => {{
        const pt = svg.createSVGPoint();
        pt.x = event.clientX;
        pt.y = event.clientY;
        return pt.matrixTransform(svg.getScreenCTM().inverse());
      }};
      svg.addEventListener('wheel', event => {{
        event.preventDefault();
        const pt = svgPoint(event);
        zoomAt(event.deltaY < 0 ? 0.86 : 1.16, pt.x, pt.y);
      }}, {{ passive: false }});
      svg.addEventListener('pointerdown', event => {{
        dragging = true;
        start = {{ clientX: event.clientX, clientY: event.clientY, box: [...box] }};
        svg.setPointerCapture(event.pointerId);
      }});
      svg.addEventListener('pointermove', event => {{
        if (!dragging || !start) return;
        const scaleX = box[2] / Math.max(svg.clientWidth, 1);
        const scaleY = box[3] / Math.max(svg.clientHeight, 1);
        box[0] = start.box[0] - (event.clientX - start.clientX) * scaleX;
        box[1] = start.box[1] - (event.clientY - start.clientY) * scaleY;
        setBox();
      }});
      svg.addEventListener('pointerup', event => {{
        dragging = false;
        start = null;
        try {{ svg.releasePointerCapture(event.pointerId); }} catch (_) {{}}
      }});
      document.querySelectorAll('[data-geo-zoom]').forEach(button => {{
        button.addEventListener('click', () => {{
          const mode = button.dataset.geoZoom;
          if (mode === 'fit') {{
            box = [...original];
            setBox();
          }} else {{
            zoomAt(mode === 'in' ? 0.82 : 1.22);
          }}
        }});
      }});
    }})();
  </script>
</body>
</html>"""
    )


def _read_geo_file(offer_id: str, item_index: int) -> tuple[dict[str, Any], str, bytes, str]:
    state = find_job_by_offer_id(offer_id)
    if not state:
        raise HTTPException(status_code=404, detail="Offer not found in XometryAnaliza.")

    sheet = state.get("sheet_metal_laser") or {}
    geo_items = sheet.get("geo_items") or []
    if item_index < 0 or item_index >= len(geo_items):
        raise HTTPException(status_code=404, detail="GEO item not found.")

    item = geo_items[item_index]
    target_path = item.get("target_path")
    if not target_path:
        raise HTTPException(status_code=404, detail="GEO item has no target path.")

    try:
        content = read_remote_geo_file(str(target_path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Remote GEO file was not found.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read remote GEO file: {type(exc).__name__}: {exc}") from exc

    filename = PureWindowsPath(str(target_path)).name or f"{offer_id}-{item_index}.geo"
    return state, str(target_path), content, filename


def _decode_geo_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _ints_from_line(value: str) -> list[int]:
    return [int(match) for match in re.findall(r"-?\d+", value)]


def _point_from_line(value: str) -> tuple[float, float] | None:
    parts = value.split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _format_mm(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") + " mm"


def _geo_thickness_from_lines(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line.upper() != "NONE":
            continue
        for next_line in lines[index + 1:index + 7]:
            parts = next_line.split()
            if not parts:
                continue
            try:
                value = float(parts[0])
            except ValueError:
                continue
            if 0 < value <= 100:
                return _format_mm(value)
    return "necunoscuta"


def _geo_preview_svg(text: str) -> tuple[str, dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines()]
    points: dict[int, tuple[float, float]] = {}
    cut_segments: list[tuple[str, tuple[int, ...]]] = []
    cut_circles: list[tuple[int, float]] = []
    bend_segments: list[tuple[str, tuple[int, ...]]] = []
    block = ""

    for index, line in enumerate(lines):
        if line.startswith("#~"):
            block = line

        if line == "P" and index + 2 < len(lines):
            point_ids = _ints_from_line(lines[index + 1])
            coords = _point_from_line(lines[index + 2])
            if len(point_ids) == 1 and coords:
                points[point_ids[0]] = coords
            continue

        if line not in {"LIN", "ARC", "CIR"} or index + 2 >= len(lines):
            continue

        refs = tuple(_ints_from_line(lines[index + 2]))
        if line == "LIN" and len(refs) >= 2:
            target = bend_segments if block == "#~371" else cut_segments if block == "#~331" else None
            if target is not None:
                target.append(("line", refs[:2]))
        elif line == "ARC" and len(refs) >= 3 and block == "#~331":
            cut_segments.append(("arc", refs[:3]))
        elif line == "CIR" and refs and index + 3 < len(lines) and block == "#~331":
            try:
                radius = float(lines[index + 3].split()[0])
            except (ValueError, IndexError):
                radius = 0.0
            if radius > 0:
                cut_circles.append((refs[0], radius))

    used_ids = set()
    for _, refs in [*cut_segments, *bend_segments]:
        used_ids.update(refs)
    for center_id, _ in cut_circles:
        used_ids.add(center_id)
    used_points = [points[point_id] for point_id in used_ids if point_id in points]

    stats: dict[str, Any] = {
        "points": len(points),
        "cut_segments": len(cut_segments),
        "bend_segments": len(bend_segments),
        "holes": len(cut_circles),
        "dimensions": "necunoscut",
        "thickness": _geo_thickness_from_lines(lines),
    }

    if not used_points:
        return '<div class="cad-empty">Nu am putut reconstrui geometria din acest fisier GEO.</div>', stats

    min_x = min(point[0] for point in used_points)
    max_x = max(point[0] for point in used_points)
    min_y = min(point[1] for point in used_points)
    max_y = max(point[1] for point in used_points)
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad = max(max(width, height) * 0.10, 18.0)
    view_w = width + pad * 2
    view_h = height + pad * 2
    stats["dimensions"] = f"{width:.1f} x {height:.1f} mm"

    def point(point_id: int) -> tuple[float, float] | None:
        raw = points.get(point_id)
        if raw is None:
            return None
        x, y = raw
        return x - min_x + pad, max_y - y + pad

    def fmt(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".")

    grid = []
    grid_step = _nice_grid_step(max(width, height))
    grid_start_x = int(min_x // grid_step) * grid_step
    grid_end_x = int(max_x // grid_step + 2) * grid_step
    grid_start_y = int(min_y // grid_step) * grid_step
    grid_end_y = int(max_y // grid_step + 2) * grid_step

    gx = grid_start_x
    while gx <= grid_end_x:
        x = gx - min_x + pad
        cls = "geo-axis" if abs(gx) < 0.0001 else "geo-grid"
        grid.append(f'<line class="{cls}" x1="{fmt(x)}" y1="0" x2="{fmt(x)}" y2="{fmt(view_h)}" />')
        gx += grid_step

    gy = grid_start_y
    while gy <= grid_end_y:
        y = max_y - gy + pad
        cls = "geo-axis" if abs(gy) < 0.0001 else "geo-grid"
        grid.append(f'<line class="{cls}" x1="0" y1="{fmt(y)}" x2="{fmt(view_w)}" y2="{fmt(y)}" />')
        gy += grid_step

    left = pad
    right = pad + width
    top = pad
    bottom = pad + height
    dim_y = bottom + pad * 0.45
    dim_x = left - pad * 0.45
    dim_arrow = (
        '<defs>'
        '<marker id="geo-arrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">'
        '<path d="M0,0 L6,3 L0,6 Z" fill="#94a3b8" />'
        '</marker>'
        '</defs>'
    )

    cut_svg = []
    cut_shadow_svg = []
    for kind, refs in cut_segments:
        if kind == "line":
            a = point(refs[0])
            b = point(refs[1])
            if not a or not b:
                continue
            cut_shadow_svg.append(
                f'<line class="geo-cut-shadow" x1="{fmt(a[0])}" y1="{fmt(a[1])}" x2="{fmt(b[0])}" y2="{fmt(b[1])}" />'
            )
            cut_svg.append(
                f'<line class="geo-cut" x1="{fmt(a[0])}" y1="{fmt(a[1])}" x2="{fmt(b[0])}" y2="{fmt(b[1])}" />'
            )
        elif kind == "arc":
            a = point(refs[0])
            b = point(refs[1])
            c = point(refs[2])
            if not a or not b or not c:
                continue
            cut_shadow_svg.append(
                f'<path class="geo-cut-shadow" d="M {fmt(a[0])} {fmt(a[1])} Q {fmt(b[0])} {fmt(b[1])} {fmt(c[0])} {fmt(c[1])}" />'
            )
            cut_svg.append(
                f'<path class="geo-arc" d="M {fmt(a[0])} {fmt(a[1])} Q {fmt(b[0])} {fmt(b[1])} {fmt(c[0])} {fmt(c[1])}" />'
            )

    hole_svg = []
    node_svg = []
    for center_id, radius in cut_circles:
        center = point(center_id)
        if not center:
            continue
        hole_svg.append(
            f'<circle class="geo-hole" cx="{fmt(center[0])}" cy="{fmt(center[1])}" r="{fmt(radius)}" />'
        )

    for point_id in sorted(used_ids):
        rendered = point(point_id)
        if rendered:
            node_svg.append(f'<circle class="geo-node" cx="{fmt(rendered[0])}" cy="{fmt(rendered[1])}" r="0.9" />')

    bend_svg = []
    for _, refs in bend_segments:
        a = point(refs[0])
        b = point(refs[1])
        if not a or not b:
            continue
        bend_svg.append(
            f'<line class="geo-bend" x1="{fmt(a[0])}" y1="{fmt(a[1])}" x2="{fmt(b[0])}" y2="{fmt(b[1])}" />'
        )

    dimensions_svg = (
        f'<g>'
        f'<line class="geo-dim" x1="{fmt(left)}" y1="{fmt(dim_y)}" x2="{fmt(right)}" y2="{fmt(dim_y)}" '
        f'marker-start="url(#geo-arrow)" marker-end="url(#geo-arrow)" />'
        f'<line class="geo-dim" x1="{fmt(left)}" y1="{fmt(bottom)}" x2="{fmt(left)}" y2="{fmt(dim_y)}" />'
        f'<line class="geo-dim" x1="{fmt(right)}" y1="{fmt(bottom)}" x2="{fmt(right)}" y2="{fmt(dim_y)}" />'
        f'<text class="geo-dim-text" x="{fmt((left + right) / 2)}" y="{fmt(dim_y + pad * 0.22)}">{width:.1f} mm</text>'
        f'<line class="geo-dim" x1="{fmt(dim_x)}" y1="{fmt(top)}" x2="{fmt(dim_x)}" y2="{fmt(bottom)}" '
        f'marker-start="url(#geo-arrow)" marker-end="url(#geo-arrow)" />'
        f'<line class="geo-dim" x1="{fmt(dim_x)}" y1="{fmt(top)}" x2="{fmt(left)}" y2="{fmt(top)}" />'
        f'<line class="geo-dim" x1="{fmt(dim_x)}" y1="{fmt(bottom)}" x2="{fmt(left)}" y2="{fmt(bottom)}" />'
        f'<text class="geo-dim-text" transform="translate({fmt(dim_x - pad * 0.24)} {fmt((top + bottom) / 2)}) rotate(-90)">{height:.1f} mm</text>'
        f'</g>'
    )

    return (
        f'<svg id="geo-render" class="geo-svg" viewBox="0 0 {fmt(view_w)} {fmt(view_h)}" '
        f'data-viewbox="0 0 {fmt(view_w)} {fmt(view_h)}" role="img" aria-label="GEO preview">'
        f'{dim_arrow}'
        f'<g>{"".join(grid)}</g>'
        f'<rect class="geo-build-plate" x="{fmt(left)}" y="{fmt(top)}" width="{fmt(width)}" height="{fmt(height)}" rx="1.5" />'
        f'{dimensions_svg}'
        f'<text class="geo-watermark" x="{fmt(left)}" y="{fmt(top - pad * 0.35)}">BUILD123 STYLE RENDER</text>'
        f'<g transform="translate(1.4 1.6)">{"".join(cut_shadow_svg)}</g>'
        f'<g>{"".join(cut_svg)}</g>'
        f'<g>{"".join(hole_svg)}</g>'
        f'<g>{"".join(bend_svg)}</g>'
        f'<g>{"".join(node_svg)}</g>'
        "</svg>",
        stats,
    )


def _nice_grid_step(span: float) -> float:
    if span <= 50:
        return 5.0
    if span <= 150:
        return 10.0
    if span <= 500:
        return 25.0
    return 50.0
