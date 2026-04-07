import json
import os
from pathlib import Path
from typing import Any

MIN_VIEWPORT = 320
MAX_VIEWPORT_W = 3840
MAX_VIEWPORT_H = 2160


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
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON in {path}: {e.msg} (line {e.lineno}, column {e.colno})."
        ) from e
    return data if isinstance(data, dict) else {}


def _normalize_presets(raw: Any) -> list[dict[str, int | str]]:
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        label = str(item.get("label") or pid).strip()
        if not pid:
            continue
        try:
            w = int(item["width"])
            h = int(item["height"])
        except (KeyError, TypeError, ValueError):
            continue
        w = max(MIN_VIEWPORT, min(MAX_VIEWPORT_W, w))
        h = max(MIN_VIEWPORT, min(MAX_VIEWPORT_H, h))
        if pid in seen:
            raise RuntimeError(f"Duplicate viewport preset id: {pid!r}")
        seen.add(pid)
        out.append({"id": pid, "label": label, "width": w, "height": h})
    return out


def load_viewport_config(repo_root: Path) -> tuple[list[dict[str, int | str]], str | None]:
    primary = _config_path(repo_root)
    example = repo_root / "config.example.json"
    data = _read_json_object(primary)
    browser = data.get("browser")
    presets_raw: Any = None
    default_id: str | None = None
    if isinstance(browser, dict):
        presets_raw = browser.get("viewport_presets")
        d = browser.get("default_viewport_preset_id")
        if isinstance(d, str) and d.strip():
            default_id = d.strip()
    presets = _normalize_presets(presets_raw)
    if not presets:
        ex = _read_json_object(example)
        b2 = ex.get("browser")
        if isinstance(b2, dict):
            presets = _normalize_presets(b2.get("viewport_presets"))
            if default_id is None:
                d2 = b2.get("default_viewport_preset_id")
                if isinstance(d2, str) and d2.strip():
                    default_id = d2.strip()
    if not presets:
        raise RuntimeError(
            "Configure browser.viewport_presets in config.json (see config.example.json). "
            f"Resolved config path: {primary}"
        )
    ids = {str(p["id"]) for p in presets}
    if default_id and default_id not in ids:
        raise RuntimeError(
            f"browser.default_viewport_preset_id {default_id!r} is not listed in viewport_presets"
        )
    return presets, default_id


def initial_viewport_from_presets(
    presets: list[dict[str, int | str]], default_id: str | None
) -> dict[str, int]:
    if default_id:
        for p in presets:
            if str(p["id"]) == default_id:
                return {"width": int(p["width"]), "height": int(p["height"])}
    p0 = presets[0]
    return {"width": int(p0["width"]), "height": int(p0["height"])}
