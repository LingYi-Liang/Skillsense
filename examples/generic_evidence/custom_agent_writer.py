from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EVIDENCE_FILE = Path(".skillsense/evidence/my-agent.jsonl")


def emit(event: dict[str, Any]) -> None:
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVIDENCE_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


emit(
    {
        "platform": "my-agent",
        "turn_id": "turn-001",
        "timestamp": "2026-05-14T10:00:00+08:00",
    }
)
emit(
    {
        "platform": "my-agent",
        "turn_id": "turn-001",
        "skill_name": "docs-helper",
        "event_type": "read",
        "certainty": "confirmed",
        "source": "my_agent_hook",
        "path": "./skills/docs-helper/SKILL.md",
        "snippet": "SKILL.md opened",
    }
)
