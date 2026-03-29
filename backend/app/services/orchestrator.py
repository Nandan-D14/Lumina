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

        if self._settings.has_kilo_code_auth():
            return await self._analyze_with_kilo_code(request, user_id)

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

    async def _analyze_with_kilo_code(self, request: AnalyzeRequest, user_id: str) -> InsightPackage:
        ingestion = await self._ingestion.prepare(request, user_id)

        system_prompt = (
            "You are a strict data analysis assistant. Return ONLY valid JSON with keys: "
            "summary (string), insights (string[]), metrics ({label, value}[]), "
            "entities ({name, type, value?}[]), visualizations ({id, title, kind, reason, labels?, values?}[]), "
            "advanced_html_report (optional string: write highly advanced, interactive HTML/JS/CSS detailing the analysis. Use Tailwind CDN and Chart.js via CDN to render beautiful dark-mode dashboards). "
            "CRITICAL INSTRUCTION: You MUST generate at least 2 chart visualizations (bar, line, or pie) with realistic, populated data arrays for `labels` and `values` based on the user's prompt. "
            "If you do not have exact data from the context, YOU MUST SYNTHESIZE OR ESTIMATE highly realistic historical or metric data yourself. "
            "NEVER output 'placeholder', 'dummy data', or empty charts. ALWAYS provide actual arrays of numbers and category labels! "
            "Allowed visualization kind values: bar, line, pie, table. No markdown or prose outside JSON."
        )
        user_prompt = (
            f"User prompt:\n{request.prompt}\n\n"
            f"Normalized corpus:\n{ingestion.normalized_corpus}\n\n"
            f"Tables JSON:\n{json.dumps([table.model_dump(mode='json') for table in ingestion.tables], ensure_ascii=False)}\n\n"
            f"Max visualizations: {request.options.max_visualizations}"
        )

        payload = {
            "model": self._settings.kilo_code_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {self._settings.kilo_code_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds * 2) as client:
                response = await client.post(self._settings.kilo_code_endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Kilo Code request failed: {exc}") from exc

        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="Kilo Code quota/rate limit exceeded. Retry shortly or update plan limits.")
        if response.status_code in {401, 403}:
            raise HTTPException(status_code=401, detail="Kilo Code credentials are invalid or unauthorized.")
        if response.status_code >= 400:
            detail = response.text.strip()
            raise HTTPException(status_code=502, detail=f"Kilo Code failed ({response.status_code}): {detail[:600]}")

        try:
            response_json = response.json()
            content = response_json["choices"][0]["message"]["content"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Kilo Code returned an unexpected response shape.") from exc

        parsed = self._extract_json_payload(content)
        if parsed is None:
            raise HTTPException(status_code=502, detail="Kilo Code response did not contain valid JSON.")

        sanitized = self._sanitize_kilo_code_payload(parsed, request.options.max_visualizations)
        enriched = self._enrich_kilo_code_payload(sanitized, ingestion.tables, request.options.max_visualizations)

        package_payload = {
            "analysis_id": ingestion.analysis_id,
            "session_id": ingestion.session_id,
            "persistence_mode": request.options.persistence_mode,
            "summary": str(enriched.get("summary") or "Analysis completed via Kilo Code."),
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
                "summary": str(enriched.get("summary") or "Analysis completed via Kilo Code."),
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

        if self._settings.has_kilo_code_auth():
            async for chunk in self._analyze_stream_with_kilo_code(request, user_id):
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

    async def _analyze_stream_with_kilo_code(self, request: AnalyzeRequest, user_id: str) -> "AsyncGenerator[str, None]":
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
        yield json.dumps({"type": "step", "message": f"Querying standard engine ({self._settings.kilo_code_model})..."}) + "\n"
        system_prompt = ("You are a strict data analysis assistant. Return ONLY valid JSON with keys: "
                         "summary (string), insights (string[]), metrics ({label, value}[]), "
                         "entities ({name, type, value?}[]), visualizations ({id, title, kind, reason, labels?, values?}[]), "
                         "advanced_html_report (optional string: write highly advanced, interactive HTML/JS/CSS detailing the analysis. Use Tailwind CDN and Chart.js via CDN to render beautiful dark-mode dashboards). "
                 "CRITICAL INSTRUCTION: You MUST generate at least 2 chart visualizations (bar, line, or pie) with realistic, populated data arrays for `labels` and `values` based on the user's prompt. "
                 "If you do not have exact data from the context, YOU MUST SYNTHESIZE OR ESTIMATE highly realistic historical or metric data yourself. "
                 "NEVER output 'placeholder', 'dummy data', or empty charts. ALWAYS provide actual arrays of numbers and category labels! "
                 "Allowed visualization kind values: bar, line, pie, table. No markdown or prose outside JSON.")
        user_prompt = f"User prompt:\n{request.prompt}\n\nNormalized corpus:\n{corpus}\n\nTables JSON:\n{json.dumps([table.model_dump(mode='json') for table in ingestion.tables], ensure_ascii=False)}\n\nMax visualizations: {request.options.max_visualizations}"

        payload = {"model": self._settings.kilo_code_model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.2}
        headers = {"Authorization": f"Bearer {self._settings.kilo_code_api_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds * 2) as client:
                request_task = asyncio.create_task(
                    client.post(self._settings.kilo_code_endpoint, headers=headers, json=payload)
                )
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
        except httpx.HTTPError as exc:
            yield json.dumps({"type": "error", "message": f"Kilo Code request failed: {exc}"}) + "\n"
            return

        if response.status_code >= 400:
            yield json.dumps({"type": "error", "message": f"Kilo Code failed ({response.status_code}): {response.text[:600]}"}) + "\n"
            return

        try:
            obj = response.json()
            content = obj["choices"][0]["message"]["content"]
        except Exception:
            yield json.dumps({"type": "error", "message": "Kilo Code returned unexpected response."}) + "\n"
            return
            
        yield json.dumps({"type": "step", "message": "Parsing structured response and validating schema..."}) + "\n"
        parsed = self._extract_json_payload(content)
        if parsed is None:
            yield json.dumps({"type": "error", "message": "Could not parse Kilo Code response into JSON."}) + "\n"
            return

        sanitized = self._sanitize_kilo_code_payload(parsed, request.options.max_visualizations)
        enriched = self._enrich_kilo_code_payload(sanitized, ingestion.tables, request.options.max_visualizations)
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

    @staticmethod
    def _sanitize_kilo_code_payload(parsed: dict[str, Any], max_visualizations: int) -> dict[str, Any]:
        summary = str(parsed.get("summary") or "").strip()
        advanced_html_report = None
        raw_advanced_html_report = parsed.get("advanced_html_report")
        if isinstance(raw_advanced_html_report, str):
            normalized_report = raw_advanced_html_report.strip()
            if normalized_report:
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
    def _enrich_kilo_code_payload(
        cls,
        sanitized: dict[str, Any],
        tables: list[TableData],
        max_visualizations: int,
    ) -> dict[str, Any]:
        enriched = dict(sanitized)

        visualizations = enriched.get("visualizations")
        if not isinstance(visualizations, list) or not visualizations:
            enriched["visualizations"] = cls._build_visualization_fallback(tables, max_visualizations)

        report = enriched.get("advanced_html_report")
        # Overwrite AI's report if it's empty, or if it hallucinates a placeholder instead of writing actual html
        if not isinstance(report, str) or not report.strip() or "placeholder" in report.lower() or "dummy data" in report.lower():
            enriched["advanced_html_report"] = cls._build_advanced_html_report(
                summary=str(enriched.get("summary") or "Analysis complete."),
                insights=[str(item) for item in enriched.get("insights", []) if str(item).strip()],
                metrics=[item for item in enriched.get("metrics", []) if isinstance(item, dict)],
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
    def _build_advanced_html_report(
        summary: str,
        insights: list[str],
        metrics: list[dict[str, Any]],
        visualizations: list[dict[str, Any]],
    ) -> str:
        safe_summary = html.escape(summary or "Analysis complete.")
        insight_items = "".join(
            f"<li>{html.escape(item)}</li>" for item in insights[:12] if item.strip()
        )
        metric_cards = "".join(
            (
                "<div class='metric-card'>"
                f"<div class='metric-label'>{html.escape(str(metric.get('label', 'Metric')))}</div>"
                f"<div class='metric-value'>{html.escape(str(metric.get('value', 'n/a')))}</div>"
                "</div>"
            )
            for metric in metrics[:12]
            if isinstance(metric, dict)
        )

        chart_candidates: list[dict[str, Any]] = []
        for vis in visualizations:
            if not isinstance(vis, dict):
                continue
            if vis.get("kind") not in {"bar", "line", "pie"}:
                continue
            labels = vis.get("labels")
            values = vis.get("values")
            if isinstance(labels, list) and isinstance(values, list) and labels and values and len(labels) == len(values):
                chart_candidates.append(
                    {
                        "id": str(vis.get("id") or "chart"),
                        "title": str(vis.get("title") or "Visualization"),
                        "kind": str(vis.get("kind") or "bar"),
                        "labels": [str(label) for label in labels],
                        "values": [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)],
                    }
                )

        charts_json = json.dumps(chart_candidates[:4], ensure_ascii=False)

        return f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>Advanced Analysis Report</title>
  <script src='https://cdn.tailwindcss.com'></script>
  <script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
  <style>
    body {{ font-family: Inter, Segoe UI, system-ui, sans-serif; background: #0b1220; color: #e5ecff; }}
    .glass {{ background: rgba(17, 24, 39, 0.7); border: 1px solid rgba(148, 163, 184, 0.2); backdrop-filter: blur(6px); }}
    .metric-card {{ border: 1px solid rgba(96, 165, 250, 0.25); background: rgba(30, 41, 59, 0.7); border-radius: 14px; padding: 14px; }}
    .metric-label {{ color: #93c5fd; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; }}
    .metric-value {{ font-size: 28px; font-weight: 700; margin-top: 6px; color: #f8fafc; }}
  </style>
</head>
<body class='p-6 md:p-8'>
  <div class='max-w-7xl mx-auto space-y-6'>
    <section class='glass rounded-2xl p-6'>
      <h1 class='text-2xl font-bold mb-3'>Detailed Analysis Report</h1>
      <p class='text-slate-200 leading-7'>{safe_summary}</p>
    </section>

    <section class='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3'>
      {metric_cards or "<div class='glass rounded-2xl p-6 text-slate-300'>No metrics generated.</div>"}
    </section>

    <section class='grid grid-cols-1 lg:grid-cols-3 gap-4'>
      <div class='glass rounded-2xl p-6 lg:col-span-1'>
        <h2 class='text-lg font-semibold mb-3'>Key Findings</h2>
        <ul class='space-y-2 list-disc list-inside text-slate-200'>
          {insight_items or "<li>No insights generated.</li>"}
        </ul>
      </div>
      <div class='glass rounded-2xl p-6 lg:col-span-2'>
        <h2 class='text-lg font-semibold mb-3'>Visualization Canvas</h2>
        <div id='chart-grid' class='grid grid-cols-1 md:grid-cols-2 gap-4'></div>
      </div>
    </section>
  </div>

  <script>
    const charts = {charts_json};
    const colors = ['#60a5fa', '#34d399', '#f59e0b', '#f472b6', '#a78bfa', '#fb7185'];
    const grid = document.getElementById('chart-grid');

    if (!charts.length) {{
      grid.innerHTML = "<div class='text-slate-300'>No chart-ready visualization data returned.</div>";
    }} else {{
      charts.forEach((chart, index) => {{
        const card = document.createElement('div');
        card.className = 'rounded-xl border border-slate-700 bg-slate-900/50 p-3';
        card.innerHTML = `<div class='text-sm text-slate-300 mb-2'>${{chart.title}}</div><canvas id='chart-${{index}}' height='180'></canvas>`;
        grid.appendChild(card);

        const ctx = card.querySelector('canvas');
        new Chart(ctx, {{
          type: chart.kind || 'bar',
          data: {{
            labels: chart.labels,
            datasets: [{{
              label: chart.title,
              data: chart.values,
              backgroundColor: chart.kind === 'pie' ? colors : colors[index % colors.length],
              borderColor: '#1f2937',
              borderWidth: 1,
              tension: 0.25,
            }}],
          }},
          options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: chart.kind === 'pie' }} }},
            scales: chart.kind === 'pie' ? {{}} : {{
              x: {{ ticks: {{ color: '#cbd5e1' }}, grid: {{ color: 'rgba(148,163,184,0.1)' }} }},
              y: {{ ticks: {{ color: '#cbd5e1' }}, grid: {{ color: 'rgba(148,163,184,0.1)' }} }},
            }},
          }},
        }});
      }});
    }}
  </script>
</body>
</html>"""
