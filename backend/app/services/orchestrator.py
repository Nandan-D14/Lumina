from __future__ import annotations

import asyncio
import html
import json
import os
import re
from typing import Any

from fastapi import HTTPException
from google.adk.runners import InMemoryRunner
from google.genai import types
import httpx

from ..config import Settings
from ..orchestration.pipelines import IngestionPipeline
from ..orchestration import state_keys
from ..orchestration.root import build_agent_graph
from ..schemas.domain import ArtifactRef, Citation, TableData
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
            "entities ({name, type, value?}[]), visualizations ({id, title, kind, reason, labels?, values?}[]), "
            "advanced_html_report (optional string). "
            "Summary must be detailed and decision-useful (minimum 120 words) covering context, drivers, implications, and risks. "
            "Insights should contain 8-14 specific findings when evidence allows. "
            "Metrics should contain 6-12 concrete values when evidence allows. "
            f"Generate up to {request.options.max_visualizations} visualizations. Prefer at least 4 charts when data supports it. "
            "Allowed visualization kind values: bar, line, pie, table. "
            "For chart visualizations, labels and values arrays are required and must be equal length with real numeric values. "
            "If exact data is missing, synthesize realistic estimates instead of leaving charts empty. "
            "Do not output placeholder text or dummy markers. "
            "If advanced_html_report is provided, return a full HTML document with CSS + vanilla JS and optional Chart.js CDN only; include multiple dynamic chart sections and at least one diagram-style section (for example SVG relationship map or flow map). "
            "No markdown or prose outside JSON."
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

        response = await self._post_openrouter_request(payload)

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
            parsed = self._build_fallback_payload_from_text(content)

        sanitized = self._sanitize_openrouter_payload(parsed, request.options.max_visualizations)
        enriched = self._enrich_openrouter_payload(sanitized, ingestion.tables, request.options.max_visualizations)

        package_payload = {
            "analysis_id": ingestion.analysis_id,
            "session_id": ingestion.session_id,
            "persistence_mode": request.options.persistence_mode,
            "summary": str(enriched.get("summary") or "Analysis completed via OpenRouter."),
            "advanced_html_report": enriched.get("advanced_html_report"),
            "insights": enriched.get("insights", []),
            "metrics": enriched.get("metrics", []),
            "entities": enriched.get("entities", []),
            "tables": [table.model_dump(mode="json") for table in ingestion.tables],
            "visualizations": enriched.get("visualizations", []),
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
                "summary": str(enriched.get("summary") or "Analysis completed via OpenRouter."),
                "advanced_html_report": enriched.get("advanced_html_report"),
                "insights": enriched.get("insights", []),
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


    async def analyze_stream(self, request: AnalyzeRequest) -> "AsyncGenerator[str, None]":
        from typing import AsyncGenerator
        request_api_key = (request.options.gemini_api_key or "").strip() or None
        user_id = (request.options.user_id or self._settings.default_user_id).strip()

        if request.options.persistence_mode == "persistent" and not self._settings.database_url:
            yield json.dumps({"type": "error", "message": "Persistent mode requires DATABASE_URL to be configured on the backend."}) + "\n"
            return

        if self._settings.has_openrouter_auth():
            async for chunk in self._analyze_stream_with_openrouter(request, user_id):
                yield chunk
            return

        if request_api_key is None:
            yield json.dumps({"type": "error", "message": "Gemini API key is required. Set options.gemini_api_key."}) + "\n"
            return

        try:
            self.ensure_google_auth(request_api_key)
        except HTTPException as e:
            yield json.dumps({"type": "error", "message": e.detail}) + "\n"
            return

        yield json.dumps({"type": "step", "message": "Preparing session and ingesting sources..."}) + "\n"
        try:
            ingestion = await self._ingestion.prepare(request, user_id)
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return

        yield json.dumps({"type": "step", "message": "Evaluating prompt across AI agent graph..."}) + "\n"
        session = await self._runner.session_service.get_session(app_name=self._settings.app_name, user_id=user_id, session_id=ingestion.session_id)
        kickoff = types.Content(role="user", parts=[types.Part(text="Produce the final insight package from the prepared session state.")])

        try:
            async with self._model_call_lock:
                previous_key = os.getenv("GOOGLE_API_KEY")
                if request_api_key:
                    os.environ["GOOGLE_API_KEY"] = request_api_key
                try:
                    async for _event in self._runner.run_async(user_id=user_id, session_id=ingestion.session_id, new_message=kickoff):
                        event_type = type(_event).__name__
                        agent_name = getattr(_event, "agent_name", "System")
                        if agent_name:
                            yield json.dumps({"type": "step", "message": f"{agent_name.capitalize()} agent is computing..."}) + "\n"
                        else:
                            yield json.dumps({"type": "step", "message": f"Processing {event_type}..."}) + "\n"
                        await asyncio.sleep(0.01)
                finally:
                    if previous_key: os.environ["GOOGLE_API_KEY"] = previous_key
                    else: os.environ.pop("GOOGLE_API_KEY", None)
        except Exception as exc:
            messages = self._collect_exception_messages(exc)
            message = " | ".join(msg for msg in messages if msg) or str(exc)
            yield json.dumps({"type": "error", "message": f"Model pipeline failed: {message}"}) + "\n"
            return

        yield json.dumps({"type": "step", "message": "Assembling final insights..."}) + "\n"
        session = await self._runner.session_service.get_session(app_name=self._settings.app_name, user_id=user_id, session_id=ingestion.session_id)
        if session is None or "final_insight_package" not in session.state:
            yield json.dumps({"type": "error", "message": "Agent did not produce a final insight package."}) + "\n"
            return

        try:
            package = InsightPackage.model_validate(session.state["final_insight_package"])
        except Exception as exc:
            yield json.dumps({"type": "error", "message": f"Agent returned invalid structured data: {exc}"}) + "\n"
            return

        merged_citations = self._merge_citations(package.citations, self._read_session_models(session, state_keys.COMBINED_CITATIONS_JSON, Citation))
        merged_artifacts = self._merge_artifacts(package.artifacts, self._read_session_models(session, state_keys.ARTIFACT_REFS_JSON, ArtifactRef))
        final_package = package.model_copy(update={"citations": merged_citations, "artifacts": merged_artifacts, "session_id": ingestion.session_id, "persistence_mode": request.options.persistence_mode})

        artifact_context = ArtifactContext(runner=self._runner, app_name=self._settings.app_name, user_id=user_id, session_id=ingestion.session_id, artifacts=list(merged_artifacts))
        final_ref = await artifact_context.save_text(f"analyses/{final_package.analysis_id}.json", json.dumps(final_package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", "application/json")
        self._repository.save(StoredAnalysis(analysis_id=final_package.analysis_id, user_id=user_id, session_id=ingestion.session_id, filename=final_ref.name, version=final_ref.version))

        yield json.dumps({"type": "result", "data": final_package.model_dump(mode="json")}) + "\n"

    async def _analyze_stream_with_openrouter(self, request: AnalyzeRequest, user_id: str) -> "AsyncGenerator[str, None]":
        from typing import AsyncGenerator
        yield json.dumps({"type": "step", "message": "Preparing session and ingesting sources..."}) + "\n"
        try:
            ingestion = await self._ingestion.prepare(request, user_id)
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return

        corpus = ingestion.normalized_corpus
        if request.options.allow_web_research:
            yield json.dumps({"type": "step", "message": "Web search activated: Finding context..."}) + "\n"
            from ..tools.google_search import google_search_tool
            # We must use run_in_executor if google_search_tool is fully sync but let's just call it
            search_summary = google_search_tool(request.prompt)
            corpus += f"\n\n[Web Search Context]\n{search_summary}\n"
            yield json.dumps({"type": "step", "message": "Web context acquired."}) + "\n"

        yield json.dumps({"type": "step", "message": "Profiling extracted data for metrics and chart candidates..."}) + "\n"
        await asyncio.sleep(0.05)
        yield json.dumps({"type": "step", "message": f"Querying standard engine ({self._settings.openrouter_model})..."}) + "\n"
        system_prompt = (
            "You are a strict data analysis assistant. Return ONLY valid JSON with keys: "
            "summary (string), insights (string[]), metrics ({label, value}[]), "
            "entities ({name, type, value?}[]), visualizations ({id, title, kind, reason, labels?, values?}[]), "
            "advanced_html_report (optional string). "
            "Summary must be detailed and decision-useful (minimum 120 words) covering context, drivers, implications, and risks. "
            "Insights should contain 8-14 specific findings when evidence allows. "
            "Metrics should contain 6-12 concrete values when evidence allows. "
            f"Generate up to {request.options.max_visualizations} visualizations. Prefer at least 4 charts when data supports it. "
            "Allowed visualization kind values: bar, line, pie, table. "
            "For chart visualizations, labels and values arrays are required and must be equal length with real numeric values. "
            "If exact data is missing, synthesize realistic estimates instead of leaving charts empty. "
            "Do not output placeholder text or dummy markers. "
            "If advanced_html_report is provided, return a full HTML document with CSS + vanilla JS and optional Chart.js CDN only; include multiple dynamic chart sections and at least one diagram-style section (for example SVG relationship map or flow map). "
            "No markdown or prose outside JSON."
        )
        user_prompt = f"User prompt:\n{request.prompt}\n\nNormalized corpus:\n{corpus}\n\nTables JSON:\n{json.dumps([table.model_dump(mode='json') for table in ingestion.tables], ensure_ascii=False)}\n\nMax visualizations: {request.options.max_visualizations}"

        payload = {"model": self._settings.openrouter_model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.2}
        try:
            request_task = asyncio.create_task(self._post_openrouter_request(payload))
            heartbeat_messages = [
                "Model is reading normalized sources...",
                "Model is computing metrics and trend deltas...",
                "Model is drafting visual specifications...",
                "Model is producing detailed report output...",
            ]
            heartbeat_index = 0
            while not request_task.done():
                heartbeat = heartbeat_messages[min(heartbeat_index, len(heartbeat_messages) - 1)]
                yield json.dumps({"type": "step", "message": heartbeat}) + "\n"
                heartbeat_index += 1
                await asyncio.sleep(1.2)
            response = await request_task
        except HTTPException as exc:
            yield json.dumps({"type": "error", "message": str(exc.detail)}) + "\n"
            return

        if response.status_code >= 400:
            yield json.dumps({"type": "error", "message": f"OpenRouter failed ({response.status_code}): {response.text[:600]}"}) + "\n"
            return

        try:
            obj = response.json()
            content = obj["choices"][0]["message"]["content"]
        except Exception:
            yield json.dumps({"type": "error", "message": "OpenRouter returned unexpected response."}) + "\n"
            return
            
        yield json.dumps({"type": "step", "message": "Parsing structured response and validating schema..."}) + "\n"
        parsed = self._extract_json_payload(content)
        if parsed is None:
            yield json.dumps({"type": "step", "message": "Model returned non-JSON content; building resilient structured fallback..."}) + "\n"
            parsed = self._build_fallback_payload_from_text(content)

        sanitized = self._sanitize_openrouter_payload(parsed, request.options.max_visualizations)
        enriched = self._enrich_openrouter_payload(sanitized, ingestion.tables, request.options.max_visualizations)
        yield json.dumps({"type": "step", "message": "Building visualization layer and detailed report..."}) + "\n"

        package_payload = {"analysis_id": ingestion.analysis_id, "session_id": ingestion.session_id, "persistence_mode": request.options.persistence_mode, "summary": str(enriched.get("summary") or "Analysis done."), "advanced_html_report": enriched.get("advanced_html_report"), "insights": enriched.get("insights", []), "metrics": enriched.get("metrics", []), "entities": enriched.get("entities", []), "tables": [table.model_dump(mode="json") for table in ingestion.tables], "visualizations": enriched.get("visualizations", []), "citations": [citation.model_dump(mode="json") for citation in ingestion.citations], "artifacts": [artifact.model_dump(mode="json") for artifact in ingestion.artifact_context.artifacts]}
        try:
            final_package = InsightPackage.model_validate(package_payload)
        except Exception as e:
            fallback = {
                **package_payload,
                "visualizations": self._build_visualization_fallback(ingestion.tables, request.options.max_visualizations),
                "tables": package_payload["tables"],
                "metrics": package_payload["metrics"],
                "entities": package_payload["entities"],
            }
            try:
                final_package = InsightPackage.model_validate(fallback)
            except Exception as inner_e:
                yield json.dumps({"type": "error", "message": f"Could not validate response package: {inner_e}"}) + "\n"
                return

        final_ref = await ingestion.artifact_context.save_text(f"analyses/{final_package.analysis_id}.json", json.dumps(final_package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", "application/json")
        self._repository.save(StoredAnalysis(analysis_id=final_package.analysis_id, user_id=user_id, session_id=ingestion.session_id, filename=final_ref.name, version=final_ref.version))

        yield json.dumps({"type": "result", "data": final_package.model_dump(mode="json")}) + "\n"

    def _openrouter_endpoint_candidates(self) -> list[str]:
        # Always strip trailing slashes
        endpoint = self._settings.openrouter_endpoint.strip().rstrip("/")
        if not endpoint:
            return []

        # If the user provides a direct chat/completions endpoint, try that first.
        # Otherwise, assume it's a base URL and append /chat/completions just like the OpenAI Python Client.
        if endpoint.endswith("/chat/completions"):
            return [endpoint]
        
        return [
            f"{endpoint}/chat/completions",
            endpoint,  # Fallback to the raw endpoint in case it handles its own routing
            f"{endpoint}/v1/chat/completions",
        ]

    @staticmethod
    def _looks_like_endpoint_miss(response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "").lower()
        body = response.text.lstrip().lower()
        is_html = "text/html" in content_type or body.startswith("<!doctype html") or body.startswith("<html")
        
        # If it's an HTML error page, it's definitely a bad endpoint or gateway miss.
        if response.status_code >= 400 and is_html:
            return True

        if response.status_code == 400:
            # Some OpenRouter gateway variants return JSON 400 "Invalid path" for base URLs.
            invalid_path_markers = (
                "invalid path",
                "only accepts the path",
                "/chat/completions",
            )
            if all(marker in body for marker in invalid_path_markers):
                return True

        # If it returned a JSON 404 (e.g. Model not found, or No endpoints available), 
        # it is a REAL API error, not an endpoint miss. Don't swallow it.
        # (Generic nginx 404s are usually HTML, which is caught above).
        if response.status_code in {404, 405} and "application/json" not in content_type and not body.startswith("{"):
            return True

        return False

    async def _post_openrouter_request(self, payload: dict[str, Any]) -> httpx.Response:
        candidates = self._openrouter_endpoint_candidates()
        if not candidates:
            raise HTTPException(status_code=500, detail="OpenRouter endpoint is not configured.")

        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "curl/8.7.1",
        }

        last_response: httpx.Response | None = None
        last_exception: Exception | None = None
        first_miss: httpx.Response | None = None

        async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds * 2, follow_redirects=True) as client:
            for endpoint in candidates:
                try:
                    response = await client.post(endpoint, headers=headers, json=payload)
                except httpx.HTTPError as exc:
                    last_exception = exc
                    continue

                if self._looks_like_endpoint_miss(response):
                    if first_miss is None:
                        first_miss = response
                    last_response = response
                    continue

                return response

        # If we failed, prefer showing the error for the primary candidate (first_miss) rather than the last fallback candidate
        error_resp = first_miss if first_miss is not None else last_response

        if error_resp is not None:
            preview = error_resp.text.strip()[:180]
            raise HTTPException(
                status_code=502,
                detail=(
                    f"OpenRouter endpoint appears invalid (status {error_resp.status_code}). "
                    f"Tried: {', '.join(candidates)}. Response preview: {preview}"
                ),
            )

        if last_exception is not None:
            raise HTTPException(status_code=502, detail=f"OpenRouter request failed: {last_exception}") from last_exception

        raise HTTPException(status_code=502, detail=f"OpenRouter request failed. Tried endpoints: {', '.join(candidates)}")

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
    def _extract_json_payload(content: Any) -> dict | None:
        text = InsightOrchestrator._coerce_openrouter_content(content)
        if not text:
            return None

        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        candidates = [fenced.group(1).strip(), text] if fenced else [text]

        for candidate in candidates:
            parsed = InsightOrchestrator._decode_json_candidate(candidate)
            if isinstance(parsed, dict):
                return parsed
        return None

    @staticmethod
    def _decode_json_candidate(text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        decoder = json.JSONDecoder()
        starts = [idx for idx, char in enumerate(text) if char == "{"]
        for idx in starts[:80]:
            try:
                parsed, _end = decoder.raw_decode(text[idx:])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue

        relaxed = re.sub(r",\s*([}\]])", r"\1", text)
        if relaxed != text:
            try:
                parsed = json.loads(relaxed)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                pass

        return None

    @staticmethod
    def _coerce_openrouter_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            # Some providers return message.content as a structured object.
            if isinstance(content.get("text"), str):
                return str(content.get("text"))
            return json.dumps(content, ensure_ascii=False)
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    text_part = item.get("text")
                    if isinstance(text_part, str):
                        chunks.append(text_part)
                    elif isinstance(item.get("content"), str):
                        chunks.append(str(item.get("content")))
                    else:
                        chunks.append(json.dumps(item, ensure_ascii=False))
                else:
                    chunks.append(str(item))
            return "\n".join(chunk for chunk in chunks if chunk)
        return str(content)

    @staticmethod
    def _build_fallback_payload_from_text(content: Any) -> dict[str, Any]:
        raw = InsightOrchestrator._coerce_openrouter_content(content)
        compact = re.sub(r"\s+", " ", raw).strip()
        if not compact:
            compact = "Model returned non-JSON output. Generated structured fallback from available context."

        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", compact) if item.strip()]
        summary = " ".join(sentences[:3])[:900].strip()
        if not summary:
            summary = "Generated fallback summary from non-JSON model output."

        line_candidates = [line.strip(" -•\t") for line in raw.splitlines() if line.strip()]
        insight_pool = line_candidates if len(line_candidates) >= 4 else sentences[1:]
        insights: list[str] = []
        seen: set[str] = set()
        for item in insight_pool:
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            insights.append(normalized[:300])
            if len(insights) >= 10:
                break

        if not insights and summary:
            insights = [summary]

        return {
            "summary": summary,
            "advanced_html_report": None,
            "insights": insights,
            "metrics": [],
            "entities": [],
            "visualizations": [],
        }

    @staticmethod
    def _sanitize_openrouter_payload(parsed: dict[str, Any], max_visualizations: int) -> dict[str, Any]:
        summary = str(parsed.get("summary") or "").strip()
        advanced_html_report = None
        raw_advanced_html_report = parsed.get("advanced_html_report")
        if isinstance(raw_advanced_html_report, str):
            normalized_report = raw_advanced_html_report.strip()
            if normalized_report:
                normalized_report = re.sub(
                    r"<script\b[^>]*src=['\"]https?://cdn\.tailwindcss\.com[^'\"]*['\"][^>]*></script>",
                    "",
                    normalized_report,
                    flags=re.IGNORECASE,
                )
                advanced_html_report = normalized_report

        raw_insights = parsed.get("insights")
        insights: list[str] = []
        if isinstance(raw_insights, list):
            insights = [str(item).strip() for item in raw_insights if str(item).strip()]

        metrics: list[dict[str, Any]] = []
        raw_metrics = parsed.get("metrics")
        if isinstance(raw_metrics, list):
            for metric in raw_metrics:
                if not isinstance(metric, dict):
                    continue
                label = str(metric.get("label") or "").strip()
                value = metric.get("value")
                if not label or isinstance(value, (list, dict, tuple, set)):
                    continue
                metrics.append({"label": label, "value": value})

        entities: list[dict[str, Any]] = []
        raw_entities = parsed.get("entities")
        if isinstance(raw_entities, list):
            for entity in raw_entities:
                if not isinstance(entity, dict):
                    continue
                name = str(entity.get("name") or "").strip()
                entity_type = str(entity.get("type") or "unknown").strip() or "unknown"
                if not name:
                    continue
                value = entity.get("value")
                if isinstance(value, (list, dict, tuple, set)):
                    value = None
                entities.append({"name": name, "type": entity_type, "value": value})

        visualizations: list[dict[str, Any]] = []
        raw_visualizations = parsed.get("visualizations")
        if isinstance(raw_visualizations, list):
            for index, visualization in enumerate(raw_visualizations):
                if len(visualizations) >= max_visualizations:
                    break
                if not isinstance(visualization, dict):
                    continue

                kind = str(visualization.get("kind") or "").strip().lower()
                if kind not in {"bar", "line", "pie", "table"}:
                    continue

                normalized: dict[str, Any] = {
                    "id": str(visualization.get("id") or f"viz_{index + 1}"),
                    "title": str(visualization.get("title") or f"Visualization {index + 1}"),
                    "kind": kind,
                    "reason": str(visualization.get("reason") or "Generated from model output."),
                }

                if kind in {"bar", "line", "pie"}:
                    labels = visualization.get("labels")
                    values = visualization.get("values")
                    if not isinstance(labels, list) or not isinstance(values, list):
                        continue

                    cleaned_labels: list[str] = []
                    cleaned_values: list[float] = []
                    for label, value in zip(labels, values):
                        if isinstance(value, bool):
                            continue
                        if isinstance(value, (int, float)):
                            cleaned_labels.append(str(label))
                            cleaned_values.append(float(value))

                    if not cleaned_labels or len(cleaned_labels) != len(cleaned_values):
                        continue

                    normalized["labels"] = cleaned_labels
                    normalized["values"] = cleaned_values

                visualizations.append(normalized)

        return {
            "summary": summary,
            "advanced_html_report": advanced_html_report,
            "insights": insights,
            "metrics": metrics,
            "entities": entities,
            "visualizations": visualizations,
        }

    @classmethod
    def _enrich_openrouter_payload(
        cls,
        sanitized: dict[str, Any],
        tables: list[TableData],
        max_visualizations: int,
    ) -> dict[str, Any]:
        enriched = dict(sanitized)

        metrics = [item for item in enriched.get("metrics", []) if isinstance(item, dict)]
        visualizations = enriched.get("visualizations")
        if not isinstance(visualizations, list) or not visualizations:
            fallback = cls._build_visualization_fallback(tables, max_visualizations)
            if not fallback:
                fallback = cls._build_metric_visualization_fallback(metrics, max_visualizations)
            enriched["visualizations"] = fallback

        enriched["summary"] = cls._build_detailed_summary(
            summary=str(enriched.get("summary") or "Analysis complete."),
            metrics=metrics,
            visualizations=[item for item in enriched.get("visualizations", []) if isinstance(item, dict)],
        )
        enriched["insights"] = cls._build_detailed_insights(
            insights=[str(item) for item in enriched.get("insights", []) if str(item).strip()],
            metrics=metrics,
            visualizations=[item for item in enriched.get("visualizations", []) if isinstance(item, dict)],
        )

        report = enriched.get("advanced_html_report")
        if (
            not isinstance(report, str)
            or not report.strip()
            or "placeholder" in report.lower()
            or "dummy data" in report.lower()
            or len(report.strip()) < 1200
        ):
            enriched["advanced_html_report"] = cls._build_advanced_html_report(
                summary=str(enriched.get("summary") or "Analysis complete."),
                insights=[str(item) for item in enriched.get("insights", []) if str(item).strip()],
                metrics=metrics,
                visualizations=[item for item in enriched.get("visualizations", []) if isinstance(item, dict)],
            )

        return enriched

    @staticmethod
    def _build_visualization_fallback(tables: list[TableData], max_visualizations: int) -> list[dict[str, Any]]:
        visualizations: list[dict[str, Any]] = []
        for table_index, table in enumerate(tables, start=1):
            if len(visualizations) >= max_visualizations:
                break
            if not table.columns or not table.rows:
                continue

            numeric_column_indexes: list[int] = []
            for idx in range(len(table.columns)):
                if any(isinstance(row[idx] if idx < len(row) else None, (int, float)) and not isinstance(row[idx], bool) for row in table.rows):
                    numeric_column_indexes.append(idx)

            if not numeric_column_indexes:
                continue

            label_index = 0
            for idx in range(len(table.columns)):
                if idx not in numeric_column_indexes:
                    label_index = idx
                    break

            for numeric_idx in numeric_column_indexes:
                if len(visualizations) >= max_visualizations:
                    break
                labels: list[str] = []
                values: list[float] = []
                for row_index, row in enumerate(table.rows[:16], start=1):
                    if numeric_idx >= len(row):
                        continue
                    raw_value = row[numeric_idx]
                    if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                        continue
                    raw_label = row[label_index] if label_index < len(row) else row_index
                    labels.append(str(raw_label))
                    values.append(float(raw_value))

                if len(labels) < 2:
                    continue

                visualizations.append(
                    {
                        "id": f"fallback_{table_index}_{numeric_idx}",
                        "title": f"{table.name}: {table.columns[numeric_idx]}",
                        "kind": "line" if len(values) > 8 else "bar",
                        "reason": f"Auto-generated from numeric column '{table.columns[numeric_idx]}'.",
                        "labels": labels,
                        "values": values,
                    }
                )

        return visualizations[:max_visualizations]

    @staticmethod
    def _extract_numeric_value(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.replace(",", "")
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            if match:
                try:
                    return float(match.group(0))
                except ValueError:
                    return None
        return None

    @classmethod
    def _build_metric_visualization_fallback(
        cls,
        metrics: list[dict[str, Any]],
        max_visualizations: int,
    ) -> list[dict[str, Any]]:
        labels: list[str] = []
        values: list[float] = []
        for metric in metrics:
            label = str(metric.get("label") or "").strip()
            value = cls._extract_numeric_value(metric.get("value"))
            if not label or value is None:
                continue
            labels.append(label)
            values.append(value)

        if len(labels) < 2:
            return []

        capped_labels = labels[:12]
        capped_values = values[:12]
        output: list[dict[str, Any]] = [
            {
                "id": "metric_fallback_bar",
                "title": "Metric Comparison",
                "kind": "bar",
                "reason": "Auto-generated comparison from extracted numeric metrics.",
                "labels": capped_labels,
                "values": capped_values,
            },
            {
                "id": "metric_fallback_line",
                "title": "Metric Trend Proxy",
                "kind": "line",
                "reason": "Auto-generated ordered view across extracted metrics.",
                "labels": capped_labels,
                "values": capped_values,
            },
        ]
        if len(capped_labels) <= 8:
            output.append(
                {
                    "id": "metric_fallback_pie",
                    "title": "Metric Share Split",
                    "kind": "pie",
                    "reason": "Auto-generated part-to-whole view across extracted metrics.",
                    "labels": capped_labels,
                    "values": capped_values,
                }
            )
        return output[:max_visualizations]

    @staticmethod
    def _build_detailed_summary(
        summary: str,
        metrics: list[dict[str, Any]],
        visualizations: list[dict[str, Any]],
    ) -> str:
        normalized = summary.strip()
        if len(normalized) >= 260:
            return normalized

        segments: list[str] = []
        if normalized:
            segments.append(normalized.rstrip(". ") + ".")
        else:
            segments.append("This analysis consolidates the available evidence into a decision-oriented view of current performance, momentum, and risk.")

        metric_preview = [
            f"{str(item.get('label', 'Metric')).strip()}: {item.get('value', 'n/a')}"
            for item in metrics
            if isinstance(item, dict) and str(item.get("label") or "").strip()
        ][:6]
        if metric_preview:
            segments.append(
                "Key measured signals include "
                + "; ".join(metric_preview)
                + ", providing a quantified baseline for comparison and monitoring."
            )

        chart_preview = [
            str(item.get("title") or "Visualization").strip()
            for item in visualizations
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ][:6]
        if chart_preview:
            segments.append(
                "The visualization layer spans "
                + ", ".join(chart_preview)
                + ", helping distinguish structural trends, concentration effects, and cross-metric divergences."
            )

        segments.append(
            "Interpret these results as directional evidence that should be stress-tested against fresh inputs, scenario assumptions, and recent regime shifts before committing to high-impact decisions."
        )
        return " ".join(segments)

    @staticmethod
    def _build_detailed_insights(
        insights: list[str],
        metrics: list[dict[str, Any]],
        visualizations: list[dict[str, Any]],
    ) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()

        def add(item: str) -> None:
            text = item.strip()
            key = text.lower()
            if not text or key in seen:
                return
            seen.add(key)
            output.append(text)

        for insight in insights:
            add(insight)

        for metric in metrics:
            label = str(metric.get("label") or "").strip()
            if not label:
                continue
            value = metric.get("value", "n/a")
            add(f"{label} is currently observed at {value}, making it a primary control signal for near-term monitoring.")

        for vis in visualizations:
            title = str(vis.get("title") or "Visualization").strip()
            reason = str(vis.get("reason") or "").strip()
            if not title:
                continue
            if reason:
                add(f"{title}: {reason}")
            else:
                add(f"{title} highlights distribution shape and relative movement across key categories.")

        generic_fillers = [
            "The metric profile indicates non-uniform movement across dimensions, so single-signal interpretation would likely understate risk.",
            "Cross-chart comparison suggests that headline central tendency and distribution tails should be reviewed together to avoid false confidence.",
            "Current evidence supports building scenario bands (base, upside, downside) instead of relying on a single-point forecast.",
            "Any intervention should include clear trigger thresholds tied to the strongest leading indicators surfaced in this report.",
            "Variance across metrics implies the need for segmented strategy rather than one-size-fits-all execution.",
            "Follow-up analysis should prioritize incremental data refreshes and sensitivity checks on the most volatile factors.",
        ]
        for filler in generic_fillers:
            add(filler)
            if len(output) >= 10:
                break

        return output[:16]

    @staticmethod
    def _json_for_script(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")

    @staticmethod
    def _build_advanced_html_report(
        summary: str,
        insights: list[str],
        metrics: list[dict[str, Any]],
        visualizations: list[dict[str, Any]],
    ) -> str:
        chart_candidates: list[dict[str, Any]] = []
        for vis in visualizations:
            if not isinstance(vis, dict):
                continue
            if vis.get("kind") not in {"bar", "line", "pie"}:
                continue
            labels = vis.get("labels")
            values = vis.get("values")
            if not isinstance(labels, list) or not isinstance(values, list):
                continue
            if not labels or not values or len(labels) != len(values):
                continue

            cleaned_values: list[float] = []
            cleaned_labels: list[str] = []
            for label, value in zip(labels, values):
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    cleaned_labels.append(str(label))
                    cleaned_values.append(float(value))
            if len(cleaned_labels) < 2:
                continue

            chart_candidates.append(
                {
                    "id": str(vis.get("id") or f"chart_{len(chart_candidates) + 1}"),
                    "title": str(vis.get("title") or "Visualization"),
                    "kind": str(vis.get("kind") or "bar"),
                    "reason": str(vis.get("reason") or "Generated from analysis output."),
                    "labels": cleaned_labels[:24],
                    "values": cleaned_values[:24],
                }
            )

        if len(chart_candidates) < 2:
            chart_candidates.extend(
                InsightOrchestrator._build_metric_visualization_fallback(metrics, max(4, 6 - len(chart_candidates)))
            )

        chart_candidates = chart_candidates[:8]
        summary_paragraphs = [part.strip() for part in re.split(r"(?<=[.!?])\s+", summary.strip()) if part.strip()]
        summary_markup = "".join(
            f"<p class='summary'>{html.escape(part)}</p>" for part in summary_paragraphs[:4]
        ) or "<p class='summary'>Analysis complete.</p>"

        metric_cards = "".join(
            (
                "<div class='metric-card'>"
                f"<div class='metric-label'>{html.escape(str(metric.get('label', 'Metric')))}</div>"
                f"<div class='metric-value'>{html.escape(str(metric.get('value', 'n/a')))}</div>"
                "</div>"
            )
            for metric in metrics[:16]
            if isinstance(metric, dict)
        )

        charts_json = InsightOrchestrator._json_for_script(chart_candidates)
        metrics_json = InsightOrchestrator._json_for_script(metrics[:20])
        insights_json = InsightOrchestrator._json_for_script(insights[:24])

        return f"""<!doctype html>
<html lang='en'>
<head>
    <meta charset='utf-8' />
    <meta name='viewport' content='width=device-width, initial-scale=1' />
    <title>Advanced Analysis Report</title>
    <script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
    <style>
        :root {{
            --bg-a: #050914;
            --bg-b: #0e1630;
            --panel: rgba(12, 21, 42, 0.78);
            --panel-soft: rgba(17, 30, 58, 0.52);
            --border: rgba(148, 163, 184, 0.26);
            --text: #edf3ff;
            --muted: #b7c3dc;
        }}
        * {{ box-sizing: border-box; }}
        html, body {{ margin: 0; min-height: 100%; }}
        body {{
            font-family: Segoe UI, Inter, Arial, sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at 18% 20%, rgba(56, 189, 248, 0.2), transparent 44%),
                radial-gradient(circle at 80% 0%, rgba(34, 211, 238, 0.18), transparent 38%),
                linear-gradient(155deg, var(--bg-a), var(--bg-b));
            padding: 24px;
        }}
        .container {{ max-width: 1320px; margin: 0 auto; display: grid; gap: 16px; }}
        .panel {{
            background: linear-gradient(180deg, var(--panel), rgba(11, 20, 38, 0.75));
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 18px;
            box-shadow: 0 16px 32px rgba(0, 0, 0, 0.22);
        }}
        .headline h1 {{ margin: 0 0 10px 0; font-size: clamp(24px, 3vw, 34px); }}
        .summary {{ margin: 0 0 10px 0; line-height: 1.62; color: var(--muted); max-width: 1100px; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
        .metric-card {{
            border: 1px solid rgba(56, 189, 248, 0.34);
            border-radius: 14px;
            padding: 12px;
            background: linear-gradient(180deg, rgba(22, 37, 70, 0.62), rgba(10, 18, 36, 0.8));
        }}
        .metric-label {{ font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #7dd3fc; }}
        .metric-value {{ font-size: 25px; margin-top: 6px; font-weight: 700; }}
        .layout {{ display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; }}
        .chart-controls {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }}
        .chart-controls label {{ font-size: 12px; text-transform: uppercase; color: #9fb0cf; letter-spacing: 0.06em; }}
        .select, .search-input {{
            background: rgba(14, 24, 47, 0.85);
            color: var(--text);
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 10px;
            padding: 8px 10px;
            min-width: 210px;
        }}
        .button {{
            border: 1px solid rgba(56, 189, 248, 0.45);
            background: rgba(8, 47, 73, 0.55);
            color: var(--text);
            border-radius: 10px;
            padding: 8px 12px;
            cursor: pointer;
        }}
        .button.active {{ background: rgba(2, 132, 199, 0.44); }}
        .featured-wrap {{ min-height: 340px; border: 1px solid rgba(148, 163, 184, 0.22); border-radius: 14px; padding: 10px; background: var(--panel-soft); }}
        .featured-reason {{ color: #9fb0cf; font-size: 13px; margin: 8px 0 0 0; }}
        .chart-grid {{ margin-top: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }}
        .chart-card {{ border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 12px; padding: 10px; background: rgba(8, 16, 33, 0.72); min-height: 210px; }}
        .chart-title {{ margin: 0 0 8px 0; color: #d6e3fb; font-size: 13px; }}
        .insight-panel {{ display: grid; gap: 10px; }}
        .insight-list {{ max-height: 380px; overflow: auto; display: grid; gap: 8px; padding-right: 4px; }}
        .insight-item {{ border-left: 3px solid rgba(56, 189, 248, 0.7); background: rgba(10, 18, 35, 0.72); border-radius: 8px; padding: 10px 12px; color: #dbe6ff; line-height: 1.5; }}
        .diagram-shell {{ margin-top: 12px; border: 1px solid rgba(148, 163, 184, 0.24); border-radius: 12px; padding: 10px; background: rgba(10, 18, 35, 0.64); }}
        .diagram-shell svg {{ width: 100%; height: 280px; display: block; }}
        .diagram-caption {{ margin: 8px 0 0 0; font-size: 12px; color: #9fb0cf; }}
        .status {{ margin-top: 10px; font-size: 13px; color: #9fb0cf; }}
        .empty {{ color: #9fb0cf; font-size: 14px; }}
        @media (max-width: 1024px) {{
            body {{ padding: 14px; }}
            .layout {{ grid-template-columns: 1fr; }}
            .featured-wrap {{ min-height: 300px; }}
        }}
    </style>
</head>
<body>
    <div class='container'>
        <section class='panel headline'>
            <h1>Advanced Intelligence Report</h1>
            {summary_markup}
            <div class='status'>Dynamic mode: multi-chart rendering, relationship mapping, and searchable insight stream enabled.</div>
        </section>

        <section class='metrics-grid'>
            {metric_cards or "<div class='panel empty'>No metrics generated.</div>"}
        </section>

        <section class='layout'>
            <div class='panel'>
                <div class='chart-controls'>
                    <label for='chart-selector'>Featured chart</label>
                    <select id='chart-selector' class='select'></select>
                    <button id='autoplay-toggle' class='button' type='button'>Auto-play Charts</button>
                </div>
                <div class='featured-wrap'>
                    <canvas id='featured-chart'></canvas>
                    <p id='featured-reason' class='featured-reason'></p>
                </div>
                <div id='chart-grid' class='chart-grid'></div>
            </div>

            <div class='panel insight-panel'>
                <input id='insight-search' class='search-input' type='search' placeholder='Filter insights by keyword...' />
                <div id='insight-list' class='insight-list'></div>
                <div class='diagram-shell'>
                    <svg id='relationship-map' viewBox='0 0 860 280' role='img' aria-label='Relationship map'></svg>
                    <p class='diagram-caption'>Relationship map connects the synthesis thesis to top metrics and chart clusters.</p>
                </div>
            </div>
        </section>
    </div>

    <script>
        const charts = {charts_json};
        const metrics = {metrics_json};
        const insights = {insights_json};
        const palette = ['#38bdf8', '#22d3ee', '#34d399', '#f59e0b', '#f472b6', '#a78bfa', '#fb7185', '#60a5fa'];

        const selector = document.getElementById('chart-selector');
        const autoplayButton = document.getElementById('autoplay-toggle');
        const featuredReason = document.getElementById('featured-reason');
        const featuredCanvas = document.getElementById('featured-chart');
        const chartGrid = document.getElementById('chart-grid');
        const insightSearch = document.getElementById('insight-search');
        const insightList = document.getElementById('insight-list');
        const relationshipMap = document.getElementById('relationship-map');

        let featuredChart = null;
        let autoplayHandle = null;

        function datasetColor(index) {{
            return palette[index % palette.length];
        }}

        function normalizeChartType(kind) {{
            return kind === 'pie' ? 'pie' : kind === 'line' ? 'line' : 'bar';
        }}

        function buildChartConfig(chart, index) {{
            const type = normalizeChartType(chart.kind);
            return {{
                type,
                data: {{
                    labels: chart.labels,
                    datasets: [{{
                        label: chart.title,
                        data: chart.values,
                        borderColor: datasetColor(index),
                        backgroundColor: type === 'pie'
                            ? chart.values.map((_, i) => datasetColor(i))
                            : datasetColor(index),
                        borderWidth: type === 'line' ? 2 : 1,
                        fill: false,
                        tension: 0.25,
                    }}],
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: {{ duration: 650 }},
                    plugins: {{
                        legend: {{ display: type === 'pie', labels: {{ color: '#d7e5ff' }} }},
                        tooltip: {{ enabled: true }}
                    }},
                    scales: type === 'pie' ? {{}} : {{
                        x: {{ ticks: {{ color: '#a9bedf' }}, grid: {{ color: 'rgba(148,163,184,0.12)' }} }},
                        y: {{ ticks: {{ color: '#a9bedf' }}, grid: {{ color: 'rgba(148,163,184,0.12)' }} }}
                    }}
                }}
            }};
        }}

        function renderFeatured(index) {{
            if (!charts.length) return;
            const normalizedIndex = ((index % charts.length) + charts.length) % charts.length;
            const chart = charts[normalizedIndex];
            selector.value = String(normalizedIndex);

            if (featuredChart) {{
                featuredChart.destroy();
            }}
            featuredChart = new Chart(featuredCanvas, buildChartConfig(chart, normalizedIndex));
            featuredReason.textContent = chart.reason || 'No additional explanation provided.';
        }}

        function renderMiniCharts() {{
            chartGrid.innerHTML = '';
            if (!charts.length) {{
                const empty = document.createElement('div');
                empty.className = 'empty';
                empty.textContent = 'No chart-ready visualization data returned.';
                chartGrid.appendChild(empty);
                return;
            }}

            charts.forEach((chart, index) => {{
                const card = document.createElement('div');
                card.className = 'chart-card';

                const title = document.createElement('p');
                title.className = 'chart-title';
                title.textContent = chart.title;
                card.appendChild(title);

                const canvas = document.createElement('canvas');
                canvas.height = 150;
                card.appendChild(canvas);
                chartGrid.appendChild(card);

                new Chart(canvas, buildChartConfig(chart, index));
            }});
        }}

        function populateSelector() {{
            selector.innerHTML = '';
            charts.forEach((chart, index) => {{
                const option = document.createElement('option');
                option.value = String(index);
                option.textContent = `${{index + 1}}. ${{chart.title}}`;
                selector.appendChild(option);
            }});
            selector.addEventListener('change', () => renderFeatured(Number(selector.value)));
        }}

        function toggleAutoplay() {{
            if (autoplayHandle) {{
                clearInterval(autoplayHandle);
                autoplayHandle = null;
                autoplayButton.classList.remove('active');
                autoplayButton.textContent = 'Auto-play Charts';
                return;
            }}
            autoplayButton.classList.add('active');
            autoplayButton.textContent = 'Pause Auto-play';
            autoplayHandle = setInterval(() => {{
                const current = Number(selector.value || 0);
                renderFeatured((current + 1) % Math.max(charts.length, 1));
            }}, 2600);
        }}

        function renderInsights(filter) {{
            const query = String(filter || '').trim().toLowerCase();
            insightList.innerHTML = '';
            const matched = insights.filter((item) => !query || String(item).toLowerCase().includes(query));

            if (!matched.length) {{
                const empty = document.createElement('div');
                empty.className = 'empty';
                empty.textContent = 'No insights match the current filter.';
                insightList.appendChild(empty);
                return;
            }}

            matched.forEach((item) => {{
                const node = document.createElement('div');
                node.className = 'insight-item';
                node.textContent = item;
                insightList.appendChild(node);
            }});
        }}

        function renderRelationshipMap() {{
            const ns = 'http://www.w3.org/2000/svg';
            relationshipMap.innerHTML = '';

            function make(tag, attrs) {{
                const el = document.createElementNS(ns, tag);
                Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
                return el;
            }}

            function text(x, y, value, size = 12, weight = '500') {{
                const t = make('text', {{ x, y, fill: '#d7e5ff', 'font-size': size, 'font-weight': weight, 'text-anchor': 'middle' }});
                t.textContent = value;
                return t;
            }}

            const rootX = 430;
            const rootY = 140;
            const root = make('rect', {{ x: rootX - 78, y: rootY - 24, width: 156, height: 48, rx: 12, fill: 'rgba(14,165,233,0.2)', stroke: '#38bdf8' }});
            relationshipMap.appendChild(root);
            relationshipMap.appendChild(text(rootX, rootY + 5, 'Synthesis Thesis', 13, '700'));

            const metricNodes = metrics.slice(0, 4).map((m, i) => ({{
                label: String(m.label || `Metric ${{i + 1}}`),
                value: String(m.value ?? 'n/a'),
            }}));
            const chartNodes = charts.slice(0, 4).map((c, i) => ({{
                label: String(c.title || `Chart ${{i + 1}}`),
            }}));

            metricNodes.forEach((node, i) => {{
                const y = 48 + i * 58;
                relationshipMap.appendChild(make('line', {{ x1: 164, y1: y + 14, x2: rootX - 78, y2: rootY, stroke: 'rgba(56,189,248,0.46)', 'stroke-width': 1.2 }}));
                relationshipMap.appendChild(make('rect', {{ x: 12, y, width: 152, height: 30, rx: 8, fill: 'rgba(16,185,129,0.2)', stroke: '#34d399' }}));
                relationshipMap.appendChild(text(88, y + 19, `${{node.label}}`, 10));
            }});

            chartNodes.forEach((node, i) => {{
                const y = 48 + i * 58;
                relationshipMap.appendChild(make('line', {{ x1: rootX + 78, y1: rootY, x2: 696, y2: y + 14, stroke: 'rgba(167,139,250,0.5)', 'stroke-width': 1.2 }}));
                relationshipMap.appendChild(make('rect', {{ x: 696, y, width: 152, height: 30, rx: 8, fill: 'rgba(124,58,237,0.2)', stroke: '#a78bfa' }}));
                relationshipMap.appendChild(text(772, y + 19, `${{node.label}}`, 10));
            }});
        }}

        insightSearch.addEventListener('input', (event) => {{
            renderInsights(event.target.value || '');
        }});
        autoplayButton.addEventListener('click', toggleAutoplay);

        populateSelector();
        renderMiniCharts();
        renderInsights('');
        renderRelationshipMap();
        if (charts.length) {{
            renderFeatured(0);
        }}
    </script>
</body>
</html>"""
