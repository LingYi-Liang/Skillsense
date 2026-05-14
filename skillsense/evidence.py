from __future__ import annotations

from pathlib import Path

from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter
from .adapters.generic import GenericAdapter
from .models import Evidence, Skill, TurnRecord


def collect_evidence(skills: list[Skill], cwd: Path | None = None) -> list[Evidence]:
    cwd = cwd or Path.cwd()
    evidence: list[Evidence] = []
    evidence.extend(CodexAdapter(cwd).collect(skills))
    evidence.extend(ClaudeCodeAdapter(cwd).collect(skills))
    evidence.extend(GenericAdapter(cwd).collect(skills))
    return _dedupe(evidence)


def collect_turns(cwd: Path | None = None) -> list[TurnRecord]:
    cwd = cwd or Path.cwd()
    turns: list[TurnRecord] = []
    turns.extend(CodexAdapter(cwd).collect_turns())
    turns.extend(ClaudeCodeAdapter(cwd).collect_turns())
    turns.extend(GenericAdapter(cwd).collect_turns())
    return _dedupe_turns(turns)


def evidence_counts(evidence: list[dict] | list[Evidence]) -> dict[str, int]:
    counts = {"loaded": 0, "read": 0, "invoked": 0, "inferred": 0, "suggested": 0}
    for item in evidence:
        event_type = item.event_type if isinstance(item, Evidence) else item.get("event_type")
        if event_type in counts:
            counts[event_type] += 1
    return counts


def _dedupe(items: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[Evidence] = []
    for item in items:
        key = (item.skill_name, item.platform, item.event_type, item.turn_id, item.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return sorted(deduped, key=lambda item: (item.timestamp, item.event_type, item.skill_name), reverse=True)


def _dedupe_turns(items: list[TurnRecord]) -> list[TurnRecord]:
    seen: set[tuple[str, str]] = set()
    deduped: list[TurnRecord] = []
    for item in items:
        key = (item.platform, item.turn_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return sorted(deduped, key=lambda item: item.timestamp, reverse=True)
