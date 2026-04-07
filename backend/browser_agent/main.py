import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from uvicorn import run as uvicorn_run

from browser_agent.audit_logging import JsonlAudit, setup_process_logging
from browser_agent.browser_manager import BrowserManager
from browser_agent.preview_publisher import PreviewPublisher
from browser_agent.run_coordinator import RunCoordinator
from browser_agent.session_fanout import SessionFanout
from browser_agent.session_store import SessionStore

START_URL = os.environ.get("BROWSER_AGENT_START_URL", "https://example.com")
HOST = os.environ.get("BROWSER_AGENT_HOST", "127.0.0.1")
PORT = int(os.environ.get("BROWSER_AGENT_PORT", "18000"))
PREVIEW_MS = int(os.environ.get("BROWSER_AGENT_PREVIEW_MS", "500"))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_STATIC_DIR = _REPO_ROOT / "frontend" / "dist"

_publisher: PreviewPublisher | None = None
_browser: BrowserManager | None = None
_audit: JsonlAudit | None = None
_session_store: SessionStore | None = None
_fanout: SessionFanout | None = None
_coordinator: RunCoordinator | None = None


class RunBody(BaseModel):
    goal: str = Field(min_length=1)
    max_steps: int = Field(default=40, ge=1, le=200)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _publisher, _browser, _audit, _session_store, _fanout, _coordinator
    jsonl_path, _ = setup_process_logging(_REPO_ROOT)
    _audit = JsonlAudit(jsonl_path)
    _audit.emit({"type": "process_boot", "pid": os.getpid()})
    _session_store = SessionStore()
    _fanout = SessionFanout()
    _browser = BrowserManager(START_URL)
    await _browser.start()
    _coordinator = RunCoordinator(_REPO_ROOT, _browser, _session_store, _fanout, _audit)
    _publisher = PreviewPublisher(interval_ms=PREVIEW_MS)
    _publisher.start(_browser.page)
    yield
    if _publisher is not None:
        await _publisher.stop()
    if _browser is not None:
        await _browser.stop()
    if _audit is not None:
        _audit.emit({"type": "process_shutdown", "pid": os.getpid()})
        _audit.close()
        _audit = None


app = FastAPI(title="browser-agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/runs")
async def post_run(body: RunBody):
    if _coordinator is None or _session_store is None:
        raise HTTPException(status_code=503, detail="server not ready")
    session = _session_store.create(body.goal)
    _session_store.append_message(session.id, {"role": "user", "content": body.goal})
    asyncio.create_task(_coordinator.run(session.id, max_steps=body.max_steps))
    return {"session_id": session.id, "status": session.status}


@app.get("/api/sessions")
async def list_sessions():
    if _session_store is None:
        raise HTTPException(status_code=503, detail="server not ready")
    return [
        {
            "id": s.id,
            "goal": s.goal,
            "status": s.status,
            "created_at": s.created_at,
            "message_count": len(s.messages),
        }
        for s in _session_store.all_sessions()
    ]


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    if _session_store is None:
        raise HTTPException(status_code=503, detail="server not ready")
    s = _session_store.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "id": s.id,
        "goal": s.goal,
        "status": s.status,
        "created_at": s.created_at,
        "error": s.error,
        "messages": s.messages,
    }


@app.websocket("/ws/session/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str):
    if _session_store is None or _fanout is None:
        await websocket.close(code=1011)
        return
    if _session_store.get(session_id) is None:
        await websocket.close(code=1008, reason="session not found")
        return
    await websocket.accept()
    await _fanout.subscribe(session_id, websocket)
    s = _session_store.get(session_id)
    assert s is not None
    try:
        await websocket.send_json(
            {
                "type": "snapshot",
                "session_id": session_id,
                "status": s.status,
                "messages": list(s.messages),
            }
        )
        while True:
            try:
                await asyncio.wait_for(websocket.receive(), timeout=120.0)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        await _fanout.unsubscribe(session_id, websocket)


@app.websocket("/ws/preview")
async def ws_preview(websocket: WebSocket):
    await websocket.accept()
    if _publisher is not None:
        await _publisher.add_client(websocket)
    try:
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        pass
    finally:
        if _publisher is not None:
            await _publisher.remove_client(websocket)


if _STATIC_DIR.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="static",
    )


def main() -> None:
    uvicorn_run(
        "browser_agent.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
