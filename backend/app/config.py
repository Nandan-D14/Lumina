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
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY_FALLBACK", "")).strip().strip("'\"").strip()
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", os.getenv("OPENROUTER_MODEL_FALLBACK", "")).strip().strip("'\"").strip()
    openrouter_endpoint: str = os.getenv("OPENROUTER_URL", os.getenv("OPENROUTER_URL_FALLBACK", "https://openrouter.ai/api/v1")).strip().strip("'\"").strip()
    cors_origins: tuple[str, ...] = ("*",)
    http_timeout_seconds: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))
    scrape_max_chars: int = int(os.getenv("SCRAPE_MAX_CHARS", "12000"))
    max_visualizations: int = int(os.getenv("MAX_VISUALIZATIONS", "4"))
    default_user_id: str = os.getenv("DEFAULT_USER_ID", "user")

    def has_google_auth(self) -> bool:
        return bool(
            os.getenv("GOOGLE_API_KEY")
            or os.getenv("GOOGLE_GENAI_USE_VERTEXAI")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
        )

    def has_openrouter_auth(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model and self.openrouter_endpoint)


@lru_cache
def get_settings() -> Settings:
    return Settings()
