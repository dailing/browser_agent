import json
import os
from pathlib import Path
from typing import Any


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def load_llm_section(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or repo_root_from_here()
    override = os.environ.get("BROWSER_AGENT_CONFIG")
    cfg_path = Path(override).expanduser().resolve() if override else root / "config.json"
    if not cfg_path.is_file():
        return {}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON in {cfg_path}: {e.msg} (line {e.lineno}, column {e.colno}). "
            "Use strict JSON: double-quoted keys, no trailing commas, no // comments."
        ) from e
    llm = data.get("llm")
    return llm if isinstance(llm, dict) else {}


def resolve_llm_settings(repo_root: Path | None = None) -> tuple[str, str | None, str, float]:
    cfg = load_llm_section(repo_root)
    key = os.environ.get("OPENAI_API_KEY") or str(cfg.get("api_key") or "").strip()
    if not key or key == "REPLACE_WITH_YOUR_MINIMAX_OR_OPENAI_KEY":
        raise RuntimeError(
            "LLM api_key missing: set OPENAI_API_KEY or llm.api_key in config.json (see config.example.json)"
        )
    base = os.environ.get("OPENAI_BASE_URL")
    if base is None:
        b = cfg.get("base_url")
        base = str(b).strip() if b else None
    model = os.environ.get("OPENAI_MODEL") or str(cfg.get("model") or "gpt-4o-mini")
    temp_raw = cfg.get("temperature", 0.2)
    try:
        temperature = float(os.environ.get("OPENAI_TEMPERATURE", temp_raw))
    except (TypeError, ValueError):
        temperature = 0.2
    return key, base, model, temperature
