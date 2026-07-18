import asyncio
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from xometry.security import require_ingest_auth
from xometry.settings import settings


def request_with_token(token: str = "") -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({"type": "http", "headers": headers})


class IngestSecurityTests(unittest.TestCase):
    def test_compatibility_mode_allows_missing_token(self):
        configured = replace(settings, api_auth_required=False, api_token="")
        with patch("xometry.security.settings", configured):
            asyncio.run(require_ingest_auth(request_with_token()))

    def test_required_mode_accepts_matching_token(self):
        configured = replace(settings, api_auth_required=True, api_token="secret")
        with patch("xometry.security.settings", configured):
            asyncio.run(require_ingest_auth(request_with_token("secret")))

    def test_required_mode_rejects_missing_token(self):
        configured = replace(settings, api_auth_required=True, api_token="secret")
        with patch("xometry.security.settings", configured):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(require_ingest_auth(request_with_token()))
        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
