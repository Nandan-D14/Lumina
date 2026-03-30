from __future__ import annotations

import hashlib

from fastapi import APIRouter

from ..config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "model": settings.default_model}


@router.get("/health/runtime")
async def health_runtime() -> dict[str, str | bool | None]:
    settings = get_settings()
    key_fingerprint = None
    if settings.nvidia_api_key:
        # Expose only a short fingerprint so we can confirm which key was loaded without leaking credentials.
        key_fingerprint = hashlib.sha256(settings.nvidia_api_key.encode("utf-8")).hexdigest()[:12]

    return {
        "status": "ok",
        "default_model": settings.default_model,
        "nvidia_enabled": settings.has_nvidia_auth(),
        "nvidia_model": settings.nvidia_model or None,
        "nvidia_endpoint": settings.nvidia_endpoint or None,
        "nvidia_key_fingerprint": key_fingerprint,
    }
