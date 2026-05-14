from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Skill


COMMON_WORDS = {
    "and",
    "for",
    "the",
    "this",
    "that",
    "with",
    "when",
    "user",
    "asks",
    "skill",
    "use",
    "used",
    "using",
}

ZH_ALIASES = {
    "readme": ["README", "文档", "说明", "快速开始", "安装", "运行"],
    "docs": ["文档", "说明", "用法"],
    "test": ["测试", "验证", "检查"],
    "debug": ["调试", "排错", "修复"],
    "python": ["Python", "脚本", "包"],
    "cli": ["命令行", "CLI"],
    "github": ["GitHub", "仓库"],
}


@dataclass(frozen=True)
class ScanRoot:
    path: Path
    platform: str
    scope: str
    allow_readme: bool = True


def default_scan_roots(cwd: Path | None = None) -> list[ScanRoot]:
    cwd = cwd or Path.cwd()
    home = Path.home()
    return [
        ScanRoot(cwd / ".claude" / "skills", "claude", "project"),
        ScanRoot(home / ".claude" / "skills", "claude", "user_global"),
        ScanRoot(cwd / ".codex" / "skills", "codex", "project"),
        ScanRoot(home / ".codex" / "skills", "codex", "user_global"),
        ScanRoot(cwd / "skills", "generic", "project"),
        ScanRoot(cwd / "examples", "generic", "example", allow_readme=False),
    ]


def scan_skills(cwd: Path | None = None) -> list[Skill]:
    skills: list[Skill] = []
    seen: set[Path] = set()
    for root in default_scan_roots(cwd):
        if not root.path.exists():
            continue
        for file_path in _skill_files(root):
            resolved = file_path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            skills.append(parse_skill_file(file_path, root.platform, root.scope))
    return sorted(skills, key=lambda item: (item.platform, item.name.lower(), item.path))


def parse_skill_file(path: Path, platform: str = "generic", scope: str = "unknown") -> Skill:
    text = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(text)
    name = frontmatter.get("name") or _heading(text) or path.parent.name
    description = frontmatter.get("description") or _description(text)
    repo_url = _repo_url(text)
    keywords = _keywords(text, name, description)
    language = detect_language(f"{name}\n{description}\n{text[:500]}")
    aliases = multilingual_aliases(keywords, description)
    return Skill(
        name=name.strip(),
        description=description.strip(),
        path=str(path),
        platform=platform,
        keywords=keywords,
        language=language,
        repo_url=repo_url,
        summary=_summary(description, text),
        risk_tags=_risk_tags(text),
        trigger_aliases=aliases,
        scope=scope,
    )


def detect_language(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[A-Za-z]{3,}", text):
        return "en"
    return "unknown"


def multilingual_aliases(keywords: list[str], description: str) -> list[str]:
    if detect_language(description) == "zh":
        return []
    aliases: list[str] = []
    for keyword in keywords:
        aliases.extend(ZH_ALIASES.get(keyword.lower(), []))
    return sorted(set(aliases))


def _skill_files(root: ScanRoot) -> list[Path]:
    files = list(root.path.rglob("SKILL.md"))
    if root.allow_readme:
        files.extend(root.path.rglob("README.md"))
    return files


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip().lower()] = value.strip().strip("\"'")
    return data


def _heading(text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _description(text: str) -> str:
    for pattern in [
        r"(?im)^description\s*:\s*(.+)$",
        r"(?im)^>\s*(Use this skill.+)$",
        r"(?im)^(Use this skill.+)$",
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if block and not block.startswith("#") and not block.startswith("---"):
            return " ".join(block.split())
    return ""


def _repo_url(text: str) -> str:
    match = re.search(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text)
    return match.group(0) if match else ""


def _keywords(text: str, name: str, description: str) -> list[str]:
    explicit: list[str] = []
    for match in re.finditer(r"(?im)^(?:keywords|triggers|trigger keywords)\s*:\s*(.+)$", text):
        explicit.extend(_split_keywords(match.group(1)))
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", f"{name} {description}".lower())
    keywords = explicit + [word for word in words if word not in COMMON_WORDS]
    return sorted(set(keywords))[:24]


def _split_keywords(value: str) -> list[str]:
    return [item.strip().strip("`") for item in re.split(r"[,，;；\n]+", value) if item.strip()]


def _summary(description: str, text: str) -> str:
    source = description or text
    source = " ".join(source.split())
    return source[:160]


def _risk_tags(text: str) -> list[str]:
    tags = []
    lowered = text.lower()
    if any(word in lowered for word in ["delete", "remove", "destructive", "rm -rf"]):
        tags.append("destructive")
    if any(word in lowered for word in ["network", "download", "upload", "api key"]):
        tags.append("network")
    if any(word in lowered for word in ["secret", "token", "credential"]):
        tags.append("secrets")
    return tags
