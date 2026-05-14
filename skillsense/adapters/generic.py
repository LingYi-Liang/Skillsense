from __future__ import annotations

import json
from pathlib import Path

from ..models import Evidence, Skill, TurnRecord


class GenericAdapter:
    name = "generic_jsonl"

    def __init__(self, cwd: Path | None = None, logs_root: Path | None = None) -> None:
        self.cwd = cwd or Path.cwd()
        self.logs_root = logs_root or self.cwd / ".skillsense" / "evidence"

    def confirmed_invocations(self) -> list[dict]:
        return []

    def collect(self, _skills: list[Skill], limit: int = 20) -> list[Evidence]:
        evidence: list[Evidence] = []
        for path in self._files(limit):
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    evidence_item = event.get("evidence") if isinstance(event.get("evidence"), dict) else event
                    if evidence_item.get("skill_name") and evidence_item.get("event_type"):
                        evidence.append(
                            Evidence(
                                skill_name=str(evidence_item.get("skill_name") or "unknown"),
                                platform=str(evidence_item.get("platform") or event.get("platform") or "generic"),
                                event_type=str(evidence_item.get("event_type") or "unknown"),
                                certainty=str(evidence_item.get("certainty") or "confirmed"),
                                source=str(evidence_item.get("source") or "generic_jsonl"),
                                turn_id=str(evidence_item.get("turn_id") or event.get("turn_id") or ""),
                                message_id=str(evidence_item.get("message_id") or event.get("message_id") or ""),
                                timestamp=str(evidence_item.get("timestamp") or event.get("timestamp") or ""),
                                path=str(evidence_item.get("path") or ""),
                                snippet=str(evidence_item.get("snippet") or ""),
                            )
                        )
        return evidence

    def collect_turns(self, limit: int = 20) -> list[TurnRecord]:
        turns: list[TurnRecord] = []
        for path in self._files(limit):
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    turn = event.get("turn") if isinstance(event.get("turn"), dict) else event
                    if not turn.get("turn_id"):
                        continue
                    turns.append(
                        TurnRecord(
                            turn_id=str(turn.get("turn_id") or ""),
                            platform=str(turn.get("platform") or event.get("platform") or "generic"),
                            timestamp=str(turn.get("timestamp") or event.get("timestamp") or ""),
                            user_message=str(turn.get("user_message") or ""),
                            assistant_summary=str(turn.get("assistant_summary") or ""),
                        )
                    )
        return turns

    def _files(self, limit: int) -> list[Path]:
        if not self.logs_root.exists():
            return []
        return sorted(self.logs_root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
