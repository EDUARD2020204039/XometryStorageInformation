import os
from typing import Any

import requests


class OdooClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("ODOO_BASE_URL", "https://habaresearch.eu").rstrip("/")
        self.db = os.getenv("ODOO_DB", "")
        self.login = os.getenv("ODOO_LOGIN", "")
        self.password = os.getenv("ODOO_PASSWORD", "")
        self.action_id = int(os.getenv("ODOO_ACTION_ID", "997") or "997")
        self.model = os.getenv("ODOO_DOSAR_MODEL", "")
        self.name_field = os.getenv("ODOO_DOSAR_NAME_FIELD", "name")
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.db and self.login and self.password)

    def authenticate(self) -> int:
        if not self.configured:
            raise RuntimeError("ODOO_BASE_URL, ODOO_DB, ODOO_LOGIN si ODOO_PASSWORD trebuie completate.")

        response = self.session.post(
            f"{self.base_url}/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "params": {
                    "db": self.db,
                    "login": self.login,
                    "password": self.password,
                },
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") or {}
        uid = result.get("uid")
        if not uid:
            raise RuntimeError(payload.get("error") or "Autentificare Odoo esuata.")
        return int(uid)

    def load_dosar_action(self) -> dict[str, Any]:
        self.authenticate()
        response = self.session.post(
            f"{self.base_url}/web/action/load",
            json={
                "jsonrpc": "2.0",
                "params": {
                    "action_id": self.action_id,
                    "additional_context": {},
                },
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        return payload.get("result") or {}

    def create_dosar(self, dosar_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
        self.authenticate()
        model = self.model
        if not model:
            action = self.load_dosar_action()
            model = action.get("res_model") or ""
        if not model:
            raise RuntimeError("Nu stiu modelul Odoo pentru dosar. Completeaza ODOO_DOSAR_MODEL dupa discovery.")

        values: dict[str, Any] = {self.name_field: dosar_name}
        field_map = {
            "ODOO_DOSAR_OFFER_FIELD": metadata.get("offer_id"),
            "ODOO_DOSAR_JOB_FIELD": metadata.get("job_id"),
            "ODOO_DOSAR_PARTS_FIELD": ", ".join(metadata.get("part_ids") or []),
            "ODOO_DOSAR_SOURCE_FIELD": "Xometry",
            "ODOO_DOSAR_URL_FIELD": metadata.get("url"),
        }
        for env_name, value in field_map.items():
            field_name = os.getenv(env_name, "")
            if field_name and value:
                values[field_name] = value

        response = self.session.post(
            f"{self.base_url}/web/dataset/call_kw/{model}/create",
            json={
                "jsonrpc": "2.0",
                "params": {
                    "model": model,
                    "method": "create",
                    "args": [values],
                    "kwargs": {},
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload["error"])

        record_id = payload.get("result")
        return {
            "success": True,
            "model": model,
            "record_id": record_id,
            "url": f"{self.base_url}/odoo/action-{self.action_id}/{model}/{record_id}" if record_id else self.base_url,
            "values": values,
        }
