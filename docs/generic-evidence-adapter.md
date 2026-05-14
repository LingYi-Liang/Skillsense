# Generic Evidence Adapter

SkillSense is not limited to Codex or Claude Code. Any agent platform can feed local evidence into SkillSense by writing newline-delimited JSON into:

```text
.skillsense/evidence/*.jsonl
```

This keeps the integration local, low-noise, and zero-token. SkillSense does not call an LLM to interpret these files. It only reads structured evidence records and turn records.

## Event Types

Use the weakest accurate event type:

| Event type | Meaning |
| --- | --- |
| `loaded` | The platform made a skill visible to the agent. This is not usage proof. |
| `read` | The agent opened or read a specific `SKILL.md`. |
| `invoked` | The platform explicitly exposed a skill invocation event. Use only when the platform really logs invocation. |
| `inferred` | Your adapter can only infer possible use from traces. This is not confirmed usage. |

If your platform does not expose explicit invocation events, do not emit `invoked`.

## Turn Record

Write one turn record when a user/assistant turn starts or completes:

```json
{"platform":"cursor","turn_id":"turn-001","timestamp":"2026-05-14T10:00:00+08:00","user_message":"check README","assistant_summary":"opened readme skill"}
```

Minimal fields:

```json
{"platform":"my-agent","turn_id":"turn-001","timestamp":"2026-05-14T10:00:00+08:00"}
```

By default, SkillSense privacy settings hide turn text in generated state. You can omit `user_message` and `assistant_summary` completely.

## Evidence Record

Write evidence records with the same `turn_id` when possible:

```json
{"platform":"cursor","turn_id":"turn-001","skill_name":"readme-runner","event_type":"read","certainty":"confirmed","source":"generic_jsonl","path":".cursor/skills/readme-runner/SKILL.md","snippet":"SKILL.md opened"}
```

Recommended fields:

| Field | Required | Notes |
| --- | --- | --- |
| `platform` | yes | `cursor`, `vscode-agent`, `my-agent`, etc. |
| `turn_id` | recommended | Lets the dashboard attach evidence to the right turn. |
| `message_id` | optional | Use if your platform exposes message ids. |
| `skill_name` | yes for evidence | Name shown in the dashboard. |
| `event_type` | yes for evidence | `loaded`, `read`, `invoked`, or `inferred`. |
| `certainty` | recommended | `confirmed`, `inferred`, or `suggested`. |
| `source` | recommended | Usually `generic_jsonl` or your adapter name. |
| `timestamp` | recommended | ISO 8601; dashboard renders local time in the browser. |
| `path` | optional | Local skill path if available. |
| `snippet` | optional | Short source detail. Avoid full private prompts. |

## Cursor Or VS Code Example

A thin extension or script can append records whenever it sees a skill list, a file open event, or an invocation event:

```jsonl
{"platform":"cursor","turn_id":"cursor-001","timestamp":"2026-05-14T10:00:00+08:00"}
{"platform":"cursor","turn_id":"cursor-001","skill_name":"readme-runner","event_type":"loaded","certainty":"confirmed","source":"cursor_extension","snippet":"Skill listed in agent context"}
{"platform":"cursor","turn_id":"cursor-001","skill_name":"readme-runner","event_type":"read","certainty":"confirmed","source":"cursor_extension","path":".cursor/skills/readme-runner/SKILL.md","snippet":"SKILL.md opened"}
```

## Custom Agent Example

Python append helper:

```python
from pathlib import Path
import json

path = Path(".skillsense/evidence/my-agent.jsonl")
path.parent.mkdir(parents=True, exist_ok=True)

def emit(event):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")

emit({"platform": "my-agent", "turn_id": "turn-001", "timestamp": "2026-05-14T10:00:00+08:00"})
emit({
    "platform": "my-agent",
    "turn_id": "turn-001",
    "skill_name": "docs-helper",
    "event_type": "read",
    "certainty": "confirmed",
    "source": "my_agent_hook",
    "path": "./skills/docs-helper/SKILL.md",
})
```

Then run:

```bash
skillsense serve --interval 2
```

Open:

```text
http://127.0.0.1:8765/dashboard.html
```

## Rules Of Thumb

- Use `loaded` for visibility only.
- Use `read` for actual `SKILL.md` file access.
- Use `invoked` only for explicit platform invocation logs.
- Keep snippets short and non-sensitive.
- Prefer stable `turn_id` values so SkillSense can build a useful live turn monitor.
