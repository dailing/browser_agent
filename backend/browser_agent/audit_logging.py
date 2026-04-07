import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


def setup_process_logging(repo_root: Path) -> tuple[Path, Path]:
    log_dir = repo_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "Z"
    pid = os.getpid()
    jsonl_path = log_dir / f"run_{stamp}_{pid}.jsonl"
    text_path = log_dir / f"run_{stamp}_{pid}.log"
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}",
    )
    logger.add(
        text_path,
        level="DEBUG",
        format="{time:ISO} | {level} | {message}",
        encoding="utf-8",
    )
    logger.info("Log files: jsonl={} text={}", jsonl_path, text_path)
    return jsonl_path, text_path


class JsonlAudit:
    def __init__(self, jsonl_path: Path) -> None:
        self._path = jsonl_path
        self._fp = open(jsonl_path, "a", encoding="utf-8")

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def emit(self, event: dict[str, Any]) -> None:
        rec = {
            **event,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        line = json.dumps(rec, ensure_ascii=False, default=str)
        self._fp.write(line + "\n")
        self._fp.flush()
        logger.debug("audit {}", line[:500] + ("..." if len(line) > 500 else ""))
