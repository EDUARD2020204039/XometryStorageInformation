"""Authentication dependencies for machine-to-machine ingestion endpoints."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from .settings import settings


def _request_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("x-api-key", "").strip()


async def require_ingest_auth(request: Request) -> None:
    """Protect writes while allowing an explicit compatibility window during migration."""
    expected = settings.api_token
    provided = _request_token(request)

    if settings.api_auth_required and not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is required but XSI_API_TOKEN is not configured",
        )

    if not settings.api_auth_required and not provided:
        return
    if expected and provided and secrets.compare_digest(provided, expected):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API token",
        headers={"WWW-Authenticate": "Bearer"},
    )
