from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, ClassVar

from playwright.async_api import Page

from browser_agent.actions.base import AgentAction

_REF_SEL = re.compile(r"^[1-9]\d*$")


def _ref_selector(ref: str) -> str:
    return f'[data-agent-ref="{ref}"]'


class GetObservationAction(AgentAction):
    description: ClassVar[str] = (
        "Refresh the structured view of the current page (URL, title, interactive elements "
        "with [ref=N] markers). Call after navigation or when the DOM may have changed."
    )
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        return ""


class GetDetailedObservationAction(AgentAction):
    description: ClassVar[str] = (
        "Detailed page context: URL, title, and an ARIA snapshot (YAML) of the document "
        "for visible structure and text. Does not add [ref=N]; use get_observation for clickable refs."
    )
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        return ""


class NavigateAction(AgentAction):
    description: ClassVar[str] = "Open a URL in the current tab."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Full https URL"}},
        "required": ["url"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        url = args.get("url") or ""
        if not url:
            return "error: missing url"
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        return f"navigated to {page.url}"


class GoBackAction(AgentAction):
    description: ClassVar[str] = "Browser back navigation."
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        await page.go_back(wait_until="domcontentloaded", timeout=30_000)
        return f"back: {page.url}"


class ClickAction(AgentAction):
    description: ClassVar[str] = "Click an element that appeared in the last observation with [ref=N]."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"ref": {"type": "string", "description": "Numeric ref from observation"}},
        "required": ["ref"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        ref = str(args.get("ref", ""))
        if not _REF_SEL.match(ref):
            return "error: invalid ref"
        await page.click(_ref_selector(ref), timeout=15_000)
        return f"clicked ref={ref}"


class FillAction(AgentAction):
    description: ClassVar[str] = "Fill an input or textarea identified by ref."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"ref": {"type": "string"}, "text": {"type": "string"}},
        "required": ["ref", "text"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        ref = str(args.get("ref", ""))
        text = args.get("text", "")
        if not _REF_SEL.match(ref):
            return "error: invalid ref"
        await page.fill(_ref_selector(ref), str(text), timeout=15_000)
        return f"filled ref={ref}"


class PressKeyAction(AgentAction):
    description: ClassVar[str] = "Press a key or named key (e.g. Enter, Tab)."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        key = args.get("key") or ""
        if not key:
            return "error: missing key"
        await page.keyboard.press(str(key))
        return f"pressed {key}"


class ScrollAction(AgentAction):
    description: ClassVar[str] = "Scroll the main viewport."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "pixels": {"type": "integer", "description": "Pixels to scroll (default 400)"},
        },
        "required": ["direction"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
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
        await page.mouse.wheel(dx, dy)
        return f"scrolled {direction} {amount}px"


class WaitMsAction(AgentAction):
    description: ClassVar[str] = "Wait for UI or network; capped at 120s."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"ms": {"type": "integer"}},
        "required": ["ms"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        ms = int(args.get("ms", 1000))
        await page.wait_for_timeout(min(max(ms, 0), 120_000))
        return f"waited {ms}ms"


class SelectOptionAction(AgentAction):
    description: ClassVar[str] = (
        "Select an option in a select element. Provide value or label (or both)."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "value": {"type": "string", "description": "Option value attribute"},
            "label": {"type": "string", "description": "Visible label"},
        },
        "required": ["ref"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        ref = str(args.get("ref", ""))
        value = args.get("value")
        label = args.get("label")
        if not _REF_SEL.match(ref):
            return "error: invalid ref"
        loc = page.locator(_ref_selector(ref))
        if value is not None:
            await loc.select_option(value=str(value), timeout=15_000)
        elif label is not None:
            await loc.select_option(label=str(label), timeout=15_000)
        else:
            return "error: need value or label"
        return f"selected ref={ref}"


class ScreenshotViewportJpegAction(AgentAction):
    """Not registered in agent tool specs; kept for reuse or manual wiring."""

    description: ClassVar[str] = (
        "Save a viewport JPEG under log/screenshots for debugging or archival."
    )
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        buf = await page.screenshot(type="jpeg", quality=80)
        out_dir = repo_root / "log" / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{session_id[:8]}_{uuid.uuid4().hex[:10]}.jpg"
        path = out_dir / fname
        path.write_bytes(buf)
        return f"saved {path.relative_to(repo_root)}"


class CloseCurrentTabAction(AgentAction):
    description: ClassVar[str] = (
        "Close the active (top) browser tab for this session. The previous tab in the stack "
        "becomes active. If it was the last tab, the session has no live browser until the next action."
    )
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        return ""


class ExportPagePdfAction(AgentAction):
    description: ClassVar[str] = "Export the current page to PDF (print layout) under log/pdf."
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        assert page is not None
        out_dir = repo_root / "log" / "pdf"
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{session_id[:8]}_{uuid.uuid4().hex[:10]}.pdf"
        path = out_dir / fname
        await page.pdf(path=str(path), print_background=True)
        return f"saved {path.relative_to(repo_root)}"
