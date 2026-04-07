from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from browser_agent.viewport_presets import MAX_VIEWPORT_H, MAX_VIEWPORT_W, MIN_VIEWPORT

DEFAULT_VIEWPORT = {"width": 1280, "height": 720}

LiveTabCallback = Callable[[str, bool], Awaitable[None]]


@dataclass
class SessionTab:
    context: BrowserContext
    page: Page
    last_activity_monotonic: float


class BrowserManager:
    def __init__(
        self,
        start_url: str,
        viewport: dict[str, int] | None = None,
        *,
        tab_idle_timeout_sec: float = 21_600.0,
    ) -> None:
        self._start_url = start_url
        self._initial_viewport = dict(viewport or DEFAULT_VIEWPORT)
        self._tab_idle_timeout_sec = tab_idle_timeout_sec
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._tabs: dict[str, SessionTab] = {}
        self._lock = asyncio.Lock()
        self._sweeper_task: asyncio.Task[None] | None = None
        self._on_live_tab: LiveTabCallback | None = None

    def set_on_live_tab(self, cb: LiveTabCallback | None) -> None:
        self._on_live_tab = cb

    @property
    def initial_viewport(self) -> dict[str, int]:
        return dict(self._initial_viewport)

    def has_live_tab(self, session_id: str) -> bool:
        return session_id in self._tabs

    def get_page_if_exists(self, session_id: str) -> Page | None:
        t = self._tabs.get(session_id)
        return t.page if t else None

    def touch_tab_activity_if_exists(self, session_id: str) -> None:
        t = self._tabs.get(session_id)
        if t:
            t.last_activity_monotonic = time.monotonic()

    async def ensure_page(self, session_id: str) -> Page:
        if self._browser is None:
            raise RuntimeError("BrowserManager not started")
        async with self._lock:
            t = self._tabs.get(session_id)
            if t is None:
                ctx = await self._browser.new_context(viewport=dict(self._initial_viewport))
                page = await ctx.new_page()
                await page.goto(self._start_url, wait_until="domcontentloaded")
                mono = time.monotonic()
                self._tabs[session_id] = SessionTab(context=ctx, page=page, last_activity_monotonic=mono)
                await self._emit_live_tab(session_id, True)
            else:
                t.last_activity_monotonic = time.monotonic()
            return self._tabs[session_id].page

    async def close_tab(self, session_id: str, *, reason: str = "idle") -> None:
        async with self._lock:
            t = self._tabs.pop(session_id, None)
        if t is None:
            return
        try:
            await t.context.close()
        except Exception:
            pass
        await self._emit_live_tab(session_id, False)

    async def _emit_live_tab(self, session_id: str, has_tab: bool) -> None:
        cb = self._on_live_tab
        if cb is not None:
            await cb(session_id, has_tab)

    async def _idle_sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(60.0)
            if self._browser is None:
                continue
            now = time.monotonic()
            for sid, t in list(self._tabs.items()):
                if now - t.last_activity_monotonic >= self._tab_idle_timeout_sec:
                    await self.close_tab(sid, reason="idle_timeout")

    async def set_viewport_size(self, width: int, height: int) -> tuple[int, int]:
        w = max(MIN_VIEWPORT, min(MAX_VIEWPORT_W, int(width)))
        h = max(MIN_VIEWPORT, min(MAX_VIEWPORT_H, int(height)))
        self._initial_viewport = {"width": w, "height": h}
        async with self._lock:
            for t in self._tabs.values():
                await t.page.set_viewport_size({"width": w, "height": h})
        return w, h

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._sweeper_task = asyncio.create_task(self._idle_sweep_loop())

    async def stop(self) -> None:
        if self._sweeper_task is not None:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass
            self._sweeper_task = None
        for sid in list(self._tabs.keys()):
            await self.close_tab(sid, reason="shutdown")
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
