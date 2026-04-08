from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from browser_agent.actions.base import AgentAction
from browser_agent.actions.browser import (
    ClickAction,
    CloseCurrentTabAction,
    ExportPagePdfAction,
    FillAction,
    GetDetailedObservationAction,
    GetObservationAction,
    GoBackAction,
    NavigateAction,
    PressKeyAction,
    ScrollAction,
    SelectOptionAction,
    WaitMsAction,
)
from browser_agent.actions.control import DoneAction
from browser_agent.actions.pdf import ConvertPdfToMarkdownAction
from browser_agent.browser_manager import BrowserManager
from browser_agent.page_context_builder import PageContextBuilder

_TOOL_CLASSES: tuple[type[AgentAction], ...] = (
    GetObservationAction,
    GetDetailedObservationAction,
    NavigateAction,
    GoBackAction,
    ClickAction,
    FillAction,
    PressKeyAction,
    ScrollAction,
    WaitMsAction,
    SelectOptionAction,
    ExportPagePdfAction,
    CloseCurrentTabAction,
    ConvertPdfToMarkdownAction,
    DoneAction,
)

TOOLS_REQUIRING_BROWSER: frozenset[str] = frozenset(
    {
        GetObservationAction.name,
        GetDetailedObservationAction.name,
        NavigateAction.name,
        GoBackAction.name,
        ClickAction.name,
        FillAction.name,
        PressKeyAction.name,
        ScrollAction.name,
        WaitMsAction.name,
        SelectOptionAction.name,
        ExportPagePdfAction.name,
        CloseCurrentTabAction.name,
    }
)

_spec_cache: list[dict[str, Any]] | None = None
_name_index: dict[str, type[AgentAction]] | None = None


def _config_path(repo_root: Path) -> Path:
    override = os.environ.get("BROWSER_AGENT_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return repo_root / "config.json"


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_post_action_stabilize_ms(repo_root: Path) -> int:
    data = _read_json_object(_config_path(repo_root))
    browser = data.get("browser")
    if not isinstance(browser, dict):
        return 0
    raw = browser.get("tool_call_delay_ms", 0)
    try:
        ms = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, ms)


def _resolve_post_action_wait_load(repo_root: Path) -> bool:
    data = _read_json_object(_config_path(repo_root))
    browser = data.get("browser")
    if not isinstance(browser, dict):
        return True
    raw = browser.get("post_action_wait_load_state", True)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.lower() in ("1", "true", "yes")
    return bool(raw)


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
    if name not in TOOLS_REQUIRING_BROWSER:
        try:
            return await cls()(
                page=None,
                repo_root=repo_root,
                session_id=session_id,
                args=args,
            )
        except Exception as e:
            return f"error: {e}"

    stabilize_ms = _resolve_post_action_stabilize_ms(repo_root)
    wait_load = _resolve_post_action_wait_load(repo_root)

    if name == CloseCurrentTabAction.name:
        depth_before = browser.stack_depth(session_id)
        try:
            phase1 = await browser.close_current_page(session_id)
        except Exception as e:
            return f"error: {e}"
        await browser.stabilize_after_action(
            session_id, stabilize_ms=stabilize_ms, wait_load_state=wait_load
        )
        stack_block = await browser.format_stack_report(session_id, depth_before)
        return f"{phase1}\n{stack_block}"

    page: Page | None = None
    try:
        page = await browser.ensure_page(session_id)
    except Exception as e:
        return f"error: {e}"

    depth_before = browser.stack_depth(session_id)

    try:
        if name in (GetObservationAction.name, GetDetailedObservationAction.name):
            phase1 = ""
        else:
            phase1 = await cls()(
                page=page,
                repo_root=repo_root,
                session_id=session_id,
                args=args,
            )
    except Exception as e:
        return f"error: {e}"

    await browser.stabilize_after_action(
        session_id, stabilize_ms=stabilize_ms, wait_load_state=wait_load
    )

    top = browser.get_page_if_exists(session_id)
    if name == GetObservationAction.name:
        if top is None:
            body = "error: no active tab for observation"
        else:
            try:
                body = await PageContextBuilder.build(top)
            except Exception as e:
                body = f"error: observation failed: {e}"
    elif name == GetDetailedObservationAction.name:
        if top is None:
            body = "error: no active tab for observation"
        else:
            try:
                body = await PageContextBuilder.build_aria_snapshot(top)
            except Exception as e:
                body = f"error: detailed observation failed: {e}"
    else:
        body = phase1

    stack_block = await browser.format_stack_report(session_id, depth_before)
    if body.endswith("\n"):
        return f"{body}{stack_block}"
    return f"{body}\n{stack_block}"
