import asyncio
from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from browser_agent.audit_logging import JsonlAudit
from browser_agent.llm_config import resolve_llm_settings

_OVERLOAD_RETRY_DELAYS_SEC = (30, 60, 120, 120)


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
        for attempt in range(len(_OVERLOAD_RETRY_DELAYS_SEC) + 1):
            try:
                resp = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=self._temperature,
                )
                break
            except Exception as e:
                will_retry = attempt < len(_OVERLOAD_RETRY_DELAYS_SEC)
                audit.emit(
                    {
                        "type": "llm_error",
                        "session_id": session_id,
                        "turn": turn,
                        "attempt": attempt + 1,
                        "will_retry": will_retry,
                        "error": str(e),
                    }
                )
                if attempt < len(_OVERLOAD_RETRY_DELAYS_SEC):
                    delay_sec = _OVERLOAD_RETRY_DELAYS_SEC[attempt]
                    logger.warning(
                        "LLM request failed; retrying in {}s (attempt {}/{})",
                        delay_sec,
                        attempt + 1,
                        len(_OVERLOAD_RETRY_DELAYS_SEC),
                    )
                    audit.emit(
                        {
                            "type": "llm_retry",
                            "session_id": session_id,
                            "turn": turn,
                            "attempt": attempt + 1,
                            "delay_sec": delay_sec,
                            "reason": "llm_request_error",
                            "error": str(e),
                        }
                    )
                    await asyncio.sleep(delay_sec)
                    continue

                logger.error("LLM request failed after retries: {}", e)
                return None

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

    async def chat_no_tools(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        session_id: str,
        audit: JsonlAudit,
        purpose: str = "text",
    ):
        """Single completion without tool calling (e.g. session analysis)."""
        audit.emit(
            {
                "type": "llm_request",
                "session_id": session_id,
                "turn": 0,
                "model": self._model,
                "messages": list(messages),
                "purpose": purpose,
            }
        )
        for attempt in range(len(_OVERLOAD_RETRY_DELAYS_SEC) + 1):
            try:
                resp = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=self._temperature,
                )
                break
            except Exception as e:
                will_retry = attempt < len(_OVERLOAD_RETRY_DELAYS_SEC)
                audit.emit(
                    {
                        "type": "llm_error",
                        "session_id": session_id,
                        "turn": 0,
                        "attempt": attempt + 1,
                        "will_retry": will_retry,
                        "purpose": purpose,
                        "error": str(e),
                    },
                )
                if attempt < len(_OVERLOAD_RETRY_DELAYS_SEC):
                    delay_sec = _OVERLOAD_RETRY_DELAYS_SEC[attempt]
                    logger.warning(
                        "LLM request failed; retrying in {}s (attempt {}/{})",
                        delay_sec,
                        attempt + 1,
                        len(_OVERLOAD_RETRY_DELAYS_SEC),
                    )
                    audit.emit(
                        {
                            "type": "llm_retry",
                            "session_id": session_id,
                            "turn": 0,
                            "attempt": attempt + 1,
                            "delay_sec": delay_sec,
                            "purpose": purpose,
                            "reason": "llm_request_error",
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(delay_sec)
                    continue
                logger.error("LLM request failed after retries: {}", e)
                return None

        ch = resp.choices[0]
        msg = ch.message
        usage = resp.usage.model_dump() if resp.usage else None
        audit.emit(
            {
                "type": "llm_response",
                "session_id": session_id,
                "turn": 0,
                "finish_reason": ch.finish_reason,
                "content": msg.content,
                "tool_calls": None,
                "usage": usage,
                "purpose": purpose,
            },
        )
        return ch
