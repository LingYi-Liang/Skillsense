from __future__ import annotations

import json
import re
from pathlib import Path


from ..models import Evidence, Skill, TurnRecord


class CodexAdapter:
    name = "codex"

    def __init__(self, cwd: Path | None = None, sessions_root: Path | None = None) -> None:
        self.cwd = cwd or Path.cwd()
        self.sessions_root = sessions_root or Path.home() / ".codex" / "sessions"

    def confirmed_invocations(self) -> list[dict]:
        return []

    def collect(self, skills: list[Skill], limit: int = 1) -> list[Evidence]:
        files = self._session_files(limit)
        evidence: list[Evidence] = []
        for path in files:
            evidence.extend(self._parse_session(path, skills))
        return evidence

    def collect_turns(self, limit: int = 1) -> list[TurnRecord]:
        turns: list[TurnRecord] = []
        for path in self._session_files(limit):
            turns.extend(self._parse_turns(path))
        return turns

    def _session_files(self, limit: int) -> list[Path]:
        if not self.sessions_root.exists():
            return []
        files = sorted(self.sessions_root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        workspace_matches = [path for path in files if self._matches_workspace(path)]
        return (workspace_matches or files)[:limit]

    def _matches_workspace(self, path: Path) -> bool:
        cwd_text = str(self.cwd)
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index > 20:
                        break
                    if cwd_text in line:
                        return True
        except OSError:
            return False
        return False

    def _parse_session(self, path: Path, skills: list[Skill]) -> list[Evidence]:
        evidence: list[Evidence] = []
        known = _known_skill_names(skills)
        current_turn_id = ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = str(event.get("timestamp") or "")
                payload = event.get("payload") or {}
                if event.get("type") == "turn_context":
                    current_turn_id = str(payload.get("turn_id") or current_turn_id)
                    continue
                if event.get("type") != "response_item":
                    continue
                item_type = payload.get("type")
                if item_type == "message":
                    evidence.extend(_loaded_from_text(payload, known, timestamp, current_turn_id, "codex_jsonl"))
                if item_type in {"function_call", "custom_tool_call"}:
                    evidence.extend(_read_from_tool_call(payload, skills, timestamp, current_turn_id, "codex_jsonl"))
                    evidence.extend(_invoked_from_tool_call(payload, timestamp, current_turn_id, "codex_jsonl"))
        return evidence

    def _parse_turns(self, path: Path) -> list[TurnRecord]:
        turns: dict[str, TurnRecord] = {}
        current_turn_id = ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = str(event.get("timestamp") or "")
                payload = event.get("payload") or {}
                if event.get("type") == "turn_context":
                    current_turn_id = str(payload.get("turn_id") or current_turn_id)
                    if current_turn_id and current_turn_id not in turns:
                        turns[current_turn_id] = TurnRecord(
                            turn_id=current_turn_id,
                            platform="codex",
                            timestamp=timestamp,
                        )
                    continue
                if event.get("type") != "response_item" or payload.get("type") != "message":
                    continue
                role = payload.get("role")
                if not current_turn_id:
                    continue
                record = turns.setdefault(
                    current_turn_id,
                    TurnRecord(turn_id=current_turn_id, platform="codex", timestamp=timestamp),
                )
                text = _message_text(payload)
                if role == "user" and text and not record.user_message:
                    record.user_message = text
                if role == "assistant" and text:
                    record.assistant_summary = text[:240]
        return sorted(turns.values(), key=lambda item: item.timestamp)


def _known_skill_names(skills: list[Skill]) -> set[str]:
    return {skill.name for skill in skills}


def _message_text(payload: dict) -> str:
    parts: list[str] = []
    content = payload.get("content") or []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
    return " ".join(part.strip() for part in parts if part.strip())


def _loaded_from_text(payload: dict, known: set[str], timestamp: str, turn_id: str, source: str) -> list[Evidence]:
    text = json.dumps(payload, ensure_ascii=False)
    if "### Available skills" not in text and "Available skills" not in text:
        return []
    evidence: list[Evidence] = []
    for name in sorted(known):
        if re.search(rf"[-*]\s+{re.escape(name)}\s*:", text):
            evidence.append(
                Evidence(
                    skill_name=name,
                    platform="codex",
                    event_type="loaded",
                    certainty="confirmed",
                    source=source,
                    turn_id=turn_id,
                    timestamp=timestamp,
                    snippet="Skill appeared in Codex available skills instructions.",
                )
            )
    return evidence


def _read_from_tool_call(payload: dict, skills: list[Skill], timestamp: str, turn_id: str, source: str) -> list[Evidence]:
    text = json.dumps(payload, ensure_ascii=False)
    if "SKILL.md" not in text:
        return []
    evidence: list[Evidence] = []
    for skill in skills:
        if skill.path and _path_matches(text, skill.path):
            evidence.append(
                Evidence(
                    skill_name=skill.name,
                    platform="codex",
                    event_type="read",
                    certainty="confirmed",
                    source=source,
                    turn_id=turn_id,
                    message_id=str(payload.get("call_id") or ""),
                    timestamp=timestamp,
                    path=skill.path,
                    snippet=_snippet(text, "SKILL.md"),
                )
            )
    return evidence


def _invoked_from_tool_call(payload: dict, timestamp: str, turn_id: str, source: str) -> list[Evidence]:
    name = str(payload.get("name") or "")
    if name not in {"skill_invocation", "invoke_skill", "use_skill"}:
        return []
    arguments = str(payload.get("arguments") or payload.get("input") or "")
    match = re.search(r"skill[_ -]?name[\"']?\s*[:=]\s*[\"']([^\"']+)", arguments, re.IGNORECASE)
    skill_name = match.group(1) if match else "unknown"
    return [
        Evidence(
            skill_name=skill_name,
            platform="codex",
            event_type="invoked",
            certainty="confirmed",
            source=source,
            turn_id=turn_id,
            message_id=str(payload.get("call_id") or ""),
            timestamp=timestamp,
            snippet=_snippet(json.dumps(payload, ensure_ascii=False), skill_name),
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
