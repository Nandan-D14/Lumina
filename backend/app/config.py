from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("AGENT_APP_NAME", "insight_orchestrator")
    default_model: str = os.getenv("AGENT_MODEL", "gemini-3-flash-preview")
    database_url: str = os.getenv("DATABASE_URL", "")
    nvidia_api_key: str = os.getenv("NVIDIA_API_KEY", "").strip().strip("'\"").strip()
    nvidia_model: str = os.getenv("NVIDIA_MODEL", "").strip().strip("'\"").strip()
    nvidia_endpoint: str = os.getenv("NVIDIA_API_URL", "https://integrate.api.nvidia.com/v1").strip().strip("'\"").strip()
    cors_origins: tuple[str, ...] = ("*",)
    http_timeout_seconds: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "120"))
    scrape_max_chars: int = int(os.getenv("SCRAPE_MAX_CHARS", "12000"))
    max_visualizations: int = int(os.getenv("MAX_VISUALIZATIONS", "8"))
    default_user_id: str = os.getenv("DEFAULT_USER_ID", "user")

    def has_google_auth(self) -> bool:
        return bool(
            os.getenv("GOOGLE_API_KEY")
            or os.getenv("GOOGLE_GENAI_USE_VERTEXAI")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
        )

    def has_nvidia_auth(self) -> bool:
        return bool(self.nvidia_api_key and self.nvidia_model and self.nvidia_endpoint)


@lru_cache
def get_settings() -> Settings:
    return Settings()
