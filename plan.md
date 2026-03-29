# Project Plan

## Vision

Build VibeVisualize as a document-intelligence app that turns messy text into structured insight. Charts remain one output surface, but the product should grow toward summaries, metrics, tabular extraction, entity detection, trends, and report-ready structured sections.

## Current State

- FastAPI backend with `GET /health` and `POST /run`
- Google ADK root agent in `agent.py`
- React + Vite frontend with a single input and chart output surface
- Docker packaging that serves the built frontend from the backend container
- Local setup documentation in `README.md`

## Gap Between Current Repo And Product Direction

- The JSON contract only supports summary plus chart data.
- The frontend renders only charts and a short summary.
- There is no schema versioning, persistence, upload pipeline, or task history.
- The product language in code still leans toward "chart generator" instead of broader insight extraction.

## Execution Phases

### Phase 1: Stabilize The MVP

- Keep backend and frontend setup reliable.
- Keep the ADK integration aligned with the installed library version.
- Preserve a strict JSON contract and clear backend error handling.
- Keep Docker and local dev workflows working.

### Phase 2: Expand The Output Contract

- Introduce a richer response schema that can support:
  - key metrics
  - tabular rows
  - extracted entities
  - trends or notable findings
  - optional chart specifications
- Version the response shape so frontend and backend changes stay coordinated.
- Update the agent prompt to produce richer structured output without breaking parseability.

### Phase 3: Broaden The Frontend

- Add result sections for non-chart outputs.
- Keep charts conditional rather than mandatory.
- Improve loading, error, and empty states around richer structured results.
- Preserve a simple UX: paste text, inspect insights, then drill into visuals or structured sections.

### Phase 4: Add Real Document Intake

- Add file upload support for documents instead of text-only pasting.
- Introduce parsing or extraction layers for PDFs and other document formats if needed.
- Keep the backend contract separate from raw file parsing so the agent receives normalized text and metadata.

### Phase 5: Production Readiness

- Harden Cloud Run deployment.
- Add environment validation and clearer startup checks.
- Add request logging, observability, and basic test coverage for `/health` and `/run`.
- Decide whether to stay single-container or split frontend hosting from backend hosting.

## Immediate Next Tasks

1. Rename product copy across the UI and docs from chart-only language to document-intelligence language.
2. Design the next JSON schema for non-chart outputs.
3. Update the frontend to render structured insight sections beyond charts.
4. Add basic backend tests for response parsing and credential handling.
5. Add an end-to-end happy-path test once real Google credentials are available.

## Success Criteria

- A user can submit messy text and receive structured insight even when no chart is appropriate.
- The backend returns parseable JSON consistently.
- The frontend can render both chart and non-chart outputs without breaking.
- Local development, Docker packaging, and Cloud Run deployment remain straightforward.
