from __future__ import annotations

import json
import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseReadinessTests(unittest.TestCase):
    def test_readme_image_links_exist_and_are_valid_pngs(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        image_paths = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
        self.assertGreaterEqual(len(image_paths), 1)

        for image_path in image_paths:
            path = ROOT / image_path
            self.assertTrue(path.exists(), f"Missing README image: {image_path}")
            data = path.read_bytes()
            self.assertGreater(len(data), 1024, f"README image is unexpectedly small: {image_path}")
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"), f"README image is not a PNG: {image_path}")
            width, height = struct.unpack(">II", data[16:24])
            self.assertGreater(width, 100)
            self.assertGreater(height, 100)

    def test_generic_evidence_examples_are_parseable(self) -> None:
        example = ROOT / "examples" / "generic_evidence" / "cursor.jsonl"
        self.assertTrue(example.exists())

        events = [json.loads(line) for line in example.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(events), 2)
        self.assertTrue(any(item.get("turn_id") for item in events))
        self.assertTrue(any(item.get("event_type") == "read" for item in events))
        self.assertTrue(all(item.get("platform") for item in events))

    def test_github_onboarding_sections_are_present(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        required = [
            "Try It In 60 Seconds",
            "Live Skill Monitor",
            "Other Agent Platforms",
            "Accuracy Notice",
            "Dashboard hierarchy",
            "localhost",
            "generic-evidence-adapter.md",
        ]
        for text in required:
            self.assertIn(text, readme)

    def test_readme_avoids_template_style(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        avoided_phrases = [
            "Not another skill",
            "What It Is Not",
            "SkillSense 不是又一个普通 skill",
        ]
        for phrase in avoided_phrases:
            self.assertNotIn(phrase, readme)

        bullet_lines = [line for line in readme.splitlines() if line.startswith("- ")]
        self.assertLessEqual(len(bullet_lines), 1)

    def test_gitignore_blocks_common_secret_files(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        required = [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa", "id_ed25519"]
        for pattern in required:
            self.assertIn(pattern, gitignore)
