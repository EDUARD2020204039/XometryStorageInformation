import logging
import os
from datetime import datetime
from typing import Any

import requests

from .odoo_client import OdooClient


logger = logging.getLogger(__name__)


class DosarService:
    """Service for allocating Xometry dossier numbers and creating their folder/Odoo record."""

    def __init__(self, api_url: str | None = None, api_token: str | None = None):
        self.api_url = (api_url or os.getenv("DOSAR_API_URL", "http://data.helpan.ro:9000")).rstrip("/")
        self.api_token = api_token if api_token is not None else os.getenv("DOSAR_API_TOKEN", "api_token_abc123")
        self.headers = {"Authorization": f"Bearer {self.api_token}"} if self.api_token else {}
        self.folder_enabled = os.getenv("DOSAR_FOLDER_ENABLED", "true").lower() in ("1", "true", "yes")
        self.odoo_required = os.getenv("ODOO_DOSAR_REQUIRED", "false").lower() in ("1", "true", "yes")

    def get_latest_dosar_id(self) -> int | None:
        try:
            response = requests.get(
                f"{self.api_url}/getLatestDosar/",
                headers=self.headers,
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            dosar_id = int(data.get("DosarID", 0))
            logger.info("Latest dosar ID: %s", dosar_id)
            return dosar_id
        except Exception as e:
            logger.error("Could not read latest dosar ID: %s", e)
            return None

    def create_dosar_folder(self, dosar_id: int, folder_name: str) -> dict[str, Any]:
        if not self.folder_enabled:
            return {
                "success": True,
                "dosar_id": dosar_id,
                "folder_name": folder_name,
                "path_linux": f"/mnt/xLucru/{folder_name}",
                "path_windows": f"X:\\{folder_name}",
                "response": {"result": "SKIPPED", "message": "DOSAR_FOLDER_ENABLED=false"},
            }

        try:
            response = requests.get(
                f"{self.api_url}/999/createFolder/{folder_name}",
                headers=self.headers,
                timeout=8,
            )
            response.raise_for_status()
            result = response.json()
            logger.info("Create folder response for %s: %s", folder_name, result)

            if result.get("result") != "OK":
                raise RuntimeError(f"Folder API error: {result.get('message')}")

            return {
                "success": True,
                "dosar_id": dosar_id,
                "folder_name": folder_name,
                "path_linux": f"/mnt/xLucru/{folder_name}",
                "path_windows": f"X:\\{folder_name}",
                "response": result,
            }
        except Exception as e:
            logger.error("Could not create dosar folder %s: %s", folder_name, e)
            return {
                "success": False,
                "error": str(e),
                "dosar_id": dosar_id,
                "folder_name": folder_name,
            }

    def create_odoo_dosar(self, folder_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
        client = OdooClient()
        if not client.configured:
            if self.odoo_required:
                return {
                    "success": False,
                    "error": "Odoo is not configured. Fill ODOO_DB, ODOO_LOGIN and ODOO_PASSWORD.",
                }
            return {"success": False, "skipped": True, "error": "Odoo is not configured"}

        try:
            return client.create_dosar(folder_name, metadata)
        except Exception as e:
            logger.error("Could not create Odoo dosar %s: %s", folder_name, e)
            return {"success": False, "error": str(e)}

    def allocate_dosar(
        self,
        offer_id: str,
        offer_title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            latest_id = self.get_latest_dosar_id()
            if latest_id is None:
                return {"success": False, "error": "Could not read latest dosar ID"}

            new_dosar_id = latest_id + 1
            folder_name = f"{new_dosar_id}_XOMETRY"
            metadata = {
                **(metadata or {}),
                "offer_id": offer_id,
                "title": offer_title,
                "dosar_id": str(new_dosar_id),
                "folder_name": folder_name,
            }

            logger.info("Allocating dosar for %s: %s", offer_id, folder_name)

            odoo_result = self.create_odoo_dosar(folder_name, metadata)
            if self.odoo_required and not odoo_result.get("success"):
                return {
                    "success": False,
                    "error": f"Odoo: {odoo_result.get('error')}",
                    "odoo": odoo_result,
                }

            folder_result = self.create_dosar_folder(new_dosar_id, folder_name)
            if not folder_result.get("success"):
                return {**folder_result, "odoo": odoo_result}

            return {
                "success": True,
                "dosar_id": str(new_dosar_id),
                "folder_name": folder_name,
                "path_linux": folder_result["path_linux"],
                "path_windows": folder_result["path_windows"],
                "allocated_at": datetime.utcnow().isoformat(),
                "odoo": odoo_result,
            }
        except Exception as e:
            logger.error("Could not allocate dosar for %s: %s", offer_id, e)
            return {"success": False, "error": str(e)}

    def check_dosar_exists(self, dosar_id: str) -> bool:
        return bool(dosar_id and str(dosar_id).isdigit())
