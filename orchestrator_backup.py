from __future__ import annotations

import asyncio
import json
import os
import re

from fastapi import HTTPException
from google.adk.runners import InMemoryRunner
from google.genai import types
import httpx

from ..config import Settings
from ..orchestration.pipelines import IngestionPipeline
from ..orchestration import state_keys
from ..orchestration.root import build_agent_graph
from ..schemas.domain import ArtifactRef, Citation
from ..schemas.requests import AnalyzeRequest
from ..schemas.responses import InsightPackage
from .analysis_repository import AnalysisRepository, StoredAnalysis
from .artifact_store import ArtifactContext


class InsightOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._graph = build_agent_graph(settings)
        self._runner = InMemoryRunner(agent=self._graph.root_agent, app_name=settings.app_name)
        self._repository = AnalysisRepository()
        self._ingestion = IngestionPipeline(settings, self._runner)
        self._model_call_lock = asyncio.Lock()

    @property
    def runner(self) -> InMemoryRunner:
        return self._runner

    @property
    def repository(self) -> AnalysisRepository:
        return self._repository

    def ensure_google_auth(self, request_api_key: str | None = None) -> None:
        if self._settings.default_model.startswith("gemini") and not (request_api_key or self._settings.has_google_auth()):
            raise HTTPException(
                status_code=500,
                detail="Missing Gemini API key. Provide options.gemini_api_key in the request (required), or configure GOOGLE_API_KEY.",
            )

    async def analyze(self, request: AnalyzeRequest) -> InsightPackage:
        request_api_key = (request.options.gemini_api_key or "").strip() or None

        user_id = (request.options.user_id or self._settings.default_user_id).strip()
        if request.options.persistence_mode == "persistent" and not self._settings.database_url:
            raise HTTPException(
                status_code=400,
                detail="Persistent mode requires DATABASE_URL to be configured on the backend.",
            )

        if self._settings.has_openrouter_auth():
            return await self._analyze_with_openrouter(request, user_id)

        if request_api_key is None:
            raise HTTPException(status_code=400, detail="Gemini API key is required. Set options.gemini_api_key.")

        self.ensure_google_auth(request_api_key)
        ingestion = await self._ingestion.prepare(request, user_id)

        session = await self._runner.session_service.get_session(
            app_name=self._settings.app_name,
            user_id=user_id,
            session_id=ingestion.session_id,
        )

        kickoff = types.Content(role="user", parts=[types.Part(text="Produce the final insight package from the prepared session state.")])
        try:
            async with self._model_call_lock:
                previous_key = os.getenv("GOOGLE_API_KEY")
                os.environ["GOOGLE_API_KEY"] = request_api_key
                try:
                    async for _event in self._runner.run_async(
                        user_id=user_id,
                        session_id=ingestion.session_id,
                        new_message=kickoff,
                    ):
                        pass
                finally:
                    if previous_key:
                        os.environ["GOOGLE_API_KEY"] = previous_key
                    else:
                        os.environ.pop("GOOGLE_API_KEY", None)
        except HTTPException:
            raise
        except Exception as exc:
            messages = self._collect_exception_messages(exc)
            message = " | ".join(msg for msg in messages if msg) or str(exc)
            upper_message = message.upper()
            if "RESOURCE_EXHAUSTED" in upper_message or "429" in upper_message:
                raise HTTPException(
                    status_code=429,
                    detail="Model quota exhausted. Retry shortly, reduce request volume, or update Gemini billing/quota settings.",
                ) from exc
            if (
                "API_KEY_INVALID" in upper_message
                or "API KEY EXPIRED" in upper_message
                or "INVALID API KEY" in upper_message
            ):
                raise HTTPException(
                    status_code=401,
                    detail="Google API key is invalid or expired. Update GOOGLE_API_KEY in .env and restart the backend.",
                ) from exc
            if "403" in upper_message or "FORBIDDEN" in upper_message:
                raise HTTPException(
                    status_code=424,
                    detail="A target website blocked automated access (HTTP 403). Try another URL, disable scraping, or enable web research to use alternative sources.",
                ) from exc
            raise HTTPException(status_code=502, detail=f"Model pipeline failed: {message}") from exc

        session = await self._runner.session_service.get_session(
            app_name=self._settings.app_name,
            user_id=user_id,
            session_id=ingestion.session_id,
        )
        if session is None or "final_insight_package" not in session.state:
            raise HTTPException(status_code=500, detail="Agent did not produce a final insight package.")

        try:
            package = InsightPackage.model_validate(session.state["final_insight_package"])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Agent returned invalid structured data: {exc}") from exc

        merged_citations = self._merge_citations(
            package.citations,
            self._read_session_models(session, state_keys.COMBINED_CITATIONS_JSON, Citation),
        )
        merged_artifacts = self._merge_artifacts(
            package.artifacts,
            self._read_session_models(session, state_keys.ARTIFACT_REFS_JSON, ArtifactRef),
        )
        final_package = package.model_copy(
            update={
                "citations": merged_citations,
                "artifacts": merged_artifacts,
                "session_id": ingestion.session_id,
                "persistence_mode": request.options.persistence_mode,
            }
        )

        if (
            not final_package.visualizations
            and not final_package.tables
            and not final_package.metrics
            and not final_package.insights
            and not final_package.summary.strip()
        ):
            raise HTTPException(status_code=422, detail="Could not extract chartable or structured data from the input.")

        artifact_context = ArtifactContext(
            runner=self._runner,
            app_name=self._settings.app_name,
            user_id=user_id,
            session_id=ingestion.session_id,
            artifacts=list(merged_artifacts),
        )
        final_ref = await artifact_context.save_text(
            f"analyses/{final_package.analysis_id}.json",
            json.dumps(final_package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            "application/json",
        )
        self._repository.save(
            StoredAnalysis(
                analysis_id=final_package.analysis_id,
                user_id=user_id,
                session_id=ingestion.session_id,
                filename=final_ref.name,
                version=final_ref.version,
            )
        )
        return final_package

    async def _analyze_with_openrouter(self, request: AnalyzeRequest, user_id: str) -> InsightPackage:
        ingestion = await self._ingestion.prepare(request, user_id)

        system_prompt = (
            "You are a strict data analysis assistant. Return ONLY valid JSON with keys: "
            "summary (string), insights (string[]), metrics ({label, value}[]), "
            "entities ({name, type, value?}[]), visualizations ({id, title, kind, reason, labels?, values?}[]). "
            "Allowed visualization kind values: bar, line, pie, table. No markdown or prose outside JSON."
        )
        user_prompt = (
            f"User prompt:\n{request.prompt}\n\n"
            f"Normalized corpus:\n{ingestion.normalized_corpus}\n\n"
            f"Tables JSON:\n{json.dumps([table.model_dump(mode='json') for table in ingestion.tables], ensure_ascii=False)}\n\n"
            f"Max visualizations: {request.options.max_visualizations}"
        )

        payload = {
            "model": self._settings.openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds * 2) as client:
                response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"OpenRouter request failed: {exc}") from exc

        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="OpenRouter quota/rate limit exceeded. Retry shortly or update plan limits.")
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=401, detail="OpenRouter credentials are invalid or unauthorized.")
        if response.status_code >= 400:
            detail = response.text.strip()
            raise HTTPException(status_code=502, detail=f"OpenRouter failed ({response.status_code}): {detail[:600]}")

        try:
            response_json = response.json()
            content = response_json["choices"][0]["message"]["content"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail="OpenRouter returned an unexpected response shape.") from exc

        parsed = self._extract_json_payload(content)
        if parsed is None:
            raise HTTPException(status_code=502, detail="OpenRouter response did not contain valid JSON.")

        package_payload = {
            "analysis_id": ingestion.analysis_id,
            "session_id": ingestion.session_id,
            "persistence_mode": request.options.persistence_mode,
            "summary": str(parsed.get("summary") or "Analysis completed via OpenRouter."),
            "insights": [str(item) for item in parsed.get("insights", []) if str(item).strip()],
            "metrics": parsed.get("metrics", []),
            "entities": parsed.get("entities", []),
            "tables": [table.model_dump(mode="json") for table in ingestion.tables],
            "visualizations": parsed.get("visualizations", []),
            "citations": [citation.model_dump(mode="json") for citation in ingestion.citations],
            "artifacts": [artifact.model_dump(mode="json") for artifact in ingestion.artifact_context.artifacts],
        }

        try:
            final_package = InsightPackage.model_validate(package_payload)
        except Exception:
            fallback_payload = {
                "analysis_id": ingestion.analysis_id,
                "session_id": ingestion.session_id,
                "persistence_mode": request.options.persistence_mode,
                "summary": str(parsed.get("summary") or "Analysis completed via OpenRouter."),
                "insights": [str(item) for item in parsed.get("insights", []) if str(item).strip()],
                "metrics": [],
                "entities": [],
                "tables": [table.model_dump(mode="json") for table in ingestion.tables],
                "visualizations": [],
                "citations": [citation.model_dump(mode="json") for citation in ingestion.citations],
                "artifacts": [artifact.model_dump(mode="json") for artifact in ingestion.artifact_context.artifacts],
            }
            final_package = InsightPackage.model_validate(fallback_payload)

        if (
            not final_package.visualizations
            and not final_package.tables
            and not final_package.metrics
            and not final_package.insights
            and not final_package.summary.strip()
        ):
            raise HTTPException(status_code=422, detail="Could not extract chartable or structured data from the input.")

        final_ref = await ingestion.artifact_context.save_text(
            f"analyses/{final_package.analysis_id}.json",
            json.dumps(final_package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            "application/json",
        )
        self._repository.save(
            StoredAnalysis(
                analysis_id=final_package.analysis_id,
                user_id=user_id,
                session_id=ingestion.session_id,
                filename=final_ref.name,
                version=final_ref.version,
            )
        )
        return final_package

    def artifact_context_for(self, analysis_id: str) -> ArtifactContext:
        stored = self._repository.get(analysis_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Analysis not found.")
        return ArtifactContext(
            runner=self._runner,
            app_name=self._settings.app_name,
            user_id=stored.user_id,
            session_id=stored.session_id,
        )

    @staticmethod
    def _read_session_models(session, key: str, model_type):
        raw = session.state.get(key)
        if not raw:
            return []
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list):
            return []
        parsed = []
        for item in items:
            try:
                parsed.append(model_type.model_validate(item))
            except Exception:
                continue
        return parsed

    @staticmethod
    def _merge_citations(primary: list[Citation], secondary: list[Citation]) -> list[Citation]:
        merged: list[Citation] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for citation in [*primary, *secondary]:
            key = (citation.title, citation.url, citation.artifact_name)
            if key in seen:
                continue
            seen.add(key)
            merged.append(citation)
        return merged

    @staticmethod
    def _merge_artifacts(primary: list[ArtifactRef], secondary: list[ArtifactRef]) -> list[ArtifactRef]:
        merged: list[ArtifactRef] = []
        seen: set[tuple[str, str, int]] = set()
        for artifact in [*primary, *secondary]:
            key = (artifact.name, artifact.mime_type, artifact.version)
            if key in seen:
                continue
            seen.add(key)
            merged.append(artifact)
        return merged

    @staticmethod
    def _collect_exception_messages(exc: BaseException) -> list[str]:
        messages: list[str] = []

        def walk(error: BaseException) -> None:
            group_exceptions = getattr(error, "exceptions", None)
            if group_exceptions:
                for inner in group_exceptions:
                    walk(inner)
                return

            text = str(error).strip()
            if text:
                messages.append(text)

            cause = error.__cause__
            if cause is not None:
                walk(cause)

        walk(exc)
        return messages

    @staticmethod
    def _extract_json_payload(content: str) -> dict | None:
        if not content:
            return None

        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None

        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
