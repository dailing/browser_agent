import json
from pathlib import Path
from typing import Any

from loguru import logger
from openai.types.chat import ChatCompletionMessageParam

from browser_agent.action_executor import ActionExecutor
from browser_agent.audit_logging import JsonlAudit
from browser_agent.browser_manager import BrowserManager
from browser_agent.llm_client import LlmClient
from browser_agent.page_context_builder import PageContextBuilder
from browser_agent.session_fanout import SessionFanout
from browser_agent.session_store import SessionStore
from browser_agent.tools_spec import AGENT_TOOLS

SYSTEM_PROMPT = """You control a headless Chromium tab via tools. The user cannot click; only you can.
Rules:
- After navigate or go_back, call get_observation before clicking or filling.
- Use refs exactly as shown in observations ([ref=N]). Do not invent refs.
- Prefer small steps: observe, act, observe again.
- When the goal is fully satisfied, call done with a concise summary.
- If stuck after retries, call done summarizing what blocked you."""


def _assistant_api_dict(msg) -> dict[str, Any]:
    d: dict[str, Any] = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = [
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
    return d


def _tool_result_audit_content(name: str, result: str) -> str | dict[str, Any]:
    if name == "get_observation" and len(result) > 6000:
        return {"truncated": True, "head": result[:6000], "total_len": len(result)}
    return result


class RunCoordinator:
    def __init__(
        self,
        repo_root: Path,
        browser: BrowserManager,
        store: SessionStore,
        fanout: SessionFanout,
        audit: JsonlAudit,
    ) -> None:
        self._repo_root = repo_root
        self._browser = browser
        self._store = store
        self._fanout = fanout
        self._audit = audit

    async def _append_and_broadcast(self, session_id: str, message: dict[str, Any]) -> None:
        self._store.append_message(session_id, message)
        self._audit.emit({"type": "conversation_message", "session_id": session_id, "message": message})
        await self._fanout.broadcast(session_id, {"type": "message", "message": message})

    async def run(self, session_id: str, max_steps: int = 40) -> None:
        session = self._store.get(session_id)
        if session is None:
            return

        self._audit.emit(
            {
                "type": "run_start",
                "session_id": session_id,
                "goal": session.goal,
                "max_steps": max_steps,
            }
        )
        await self._fanout.broadcast(
            session_id,
            {
                "type": "snapshot",
                "session_id": session_id,
                "status": session.status,
                "messages": list(session.messages),
            },
        )

        try:
            llm = LlmClient()
        except RuntimeError as e:
            logger.error("{}", e)
            self._store.set_status(session_id, "failed", str(e))
            self._audit.emit({"type": "run_failed", "session_id": session_id, "error": str(e)})
            await self._fanout.broadcast(
                session_id,
                {"type": "status", "session_id": session_id, "status": "failed", "error": str(e)},
            )
            return

        page = self._browser.page
        builder = PageContextBuilder(page)
        executor = ActionExecutor(page, self._repo_root, builder)

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        for m in session.messages:
            messages.append(dict(m))  # type: ignore[arg-type]

        turn = 0
        stop_reason: str | None = None
        try:
            while turn < max_steps:
                turn += 1
                choice = await llm.chat(
                    messages,
                    AGENT_TOOLS,
                    session_id=session_id,
                    turn=turn,
                    audit=self._audit,
                )
                msg = choice.message

                if not msg.tool_calls and (msg.content or "").strip():
                    rec = _assistant_api_dict(msg)
                    messages.append(rec)  # type: ignore[arg-type]
                    await self._append_and_broadcast(session_id, rec)
                    self._store.set_status(session_id, "completed")
                    stop_reason = "assistant_text"
                    break

                if msg.tool_calls:
                    rec = _assistant_api_dict(msg)
                    messages.append(rec)  # type: ignore[arg-type]
                    await self._append_and_broadcast(session_id, rec)

                    for tc in msg.tool_calls:
                        name = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError as e:
                            err = f"error: bad tool arguments: {e}"
                            self._audit.emit(
                                {
                                    "type": "tool_call",
                                    "session_id": session_id,
                                    "turn": turn,
                                    "name": name,
                                    "arguments": tc.function.arguments,
                                    "parse_error": str(e),
                                }
                            )
                            tool_payload: dict[str, Any] = {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": err,
                            }
                            messages.append(tool_payload)  # type: ignore[arg-type]
                            await self._append_and_broadcast(session_id, tool_payload)
                            continue

                        self._audit.emit(
                            {
                                "type": "tool_call",
                                "session_id": session_id,
                                "turn": turn,
                                "name": name,
                                "arguments": args,
                            }
                        )

                        if name == "done":
                            summary = str(args.get("summary", ""))
                            self._audit.emit(
                                {
                                    "type": "tool_result",
                                    "session_id": session_id,
                                    "turn": turn,
                                    "name": name,
                                    "content": summary,
                                }
                            )
                            tool_payload = {"role": "tool", "tool_call_id": tc.id, "content": summary}
                            messages.append(tool_payload)  # type: ignore[arg-type]
                            await self._append_and_broadcast(session_id, tool_payload)
                            self._store.set_status(session_id, "completed")
                            stop_reason = "done_tool"
                            break

                        result = await executor.execute(session_id, name, args)
                        self._audit.emit(
                            {
                                "type": "tool_result",
                                "session_id": session_id,
                                "turn": turn,
                                "name": name,
                                "content": _tool_result_audit_content(name, result),
                            }
                        )
                        tool_payload = {"role": "tool", "tool_call_id": tc.id, "content": result}
                        messages.append(tool_payload)  # type: ignore[arg-type]
                        await self._append_and_broadcast(session_id, tool_payload)

                    if stop_reason == "done_tool":
                        break
                    continue

                stop_reason = "empty_turn"
                self._store.set_status(session_id, "failed", "empty_llm_turn")
                break

            if stop_reason is None:
                self._store.set_status(session_id, "failed", "max_steps_exceeded")
                self._audit.emit({"type": "run_max_steps", "session_id": session_id, "max_steps": max_steps})

        except Exception as e:
            logger.exception("Run failed")
            self._store.set_status(session_id, "failed", str(e))
            self._audit.emit({"type": "run_failed", "session_id": session_id, "error": str(e)})
            await self._append_and_broadcast(
                session_id,
                {"role": "assistant", "content": f"_Run error: {e}_"},
            )

        final = self._store.get(session_id)
        st = final.status if final else "unknown"
        self._audit.emit({"type": "run_end", "session_id": session_id, "status": st})
        await self._fanout.broadcast(
            session_id,
            {"type": "status", "session_id": session_id, "status": st, "error": final.error if final else None},
        )
