from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from browser_agent.viewport_presets import MAX_VIEWPORT_H, MAX_VIEWPORT_W, MIN_VIEWPORT

DEFAULT_VIEWPORT = {"width": 1280, "height": 720}

LiveTabCallback = Callable[[str, bool], Awaitable[None]]


@dataclass
class SessionTab:
    context: BrowserContext
    page_stack: list[Page] = field(default_factory=list)
    last_activity_monotonic: float = 0.0

    @property
    def page(self) -> Page:
        return self.page_stack[-1]


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
        t = self._tabs.get(session_id)
        return bool(t and t.page_stack)

    def stack_depth(self, session_id: str) -> int:
        t = self._tabs.get(session_id)
        return len(t.page_stack) if t else 0

    def get_page_if_exists(self, session_id: str) -> Page | None:
        t = self._tabs.get(session_id)
        if not t or not t.page_stack:
            return None
        return t.page_stack[-1]

    def touch_tab_activity_if_exists(self, session_id: str) -> None:
        t = self._tabs.get(session_id)
        if t:
            t.last_activity_monotonic = time.monotonic()

    def _schedule_handle_new_page(self, session_id: str, page: Page) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._handle_new_page(session_id, page))

    def _schedule_on_page_closed(self, session_id: str, page: Page) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._on_page_closed(session_id, page))

    def _register_page_close(self, session_id: str, page: Page) -> None:
        page.once("close", lambda: self._schedule_on_page_closed(session_id, page))

    async def _handle_new_page(self, session_id: str, page: Page) -> None:
        async with self._lock:
            t = self._tabs.get(session_id)
            if t is None:
                return
            try:
                await page.set_viewport_size(dict(self._initial_viewport))
            except Exception:
                pass
            t.page_stack.append(page)
            self._register_page_close(session_id, page)

    async def _on_page_closed(self, session_id: str, page: Page) -> None:
        ctx_to_close: BrowserContext | None = None
        emit_sid: str | None = None
        async with self._lock:
            t = self._tabs.get(session_id)
            if not t:
                return
            try:
                t.page_stack.remove(page)
            except ValueError:
                return
            if not t.page_stack:
                ctx_to_close = t.context
                self._tabs.pop(session_id, None)
                emit_sid = session_id
        if ctx_to_close is not None:
            try:
                await ctx_to_close.close()
            except Exception:
                pass
        if emit_sid is not None:
            await self._emit_live_tab(emit_sid, False)

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
                t = SessionTab(context=ctx, page_stack=[page], last_activity_monotonic=mono)
                self._register_page_close(session_id, page)

                def _on_page(p: Page) -> None:
                    self._schedule_handle_new_page(session_id, p)

                ctx.on("page", _on_page)
                self._tabs[session_id] = t
                await self._emit_live_tab(session_id, True)
            else:
                t.last_activity_monotonic = time.monotonic()
                if not t.page_stack:
                    page = await t.context.new_page()
                    await page.goto(self._start_url, wait_until="domcontentloaded")
                    t.page_stack.append(page)
                    self._register_page_close(session_id, page)
                    await self._emit_live_tab(session_id, True)
            return t.page_stack[-1]

    async def stabilize_after_action(
        self, session_id: str, *, stabilize_ms: int, wait_load_state: bool
    ) -> None:
        if stabilize_ms > 0:
            await asyncio.sleep(stabilize_ms / 1000.0)
        page = self.get_page_if_exists(session_id)
        if page is None or not wait_load_state:
            return
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30_000)
        except Exception:
            pass

    async def format_stack_report(self, session_id: str, depth_before: int) -> str:
        lines: list[str] = ["---"]
        t = self._tabs.get(session_id)
        depth = len(t.page_stack) if t else 0
        if depth > depth_before:
            lines.append(f"Notice: new tab is now active (stack depth {depth}).")
        if not t or not t.page_stack:
            lines.append("Stack: depth=0 (no active tab)")
            return "\n".join(lines)
        lines.append(f"Stack: depth={depth}")
        for i, p in enumerate(t.page_stack):
            mark = "*" if i == depth - 1 else " "
            url = ""
            title = ""
            try:
                url = p.url or ""
            except Exception:
                url = ""
            try:
                title = await p.title()
            except Exception:
                title = ""
            prefix = f"  [{i + 1}]{mark}"
            lines.append(f"{prefix} url={url[:500]}")
            if title:
                lines.append(f"       title={title[:200]}")
        top = t.page_stack[-1]
        active_url = ""
        active_title = ""
        try:
            active_url = top.url or ""
        except Exception:
            pass
        try:
            active_title = await top.title()
        except Exception:
            active_title = ""
        lines.append(f"Active: url={active_url[:800]} title={active_title[:200] if active_title else ''}")
        return "\n".join(lines)

    async def close_current_page(self, session_id: str) -> str:
        top: Page | None = None
        async with self._lock:
            t = self._tabs.get(session_id)
            if t is None or not t.page_stack:
                return "error: no active tab"
            top = t.page_stack.pop()
        try:
            await top.close()
        except Exception:
            pass
        ctx_to_close: BrowserContext | None = None
        async with self._lock:
            t = self._tabs.get(session_id)
            if t is not None and not t.page_stack:
                ctx_to_close = t.context
                self._tabs.pop(session_id, None)
        if ctx_to_close is not None:
            try:
                await ctx_to_close.close()
            except Exception:
                pass
            await self._emit_live_tab(session_id, False)
            return "closed current tab; no tabs left in session"
        return "closed current tab"

    async def close_tab(self, session_id: str, *, reason: str = "idle") -> None:
        """Close the entire browser context for this session (all tabs)."""
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
                for p in t.page_stack:
                    try:
                        await p.set_viewport_size({"width": w, "height": h})
                    except Exception:
                        pass
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
