from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


UNKNOWN = "unknown"


@dataclass
class Skill:
    name: str
    description: str
    path: str
    platform: str = "generic"
    keywords: list[str] = field(default_factory=list)
    language: str = UNKNOWN
    repo_url: str = ""
    summary: str = ""
    risk_tags: list[str] = field(default_factory=list)
    trigger_aliases: list[str] = field(default_factory=list)
    stars: str = UNKNOWN
    maintenance: str = UNKNOWN
    scope: str = "unknown"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        return cls(
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            path=str(data.get("path") or ""),
            platform=str(data.get("platform") or "generic"),
            keywords=list(data.get("keywords") or []),
            language=str(data.get("language") or UNKNOWN),
            repo_url=str(data.get("repo_url") or ""),
            summary=str(data.get("summary") or ""),
            risk_tags=list(data.get("risk_tags") or []),
            trigger_aliases=list(data.get("trigger_aliases") or []),
            stars=str(data.get("stars") or UNKNOWN),
            maintenance=str(data.get("maintenance") or UNKNOWN),
            scope=str(data.get("scope") or UNKNOWN),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillRecommendation:
    name: str
    status: str
    confidence: float
    reasons: list[str]
    skill: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    skill_name: str
    platform: str
    event_type: str
    certainty: str
    source: str
    turn_id: str = ""
    message_id: str = ""
    timestamp: str = ""
    path: str = ""
    snippet: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return cls(
            skill_name=str(data.get("skill_name") or UNKNOWN),
            platform=str(data.get("platform") or UNKNOWN),
            event_type=str(data.get("event_type") or UNKNOWN),
            certainty=str(data.get("certainty") or UNKNOWN),
            source=str(data.get("source") or UNKNOWN),
            turn_id=str(data.get("turn_id") or ""),
            message_id=str(data.get("message_id") or ""),
            timestamp=str(data.get("timestamp") or ""),
            path=str(data.get("path") or ""),
            snippet=str(data.get("snippet") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnRecord:
    turn_id: str
    platform: str
    timestamp: str = ""
    user_message: str = ""
    assistant_summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TurnRecord":
        return cls(
            turn_id=str(data.get("turn_id") or ""),
            platform=str(data.get("platform") or UNKNOWN),
            timestamp=str(data.get("timestamp") or ""),
            user_message=str(data.get("user_message") or ""),
            assistant_summary=str(data.get("assistant_summary") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def skills_from_dicts(items: list[dict[str, Any]]) -> list[Skill]:
    return [Skill.from_dict(item) for item in items]


def skills_to_dicts(skills: list[Skill]) -> list[dict[str, Any]]:
    return [skill.to_dict() for skill in skills]


def evidence_to_dicts(items: list[Evidence]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in items]


def turns_to_dicts(items: list[TurnRecord]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in items]
