import os
import re
from typing import Any

import requests


class OdooClient:
    def __init__(self) -> None:
        self.base_url = (os.getenv("ODOO_BASE_URL") or os.getenv("ODOO_URL") or "https://habaresearch.eu").rstrip("/")
        self.db = os.getenv("ODOO_DB", "")
        self.login = os.getenv("ODOO_LOGIN") or os.getenv("ODOO_USER", "")
        self.password = os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY", "")
        self.action_id = int(os.getenv("ODOO_ACTION_ID", "997") or "997")
        self.model = os.getenv("ODOO_DOSAR_MODEL", "")
        self.name_field = os.getenv("ODOO_DOSAR_NAME_FIELD", "name")
        self.session = requests.Session()
        self.uid: int | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.db and self.login and self.password)

    def _jsonrpc(self, service: str, method: str, args: list[Any]) -> Any:
        response = self.session.post(
            f"{self.base_url}/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "service": service,
                    "method": method,
                    "args": args,
                },
                "id": 1,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        return payload.get("result")

    def authenticate(self) -> int:
        if not self.configured:
            raise RuntimeError("ODOO_BASE_URL/ODOO_URL, ODOO_DB, ODOO_LOGIN/ODOO_USER si ODOO_PASSWORD/ODOO_API_KEY trebuie completate.")

        if self.uid:
            return self.uid

        uid = self._jsonrpc("common", "authenticate", [self.db, self.login, self.password, {}])
        if not uid:
            raise RuntimeError("Autentificare Odoo esuata.")
        self.uid = int(uid)
        return self.uid

    def load_dosar_action(self) -> dict[str, Any]:
        uid = self.authenticate()
        fields = ["name", "res_model", "view_mode", "views", "context", "domain"]
        result = self._jsonrpc(
            "object",
            "execute_kw",
            [self.db, uid, self.password, "ir.actions.act_window", "read", [[self.action_id], fields], {}],
        )
        if result:
            return result[0] or {}

        fallback = self._jsonrpc(
            "object",
            "execute_kw",
            [self.db, uid, self.password, "ir.actions.actions", "read", [[self.action_id], ["name", "type"]], {}],
        )
        return (fallback or [{}])[0] or {}

    def create_dosar(self, dosar_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
        uid = self.authenticate()
        model = self.model
        if not model:
            action = self.load_dosar_action()
            model = action.get("res_model") or ""
        if not model:
            raise RuntimeError("Nu stiu modelul Odoo pentru dosar. Completeaza ODOO_DOSAR_MODEL dupa discovery.")

        values: dict[str, Any] = {self.name_field: dosar_name}
        field_map = {
            "ODOO_DOSAR_ID_FIELD": metadata.get("dosar_id"),
            "ODOO_DOSAR_OFFER_FIELD": metadata.get("offer_id"),
            "ODOO_DOSAR_JOB_FIELD": metadata.get("job_id"),
            "ODOO_DOSAR_PARTS_FIELD": ", ".join(metadata.get("part_ids") or []),
            "ODOO_DOSAR_SOURCE_FIELD": "Xometry",
            "ODOO_DOSAR_URL_FIELD": metadata.get("url"),
        }
        for env_name, value in field_map.items():
            field_name = os.getenv(env_name, "")
            if field_name and value:
                if env_name == "ODOO_DOSAR_ID_FIELD":
                    value = int(value)
                values[field_name] = value

        record_id = self._jsonrpc(
            "object",
            "execute_kw",
            [self.db, uid, self.password, model, "create", [values], {}],
        )
        return {
            "success": True,
            "model": model,
            "record_id": record_id,
            "url": f"{self.base_url}/odoo/action-{self.action_id}/{model}/{record_id}" if record_id else self.base_url,
            "values": values,
        }

    def get_latest_dosar_id(self) -> int | None:
        uid = self.authenticate()
        model = self.model
        if not model:
            action = self.load_dosar_action()
            model = action.get("res_model") or ""
        if not model:
            raise RuntimeError("Nu stiu modelul Odoo pentru dosar. Completeaza ODOO_DOSAR_MODEL dupa discovery.")

        id_field = os.getenv("ODOO_DOSAR_ID_FIELD", "")
        fields = [self.name_field]
        if id_field:
            fields.append(id_field)

        records = self._jsonrpc(
            "object",
            "execute_kw",
            [self.db, uid, self.password, model, "search_read", [[], fields], {"limit": 200, "order": "id desc"}],
        ) or []

        latest: int | None = None
        for record in records:
            candidates = []
            if id_field:
                candidates.append(record.get(id_field))
            candidates.append(record.get(self.name_field))

            for value in candidates:
                if value in (None, False, ""):
                    continue
                match = re.search(r"\d+", str(value))
                if match:
                    number = int(match.group(0))
                    latest = number if latest is None else max(latest, number)

        return latest
