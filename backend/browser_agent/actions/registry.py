from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Page

from browser_agent.actions.base import AgentAction
from browser_agent.actions.browser import (
    ClickAction,
    ExportPagePdfAction,
    FillAction,
    GetObservationAction,
    GoBackAction,
    NavigateAction,
    PressKeyAction,
    ScreenshotViewportJpegAction,
    ScrollAction,
    SelectOptionAction,
    WaitMsAction,
)
from browser_agent.actions.control import DoneAction
from browser_agent.actions.pdf import ConvertPdfToMarkdownAction
from browser_agent.browser_manager import BrowserManager

_TOOL_CLASSES: tuple[type[AgentAction], ...] = (
    GetObservationAction,
    NavigateAction,
    GoBackAction,
    ClickAction,
    FillAction,
    PressKeyAction,
    ScrollAction,
    WaitMsAction,
    SelectOptionAction,
    ScreenshotViewportJpegAction,
    ExportPagePdfAction,
    ConvertPdfToMarkdownAction,
    DoneAction,
)

TOOLS_REQUIRING_BROWSER: frozenset[str] = frozenset(
    {
        GetObservationAction.name,
        NavigateAction.name,
        GoBackAction.name,
        ClickAction.name,
        FillAction.name,
        PressKeyAction.name,
        ScrollAction.name,
        WaitMsAction.name,
        SelectOptionAction.name,
        ScreenshotViewportJpegAction.name,
        ExportPagePdfAction.name,
    }
)

_spec_cache: list[dict[str, Any]] | None = None
_name_index: dict[str, type[AgentAction]] | None = None


def get_agent_tool_specs() -> list[dict[str, Any]]:
    global _spec_cache
    if _spec_cache is None:
        _spec_cache = [cls.tool_dict() for cls in _TOOL_CLASSES]
    return _spec_cache


def _registry_by_name() -> dict[str, type[AgentAction]]:
    global _name_index
    if _name_index is None:
        _name_index = {cls.name: cls for cls in _TOOL_CLASSES}
    return _name_index


async def execute_action(
    name: str,
    *,
    browser: BrowserManager,
    session_id: str,
    repo_root: Path,
    args: dict[str, Any],
) -> str:
    cls = _registry_by_name().get(name)
    if cls is None:
        return f"error: unknown tool {name}"
    page: Page | None = None
    if name in TOOLS_REQUIRING_BROWSER:
        page = await browser.ensure_page(session_id)
    try:
        return await cls()(
            page=page,
            repo_root=repo_root,
            session_id=session_id,
            args=args,
        )
    except Exception as e:
        return f"error: {e}"
