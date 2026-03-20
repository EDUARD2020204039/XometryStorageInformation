"""
Serviciu pentru gestionarea dosarelor
"""
import requests
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class DosarService:
    """Serviciu pentru alocarea și gestionarea dosarelor"""
    
    def __init__(self, api_url: str = "http://data.helpan.ro:9000", api_token: str = "api_token_abc123"):
        self.api_url = api_url
        self.api_token = api_token
        self.headers = {'Authorization': f'Bearer {api_token}'}
    
    def get_latest_dosar_id(self) -> Optional[int]:
        """Obține ultimul ID de dosar alocat"""
        try:
            response = requests.get(
                f'{self.api_url}/getLatestDosar/',
                headers=self.headers,
                timeout=5
            )
            response.raise_for_status()
            
            data = response.json()
            dosar_id = int(data.get('DosarID', 0))
            logger.info(f"Ultimul dosar ID: {dosar_id}")
            return dosar_id
            
        except Exception as e:
            logger.error(f"Eroare la obținerea ultimului dosar ID: {e}")
            return None
    
    def create_dosar_folder(self, dosar_id: int, folder_name: str) -> Dict[str, Any]:
        """Creează folderul pentru dosar"""
        try:
            response = requests.get(
                f'{self.api_url}/999/createFolder/{folder_name}',
                headers=self.headers,
                timeout=5
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Răspuns creare folder {folder_name}: {result}")
            
            if result.get("result") != "OK":
                raise Exception(f"Eroare de la creare -- {result.get('message')}")
            
            return {
                'success': True,
                'dosar_id': dosar_id,
                'folder_name': folder_name,
                'path_linux': f"/mnt/xLucru/{folder_name}",
                'path_windows': f"X:\\{folder_name}",
                'response': result
            }
            
        except Exception as e:
            logger.error(f"Eroare la crearea folderului {folder_name}: {e}")
            return {
                'success': False,
                'error': str(e),
                'dosar_id': dosar_id,
                'folder_name': folder_name
            }
    
    def allocate_dosar(self, offer_id: str, offer_title: str = "") -> Dict[str, Any]:
        """Alocă un dosar nou pentru o ofertă"""
        try:
            # 1. Obține ultimul ID de dosar
            latest_id = self.get_latest_dosar_id()
            if latest_id is None:
                return {
                    'success': False,
                    'error': 'Nu s-a putut obține ultimul ID de dosar'
                }
            
            # 2. Calculează noul ID
            new_dosar_id = latest_id + 1
            
            # 3. Pregătește numele folderului - simplu: {dosar_id}_XOMETRY
            folder_name = f"{new_dosar_id}_XOMETRY"
            
            logger.info(f"Alocare dosar pentru {offer_id}: {folder_name}")
            
            # 4. Creează folderul
            result = self.create_dosar_folder(new_dosar_id, folder_name)
            
            if result['success']:
                return {
                    'success': True,
                    'dosar_id': str(new_dosar_id),
                    'folder_name': folder_name,
                    'path_linux': result['path_linux'],
                    'path_windows': result['path_windows'],
                    'allocated_at': datetime.utcnow().isoformat()
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"Eroare la alocarea dosarului pentru {offer_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def check_dosar_exists(self, dosar_id: str) -> bool:
        """Verifică dacă un dosar există deja"""
        try:
            # Poți implementa o verificare aici dacă API-ul suportă
            # Pentru moment, presupunem că dacă avem un ID, există
            return bool(dosar_id and dosar_id.isdigit())
        except Exception:
            return False
