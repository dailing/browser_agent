import asyncio
import base64
import json
import os
import time
from pathlib import Path

from playwright.async_api import Page


class PreviewPublisher:
    def __init__(self, interval_ms: int = 500) -> None:
        self._interval_ms = interval_ms
        self._clients: set = set()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._debug_path = os.environ.get("BROWSER_AGENT_DEBUG_JPEG")
        self._debug_written = False

    async def add_client(self, websocket) -> None:
        async with self._lock:
            self._clients.add(websocket)

    async def remove_client(self, websocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def _loop(self, page: Page) -> None:
        while True:
            async with self._lock:
                has_clients = len(self._clients) > 0
            if has_clients:
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
                            "mime": "image/jpeg",
                            "data": b64,
                            "viewport_width": vs["width"],
                            "viewport_height": vs["height"],
                            "ts": int(time.time() * 1000),
                        }
                    )
                    async with self._lock:
                        dead: list = []
                        for ws in self._clients:
                            try:
                                await ws.send_text(payload)
                            except Exception:
                                dead.append(ws)
                        for ws in dead:
                            self._clients.discard(ws)
                except Exception:
                    pass
            await asyncio.sleep(self._interval_ms / 1000)

    def start(self, page: Page) -> None:
        self._task = asyncio.create_task(self._loop(page))

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
