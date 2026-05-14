from __future__ import annotations

import json
import re
from pathlib import Path


from ..models import Evidence, Skill, TurnRecord


class ClaudeCodeAdapter:
    name = "claude_code"

    def __init__(self, cwd: Path | None = None, projects_root: Path | None = None) -> None:
        self.cwd = cwd or Path.cwd()
        self.projects_root = projects_root or Path.home() / ".claude" / "projects"

    def confirmed_invocations(self) -> list[dict]:
        return []

    def collect(self, skills: list[Skill], limit: int = 3) -> list[Evidence]:
        files = self._project_files(limit)
        evidence: list[Evidence] = []
        for path in files:
            evidence.extend(self._parse_project_file(path, skills))
        return evidence

    def collect_turns(self, limit: int = 3) -> list[TurnRecord]:
        turns: dict[str, TurnRecord] = {}
        for path in self._project_files(limit):
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    turn_id = str(event.get("promptId") or event.get("uuid") or "")
                    if not turn_id:
                        continue
                    record = turns.setdefault(
                        turn_id,
                        TurnRecord(
                            turn_id=turn_id,
                            platform="claude_code",
                            timestamp=str(event.get("timestamp") or ""),
                        ),
                    )
                    message = event.get("message") or {}
                    role = message.get("role") if isinstance(message, dict) else ""
                    text = _message_text(message)
                    if role == "user" and text and not record.user_message:
                        record.user_message = text
                    if role == "assistant" and text:
                        record.assistant_summary = text[:240]
        return sorted(turns.values(), key=lambda item: item.timestamp)

    def _project_files(self, limit: int) -> list[Path]:
        if not self.projects_root.exists():
            return []
        files = sorted(self.projects_root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        return files[:limit]

    def _parse_project_file(self, path: Path, skills: list[Skill]) -> list[Evidence]:
        evidence: list[Evidence] = []
        known = {skill.name for skill in skills}
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = str(event.get("timestamp") or "")
                turn_id = str(event.get("promptId") or "")
                message_id = str(event.get("messageId") or event.get("uuid") or "")
                attachment = event.get("attachment") or {}
                if attachment.get("type") == "skill_listing":
                    evidence.extend(_loaded_from_listing(attachment.get("content", ""), known, timestamp, turn_id, message_id))
                evidence.extend(_read_from_event(event, skills, timestamp, turn_id, message_id))
                evidence.extend(_invoked_from_event(event, timestamp, turn_id, message_id))
        return evidence


def _loaded_from_listing(content: str, known: set[str], timestamp: str, turn_id: str, message_id: str) -> list[Evidence]:
    evidence: list[Evidence] = []
    for name in sorted(known):
        if re.search(rf"[-*]\s+{re.escape(name)}\s*:", content):
            evidence.append(
                Evidence(
                    skill_name=name,
                    platform="claude_code",
                    event_type="loaded",
                    certainty="confirmed",
                    source="claude_jsonl",
                    turn_id=turn_id,
                    message_id=message_id,
                    timestamp=timestamp,
                    snippet="Skill appeared in Claude Code skill listing attachment.",
                )
            )
    return evidence


def _message_text(message: dict) -> str:
    parts: list[str] = []
    content = message.get("content") if isinstance(message, dict) else []
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
    return " ".join(part.strip() for part in parts if part.strip())


def _read_from_event(event: dict, skills: list[Skill], timestamp: str, turn_id: str, message_id: str) -> list[Evidence]:
    text = json.dumps(event, ensure_ascii=False)
    if "SKILL.md" not in text:
        return []
    evidence: list[Evidence] = []
    for skill in skills:
        if skill.path and _path_matches(text, skill.path):
            evidence.append(
                Evidence(
                    skill_name=skill.name,
                    platform="claude_code",
                    event_type="read",
                    certainty="confirmed",
                    source="claude_jsonl",
                    turn_id=turn_id,
                    message_id=message_id,
                    timestamp=timestamp,
                    path=skill.path,
                    snippet=_snippet(text, "SKILL.md"),
                )
            )
    return evidence


def _invoked_from_event(event: dict, timestamp: str, turn_id: str, message_id: str) -> list[Evidence]:
    text = json.dumps(event, ensure_ascii=False)
    if "skill_invocation" not in text and "invoke_skill" not in text:
        return []
    match = re.search(r"skill[_ -]?name[\"']?\s*[:=]\s*[\"']([^\"']+)", text, re.IGNORECASE)
    skill_name = match.group(1) if match else "unknown"
    return [
        Evidence(
            skill_name=skill_name,
            platform="claude_code",
            event_type="invoked",
            certainty="confirmed",
            source="claude_jsonl",
            turn_id=turn_id,
            message_id=message_id,
            timestamp=timestamp,
            snippet=_snippet(text, skill_name),
        )
    ]


def _path_matches(text: str, path: str) -> bool:
    normalized_text = text.replace("\\\\", "/").replace("\\", "/").lower()
    normalized_text = re.sub(r"/+", "/", normalized_text)
    normalized_path = path.replace("\\", "/").lower()
    normalized_path = re.sub(r"/+", "/", normalized_path)
    return normalized_path in normalized_text


def _snippet(text: str, needle: str, width: int = 220) -> str:
    index = text.lower().find(needle.lower())
    if index < 0:
        return text[:width]
    start = max(0, index - 80)
    return text[start : start + width]
