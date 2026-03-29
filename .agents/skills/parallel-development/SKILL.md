---
name: parallel-development
description: Instructions for coordinating parallel development between Antigravity (Frontend) and Codex (Backend) to avoid merge conflicts.
---

# Parallel Development Protocol

You are operating in a multi-agent environment where two different AI coders (Antigravity and Codex) are working simultaneously on the same repository. To ensure smooth progress and zero file conflicts, **you must strictly adhere to the following partitioning rules.**

## 1. Domain Partitioning

### 🟢 Antigravity Domain (Frontend & UI/UX)
**Allowed Directories/Files:**
- `frontend/src/*`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`

**Responsibilities:**
- React component architecture and state management.
- Chart.js integration and visualizations.
- Tailwind CSS styling and animations.
- Calling the backend endpoints.

### 🛠️ Codex Domain (Backend & Infrastructure)
**Allowed Directories/Files:**
- `main.py`
- `agent.py`
- `requirements.txt`
- `Dockerfile`
- `.env.example`
- `README.md`

**Responsibilities:**
- FastAPI routing and endpoint definitions.
- Google ADK configuration and `LlmAgent` tuning.
- Gemini prompt engineering and JSON extraction logic.
- Containerization and Cloud Run deployment scripts.

---

## 2. Strict Rules of Engagement

1. **Do Not Cross the Boundary:** Under no circumstances should you edit a file that belongs to the other agent's domain. If a change is required in the other domain (e.g., Antigravity needs a new API field), you must document the requirement in a shared communication file or inform the user to pass the request to the other agent.
2. **The API Contract is Immutable by Default:** The backend `/run` endpoint currently accepts `{"text": string}` and returns:
   ```json
   {
     "summary": "string",
     "chart_type": "bar | pie | line",
     "chart_data": {
       "labels": ["string"],
       "values": [number]
     }
   }
   ```
   If Codex decides to change this schema, Codex must notify the user to inform Antigravity. If Antigravity needs a change, Antigravity must notify the user to inform Codex.
3. **No Global Formatting:** Do not run whole-project formatters (like `black .` or `prettier --write .`) outside of your specific directories, as this will overwrite the other agent's uncommitted work.

## 3. Workflow for This Session

If you are **Antigravity**:
Proceed with implementing the **Visualization History**, **Chart Customization (Overrides)**, and **UI Polish** inside `frontend/src/`.

If you are **Codex**:
Proceed with **Prompt Engineering V2** (handling edge cases in `agent.py`), implementing the **Export Service** (`/export` in `main.py`), and finalizing the **Documentation/Dockerfile**.
