from __future__ import annotations

import hashlib

import httpx
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from ..config import get_settings
from ..schemas.domain import ArtifactRef, Citation
from ..services.web import WebClient
from .research_state import append_artifact_ref, append_citation


async def fetch_url(url: str, tool_context: ToolContext) -> dict[str, str | int]:
    """Fetch a public URL and save the raw HTML as an artifact."""

    settings = get_settings()
    web_client = WebClient(settings)
    try:
        final_url, html, content_type = await web_client.fetch(url)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        return {
            "url": url,
            "error": f"Fetch blocked with HTTP {status}.",
            "status_code": int(status) if isinstance(status, int) else 0,
        }
    except httpx.HTTPError as exc:
        return {
            "url": url,
            "error": f"Fetch failed: {exc}",
        }

    digest = hashlib.sha1(final_url.encode("utf-8")).hexdigest()[:12]
    artifact_name = f"research/{digest}.html"
    version = await tool_context.save_artifact(
        artifact_name,
        types.Part.from_text(text=html),
        custom_metadata={"mime_type": content_type},
    )
    append_artifact_ref(tool_context, ArtifactRef(name=artifact_name, mime_type=content_type, version=version))
    append_citation(tool_context, Citation(title=final_url, url=final_url, artifact_name=artifact_name))
    return {
        "url": final_url,
        "artifact_name": artifact_name,
        "version": version,
        "content_type": content_type,
    }
