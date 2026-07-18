"""Central runtime configuration for xometry-app."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str) -> tuple[str, ...]:
    value = os.getenv(name, default)
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_version: str
    environment: str
    database_url: str
    public_base_url: str
    analysis_internal_url: str
    analysis_public_url: str
    api_auth_required: bool
    api_token: str
    cors_origins: tuple[str, ...]
    cors_origin_regex: str


def load_settings() -> Settings:
    return Settings(
        app_version=os.getenv("APP_VERSION", "2.0.0-refactor"),
        environment=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/app.db"),
        public_base_url=os.getenv("XSI_PUBLIC_BASE_URL", "https://xsi.habaresearch.eu").rstrip("/"),
        analysis_internal_url=os.getenv("XOMETRY_AGENT_URL", "http://xometryanaliza:4468").rstrip("/"),
        analysis_public_url=os.getenv("XOMETRY_AGENT_PUBLIC_URL", "https://qa.habaresearch.eu").rstrip("/"),
        api_auth_required=_bool("XSI_API_AUTH_REQUIRED", False),
        api_token=os.getenv("XSI_API_TOKEN", os.getenv("BACKEND_API_KEY", "")),
        cors_origins=_csv("XSI_CORS_ORIGINS", "https://partner.xometry.eu"),
        cors_origin_regex=os.getenv(
            "XSI_CORS_ORIGIN_REGEX",
            r"^chrome-extension://[a-p]{32}$",
        ),
    )


settings = load_settings()
