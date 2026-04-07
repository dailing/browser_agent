from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from browser_agent.browser_manager import BrowserManager


class PreviewPublisher:
    """Per-session preview: JPEG stream for a session's tab, or placeholder when no tab."""

    def __init__(self, interval_ms: int, browser: BrowserManager) -> None:
        self._interval_ms = interval_ms
        self._browser = browser
        self._clients: dict[str, set[WebSocket]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._debug_path = os.environ.get("BROWSER_AGENT_DEBUG_JPEG")
        self._debug_written = False

    async def add_client(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.setdefault(session_id, set()).add(websocket)
            task = self._tasks.get(session_id)
            if task is None or task.done():
                self._tasks[session_id] = asyncio.create_task(self._session_loop(session_id))

    async def remove_client(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            subs = self._clients.get(session_id)
            if subs is None:
                return
            subs.discard(websocket)
            if not subs:
                del self._clients[session_id]
                t = self._tasks.pop(session_id, None)
        if t is not None:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def _session_loop(self, session_id: str) -> None:
        interval = self._interval_ms / 1000.0
        try:
            while True:
                async with self._lock:
                    subs = list(self._clients.get(session_id, ()))
                if not subs:
                    return

                page = self._browser.get_page_if_exists(session_id)
                if page is None:
                    payload = json.dumps(
                        {
                            "type": "preview",
                            "state": "placeholder",
                            "reason": "no_live_tab",
                            "session_id": session_id,
                            "ts": int(time.time() * 1000),
                        }
                    )
                    dead: list[WebSocket] = []
                    for ws in subs:
                        try:
                            if ws.client_state == WebSocketState.CONNECTED:
                                await ws.send_text(payload)
                            else:
                                dead.append(ws)
                        except Exception:
                            dead.append(ws)
                    if dead:
                        async with self._lock:
                            bag = self._clients.get(session_id)
                            if bag is not None:
                                for ws in dead:
                                    bag.discard(ws)
                                if not bag:
                                    del self._clients[session_id]
                                    return
                    await asyncio.sleep(interval)
                    continue

                try:
                    data = await page.screenshot(type="jpeg", quality=82)
                    if self._debug_path and not self._debug_written:
                        Path(self._debug_path).write_bytes(data)
                        self._debug_written = True
                    b64 = base64.b64encode(data).decode("ascii")
                    vs = page.viewport_size
                    payload = json.dumps(
                        {
                            "type": "preview",
                            "state": "live",
                            "mime": "image/jpeg",
                            "data": b64,
                            "viewport_width": vs["width"],
                            "viewport_height": vs["height"],
                            "session_id": session_id,
                            "ts": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    payload = json.dumps(
                        {
                            "type": "preview",
                            "state": "placeholder",
                            "reason": "screenshot_error",
                            "session_id": session_id,
                            "ts": int(time.time() * 1000),
                        }
                    )

                dead2: list[WebSocket] = []
                for ws in subs:
                    try:
                        if ws.client_state == WebSocketState.CONNECTED:
                            await ws.send_text(payload)
                        else:
                            dead2.append(ws)
                    except Exception:
                        dead2.append(ws)
                if dead2:
                    async with self._lock:
                        bag = self._clients.get(session_id)
                        if bag is not None:
                            for ws in dead2:
                                bag.discard(ws)
                            if not bag:
                                del self._clients[session_id]
                                return

                await asyncio.sleep(interval)
        finally:
            async with self._lock:
                self._tasks.pop(session_id, None)

    def start(self, _page=None) -> None:
        pass

    async def stop(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
            self._clients.clear()
        for t in tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
