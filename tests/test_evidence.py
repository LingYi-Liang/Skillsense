from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from skillsense.adapters.claude_code import ClaudeCodeAdapter
from skillsense.adapters.codex import CodexAdapter
from skillsense.adapters.generic import GenericAdapter
from skillsense.models import Skill


class EvidenceAdapterTests(unittest.TestCase):
    def test_codex_jsonl_loaded_read_and_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_path = root / "skills" / "readme-runner" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("# README Runner", encoding="utf-8")
            session = root / "sessions" / "rollout.jsonl"
            session.parent.mkdir()
            write_jsonl(
                session,
                [
                    {"timestamp": "1", "type": "turn_context", "payload": {"turn_id": "turn-1", "cwd": str(root)}},
                    {
                        "timestamp": "2",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Please check whether the README can run."}],
                        },
                    },
                    {
                        "timestamp": "3",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "developer",
                            "content": [{"type": "input_text", "text": "### Available skills\n- readme-runner: Use for README checks."}],
                        },
                    },
                    {
                        "timestamp": "4",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "shell_command",
                            "call_id": "call-read",
                            "arguments": json.dumps({"command": f"Get-Content -Path '{skill_path}'"}),
                        },
                    },
                    {
                        "timestamp": "5",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "invoke_skill",
                            "call_id": "call-invoke",
                            "arguments": '{"skill_name":"readme-runner"}',
                        },
                    },
                ],
            )
            skill = Skill(name="readme-runner", description="", path=str(skill_path), platform="generic")
            evidence = CodexAdapter(root, session.parent).collect([skill])
            event_types = {item.event_type for item in evidence}
            self.assertIn("loaded", event_types)
            self.assertIn("read", event_types)
            self.assertIn("invoked", event_types)
            turns = CodexAdapter(root, session.parent).collect_turns()
            self.assertEqual(turns[0].turn_id, "turn-1")
            self.assertIn("README", turns[0].user_message)

    def test_generic_jsonl_adapter_supports_other_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / ".skillsense" / "evidence" / "cursor.jsonl"
            logs.parent.mkdir(parents=True)
            write_jsonl(
                logs,
                [
                    {
                        "platform": "cursor",
                        "turn_id": "turn-1",
                        "timestamp": "1",
                        "user_message": "use docs skill",
                        "assistant_summary": "opened docs skill",
                    },
                    {
                        "platform": "cursor",
                        "turn_id": "turn-1",
                        "timestamp": "2",
                        "skill_name": "docs",
                        "event_type": "read",
                        "certainty": "confirmed",
                        "snippet": "SKILL.md opened",
                    },
                ],
            )

            adapter = GenericAdapter(root)
            evidence = adapter.collect([])
            turns = adapter.collect_turns()

            self.assertEqual(evidence[0].platform, "cursor")
            self.assertEqual(evidence[0].event_type, "read")
            self.assertEqual(turns[0].platform, "cursor")

    def test_claude_jsonl_loaded_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_path = root / "skills" / "readme-runner" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("# README Runner", encoding="utf-8")
            session = root / "projects" / "session.jsonl"
            session.parent.mkdir()
            write_jsonl(
                session,
                [
                    {
                        "timestamp": "1",
                        "promptId": "turn-1",
                        "messageId": "msg-1",
                        "attachment": {
                            "type": "skill_listing",
                            "content": "- readme-runner: Use for README checks.",
                        },
                    },
                    {
                        "timestamp": "2",
                        "promptId": "turn-1",
                        "messageId": "msg-2",
                        "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": str(skill_path)}}]},
                    },
                ],
            )
            skill = Skill(name="readme-runner", description="", path=str(skill_path), platform="generic")
            evidence = ClaudeCodeAdapter(root, session.parent).collect([skill])
            event_types = {item.event_type for item in evidence}
            self.assertIn("loaded", event_types)
            self.assertIn("read", event_types)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
