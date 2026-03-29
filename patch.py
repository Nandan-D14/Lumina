import json

with open('backend/app/services/orchestrator.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_stream_methods = '''
    async def analyze_stream(self, request: AnalyzeRequest) -> "AsyncGenerator[str, None]":
        from typing import AsyncGenerator
        request_api_key = (request.options.gemini_api_key or "").strip() or None
        user_id = (request.options.user_id or self._settings.default_user_id).strip()

        if request.options.persistence_mode == "persistent" and not self._settings.database_url:
            yield json.dumps({"type": "error", "message": "Persistent mode requires DATABASE_URL to be configured on the backend."}) + "\\n"
            return

        if self._settings.has_openrouter_auth():
            async for chunk in self._analyze_stream_with_openrouter(request, user_id):
                yield chunk
            return

        if request_api_key is None:
            yield json.dumps({"type": "error", "message": "Gemini API key is required. Set options.gemini_api_key."}) + "\\n"
            return

        try:
            self.ensure_google_auth(request_api_key)
        except HTTPException as e:
            yield json.dumps({"type": "error", "message": e.detail}) + "\\n"
            return

        yield json.dumps({"type": "step", "message": "Preparing session and ingesting sources..."}) + "\\n"
        try:
            ingestion = await self._ingestion.prepare(request, user_id)
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\\n"
            return

        yield json.dumps({"type": "step", "message": "Evaluating prompt across AI agent graph..."}) + "\\n"
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
                            yield json.dumps({"type": "step", "message": f"{agent_name.capitalize()} agent is computing..."}) + "\\n"
                        else:
                            yield json.dumps({"type": "step", "message": f"Processing {event_type}..."}) + "\\n"
                        await asyncio.sleep(0.01)
                finally:
                    if previous_key: os.environ["GOOGLE_API_KEY"] = previous_key
                    else: os.environ.pop("GOOGLE_API_KEY", None)
        except Exception as exc:
            messages = self._collect_exception_messages(exc)
            message = " | ".join(msg for msg in messages if msg) or str(exc)
            yield json.dumps({"type": "error", "message": f"Model pipeline failed: {message}"}) + "\\n"
            return

        yield json.dumps({"type": "step", "message": "Assembling final insights..."}) + "\\n"
        session = await self._runner.session_service.get_session(app_name=self._settings.app_name, user_id=user_id, session_id=ingestion.session_id)
        if session is None or "final_insight_package" not in session.state:
            yield json.dumps({"type": "error", "message": "Agent did not produce a final insight package."}) + "\\n"
            return

        try:
            package = InsightPackage.model_validate(session.state["final_insight_package"])
        except Exception as exc:
            yield json.dumps({"type": "error", "message": f"Agent returned invalid structured data: {exc}"}) + "\\n"
            return

        merged_citations = self._merge_citations(package.citations, self._read_session_models(session, state_keys.COMBINED_CITATIONS_JSON, Citation))
        merged_artifacts = self._merge_artifacts(package.artifacts, self._read_session_models(session, state_keys.ARTIFACT_REFS_JSON, ArtifactRef))
        final_package = package.model_copy(update={"citations": merged_citations, "artifacts": merged_artifacts, "session_id": ingestion.session_id, "persistence_mode": request.options.persistence_mode})

        artifact_context = ArtifactContext(runner=self._runner, app_name=self._settings.app_name, user_id=user_id, session_id=ingestion.session_id, artifacts=list(merged_artifacts))
        final_ref = await artifact_context.save_text(f"analyses/{final_package.analysis_id}.json", json.dumps(final_package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\\n", "application/json")
        self._repository.save(StoredAnalysis(analysis_id=final_package.analysis_id, user_id=user_id, session_id=ingestion.session_id, filename=final_ref.name, version=final_ref.version))

        yield json.dumps({"type": "result", "data": final_package.model_dump(mode="json")}) + "\\n"

    async def _analyze_stream_with_openrouter(self, request: AnalyzeRequest, user_id: str) -> "AsyncGenerator[str, None]":
        from typing import AsyncGenerator
        yield json.dumps({"type": "step", "message": "Preparing session and ingesting sources..."}) + "\\n"
        try:
            ingestion = await self._ingestion.prepare(request, user_id)
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\\n"
            return

        if request.options.allow_web_research:
            yield json.dumps({"type": "step", "message": "Web search activated: Finding context..."}) + "\\n"
            from ..tools.google_search import google_search_tool
            # We must use run_in_executor if google_search_tool is fully sync but let's just call it
            search_summary = google_search_tool(request.prompt)
            ingestion.normalized_corpus += f"\\n\\n[Web Search Context]\\n{search_summary}\\n"
            yield json.dumps({"type": "step", "message": "Web context acquired."}) + "\\n"

        yield json.dumps({"type": "step", "message": f"Querying standard engine ({self._settings.openrouter_model})..."}) + "\\n"
        system_prompt = ("You are a strict data analysis assistant. Return ONLY valid JSON with keys: "
                         "summary (string), insights (string[]), metrics ({label, value}[]), "
                         "entities ({name, type, value?}[]), visualizations ({id, title, kind, reason, labels?, values?}[]). "
                         "Allowed visualization kind values: bar, line, pie, table. No markdown or prose outside JSON.")
        user_prompt = f"User prompt:\\n{request.prompt}\\n\\nNormalized corpus:\\n{ingestion.normalized_corpus}\\n\\nTables JSON:\\n{json.dumps([table.model_dump(mode='json') for table in ingestion.tables], ensure_ascii=False)}\\n\\nMax visualizations: {request.options.max_visualizations}"

        payload = {"model": self._settings.openrouter_model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.2}
        headers = {"Authorization": f"Bearer {self._settings.openrouter_api_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds * 2) as client:
                response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        except httpx.HTTPError as exc:
            yield json.dumps({"type": "error", "message": f"OpenRouter request failed: {exc}"}) + "\\n"
            return

        if response.status_code >= 400:
            yield json.dumps({"type": "error", "message": f"OpenRouter failed ({response.status_code}): {response.text[:600]}"}) + "\\n"
            return

        try:
            obj = response.json()
            content = obj["choices"][0]["message"]["content"]
        except Exception:
            yield json.dumps({"type": "error", "message": "OpenRouter returned unexpected response."}) + "\\n"
            return
            
        yield json.dumps({"type": "step", "message": "Parsing insights and rendering charts..."}) + "\\n"
        parsed = self._extract_json_payload(content)
        if parsed is None:
            yield json.dumps({"type": "error", "message": "Could not parse OpenRouter response into JSON."}) + "\\n"
            return

        package_payload = {"analysis_id": ingestion.analysis_id, "session_id": ingestion.session_id, "persistence_mode": request.options.persistence_mode, "summary": str(parsed.get("summary") or "Analysis done."), "insights": [str(item) for item in parsed.get("insights", []) if str(item).strip()], "metrics": parsed.get("metrics", []), "entities": parsed.get("entities", []), "tables": [table.model_dump(mode="json") for table in ingestion.tables], "visualizations": parsed.get("visualizations", []), "citations": [citation.model_dump(mode="json") for citation in ingestion.citations], "artifacts": [artifact.model_dump(mode="json") for artifact in ingestion.artifact_context.artifacts]}
        try:
            final_package = InsightPackage.model_validate(package_payload)
        except Exception as e:
            fallback = {"visualizations": [], "tables": [], "metrics": [], **package_payload}
            try:
                final_package = InsightPackage.model_validate(fallback)
            except Exception as inner_e:
                yield json.dumps({"type": "error", "message": f"Could not validate response package: {inner_e}"}) + "\\n"
                return

        final_ref = await ingestion.artifact_context.save_text(f"analyses/{final_package.analysis_id}.json", json.dumps(final_package.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\\n", "application/json")
        self._repository.save(StoredAnalysis(analysis_id=final_package.analysis_id, user_id=user_id, session_id=ingestion.session_id, filename=final_ref.name, version=final_ref.version))

        yield json.dumps({"type": "result", "data": final_package.model_dump(mode="json")}) + "\\n"
'''

content = content.replace('    def artifact_context_for(self, analysis_id: str) -> ArtifactContext:', new_stream_methods + '\n    def artifact_context_for(self, analysis_id: str) -> ArtifactContext:')
with open('backend/app/services/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(content)
