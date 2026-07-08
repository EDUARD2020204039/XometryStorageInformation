import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


CAD_EXTENSIONS = {".stp", ".step", ".sldprt", ".sldasm", ".x_t", ".igs", ".iges", ".dxf", ".dwg"}
COMMAND_EXTENSIONS = {".geo", ".lst", ".html", ".htm", ".mcam", ".nc"}
BEND_EXTENSIONS = {".bnc"}


def _safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip()
    return value[:180] or "file"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{suffix}"


def _copy_file(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(dest_dir / _safe_name(src.name))
    shutil.copy2(src, dest)
    return dest


def _route_for_extension(ext: str, paths: dict[str, Path]) -> Path:
    ext = ext.lower()
    if ext in CAD_EXTENSIONS:
        return paths["3D"]
    if ext in COMMAND_EXTENSIONS:
        return paths["COMANDA"]
    if ext in BEND_EXTENSIONS:
        return paths["INDOIRE"]
    return paths["DOC"]


def _extract_zip(src: Path, paths: dict[str, Path], copied: list[str]) -> None:
    try:
        with zipfile.ZipFile(src) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_name = Path(member.filename.replace("\\", "/")).name
                if not member_name:
                    continue
                ext = Path(member_name).suffix.lower()
                dest_dir = _route_for_extension(ext, paths)
                dest = _unique_path(dest_dir / _safe_name(member_name))
                with archive.open(member) as source, open(dest, "wb") as target:
                    shutil.copyfileobj(source, target)
                copied.append(str(dest))
    except zipfile.BadZipFile:
        return


def _copy_local_docs(offer_id: str, paths: dict[str, Path], copied: list[str]) -> None:
    docs_dir = Path("static") / "docs" / str(offer_id)
    if not docs_dir.exists():
        return
    for item in docs_dir.rglob("*"):
        if not item.is_file():
            continue
        dest = _copy_file(item, paths["DOC"])
        copied.append(str(dest))
        if item.suffix.lower() == ".zip":
            _extract_zip(item, paths, copied)


def download_document_links(offer_id: str, links: list[dict[str, Any]] | None) -> dict[str, Any]:
    docs_dir = Path("static") / "docs" / str(offer_id)
    docs_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    warnings: list[str] = []

    for index, item in enumerate(links or []):
        url = item.get("url") or item.get("href")
        if not url:
            continue
        filename = item.get("filename") or item.get("label") or f"Doc {offer_id}-{index + 1}.zip"
        if not Path(str(filename)).suffix:
            filename = f"{filename}.zip"
        dest = _unique_path(docs_dir / _safe_name(str(filename)))
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            dest.write_bytes(response.content)
            downloaded.append(str(dest))
        except Exception as exc:
            warnings.append(f"Nu am putut descarca {url}: {type(exc).__name__}: {exc}")

    return {
        "success": not warnings,
        "downloaded": downloaded,
        "warnings": warnings,
    }


def _copy_agent_geo(offer_id: str, paths: dict[str, Path], copied: list[str], warnings: list[str]) -> None:
    agent_url = (os.getenv("XOMETRY_AGENT_URL") or os.getenv("AGENT_URL") or "http://192.168.2.23:4468").rstrip("/")
    try:
        response = requests.get(f"{agent_url}/api/agents/geo/{quote(str(offer_id), safe='')}", timeout=10)
        if response.status_code == 404:
            return
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        warnings.append(f"Nu am putut citi GEO de la agent: {type(exc).__name__}: {exc}")
        return

    geo_items = payload.get("geo_items") or []
    for index, item in enumerate(geo_items):
        if item.get("geo_exists") is not True:
            continue
        try:
            file_response = requests.get(
                f"{agent_url}/api/agents/geo/{quote(str(offer_id), safe='')}/files/{index}",
                timeout=30,
            )
            file_response.raise_for_status()
            filename = item.get("target_path") or f"{offer_id}-{index}.geo"
            filename = Path(str(filename).replace("\\", "/")).name
            dest = _unique_path(paths["COMANDA"] / _safe_name(filename))
            dest.write_bytes(file_response.content)
            copied.append(str(dest))
        except Exception as exc:
            warnings.append(f"Nu am putut copia GEO #{index + 1}: {type(exc).__name__}: {exc}")


def create_xometry_workspace(folder_name: str, offer_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(os.getenv("DOSAR_ROOT_PATH", "/mnt/xLucru"))
    folder = root / _safe_name(folder_name)
    subfolders = ["3D", "COMANDA", "INDOIRE", "DOC", "OFERTA"]
    paths = {name: folder / name for name in subfolders}
    copied: list[str] = []
    warnings: list[str] = []

    folder.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    _copy_local_docs(offer_id, paths, copied)
    _copy_agent_geo(offer_id, paths, copied, warnings)

    status_lines = [
        f"Dosar: {folder_name}",
        f"Oferta Xometry: {offer_id}",
        f"Creat: {datetime.utcnow().isoformat()}Z",
    ]
    metadata = metadata or {}
    if metadata.get("job_id"):
        status_lines.append(f"Job: {metadata['job_id']}")
    if metadata.get("url"):
        status_lines.append(f"URL: {metadata['url']}")
    if copied:
        status_lines.append("")
        status_lines.append("Fisiere copiate:")
        status_lines.extend(f"- {item}" for item in copied)
    if warnings:
        status_lines.append("")
        status_lines.append("Avertizari:")
        status_lines.extend(f"- {item}" for item in warnings)
    (folder / "status.txt").write_text("\n".join(status_lines) + "\n", encoding="utf-8")

    return {
        "success": True,
        "folder": str(folder),
        "subfolders": {name: str(path) for name, path in paths.items()},
        "copied_files": copied,
        "warnings": warnings,
    }
