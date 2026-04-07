import re
import uuid
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from browser_agent.page_context_builder import PageContextBuilder

_REF_SEL = re.compile(r"^[1-9]\d*$")


def _ref_selector(ref: str) -> str:
    return f'[data-agent-ref="{ref}"]'


class ActionExecutor:
    def __init__(
        self,
        page: Page,
        repo_root: Path,
        context_builder: PageContextBuilder,
    ) -> None:
        self._page = page
        self._repo_root = repo_root
        self._context = context_builder

    async def execute(self, session_id: str, name: str, args: dict[str, Any]) -> str:
        try:
            return await self._dispatch(session_id, name, args)
        except Exception as e:
            return f"error: {e}"

    async def _dispatch(self, session_id: str, name: str, args: dict[str, Any]) -> str:
        if name == "navigate":
            url = args.get("url") or ""
            if not url:
                return "error: missing url"
            await self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            return f"navigated to {self._page.url}"

        if name == "go_back":
            await self._page.go_back(wait_until="domcontentloaded", timeout=30_000)
            return f"back: {self._page.url}"

        if name == "click":
            ref = str(args.get("ref", ""))
            if not _REF_SEL.match(ref):
                return "error: invalid ref"
            sel = _ref_selector(ref)
            await self._page.click(sel, timeout=15_000)
            return f"clicked ref={ref}"

        if name == "fill":
            ref = str(args.get("ref", ""))
            text = args.get("text", "")
            if not _REF_SEL.match(ref):
                return "error: invalid ref"
            sel = _ref_selector(ref)
            await self._page.fill(sel, str(text), timeout=15_000)
            return f"filled ref={ref}"

        if name == "press_key":
            key = args.get("key") or ""
            if not key:
                return "error: missing key"
            await self._page.keyboard.press(str(key))
            return f"pressed {key}"

        if name == "scroll":
            direction = (args.get("direction") or "down").lower()
            amount = int(args.get("pixels", 400))
            dx, dy = 0, 0
            if direction == "down":
                dy = amount
            elif direction == "up":
                dy = -amount
            elif direction == "right":
                dx = amount
            elif direction == "left":
                dx = -amount
            else:
                return "error: direction must be up|down|left|right"
            await self._page.mouse.wheel(dx, dy)
            return f"scrolled {direction} {amount}px"

        if name == "wait_ms":
            ms = int(args.get("ms", 1000))
            await self._page.wait_for_timeout(min(max(ms, 0), 120_000))
            return f"waited {ms}ms"

        if name == "select_option":
            ref = str(args.get("ref", ""))
            value = args.get("value")
            label = args.get("label")
            if not _REF_SEL.match(ref):
                return "error: invalid ref"
            sel = _ref_selector(ref)
            loc = self._page.locator(sel)
            if value is not None:
                await loc.select_option(value=str(value), timeout=15_000)
            elif label is not None:
                await loc.select_option(label=str(label), timeout=15_000)
            else:
                return "error: need value or label"
            return f"selected ref={ref}"

        if name == "get_observation":
            return await self._context.build()

        if name == "screenshot_viewport_jpeg":
            buf = await self._page.screenshot(type="jpeg", quality=80)
            out_dir = self._repo_root / "log" / "screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{session_id[:8]}_{uuid.uuid4().hex[:10]}.jpg"
            path = out_dir / fname
            path.write_bytes(buf)
            return f"saved {path.relative_to(self._repo_root)}"

        if name == "export_page_pdf":
            out_dir = self._repo_root / "log" / "pdf"
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{session_id[:8]}_{uuid.uuid4().hex[:10]}.pdf"
            path = out_dir / fname
            await self._page.pdf(path=str(path), print_background=True)
            return f"saved {path.relative_to(self._repo_root)}"

        return f"error: unknown tool {name}"
