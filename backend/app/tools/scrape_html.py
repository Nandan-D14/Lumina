from __future__ import annotations

import hashlib
from typing import Optional

import httpx
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from ..config import get_settings
from ..schemas.domain import ArtifactRef, Citation
from ..services.web import WebClient
from .research_state import append_artifact_ref, append_citation


async def scrape_html(
    tool_context: ToolContext,
    url: Optional[str] = None,
    html_artifact_name: Optional[str] = None,
) -> dict[str, str | int]:
    """Scrape clean text from a fetched page or directly from a public URL."""

    settings = get_settings()
    web_client = WebClient(settings)

    if html_artifact_name:
        part = await tool_context.load_artifact(html_artifact_name)
        if part is None:
            return {
                "url": url or html_artifact_name,
                "error": f"HTML artifact could not be loaded: {html_artifact_name}",
            }

        if getattr(part, "text", None):
            html = part.text
        else:
            inline_data = getattr(part, "inline_data", None)
            if inline_data and getattr(inline_data, "data", None):
                html = inline_data.data.decode("utf-8", errors="ignore")
            else:
                return {
                    "url": url or html_artifact_name,
                    "error": f"Loaded artifact has no text payload: {html_artifact_name}",
                }

        title, text = web_client.scrape(html)
        source_url = url or html_artifact_name
    elif url:
        try:
            source_url, html, _ = await web_client.fetch(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return {
                "url": url,
                "error": f"Scrape blocked with HTTP {status}.",
                "status_code": int(status) if isinstance(status, int) else 0,
            }
        except httpx.HTTPError as exc:
            return {
                "url": url,
                "error": f"Scrape failed: {exc}",
            }

        title, text = web_client.scrape(html)
    else:
        raise ValueError("Either url or html_artifact_name must be provided.")

    digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:12]
    artifact_name = f"research/{digest}.txt"
    version = await tool_context.save_artifact(
        artifact_name,
        types.Part.from_text(text=text),
        custom_metadata={"mime_type": "text/plain"},
    )
    append_artifact_ref(tool_context, ArtifactRef(name=artifact_name, mime_type="text/plain", version=version))
    append_citation(tool_context, Citation(title=title, url=source_url, artifact_name=artifact_name))
    return {
        "url": source_url,
        "title": title,
        "artifact_name": artifact_name,
        "version": version,
        "text_excerpt": text[:1000],
    }
