import asyncio
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class SessionFanout:
    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subs.setdefault(session_id, set()).add(ws)

    async def unsubscribe(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            subs = self._subs.get(session_id)
            if subs is None:
                return
            subs.discard(ws)
            if not subs:
                del self._subs[session_id]

    async def broadcast(self, session_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            subs = list(self._subs.get(session_id, ()))
        dead: list[WebSocket] = []
        for ws in subs:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                bag = self._subs.get(session_id)
                if bag is not None:
                    for ws in dead:
                        bag.discard(ws)
