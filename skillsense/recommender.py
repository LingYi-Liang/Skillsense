from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import Skill, SkillRecommendation
from .scanner import detect_language


PROMPT_ALIASES = {
    "readme": ["readme", "说明", "文档", "快速开始", "quickstart"],
    "setup": ["setup", "install", "安装", "配置"],
    "run": ["run", "运行", "能不能跑", "启动"],
    "test": ["test", "测试", "检查", "validate", "验证"],
    "debug": ["debug", "报错", "修复", "排错"],
    "docs": ["docs", "documentation", "文档", "说明"],
    "python": ["python", "pyproject", "pip"],
    "node": ["node", "npm", "package.json", "javascript"],
}

STRONG_INTENTS = {"readme", "docs", "setup", "python", "node"}
GENERIC_INTENTS = {"run", "test", "debug"}


def suggest_skills(
    prompt: str,
    skills: list[Skill],
    cwd: Path | None = None,
    config: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[SkillRecommendation]:
    config = config or {}
    preferences = config.get("preferences", {})
    muted = set(preferences.get("mute", []))
    preferred = set(preferences.get("prefer", []))
    prompt_terms = _prompt_terms(prompt)
    results: list[SkillRecommendation] = []
    for skill in skills:
        if skill.name in muted:
            continue
        confidence, reasons = _score_skill(skill, prompt, prompt_terms, cwd or Path.cwd())
        if skill.name in preferred:
            confidence += 0.12
            reasons.append("user preference boosts this skill")
        confidence = min(confidence, 0.98)
        if confidence >= 0.18:
            results.append(
                SkillRecommendation(
                    name=skill.name,
                    status="suggested",
                    confidence=round(confidence, 2),
                    reasons=reasons,
                    skill=skill.to_dict(),
                )
            )
    return sorted(results, key=lambda item: item.confidence, reverse=True)[:limit]


def project_recommendations(cwd: Path | None = None, skills: list[Skill] | None = None) -> list[dict[str, Any]]:
    cwd = cwd or Path.cwd()
    skills = skills or []
    names = " ".join(skill.name.lower() for skill in skills)
    recommendations: list[dict[str, Any]] = []
    if (cwd / "README.md").exists() and "readme" not in names and "docs" not in names:
        recommendations.append(
            {
                "name": "README validation skill",
                "status": "recommended",
                "confidence": 0.72,
                "reasons": ["project has README.md but no obvious README/docs skill is indexed"],
            }
        )
    if (cwd / "pyproject.toml").exists() and "python" not in names:
        recommendations.append(
            {
                "name": "Python project skill",
                "status": "recommended",
                "confidence": 0.64,
                "reasons": ["project has pyproject.toml but no obvious Python skill is indexed"],
            }
        )
    if (cwd / "package.json").exists() and "node" not in names and "javascript" not in names:
        recommendations.append(
            {
                "name": "Node.js project skill",
                "status": "recommended",
                "confidence": 0.64,
                "reasons": ["project has package.json but no obvious Node.js skill is indexed"],
            }
        )
    if (cwd / "tests").exists() and "test" not in names:
        recommendations.append(
            {
                "name": "Testing workflow skill",
                "status": "recommended",
                "confidence": 0.58,
                "reasons": ["project has tests/ but no obvious testing skill is indexed"],
            }
        )
    return recommendations


def conflict_map(skills: list[Skill]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(skills):
        left_terms = set(left.keywords)
        for right in skills[index + 1 :]:
            overlap = sorted(left_terms.intersection(right.keywords))
            if len(overlap) >= 3:
                conflicts.append(
                    {
                        "skills": [left.name, right.name],
                        "scopes": [left.scope, right.scope],
                        "overlap": overlap[:8],
                        "reason": "trigger keywords overlap",
                    }
                )
    return conflicts


def rewrite_description(skill: Skill) -> str:
    base_terms = sorted(set(skill.keywords + skill.trigger_aliases))[:10]
    focus = ", ".join(base_terms) if base_terms else skill.name
    if any(term.lower() in {"readme", "docs", "documentation", "setup", "install"} for term in base_terms):
        return (
            "Use this skill when the user asks to test, validate, debug, or fix README "
            "installation, setup, quickstart, usage, or run commands in a local project."
        )
    return (
        f"Use this skill when the user asks to plan, inspect, validate, debug, or improve "
        f"work related to {focus}. Mention concrete trigger words and when this skill should not be used."
    )


def why_recommended(skill: Skill, prompt: str, cwd: Path | None = None) -> list[str]:
    _, reasons = _score_skill(skill, prompt, _prompt_terms(prompt), cwd or Path.cwd())
    return reasons or ["the prompt has weak overlap with this skill"]


def _score_skill(skill: Skill, prompt: str, prompt_terms: set[str], cwd: Path) -> tuple[float, list[str]]:
    skill_terms = {term.lower() for term in skill.keywords + skill.trigger_aliases}
    description_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", skill.description.lower()))
    overlap = sorted(prompt_terms.intersection(skill_terms.union(description_terms)))
    confidence = 0.0
    reasons: list[str] = []
    if overlap:
        strong_overlap = [term for term in overlap if term in STRONG_INTENTS]
        generic_overlap = [term for term in overlap if term in GENERIC_INTENTS]
        confidence += min(0.5, 0.16 * len(strong_overlap) + 0.07 * len(generic_overlap))
        reasons.append(f"prompt overlaps trigger terms: {', '.join(overlap[:6])}")
    for canonical, aliases in PROMPT_ALIASES.items():
        if any(alias.lower() in prompt.lower() for alias in aliases) and canonical in skill_terms.union(description_terms):
            confidence += 0.18 if canonical in STRONG_INTENTS else 0.06
            reasons.append(f"prompt intent matches {canonical}")
    if (cwd / "README.md").exists() and {"readme", "docs", "documentation"}.intersection(skill_terms):
        confidence += 0.12
        reasons.append("project contains README.md")
    if (cwd / "pyproject.toml").exists() and "python" in skill_terms and "python" in prompt_terms:
        confidence += 0.1
        reasons.append("project contains pyproject.toml")
    alias_hit = any(alias.lower() in prompt.lower() for alias in skill.trigger_aliases)
    if detect_language(prompt) == "zh" and alias_hit:
        confidence += 0.08
        reasons.append("Chinese prompt matches generated trigger aliases")
    return confidence, reasons


def _prompt_terms(prompt: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", prompt.lower()))
    for canonical, aliases in PROMPT_ALIASES.items():
        if any(alias.lower() in prompt.lower() for alias in aliases):
            terms.add(canonical)
    return terms
