from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

DEFAULT_VIEWPORT = {"width": 1280, "height": 720}


class BrowserManager:
    def __init__(self, start_url: str) -> None:
        self._start_url = start_url
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserManager not started")
        return self._page

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(viewport=DEFAULT_VIEWPORT)
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
