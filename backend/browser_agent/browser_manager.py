from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from browser_agent.viewport_presets import MAX_VIEWPORT_H, MAX_VIEWPORT_W, MIN_VIEWPORT

DEFAULT_VIEWPORT = {"width": 1280, "height": 720}


class BrowserManager:
    def __init__(self, start_url: str, viewport: dict[str, int] | None = None) -> None:
        self._start_url = start_url
        self._initial_viewport = viewport or DEFAULT_VIEWPORT
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserManager not started")
        return self._page

    async def set_viewport_size(self, width: int, height: int) -> tuple[int, int]:
        w = max(MIN_VIEWPORT, min(MAX_VIEWPORT_W, int(width)))
        h = max(MIN_VIEWPORT, min(MAX_VIEWPORT_H, int(height)))
        await self.page.set_viewport_size({"width": w, "height": h})
        return w, h

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(viewport=dict(self._initial_viewport))
        self._page = await self._context.new_page()
        await self._page.goto(self._start_url, wait_until="domcontentloaded")

    async def stop(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
