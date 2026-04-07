# brower_agent

Headless browser agent with live JPEG preview (`plain.md`): Playwright, FastAPI, Vue 3 + Bootstrap, **markdown-it** session UI, OpenAI tool-calling loop, JSONL audit logs under `log/`.

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (for the frontend)
- `OPENAI_API_KEY` (agent). Optional: `OPENAI_BASE_URL`, `OPENAI_MODEL` (default `gpt-4o-mini`).

## Backend (`backend/`, uv)

```bash
cd backend
uv sync
uv run playwright install chromium
uv run browser-agent
```

Defaults: `http://127.0.0.1:18000` (serves built frontend from `frontend/dist/` when present), preview WebSocket `ws://127.0.0.1:18000/ws/preview`, initial page `https://example.com`.

Environment: `BROWSER_AGENT_START_URL`, `BROWSER_AGENT_HOST`, `BROWSER_AGENT_PORT`, `BROWSER_AGENT_PREVIEW_MS`, `BROWSER_AGENT_DEBUG_JPEG`.

Each server process writes **loguru** text logs and a **JSON Lines** audit file under `log/run_<utc>_<pid>.jsonl` and `log/run_<utc>_<pid>.log` (LLM requests/responses, tool calls/results, conversation messages).

API: `POST /api/runs` `{ "goal", "max_steps" }`, `GET /api/sessions`, `GET /api/sessions/{id}`, WebSocket ` /ws/session/{id}` for live session updates.

## Frontend (`frontend/`)

```bash
cd frontend
npm install
npm run build
```

Vite dev proxies `/ws`, `/health`, and `/api` to port 18000. For an all-in-one UI, build the frontend and start the backend (static files from `frontend/dist/`).

Python is pinned via `backend/.python-version` (3.12) and `requires-python` in `pyproject.toml`.
