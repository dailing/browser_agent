from pathlib import Path
from typing import Any

from browser_agent.actions import execute_action
from browser_agent.browser_manager import BrowserManager


class ActionExecutor:
    def __init__(self, browser: BrowserManager, repo_root: Path) -> None:
        self._browser = browser
        self._repo_root = repo_root

    async def execute(self, session_id: str, name: str, args: dict[str, Any]) -> str:
        return await execute_action(
            name,
            browser=self._browser,
            session_id=session_id,
            repo_root=self._repo_root,
            args=args,
        )
