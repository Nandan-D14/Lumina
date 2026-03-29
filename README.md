# Lumina Backend Orchestrator

This project now uses a dedicated `backend/` package for the server and ADK orchestration layer. The backend accepts text, CSV, JSON, PDF, and URL sources, then builds an insight package with summaries, metrics, entities, tables, visualizations, citations, and artifacts.

## Repo Layout

- `backend/`: FastAPI app, schemas, services, ADK agents, orchestration, and tests
- `frontend/`: React client owned by the frontend workflow
- `main.py`: thin compatibility wrapper that exposes `backend.app.main:app`
- `agent.py`: thin compatibility wrapper that exposes the root ADK graph

## Ownership Boundary

This phase keeps backend and infrastructure work inside:

- `backend/`
- `main.py`
- `agent.py`
- `requirements.txt`
- `Dockerfile`
- `.env.example`
- `README.md`

The frontend remains on the existing contract until it migrates from `POST /run` to `POST /api/v1/analyze`.

## Parallel Development Handoff

This repository is currently being developed with a strict two-agent partitioning model.

- Antigravity owns frontend implementation in `frontend/*`.
- Codex owns root-level backend/infrastructure wrappers and docs (`main.py`, `agent.py`, `requirements.txt`, `Dockerfile`, `.env.example`, `README.md`).

When a requested change spans both areas:

1. Codex updates contract/docs in root-owned files first.
2. Antigravity implements frontend wiring for the contract in `frontend/src/*`.
3. If additional backend package changes are needed outside Codex-owned files, request a boundary override before implementation.

## Backend API

- `GET /health`
- `POST /api/v1/analyze`
- `POST /api/v1/export`
- `POST /run` for legacy frontend compatibility

### `POST /api/v1/analyze`

```json
{
  "prompt": "Compare the quarterly revenue and recommend a visualization.",
  "sources": [
    { "type": "text", "text": "Q1 revenue was 45, Q2 was 89, Q3 was 72." }
  ],
  "options": {
    "allow_web_research": false,
    "allow_scraping": true,
    "max_visualizations": 3,
    "persistence_mode": "session",
    "gemini_api_key": "your_gemini_key",
    "user_id": "optional-user-id"
  }
}
```

Notes:

- `options.gemini_api_key` is required for analyze requests.
- `options.persistence_mode` supports `session` and `persistent`.
- `persistent` mode requires backend `DATABASE_URL` to be configured.

Provider selection:

- If `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are configured, backend routes analysis generation through OpenRouter.
- Frontend still sends `options.gemini_api_key` for compatibility, but OpenRouter mode does not require that key to succeed.

### `POST /api/v1/export`

```json
{
  "analysis_id": "your-analysis-id",
  "format": "json"
}
```

### `POST /run`

Legacy compatibility endpoint:

```json
{
  "text": "Q1 revenue was 45, Q2 was 89, Q3 was 72."
}
```

It maps the first chart-compatible visualization from the new insight package back to the old chart response shape.

## Environment

Copy the template:

```powershell
Copy-Item .env.example .env
```

Required for Gemini-backed agent calls:

- `GOOGLE_API_KEY`
  or
- Vertex AI auth variables such as `GOOGLE_GENAI_USE_VERTEXAI` and `GOOGLE_CLOUD_PROJECT`

For persistent mode:

- `DATABASE_URL` (PostgreSQL/Neon connection string)

Optional OpenRouter provider:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

Useful optional variables:

- `AGENT_MODEL`
- `AGENT_APP_NAME`
- `HTTP_TIMEOUT_SECONDS`
- `SCRAPE_MAX_CHARS`
- `MAX_VISUALIZATIONS`

## Local Development

Backend:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

## Tests

Run backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests
```

## Docker

The Dockerfile is multi-stage and builds the frontend automatically:

```powershell
docker build -t vibe-visualize .
docker run --rm -p 8080:8080 --env-file .env vibe-visualize
```

## Cloud Run

Build and deploy with Cloud Run using the same container:

```powershell
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/vibe-visualize
gcloud run deploy vibe-visualize `
  --image gcr.io/YOUR_PROJECT_ID/vibe-visualize `
  --platform managed `
  --region YOUR_REGION `
  --allow-unauthenticated `
  --set-env-vars AGENT_MODEL=gemini-3-flash-preview
```

Provide either `GOOGLE_API_KEY` or Vertex AI credentials in the Cloud Run environment.
