from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from ..config import Settings


class WebClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch(self, url: str) -> tuple[str, str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
            return str(response.url), response.text, content_type

    def scrape(self, html: str) -> tuple[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else "Web source"
        chunks: list[str] = []
        for node in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            text = " ".join(node.get_text(" ", strip=True).split())
            if text:
                chunks.append(text)
        text = "\n".join(chunks)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return title, text[: self._settings.scrape_max_chars]
