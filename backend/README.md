# browser-agent (backend)

Headless Chromium preview: Playwright JPEG screenshots over WebSocket.

## Setup

```bash
uv sync
uv run playwright install chromium
```

## Run

```bash
uv run browser-agent
# or
uv run uvicorn browser_agent.main:app --host 127.0.0.1 --port 18000
```

Environment:

- `BROWSER_AGENT_START_URL` — initial page (default `https://example.com`)
- `BROWSER_AGENT_HOST` / `BROWSER_AGENT_PORT` — bind address
- `BROWSER_AGENT_PREVIEW_MS` — screenshot interval when clients connected
- `BROWSER_AGENT_DEBUG_JPEG` — if set, write first frame bytes to this path (Phase A check)
