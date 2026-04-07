from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, ClassVar

import httpx
from playwright.async_api import Page

from browser_agent.actions.base import AgentAction


def _api_base() -> str:
    base = (os.environ.get("PDF_READER_API_BASE") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("PDF_READER_API_BASE is not set")
    return base


def _is_failed_status(status: str) -> bool:
    return status.lower() in {"failed", "error", "cancelled"}


def _is_complete_status(status: str, progress: int) -> bool:
    s = status.lower()
    if s == "completed":
        return True
    return progress >= 100 and not _is_failed_status(s)


async def _upload(client: httpx.AsyncClient, base: str, pdf_path: Path) -> dict:
    data = pdf_path.read_bytes()
    files = {"file": (pdf_path.name, data, "application/pdf")}
    r = await client.post(f"{base}/api/upload-pdf", files=files, timeout=120.0)
    r.raise_for_status()
    return r.json()


async def _get_document(client: httpx.AsyncClient, base: str, document_id: int) -> dict:
    r = await client.get(f"{base}/api/documents/{document_id}", timeout=60.0)
    r.raise_for_status()
    return r.json()


async def _get_markdown_text(client: httpx.AsyncClient, base: str, document_id: int) -> str:
    r = await client.get(f"{base}/api/documents/{document_id}/markdown", timeout=120.0)
    r.raise_for_status()
    return r.text


async def _convert_pdf_via_reader_api(
    pdf_path: Path,
    *,
    poll_interval_sec: float = 2.0,
    max_wait_sec: float = 900.0,
) -> tuple[int, str]:
    base = _api_base()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait_sec

    async with httpx.AsyncClient() as client:
        up = await _upload(client, base, pdf_path)
        if not up.get("success"):
            raise RuntimeError(str(up.get("message") or "upload failed"))
        document_id = int(up["document_id"])

        while loop.time() < deadline:
            doc = await _get_document(client, base, document_id)
            profile = doc.get("paper_profile") or {}
            cstatus = str(profile.get("conversion_status") or "")
            progress = int(profile.get("conversion_progress") or 0)
            if cstatus and _is_failed_status(cstatus):
                msg = profile.get("conversion_message") or "conversion failed"
                raise RuntimeError(str(msg))
            if cstatus and _is_complete_status(cstatus, progress):
                text = await _get_markdown_text(client, base, document_id)
                return document_id, text
            await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"timed out after {int(max_wait_sec)}s waiting for document {document_id}")


def _markdown_download_url(document_id: int) -> str:
    return f"{_api_base()}/api/documents/{document_id}/markdown/download"


class ConvertPdfToMarkdownAction(AgentAction):
    description: ClassVar[str] = (
        "Upload a PDF to the configured PDF Reader API (PDF_READER_API_BASE), wait until "
        "conversion_status is completed, then return markdown text. Saves a copy under log/markdown. "
        "Use a path relative to the project root (e.g. log/pdf/abc.pdf) or an absolute path."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "pdf_path": {
                "type": "string",
                "description": "Path to the .pdf file, relative to project root or absolute",
            },
        },
        "required": ["pdf_path"],
    }

    async def __call__(
        self,
        *,
        page: Page | None,
        repo_root: Path,
        session_id: str,
        args: dict[str, Any],
    ) -> str:
        raw = str(args.get("pdf_path") or "").strip()
        if not raw:
            return "error: missing pdf_path"
        p = Path(raw)
        if not p.is_absolute():
            p = (repo_root / p).resolve()
        else:
            p = p.resolve()
        if not p.is_file():
            return f"error: pdf not found: {p}"
        if p.suffix.lower() != ".pdf":
            return "error: file must be .pdf"
        try:
            doc_id, md = await _convert_pdf_via_reader_api(p)
        except Exception as e:
            return f"error: {e}"
        out_dir = repo_root / "log" / "markdown"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{session_id[:8]}_{doc_id}.md"
        out_path.write_text(md, encoding="utf-8")
        rel = out_path.relative_to(repo_root)
        dl = _markdown_download_url(doc_id)
        cap = 50_000
        header = f"document_id={doc_id}\nsaved {rel}\ndownload {dl}\n\n---\n\n"
        if len(md) <= cap:
            return header + md
        return (
            f"document_id={doc_id}\nsaved {rel}\ndownload {dl}\n"
            f"markdown truncated in tool result ({cap} of {len(md)} chars); full content on disk.\n\n---\n\n"
            f"{md[:cap]}\n\n... [truncated]"
        )
