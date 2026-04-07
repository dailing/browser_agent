from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from playwright.async_api import Page


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def default_tool_name(class_name: str) -> str:
    if class_name.endswith("Action"):
        class_name = class_name[:-6]
    return _camel_to_snake(class_name)


class AgentAction(ABC):
    """One LLM tool: OpenAI tool dict from class attrs; runtime via async __call__(...)."""

    name: ClassVar[str] = ""
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "name" not in cls.__dict__ or not cls.__dict__["name"]:
            cls.name = default_tool_name(cls.__name__)

    @classmethod
    def tool_dict(cls) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": cls.parameters,
            },
        }

    @abstractmethod
    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        ...
