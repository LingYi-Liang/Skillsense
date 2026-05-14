from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "skillsense.cli", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


class SkillSenseCliTests(unittest.TestCase):
    def test_scan_list_suggest_status_report_watch_and_config(self) -> None:
        scan = run_cli("scan")
        self.assertEqual(scan.returncode, 0, scan.stderr)
        self.assertIn("Scanned", scan.stdout)
        run_cli("config", "set", "network.enabled", "false")

        index_path = ROOT / ".skillsense" / "skills_index.json"
        self.assertTrue(index_path.exists())
        index = json.loads(index_path.read_text(encoding="utf-8"))
        names = [item["name"] for item in index["skills"]]
        self.assertIn("readme-runner", names)

        run_cli("unmute", "readme-runner")
        run_cli("unprefer", "readme-runner")

        listed = run_cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("readme-runner", listed.stdout)

        suggest = run_cli("suggest", "帮我检查 README 能不能跑")
        self.assertEqual(suggest.returncode, 0, suggest.stderr)
        self.assertIn("readme-runner", suggest.stdout)
        self.assertIn("suggested", suggest.stdout)

        status = run_cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("SkillSense -", status.stdout)

        evidence = run_cli("evidence")
        self.assertEqual(evidence.returncode, 0, evidence.stderr)
        self.assertTrue("loaded -" in evidence.stdout or "No confirmed evidence detected." in evidence.stdout)

        watch = run_cli("watch", "--once")
        self.assertEqual(watch.returncode, 0, watch.stderr)
        self.assertIn("Updated dashboard", watch.stdout)

        report = run_cli("report")
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertTrue((ROOT / ".skillsense" / "report.md").exists())
        self.assertTrue((ROOT / ".skillsense" / "state.json").exists())
        dashboard = ROOT / ".skillsense" / "dashboard.html"
        self.assertTrue(dashboard.exists())
        dashboard_text = dashboard.read_text(encoding="utf-8")
        self.assertIn('class="info"', dashboard_text)
        self.assertIn('data-tooltip="network_tooltip"', dashboard_text)
        self.assertIn("network_tooltip", dashboard_text)
        self.assertIn('data-tooltip="metric_loaded_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="metric_read_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="metric_invoked_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="metric_inferred_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="metric_suggested_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="live_monitor_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="evidence_timeline_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="suggested_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="recommended_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="project_conflicts_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="supporting_insights_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="local_skill_index_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="intervention_queue_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="advanced_settings_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="policy_settings_title_tooltip"', dashboard_text)
        self.assertIn('data-tooltip="privacy_settings_title_tooltip"', dashboard_text)
        self.assertIn("trigger_diagnostics_title", dashboard_text)
        self.assertIn("trigger_diagnostics_tooltip", dashboard_text)
        self.assertIn("trigger_diagnostics_note", dashboard_text)
        self.assertIn("detected_evidence_label", dashboard_text)
        self.assertIn("missed_candidates_label", dashboard_text)
        self.assertIn("possible_confusion_label", dashboard_text)
        self.assertIn("const text = td(key);", dashboard_text)
        self.assertNotIn('http-equiv="refresh"', dashboard_text)
        self.assertIn("skillsense serve", dashboard_text)
        self.assertIn('id="language-select"', dashboard_text)
        self.assertIn('id="network-toggle"', dashboard_text)
        self.assertIn('data-network-enabled=', dashboard_text)
        self.assertIn('fetch("/api/network"', dashboard_text)
        self.assertIn('<option value="ja">', dashboard_text)
        self.assertIn('<option value="ko">', dashboard_text)
        self.assertIn('<option value="es">', dashboard_text)
        self.assertIn('<option value="fr">', dashboard_text)
        self.assertNotIn("language-apply", dashboard_text)
        self.assertIn("skillsense.dashboard.language", dashboard_text)
        self.assertIn("isUserBusy", dashboard_text)
        self.assertIn("data-local-time", dashboard_text)
        self.assertIn('data-i18n-direct="skill_path_label"', dashboard_text)
        self.assertIn("metadata_cache", (ROOT / "skillsense" / "config.py").read_text(encoding="utf-8"))
        self.assertIn("data-detail-key=\"global-skills\"", dashboard_text)
        self.assertIn("Adapter Capability", dashboard_text)
        self.assertIn("adapter_capability_title", dashboard_text)
        self.assertIn("Invoked detection: requires explicit platform event", dashboard_text)
        self.assertIn("turnSummaryText", dashboard_text)
        self.assertIn("data-ja=", dashboard_text)
        self.assertIn("data-es=", dashboard_text)
        self.assertIn("Live Skill Monitor", dashboard_text)
        self.assertIn('id="turn-limit"', dashboard_text)
        self.assertIn("bindPanels", dashboard_text)
        self.assertIn("bindTurnLimit", dashboard_text)
        self.assertIn("Evidence Timeline", dashboard_text)
        self.assertIn("Supporting Insights", dashboard_text)
        self.assertIn("supporting_insights_title", dashboard_text)
        self.assertIn("supporting_insights_note", dashboard_text)
        self.assertIn("Intervention Queue", dashboard_text)
        self.assertIn("intervention_queue_title", dashboard_text)
        self.assertIn("Policy Settings", dashboard_text)
        self.assertIn("policy_settings_title", dashboard_text)
        self.assertIn("Advanced Settings", dashboard_text)
        self.assertIn("advanced_settings_title", dashboard_text)
        self.assertIn("privacy_settings_title", dashboard_text)
        self.assertIn("intervention-action", dashboard_text)
        self.assertIn("/api/interventions/", dashboard_text)
        self.assertIn("privacy.store_turn_text", dashboard_text)
        self.assertTrue((ROOT / "docs" / "generic-evidence-adapter.md").exists())
        self.assertTrue((ROOT / "examples" / "generic_evidence" / "cursor.jsonl").exists())
        self.assertTrue((ROOT / "examples" / "generic_evidence" / "custom_agent_writer.py").exists())

        state = json.loads((ROOT / ".skillsense" / "state.json").read_text(encoding="utf-8"))
        if state.get("turns"):
            self.assertEqual(state["turns"][0].get("user_message", ""), "")

        why_not = run_cli("why-not", "readme-runner", "帮我检查 README 能不能跑")
        self.assertEqual(why_not.returncode, 0, why_not.stderr)
        self.assertIn("cannot mark it as confirmed", why_not.stdout)

        rewrite = run_cli("rewrite-description", "readme-runner")
        self.assertEqual(rewrite.returncode, 0, rewrite.stderr)
        self.assertIn("README installation", rewrite.stdout)

        diagnose = run_cli("diagnose")
        self.assertEqual(diagnose.returncode, 0, diagnose.stderr)
        self.assertTrue((ROOT / ".skillsense" / "interventions.json").exists())
        interventions = run_cli("interventions")
        self.assertEqual(interventions.returncode, 0, interventions.stderr)

        prefer = run_cli("prefer", "readme-runner")
        self.assertEqual(prefer.returncode, 0, prefer.stderr)
        mute = run_cli("mute", "readme-runner")
        self.assertEqual(mute.returncode, 0, mute.stderr)
        config = json.loads((ROOT / ".skillsense" / "config.json").read_text(encoding="utf-8"))
        self.assertIn("readme-runner", config["preferences"]["mute"])
        self.assertNotIn("readme-runner", config["preferences"]["prefer"])

        set_language = run_cli("config", "set", "language", "zh-CN")
        self.assertEqual(set_language.returncode, 0, set_language.stderr)
        get_language = run_cli("config", "get", "language")
        self.assertEqual(get_language.returncode, 0, get_language.stderr)
        self.assertIn("zh-CN", get_language.stdout)

        set_network = run_cli("config", "set", "network.enabled", "false")
        self.assertEqual(set_network.returncode, 0, set_network.stderr)
        config = json.loads((ROOT / ".skillsense" / "config.json").read_text(encoding="utf-8"))
        self.assertIs(config["network"]["enabled"], False)

        set_privacy = run_cli("config", "set", "privacy.store_turn_text", "false")
        self.assertEqual(set_privacy.returncode, 0, set_privacy.stderr)
        config = json.loads((ROOT / ".skillsense" / "config.json").read_text(encoding="utf-8"))
        self.assertIs(config["privacy"]["store_turn_text"], False)

        reset_state = run_cli("reset-state")
        self.assertEqual(reset_state.returncode, 0, reset_state.stderr)
        self.assertFalse((ROOT / ".skillsense" / "state.json").exists())
        self.assertFalse((ROOT / ".skillsense" / "interventions.json").exists())
        self.assertFalse((ROOT / ".skillsense" / "metadata_cache.json").exists())

        watch_after_reset = run_cli("watch", "--once")
        self.assertEqual(watch_after_reset.returncode, 0, watch_after_reset.stderr)
        self.assertTrue((ROOT / ".skillsense" / "dashboard.html").exists())

        cleanup = run_cli("unmute", "readme-runner")
        self.assertEqual(cleanup.returncode, 0, cleanup.stderr)


if __name__ == "__main__":
    unittest.main()
