from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from google.adk.runners import InMemoryRunner

from ..config import Settings
from ..schemas.domain import Citation, FileSourceInput, NormalizedSource, SourceInput, TableData, TextSourceInput, UrlSourceInput
from ..schemas.requests import AnalyzeRequest
from ..services.artifact_store import ArtifactContext
from ..services.web import WebClient
from ..tools.parse_csv_json import parse_csv_bytes, parse_json_bytes
from ..tools.parse_pdf import parse_pdf_bytes
from . import state_keys


@dataclass
class IngestionResult:
    analysis_id: str
    session_id: str
    normalized_sources: list[NormalizedSource]
    citations: list[Citation]
    tables: list[TableData]
    artifact_context: ArtifactContext

    @property
    def normalized_corpus(self) -> str:
        sections = []
        for source in self.normalized_sources:
            sections.append(f"[{source.title} | {source.source_type}]\n{source.text_content}")
        return "\n\n".join(sections).strip()


def should_run_research(request: AnalyzeRequest) -> bool:
    return request.options.allow_web_research


class IngestionPipeline:
    def __init__(self, settings: Settings, runner: InMemoryRunner) -> None:
        self._settings = settings
        self._runner = runner
        self._web_client = WebClient(settings)

    async def prepare(self, request: AnalyzeRequest, user_id: str) -> IngestionResult:
        analysis_id = str(uuid.uuid4())

        artifacts = ArtifactContext(
            runner=self._runner,
            app_name=self._settings.app_name,
            user_id=user_id,
            session_id=analysis_id,
        )

        normalized_sources: list[NormalizedSource] = []
        citations: list[Citation] = []
        tables: list[TableData] = []

        for index, source in enumerate(request.sources, start=1):
            normalized = await self._normalize_source(index, source, request.options.allow_scraping, artifacts)
            normalized_sources.append(normalized)
            citations.append(normalized.citation)
            tables.extend(normalized.tables)

        state = {
            state_keys.ANALYSIS_ID: analysis_id,
            state_keys.USER_PROMPT: request.prompt,
            state_keys.ALLOW_WEB_RESEARCH: request.options.allow_web_research,
            state_keys.SHOULD_RUN_RESEARCH: should_run_research(request),
            state_keys.ALLOW_SCRAPING: request.options.allow_scraping,
            state_keys.MAX_VISUALIZATIONS: min(request.options.max_visualizations, self._settings.max_visualizations),
            state_keys.NORMALIZED_CORPUS: self._build_corpus(request.prompt, normalized_sources),
            state_keys.NORMALIZED_TABLES_JSON: json.dumps([table.model_dump(mode="json") for table in tables], ensure_ascii=False),
            state_keys.INITIAL_CITATIONS_JSON: json.dumps([citation.model_dump(mode="json") for citation in citations], ensure_ascii=False),
            state_keys.ARTIFACT_REFS_JSON: json.dumps([artifact.model_dump(mode="json") for artifact in artifacts.artifacts], ensure_ascii=False),
        }
        state[state_keys.COMBINED_CITATIONS_JSON] = state[state_keys.INITIAL_CITATIONS_JSON]
        state["ingestion_branch"] = "{}"
        state["research_branch"] = "{}"
        state["insights_branch"] = "{}"
        state["entities_branch"] = "{}"
        state["visualizations_branch"] = "{}"
        state["table_reasoner_branch"] = "{}"


        session = await self._runner.session_service.create_session(
            app_name=self._settings.app_name,
            user_id=user_id,
            state=state,
            session_id=analysis_id,
        )

        return IngestionResult(
            analysis_id=analysis_id,
            session_id=session.id,
            normalized_sources=normalized_sources,
            citations=citations,
            tables=tables,
            artifact_context=artifacts,
        )

    async def _normalize_source(
        self,
        index: int,
        source: SourceInput,
        allow_scraping: bool,
        artifacts: ArtifactContext,
    ) -> NormalizedSource:
        source_id = f"source_{index}"
        if isinstance(source, TextSourceInput):
            title = source.title or f"Text source {index}"
            raw_name = f"inputs/{source_id}.txt"
            raw_ref = await artifacts.save_text(raw_name, source.text)
            citation = Citation(title=title, artifact_name=raw_ref.name)
            return NormalizedSource(
                source_id=source_id,
                source_type="text",
                title=title,
                mime_type="text/plain",
                text_content=source.text.strip(),
                citation=citation,
                artifact_names=[raw_ref.name],
            )

        if isinstance(source, UrlSourceInput):
            title = source.title or source.url
            text_content = f"URL source: {source.url}"
            artifact_names: list[str] = []
            source_url = source.url
            if allow_scraping:
                try:
                    final_url, html, _ = await self._web_client.fetch(source.url)
                    html_ref = await artifacts.save_text(f"inputs/{source_id}.html", html, "text/html")
                    page_title, scraped_text = self._web_client.scrape(html)
                    text_ref = await artifacts.save_text(f"inputs/{source_id}.scraped.txt", scraped_text)
                    title = source.title or page_title
                    text_content = scraped_text or text_content
                    artifact_names.extend([html_ref.name, text_ref.name])
                    source_url = final_url
                except Exception as exc:
                    text_content = f"URL source could not be fetched/scraped ({source.url}): {exc}"
            citation = Citation(title=title, url=source_url, artifact_name=artifact_names[-1] if artifact_names else None)
            return NormalizedSource(
                source_id=source_id,
                source_type="url",
                title=title,
                mime_type="text/html",
                text_content=text_content,
                citation=citation,
                artifact_names=artifact_names,
            )

        if isinstance(source, FileSourceInput):
            return await self._normalize_file_source(source_id, source, artifacts)

        raise HTTPException(status_code=400, detail="Unsupported source type.")

    async def _normalize_file_source(self, source_id: str, source: FileSourceInput, artifacts: ArtifactContext) -> NormalizedSource:
        try:
            payload = base64.b64decode(source.content_base64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid base64 payload for {source.filename}.") from exc

        raw_ref = await artifacts.save_bytes(f"inputs/{source_id}.{source.filename}", payload, source.mime_type)
        lower_name = source.filename.lower()
        tables: list[TableData] = []

        try:
            if lower_name.endswith(".csv") or source.mime_type == "text/csv":
                text_content, tables = parse_csv_bytes(payload, source.filename)
            elif lower_name.endswith(".json") or source.mime_type == "application/json":
                text_content, tables = parse_json_bytes(payload, source.filename)
            elif lower_name.endswith(".pdf") or source.mime_type == "application/pdf":
                text_content = parse_pdf_bytes(payload)
            else:
                raise HTTPException(status_code=415, detail=f"Unsupported file type for {source.filename}.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not parse {source.filename}: {exc}") from exc

        normalized_ref = await artifacts.save_text(f"inputs/{source_id}.normalized.txt", text_content)
        citation = Citation(title=source.filename, artifact_name=normalized_ref.name)
        return NormalizedSource(
            source_id=source_id,
            source_type="file",
            title=source.filename,
            mime_type=source.mime_type,
            text_content=text_content,
            tables=tables,
            citation=citation,
            artifact_names=[raw_ref.name, normalized_ref.name],
        )

    def _build_corpus(self, prompt: str, sources: list[NormalizedSource]) -> str:
        sections = [f"User prompt:\n{prompt.strip()}"]
        for source in sources:
            sections.append(f"Source: {source.title} ({source.source_type})\n{source.text_content}")
        return "\n\n".join(section.strip() for section in sections if section.strip())
