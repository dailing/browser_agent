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
    """Per-session preview WebSocket: idle until a tab exists, then stream JPEGs."""

    def __init__(self, interval_ms: int, browser: BrowserManager) -> None:
        self._interval_ms = interval_ms
        self._browser = browser
        self._clients: dict[str, set[WebSocket]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._tab_wake: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._idle_ping_sec = float(os.environ.get("BROWSER_AGENT_PREVIEW_IDLE_PING_SEC", "20"))
        self._debug_path = os.environ.get("BROWSER_AGENT_DEBUG_JPEG")
        self._debug_written = False

    async def wake_tab_waiters(self, session_id: str) -> None:
        async with self._lock:
            ev = self._tab_wake.get(session_id)
        if ev is not None:
            ev.set()

    async def add_client(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.setdefault(session_id, set()).add(websocket)
            task = self._tasks.get(session_id)
            if task is None or task.done():
                self._tasks[session_id] = asyncio.create_task(self._session_loop(session_id))
        if self._browser.get_page_if_exists(session_id) is None:
            await self._send_waiting_to_ws(websocket, session_id)

    async def remove_client(self, session_id: str, websocket: WebSocket) -> None:
        t: asyncio.Task[None] | None = None
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

    async def drop_session(self, session_id: str) -> None:
        async with self._lock:
            subs = self._clients.pop(session_id, None)
            ws_list = list(subs) if subs else []
            t = self._tasks.pop(session_id, None)
        if t is not None:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        for ws in ws_list:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.close(code=1008, reason="session deleted")
            except Exception:
                pass

    def _waiting_payload(self, session_id: str) -> str:
        return json.dumps(
            {
                "type": "preview",
                "state": "waiting",
                "reason": "no_live_tab",
                "session_id": session_id,
                "ts": int(time.time() * 1000),
            }
        )

    async def _send_waiting_to_ws(self, ws: WebSocket, session_id: str) -> None:
        payload = self._waiting_payload(session_id)
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_text(payload)
        except Exception:
            pass

    async def _broadcast_text(self, session_id: str, subs: list[WebSocket], payload: str) -> bool:
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
                        return False
        return True

    async def _session_loop(self, session_id: str) -> None:
        interval = self._interval_ms / 1000.0
        tab_evt = asyncio.Event()
        async with self._lock:
            self._tab_wake[session_id] = tab_evt
        had_live_page = False
        try:
            while True:
                async with self._lock:
                    subs = list(self._clients.get(session_id, ()))
                if not subs:
                    return

                page = self._browser.get_page_if_exists(session_id)
                if page is None:
                    had_live_page = False
                    payload = self._waiting_payload(session_id)
                    if not await self._broadcast_text(session_id, subs, payload):
                        return
                    while True:
                        async with self._lock:
                            subs2 = list(self._clients.get(session_id, ()))
                        if not subs2:
                            return
                        if self._browser.get_page_if_exists(session_id) is not None:
                            break
                        tab_evt.clear()
                        if self._browser.get_page_if_exists(session_id) is not None:
                            break
                        try:
                            await asyncio.wait_for(
                                tab_evt.wait(),
                                timeout=max(1.0, self._idle_ping_sec),
                            )
                            break
                        except asyncio.TimeoutError:
                            ping = json.dumps(
                                {
                                    "type": "preview",
                                    "state": "ping",
                                    "session_id": session_id,
                                    "ts": int(time.time() * 1000),
                                }
                            )
                            if not await self._broadcast_text(session_id, subs2, ping):
                                return
                    continue

                if not had_live_page:
                    had_live_page = True
                    open_payload = json.dumps(
                        {
                            "type": "preview",
                            "state": "tab_opened",
                            "session_id": session_id,
                            "ts": int(time.time() * 1000),
                        }
                    )
                    if not await self._broadcast_text(session_id, subs, open_payload):
                        return
                    async with self._lock:
                        subs = list(self._clients.get(session_id, ()))
                    if not subs:
                        return

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

                if not await self._broadcast_text(session_id, subs, payload):
                    return

                await asyncio.sleep(interval)
        finally:
            async with self._lock:
                self._tab_wake.pop(session_id, None)
                self._tasks.pop(session_id, None)

    def start(self, _page=None) -> None:
        pass

    async def stop(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
            self._clients.clear()
            self._tab_wake.clear()
        for t in tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
