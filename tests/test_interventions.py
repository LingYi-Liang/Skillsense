from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skillsense.interventions import apply_intervention, build_interventions, save_interventions
from skillsense.models import Skill, SkillRecommendation


def skill(name: str, description: str, path: str = "") -> Skill:
    return Skill(
        name=name,
        description=description,
        path=path,
        platform="generic",
        keywords=["readme", "run", "test"],
        scope="project",
    )


class InterventionTests(unittest.TestCase):
    def test_builds_conflict_and_description_risks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills = [
                skill("docs-a", "docs"),
                skill("docs-b", "Use for README setup run and test validation tasks."),
            ]
            conflicts = [
                {"skills": ["docs-a", "docs-b"], "overlap": ["readme", "run", "test"], "reason": "trigger overlap"}
            ]

            items = build_interventions(skills, [], [], [], conflicts, root)
            types = {item["type"] for item in items}

            self.assertIn("conflict_risk", types)
            self.assertIn("description_too_broad", types)

    def test_builds_missed_wrong_skill_and_error_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wanted = skill("skill-a", "Use for README setup validation and run commands.")
            read = skill("skill-b", "Use for unrelated deployment operations.")
            suggested = [
                SkillRecommendation("skill-a", "suggested", 0.9, ["prompt intent matches readme"], wanted.to_dict())
            ]
            evidence = [
                {
                    "skill_name": "skill-b",
                    "event_type": "read",
                    "certainty": "confirmed",
                    "turn_id": "turn-1",
                }
            ]
            turns = [{"turn_id": "turn-1", "assistant_summary": "The command failed with an error."}]

            items = build_interventions([wanted, read], suggested, evidence, turns, [], root)
            types = {item["type"] for item in items}

            self.assertIn("missed_skill_risk", types)
            self.assertIn("wrong_skill_risk", types)
            self.assertIn("answer_error_signal", types)

    def test_apply_intervention_requires_explicit_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "skills" / "demo" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("---\ndescription: old docs helper\n---\n", encoding="utf-8")
            item = {
                "id": "demo-fix",
                "type": "description_too_broad",
                "severity": "medium",
                "skills": ["demo"],
                "reason": "too broad",
                "impact": "unclear trigger",
                "proposal": {
                    "target_path": str(target),
                    "suggested_description": "Use this skill for README setup validation and runnable examples.",
                    "preview_diff": "- description: old\n+ description: new",
                },
                "requires_user_approval": True,
                "status": "open",
            }
            save_interventions([item], root)

            self.assertIn("old docs helper", target.read_text(encoding="utf-8"))
            ok, message = apply_intervention("demo-fix", root)

            self.assertTrue(ok, message)
            self.assertIn(
                "description: Use this skill for README setup validation and runnable examples.",
                target.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
