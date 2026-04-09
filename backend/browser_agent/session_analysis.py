"""Prompts and transcript formatting for post-hoc session / flow analysis."""

from __future__ import annotations

import json
from typing import Any

SESSION_ANALYSIS_SYSTEM_PROMPT = """The transcript and session metadata are ABOVE this block (same user message). You are a senior automation analyst. Each line block is one stored message with its database message_id; long JSON may be truncated per block with a per-block character cap. There is no global cap on how many blocks—only per-block truncation. Analyze the full sequence end-to-end.

Your job is to produce a clear, actionable playbook that lets a human or an agent repeat the same end-to-end workflow later, with explicit logic chains.

For every meaningful step (each user turn, each assistant message, each tool result row—use message_id to refer to rows), cover:

1) What happened (short title).
2) Who acted: user (instruction), assistant (planning/text), or tool (browser/system).
3) Exact tool/function name and parsed arguments when applicable (summarize huge payloads).
4) Was this step necessary for reaching the goal, or redundant / exploratory / retry? Say why briefly.
5) Logic chain — action basis (be explicit):
   - Basis type: content-driven (depends on live page text, snapshot, refs, layout) vs fixed (would be the same without looking at the page) vs hybrid.
   - If navigation or click: state the URL pattern (exact URL if fixed; pattern, query keys, or "unknown/dynamic" if not). Say whether the URL was chosen from observation or from user text alone.
   - If click/fill/hover: was the target chosen from refs/labels seen in observation? Cite the observable cue (button text, role, ref) vs "blind" sequence.
   - Stability: is this action stable across runs (same URL, same control text) or may change (dynamic lists, A/B, locale, login state)? Mark fixed | likely_stable | may_change | unknown.
6) If the step depends on prior tool output, name that dependency using message_id when possible (e.g. "uses refs from message_id=12").

Then provide:

A) A narrative timeline (numbered, reference message_id).
B) A flowchart in Mermaid syntax (`flowchart TD` or `flowchart LR`). Each node label must encode the action basis (e.g. "Click 'Submit' [content-driven, refs from obs msg 12]" or "Open https://example.com/foo [fixed URL]").
C) A "Replay checklist": minimal ordered steps to reproduce, each with basis + stability.
D) Risks and fallbacks: what could differ next time and how to adapt.

Use Markdown headings (## / ###). Write primarily in the same language as the user messages in the transcript; if mixed, use English for structure and mirror user language where helpful.

If the transcript is empty or too sparse, say what is missing instead of inventing steps."""

PER_MESSAGE_CHAR_LIMIT = 8000

_INSTRUCTIONS_SEPARATOR = "\n\n<<<ANALYSIS_INSTRUCTIONS>>>\n\n"


def _truncate_segment(text: str, limit: int) -> str:
    t = text or ""
    if limit <= 0 or len(t) <= limit:
        return t
    head = t[:limit]
    return f"{head}\n\n[... truncated {len(t) - limit} chars ...]"


def build_session_analysis_user_content(
    message_rows: list[tuple[int, dict[str, Any]]],
    *,
    session_meta: dict[str, Any] | None = None,
    per_message_char_limit: int = PER_MESSAGE_CHAR_LIMIT,
    instructions: str = SESSION_ANALYSIS_SYSTEM_PROMPT,
) -> str:
    """One concatenated user payload: metadata + each DB message (id + truncated JSON) + instructions last.

    ``message_rows`` is (message_row_id, payload) in chronological order, matching ``MessageRow.id``.
    """
    lim = per_message_char_limit
    chunks: list[str] = []

    if session_meta:
        meta_s = json.dumps(session_meta, ensure_ascii=False)
        chunks.append(
            f"[session_meta]\n{_truncate_segment(meta_s, lim)}"
        )

    for mid, payload in message_rows:
        role = payload.get("role", "?")
        line = json.dumps(payload, ensure_ascii=False)
        chunks.append(
            f"[message_id={mid} role={role}]\n{_truncate_segment(line, lim)}"
        )

    body = "\n\n".join(chunks)
    return f"{body}{_INSTRUCTIONS_SEPARATOR}\n\n{instructions.strip()}"
