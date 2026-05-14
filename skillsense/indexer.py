from __future__ import annotations

from pathlib import Path

from .config import ensure_state_dir, index_path, load_json, write_json
from .models import Skill, skills_from_dicts, skills_to_dicts


def save_index(skills: list[Skill], cwd: Path | None = None) -> Path:
    ensure_state_dir(cwd)
    path = index_path(cwd)
    write_json(path, {"skills": skills_to_dicts(skills)})
    return path


def load_index(cwd: Path | None = None) -> list[Skill]:
    data = load_json(index_path(cwd), {"skills": []})
    return skills_from_dicts(data.get("skills", []))


def find_skill(skills: list[Skill], name: str) -> Skill | None:
    needle = name.lower()
    for skill in skills:
        if skill.name.lower() == needle:
            return skill
    for skill in skills:
        if needle in skill.name.lower():
            return skill
    return None
