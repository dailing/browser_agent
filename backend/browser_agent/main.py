import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocket as StarletteWebSocket
from sqlalchemy.ext.asyncio import AsyncEngine
from uvicorn import run as uvicorn_run

from browser_agent.audit_logging import JsonlAudit, setup_process_logging
from browser_agent.browser_manager import BrowserManager
from browser_agent.database import create_schema, default_db_path, make_engine, make_session_factory
from browser_agent.preview_publisher import PreviewPublisher
from browser_agent.run_coordinator import RunCoordinator
from browser_agent.llm_client import LlmClient
from browser_agent.session_fanout import SessionFanout
from browser_agent.session_analysis import build_session_analysis_user_content
from browser_agent.session_store import DbSessionStore
from browser_agent.skills_store import list_skills as scan_skills, load_skill
from browser_agent.viewport_presets import (
    initial_viewport_from_presets,
    load_viewport_config,
)

START_URL = os.environ.get("BROWSER_AGENT_START_URL", "https://example.com")
HOST = os.environ.get("BROWSER_AGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("BROWSER_AGENT_PORT", "18000"))
PREVIEW_MS = int(os.environ.get("BROWSER_AGENT_PREVIEW_MS", "500"))

os.environ.setdefault("PDF_READER_API_BASE", "http://server.tail13fe1.ts.net:10000")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_STATIC_DIR = _REPO_ROOT / "frontend" / "dist"
_SKILLS_DIR = _REPO_ROOT / "_skills"


def _config_path(repo_root: Path) -> Path:
    override = os.environ.get("BROWSER_AGENT_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return repo_root / "config.json"


def _read_json_object(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON in {path}: {e.msg} (line {e.lineno}, column {e.colno}). "
            "Use strict JSON: double-quoted keys, no trailing commas, no // comments."
        ) from e
    return data if isinstance(data, dict) else {}


def _resolve_session_tab_idle_sec(repo_root: Path) -> float:
    default_sec = 600.0
    data = _read_json_object(_config_path(repo_root))
    browser = data.get("browser")
    if not isinstance(browser, dict):
        return default_sec
    raw = browser.get("session_tab_idle_sec")
    try:
        sec = float(raw)
    except (TypeError, ValueError):
        return default_sec
    return sec if sec > 0 else default_sec


class HttpOnlyStaticFiles(StaticFiles):
    """StaticFiles mounted at `/` must not receive WebSocket scopes (e.g. `/ws/preview` without id)."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            ws = StarletteWebSocket(scope, receive=receive, send=send)
            await ws.close(code=1008, reason="Not a WebSocket endpoint")
            return
        await super().__call__(scope, receive, send)

_publisher: PreviewPublisher | None = None
_browser: BrowserManager | None = None
_audit: JsonlAudit | None = None
_engine: AsyncEngine | None = None
_session_store: DbSessionStore | None = None
_fanout: SessionFanout | None = None
_coordinator: RunCoordinator | None = None
_session_op_locks: dict[str, asyncio.Lock] = {}
_viewport_presets: list[dict] = []
_preset_by_id: dict[str, dict] = {}


def _op_lock(session_id: str) -> asyncio.Lock:
    lock = _session_op_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_op_locks[session_id] = lock
    return lock


_PW_MOUSE_BUTTON = {0: "left", 1: "middle", 2: "right"}


async def _apply_remote_mouse_json(session_id: str, raw: str) -> None:
    if _browser is None:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if data.get("type") != "mouse":
        return
    ev = data.get("event")
    if ev not in ("move", "down", "up"):
        return
    try:
        x = float(data["x"])
        y = float(data["y"])
    except (KeyError, TypeError, ValueError):
        return
    try:
        btn = int(data.get("button", 0))
    except (TypeError, ValueError):
        btn = 0
    pw_btn = _PW_MOUSE_BUTTON.get(btn, "left")
    page = _browser.get_page_if_exists(session_id)
    if page is None:
        return
    try:
        if ev == "move":
            await page.mouse.move(x, y)
            return
        await page.mouse.move(x, y)
        if ev == "down":
            await page.mouse.down(button=pw_btn)
        else:
            await page.mouse.up(button=pw_btn)
    except Exception:
        pass


class CreateSessionBody(BaseModel):
    name: str | None = Field(default=None, max_length=512)
    max_steps: int = Field(default=40, ge=1, le=200)


class PushMessageBody(BaseModel):
    text: str = Field(min_length=1)


class SetViewportBody(BaseModel):
    preset_id: str = Field(min_length=1, max_length=64)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _publisher, _browser, _audit, _engine, _session_store, _fanout, _coordinator
    global _viewport_presets, _preset_by_id
    jsonl_path, _ = setup_process_logging(_REPO_ROOT)
    _audit = JsonlAudit(jsonl_path)
    _audit.emit({"type": "process_boot", "pid": os.getpid()})
    _engine = make_engine(default_db_path(_REPO_ROOT))
    await create_schema(_engine)
    _session_store = DbSessionStore(make_session_factory(_engine))
    _fanout = SessionFanout()
    presets, default_vp_id = load_viewport_config(_REPO_ROOT)
    _viewport_presets = list(presets)
    _preset_by_id = {str(p["id"]): p for p in _viewport_presets}
    initial_vp = initial_viewport_from_presets(_viewport_presets, default_vp_id)
    tab_idle_sec = _resolve_session_tab_idle_sec(_REPO_ROOT)
    _browser = BrowserManager(
        START_URL, viewport=initial_vp, tab_idle_timeout_sec=tab_idle_sec
    )
    await _browser.start()

    _publisher = PreviewPublisher(interval_ms=PREVIEW_MS, browser=_browser)
    _publisher.start()

    async def _broadcast_live_tab(sid: str, has_tab: bool) -> None:
        if _fanout is not None:
            await _fanout.broadcast(
                sid,
                {"type": "live_tab", "session_id": sid, "has_live_tab": has_tab},
            )
        if has_tab and _publisher is not None:
            await _publisher.wake_tab_waiters(sid)

    _browser.set_on_live_tab(_broadcast_live_tab)
    _coordinator = RunCoordinator(_REPO_ROOT, _browser, _session_store, _fanout, _audit)
    yield
    if _publisher is not None:
        await _publisher.stop()
    if _browser is not None:
        await _browser.stop()
    if _audit is not None:
        _audit.emit({"type": "process_shutdown", "pid": os.getpid()})
        _audit.close()
        _audit = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None


app = FastAPI(title="browser-agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/api/skills")
async def api_list_skills():
    return scan_skills(_SKILLS_DIR)


@app.get("/api/skills/{skill_id}")
async def api_get_skill(skill_id: str):
    data = load_skill(_SKILLS_DIR, skill_id)
    if data is None:
        raise HTTPException(status_code=404, detail="not found")
    return data


@app.post("/api/sessions")
async def create_session(body: CreateSessionBody):
    if _session_store is None:
        raise HTTPException(status_code=503, detail="server not ready")
    session = await _session_store.create_empty(name=body.name, max_steps=body.max_steps)
    return {"session_id": session.id, "status": session.status, "name": session.name}


@app.post("/api/sessions/{session_id}/messages")
async def push_user_message(session_id: str, body: PushMessageBody):
    if _coordinator is None or _session_store is None or _fanout is None or _audit is None:
        raise HTTPException(status_code=503, detail="server not ready")
    user_msg = {"role": "user", "content": body.text.strip()}
    async with _op_lock(session_id):
        s = await _session_store.get(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="not found")
        if s.status == "running":
            raise HTTPException(status_code=409, detail="agent_busy")
        await _session_store.append_message(session_id, user_msg)
        await _session_store.set_status(session_id, "running", None)
        _audit.emit({"type": "conversation_message", "session_id": session_id, "message": user_msg})
        await _fanout.broadcast(session_id, {"type": "message", "message": user_msg})
    if _browser is not None:
        _browser.touch_tab_activity_if_exists(session_id)
    asyncio.create_task(_coordinator.run(session_id))
    return {"ok": True, "status": "running"}


@app.get("/api/sessions")
async def list_sessions():
    if _session_store is None:
        raise HTTPException(status_code=503, detail="server not ready")
    rows = await _session_store.list_summaries()
    for r in rows:
        r["has_live_tab"] = _browser.has_live_tab(r["id"]) if _browser is not None else False
    return rows


@app.get("/api/browser/viewport")
async def get_browser_viewport():
    if _browser is None:
        raise HTTPException(status_code=503, detail="server not ready")
    iv = _browser.initial_viewport
    return {
        "presets": list(_viewport_presets),
        "current": {"width": iv["width"], "height": iv["height"]},
    }


@app.post("/api/browser/viewport")
async def set_browser_viewport(body: SetViewportBody):
    if _browser is None:
        raise HTTPException(status_code=503, detail="server not ready")
    preset = _preset_by_id.get(body.preset_id)
    if preset is None:
        raise HTTPException(status_code=400, detail="unknown preset_id")
    w, h = await _browser.set_viewport_size(int(preset["width"]), int(preset["height"]))
    if _audit is not None:
        _audit.emit(
            {"type": "browser_viewport", "preset_id": body.preset_id, "width": w, "height": h}
        )
    return {"ok": True, "width": w, "height": h, "preset_id": body.preset_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if _session_store is None or _fanout is None:
        raise HTTPException(status_code=503, detail="server not ready")
    async with _op_lock(session_id):
        s = await _session_store.get(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="not found")
        if s.status == "running":
            raise HTTPException(status_code=409, detail="agent_busy")
        deleted = await _session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="not found")
    if _browser is not None:
        await _browser.close_tab(session_id)
    await _fanout.drop_session(session_id)
    if _publisher is not None:
        await _publisher.drop_session(session_id)
    _session_op_locks.pop(session_id, None)
    return {"ok": True}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    if _session_store is None:
        raise HTTPException(status_code=503, detail="server not ready")
    s = await _session_store.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="not found")
    has_tab = _browser.has_live_tab(session_id) if _browser is not None else False
    return {
        "id": s.id,
        "name": s.name,
        "status": s.status,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "max_steps": s.max_steps,
        "error": s.error,
        "messages": s.messages,
        "has_live_tab": has_tab,
    }


@app.post("/api/sessions/{session_id}/session-analysis")
async def post_session_analysis(session_id: str):
    if _session_store is None or _audit is None:
        raise HTTPException(status_code=503, detail="server not ready")
    s = await _session_store.get(session_id, with_message_row_ids=True)
    if s is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        llm = LlmClient(_REPO_ROOT)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    row_ids = s.message_row_ids
    if row_ids is None or len(row_ids) != len(s.messages):
        raise HTTPException(status_code=500, detail="internal_error: message_row_ids")
    message_rows = list(zip(row_ids, s.messages))
    user_content = build_session_analysis_user_content(
        message_rows,
        session_meta={
            "id": s.id,
            "name": s.name,
            "status": s.status,
            "max_steps": s.max_steps,
            "error": s.error,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "message_count": len(s.messages),
        },
    )
    messages = [{"role": "user", "content": user_content}]
    choice = await llm.chat_no_tools(
        messages,
        session_id=session_id,
        audit=_audit,
        purpose="session_analysis",
    )
    if choice is None:
        raise HTTPException(status_code=502, detail="llm_request_failed")
    text = (choice.message.content or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="empty_llm_response")
    return {"markdown": text}


@app.websocket("/ws/session/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str):
    if _session_store is None or _fanout is None:
        await websocket.close(code=1011)
        return
    s = await _session_store.get(session_id)
    if s is None:
        await websocket.close(code=1008, reason="session not found")
        return
    await websocket.accept()
    await _fanout.subscribe(session_id, websocket)
    try:
        has_tab = _browser.has_live_tab(session_id) if _browser is not None else False
        await websocket.send_json(
            {
                "type": "snapshot",
                "session_id": session_id,
                "status": s.status,
                "messages": list(s.messages),
                "has_live_tab": has_tab,
            }
        )
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=120.0)
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await _fanout.unsubscribe(session_id, websocket)


@app.websocket("/ws/preview/{session_id}")
async def ws_preview(websocket: WebSocket, session_id: str):
    if _session_store is None:
        await websocket.close(code=1011)
        return
    s = await _session_store.get(session_id)
    if s is None:
        await websocket.close(code=1008, reason="session not found")
        return
    await websocket.accept()
    if _publisher is not None:
        await _publisher.add_client(session_id, websocket)
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("type") == "websocket.receive":
                text = msg.get("text")
                if text:
                    await _apply_remote_mouse_json(session_id, text)
    except WebSocketDisconnect:
        pass
    finally:
        if _publisher is not None:
            await _publisher.remove_client(session_id, websocket)


@app.websocket("/ws/preview")
async def ws_preview_legacy(websocket: WebSocket):
    await websocket.accept()
    await websocket.close(
        code=1008,
        reason="Use ws/preview/{session_id} (per-session preview)",
    )


if _STATIC_DIR.is_dir():
    app.mount(
        "/",
        HttpOnlyStaticFiles(directory=str(_STATIC_DIR), html=True),
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
