import json
import os
import asyncio
from pathlib import Path
from typing import Any

from loguru import logger
from openai.types.chat import ChatCompletionMessageParam

from browser_agent.action_executor import ActionExecutor
from browser_agent.audit_logging import JsonlAudit
from browser_agent.browser_manager import BrowserManager
from browser_agent.llm_client import LlmClient
from browser_agent.actions.registry import TOOLS_REQUIRING_BROWSER
from browser_agent.session_fanout import SessionFanout
from browser_agent.session_store import DbSessionStore
from browser_agent.tools_spec import AGENT_TOOLS

SYSTEM_PROMPT = """You control a headless Chromium tab via tools. The user cannot click; only you can.
The conversation may continue across multiple user messages: answer the latest request using full prior context.
Rules:
- After navigate or go_back, call get_observation before clicking or filling.
- Use refs exactly as shown in observations ([ref=N]). Do not invent refs.
- Prefer small steps: observe, act, observe again.
- To turn a page into markdown text: export_page_pdf (saves under log/pdf), then convert_pdf_to_markdown with that pdf_path (relative to project root). The tool returns markdown and a download URL from the PDF Reader API.
- When the user's request is fully satisfied for this turn, call done with a concise summary.
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
    if name == "convert_pdf_to_markdown" and len(result) > 8000:
        return {"truncated": True, "head": result[:8000], "total_len": len(result)}
    return result


def _first_user_task_preview(messages: list[dict[str, Any]], limit: int = 500) -> str:
    for m in messages:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str) and c.strip():
            return c[:limit]
    return ""


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


def _resolve_tool_call_delay_ms(repo_root: Path) -> int:
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


def _invalid_tool_call_argument_error(msg) -> str | None:
    if not msg.tool_calls:
        return None
    for tc in msg.tool_calls:
        raw = tc.function.arguments or "{}"
        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            return (
                f"invalid tool arguments from model: tool={tc.function.name} id={tc.id} "
                f"error={e.msg} at line {e.lineno} col {e.colno}"
            )
    return None


class RunCoordinator:
    def __init__(
        self,
        repo_root: Path,
        browser: BrowserManager,
        store: DbSessionStore,
        fanout: SessionFanout,
        audit: JsonlAudit,
    ) -> None:
        self._repo_root = repo_root
        self._browser = browser
        self._store = store
        self._fanout = fanout
        self._audit = audit
        self._tool_call_delay_ms = _resolve_tool_call_delay_ms(repo_root)

    async def _append_and_broadcast(self, session_id: str, message: dict[str, Any]) -> None:
        await self._store.append_message(session_id, message)
        self._audit.emit({"type": "conversation_message", "session_id": session_id, "message": message})
        await self._fanout.broadcast(session_id, {"type": "message", "message": message})

    async def run(self, session_id: str) -> None:
        session = await self._store.get(session_id)
        if session is None:
            return

        max_steps = session.max_steps
        self._audit.emit(
            {
                "type": "run_start",
                "session_id": session_id,
                "name": session.name,
                "task_preview": _first_user_task_preview(session.messages),
                "max_steps": max_steps,
            }
        )
        has_tab = self._browser.has_live_tab(session_id)
        await self._fanout.broadcast(
            session_id,
            {
                "type": "snapshot",
                "session_id": session_id,
                "status": session.status,
                "messages": list(session.messages),
                "has_live_tab": has_tab,
            },
        )

        try:
            llm = LlmClient(self._repo_root)
        except (RuntimeError, ValueError) as e:
            logger.error("{}", e)
            await self._store.set_status(session_id, "failed", str(e))
            self._audit.emit({"type": "run_failed", "session_id": session_id, "error": str(e)})
            await self._fanout.broadcast(
                session_id,
                {"type": "status", "session_id": session_id, "status": "failed", "error": str(e)},
            )
            return

        self._browser.touch_tab_activity_if_exists(session_id)
        executor = ActionExecutor(self._browser, self._repo_root)

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        for m in session.messages:
            messages.append(dict(m))  # type: ignore[arg-type]

        turn = 0
        stop_reason: str | None = None
        llm_invalid_args_retries = 3
        try:
            while turn < max_steps:
                turn += 1
                msg = None
                last_invalid_error: str | None = None
                for attempt in range(1, llm_invalid_args_retries + 1):
                    choice = await llm.chat(
                        messages,
                        AGENT_TOOLS,
                        session_id=session_id,
                        turn=turn,
                        audit=self._audit,
                    )
                    candidate = choice.message
                    invalid_err = _invalid_tool_call_argument_error(candidate)
                    if invalid_err is None:
                        msg = candidate
                        break
                    last_invalid_error = invalid_err
                    self._audit.emit(
                        {
                            "type": "llm_invalid_tool_arguments",
                            "session_id": session_id,
                            "turn": turn,
                            "attempt": attempt,
                            "error": invalid_err,
                        }
                    )
                if msg is None:
                    err = (
                        f"llm produced invalid tool arguments after {llm_invalid_args_retries} attempts: "
                        f"{last_invalid_error or 'unknown_error'}"
                    )
                    await self._store.set_status(session_id, "failed", err)
                    self._audit.emit({"type": "run_failed", "session_id": session_id, "error": err})
                    await self._append_and_broadcast(
                        session_id,
                        {"role": "assistant", "content": f"_Run error: {err}_"},
                    )
                    stop_reason = "invalid_tool_arguments"
                    break

                if not msg.tool_calls and (msg.content or "").strip():
                    rec = _assistant_api_dict(msg)
                    messages.append(rec)  # type: ignore[arg-type]
                    await self._append_and_broadcast(session_id, rec)
                    await self._store.set_status(session_id, "idle", None)
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

                        result = await executor.execute(session_id, name, args)
                        if name in TOOLS_REQUIRING_BROWSER:
                            self._browser.touch_tab_activity_if_exists(session_id)
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
                        if self._tool_call_delay_ms > 0:
                            await asyncio.sleep(self._tool_call_delay_ms / 1000.0)

                        if name == "done":
                            await self._store.set_status(session_id, "idle", None)
                            stop_reason = "done_tool"
                            break

                    if stop_reason == "done_tool":
                        break
                    continue

                stop_reason = "empty_turn"
                await self._store.set_status(session_id, "failed", "empty_llm_turn")
                break

            if stop_reason is None:
                await self._store.set_status(session_id, "failed", "max_steps_exceeded")
                self._audit.emit({"type": "run_max_steps", "session_id": session_id, "max_steps": max_steps})

        except Exception as e:
            logger.exception("Run failed")
            await self._store.set_status(session_id, "failed", str(e))
            self._audit.emit({"type": "run_failed", "session_id": session_id, "error": str(e)})
            await self._append_and_broadcast(
                session_id,
                {"role": "assistant", "content": f"_Run error: {e}_"},
            )

        final = await self._store.get(session_id)
        st = final.status if final else "unknown"
        self._audit.emit({"type": "run_end", "session_id": session_id, "status": st})
        await self._fanout.broadcast(
            session_id,
            {"type": "status", "session_id": session_id, "status": st, "error": final.error if final else None},
        )
