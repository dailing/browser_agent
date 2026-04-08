"""Load skills from repo/_skills/<id>/SKILL.md (optional YAML-like frontmatter)."""

from __future__ import annotations

from pathlib import Path


def _parse_skill_md(raw: str) -> tuple[dict[str, str], str]:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    meta: dict[str, str] = {}
    if not text.startswith("---\n"):
        return meta, text.strip()
    end = text.find("\n---\n", 4)
    if end == -1:
        return meta, text.strip()
    fm = text[4:end]
    body = text[end + 5 :]
    for line in fm.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            meta[k] = v
    return meta, body.strip()


def _skill_file(skills_dir: Path, skill_id: str) -> Path | None:
    if not skill_id or "/" in skill_id or "\\" in skill_id or skill_id.startswith("."):
        return None
    p = skills_dir / skill_id / "SKILL.md"
    if p.is_file():
        return p
    return None


def load_skill(skills_dir: Path, skill_id: str) -> dict | None:
    path = _skill_file(skills_dir, skill_id)
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _parse_skill_md(raw)
    if not body:
        return None
    name = (meta.get("name") or skill_id).strip() or skill_id
    desc = meta.get("description", "").strip() or None
    return {
        "id": skill_id,
        "name": name,
        "description": desc,
        "body": body,
    }


def list_skills(skills_dir: Path) -> list[dict]:
    if not skills_dir.is_dir():
        return []
    out: list[dict] = []
    for child in sorted(skills_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        data = load_skill(skills_dir, child.name)
        if data is None:
            continue
        out.append(
            {
                "id": data["id"],
                "name": data["name"],
                "description": data["description"],
            }
        )
    return out
