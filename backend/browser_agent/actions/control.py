from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from playwright.async_api import Page

from browser_agent.actions.base import AgentAction


class DoneAction(AgentAction):
    description: ClassVar[str] = "Finish the task when the user goal is satisfied."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"summary": {"type": "string", "description": "Short outcome summary"}},
        "required": ["summary"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        return str(args.get("summary", ""))
