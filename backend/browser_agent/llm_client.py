from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from browser_agent.audit_logging import JsonlAudit
from browser_agent.llm_config import resolve_llm_settings


class LlmClient:
    def __init__(self, repo_root: Path | None = None) -> None:
        key, base, model, temperature = resolve_llm_settings(repo_root)
        kwargs: dict[str, Any] = {"api_key": key}
        if base:
            kwargs["base_url"] = base
        self._client = AsyncOpenAI(**kwargs)
        self._model = model
        self._temperature = temperature

    @property
    def model(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[ChatCompletionMessageParam],
        tools: list[dict[str, Any]],
        *,
        session_id: str,
        turn: int,
        audit: JsonlAudit,
    ):
        audit.emit(
            {
                "type": "llm_request",
                "session_id": session_id,
                "turn": turn,
                "model": self._model,
                "messages": list(messages),
            }
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self._temperature,
            )
        except Exception as e:
            logger.exception("LLM request failed")
            audit.emit(
                {
                    "type": "llm_error",
                    "session_id": session_id,
                    "turn": turn,
                    "error": str(e),
                }
            )
            raise

        ch = resp.choices[0]
        msg = ch.message
        tool_calls_serial = None
        if msg.tool_calls:
            tool_calls_serial = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        usage = resp.usage.model_dump() if resp.usage else None
        audit.emit(
            {
                "type": "llm_response",
                "session_id": session_id,
                "turn": turn,
                "finish_reason": ch.finish_reason,
                "content": msg.content,
                "tool_calls": tool_calls_serial,
                "usage": usage,
            }
        )
        return ch
