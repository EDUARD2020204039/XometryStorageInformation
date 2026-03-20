"""
Utilitare pentru gestionarea imaginilor
"""
import os
import requests
import hashlib
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def download_and_save_image(image_url: str, offer_id: str, part_id: str) -> Optional[str]:
    """
    Descarcă o imagine de la URL-ul dat și o salvează local
    
    Args:
        image_url: URL-ul imaginii de descărcat
        offer_id: ID-ul ofertei
        part_id: ID-ul reperului
        
    Returns:
        Calea locală către imaginea salvată sau None dacă descărcarea a eșuat
    """
    try:
        # Creează directorul pentru ofertă dacă nu există
        offer_dir = Path(f"static/images/parts/{offer_id}")
        offer_dir.mkdir(parents=True, exist_ok=True)
        
        # Generează numele fișierului bazat pe part_id și hash-ul URL-ului
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
        filename = f"{part_id}_{url_hash}.jpg"
        file_path = offer_dir / filename
        
        # Verifică dacă imaginea există deja
        if file_path.exists():
            logger.info(f"Imaginea există deja: {file_path}")
            return str(file_path.relative_to("static"))
        
        # Descarcă imaginea
        logger.info(f"Descărcare imagine de la: {image_url}")
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        
        # Verifică tipul de conținut
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            logger.warning(f"URL-ul nu pare să fie o imagine: {content_type}")
            return None
        
        # Salvează imaginea
        with open(file_path, 'wb') as f:
            f.write(response.content)
        
        logger.info(f"Imagine salvată cu succes: {file_path}")
        return str(file_path.relative_to("static"))
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Eroare la descărcarea imaginii {image_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Eroare neașteptată la salvarea imaginii {image_url}: {e}")
        return None

def save_base64_image(base64_data: str, offer_id: str, part_id: str) -> Optional[str]:
    """
    Salvează o imagine primită ca base64 local
    """
    try:
        import base64
        import re

        # Creează directorul pentru ofertă dacă nu există
        offer_dir = Path(f"static/images/parts/{offer_id}")
        offer_dir.mkdir(parents=True, exist_ok=True)

        # Curăță header-ul dacă există (data:image/jpeg;base64,...) și detectează extensia
        ext = "jpg"
        if base64_data.startswith("data:") and "base64," in base64_data:
            header, b64 = base64_data.split("base64,", 1)
            base64_data = b64
            # detect extension from mime
            try:
                mime = header.split("data:")[1].split(";")[0].strip()
                if "/" in mime:
                    ext = mime.split("/")[-1].strip()
            except Exception:
                ext = "jpg"
        elif "base64," in base64_data:
            base64_data = base64_data.split("base64,")[1]

        # Generează numele fișierului
        filename = f"{part_id}_b64.{ext}"
        file_path = offer_dir / filename

        # Salvează imaginea
        with open(file_path, 'wb') as f:
            f.write(base64.b64decode(base64_data))

        logger.info(f"Imagine Base64 salvată: {file_path}")
        return str(file_path.relative_to("static"))

    except Exception as e:
        logger.error(f"Eroare la salvarea imaginii base64: {e}")
        return None

def get_image_path(part) -> str:
    """
    Returnează calea către imaginea reperului (locală sau externă)
    
    Args:
        part: Obiectul Part din baza de date
        
    Returns:
        URL-ul către imagine (local sau extern)
    """
    if part.local_image_path and os.path.exists(f"static/{part.local_image_path}"):
        return f"/static/{part.local_image_path}"
    elif part.image_url:
        return part.image_url
    else:
        return None

def cleanup_old_images(offer_id: str, keep_parts: list) -> None:
    """
    Șterge imaginile vechi care nu mai sunt folosite
    
    Args:
        offer_id: ID-ul ofertei
        keep_parts: Lista de part_id-uri care trebuie păstrate
    """
    try:
        offer_dir = Path(f"static/images/parts/{offer_id}")
        if not offer_dir.exists():
            return
        
        # Șterge fișierele care nu corespund cu part_id-urile actuale
        for file_path in offer_dir.iterdir():
            if file_path.is_file():
                # Extrage part_id din numele fișierului
                filename = file_path.stem
                part_id = filename.split('_')[0]
                
                if part_id not in keep_parts:
                    logger.info(f"Ștergere imagine veche: {file_path}")
                    file_path.unlink()
                    
    except Exception as e:
        logger.error(f"Eroare la curățarea imaginilor vechi: {e}")
