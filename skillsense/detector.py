from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Skill
from .recommender import why_recommended


def generic_detection() -> dict[str, list[dict[str, Any]]]:
    return {"confirmed": [], "inferred": []}


def why_not_used(skill: Skill, prompt: str, cwd: Path | None = None) -> list[str]:
    reasons = [
        "No hook, event, trace, or adapter invocation log was found, so SkillSense cannot mark it as confirmed.",
        "The generic adapter can suggest skills, but it cannot prove the agent invoked one.",
    ]
    recommendation_reasons = why_recommended(skill, prompt, cwd)
    if recommendation_reasons and "weak overlap" in recommendation_reasons[0]:
        reasons.append("The user prompt may not include enough trigger words from the skill description.")
    else:
        reasons.append("The skill appears relevant, but relevance alone is not invocation evidence.")
    if len(skill.description.split()) < 8:
        reasons.append("The skill description is short, which can make triggering less reliable.")
    reasons.append("If the platform did not load this skill directory, the agent could not use it.")
    return reasons
