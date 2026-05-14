from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import dashboard_path, ensure_state_dir, report_path, state_path, write_json
from .interventions import build_interventions, save_interventions
from .models import Evidence, Skill, SkillRecommendation, TurnRecord, evidence_to_dicts, turns_to_dicts
from .recommender import conflict_map, project_recommendations, rewrite_description


NETWORK_TOOLTIP = (
    "Networking is optional and disabled by default. When enabled, it may fetch repo stars, "
    "maintenance status, or remote metadata. Core scan, suggest, status, and report features stay local."
)


def build_state(
    skills: list[Skill],
    suggested: list[SkillRecommendation] | None = None,
    evidence: list[Evidence] | None = None,
    turns: list[TurnRecord] | None = None,
    cwd: Path | None = None,
    prompt: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cwd = cwd or Path.cwd()
    config = config or {}
    suggested_items = [item.to_dict() for item in suggested or []]
    evidence_items = evidence_to_dicts(evidence or [])
    turn_items = _attach_evidence_to_turns(turns_to_dicts(turns or []), evidence_items)
    privacy = config.get("privacy", {})
    turn_items = _apply_turn_privacy(turn_items, privacy)
    recommended = project_recommendations(cwd, skills)
    conflicts = conflict_map(skills)
    interventions = build_interventions(skills, suggested or [], evidence_items, turn_items, conflicts, cwd)
    return {
        "prompt": prompt,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "confirmed": [],
        "inferred": [],
        "evidence": evidence_items,
        "turns": turn_items,
        "suggested": suggested_items,
        "recommended": recommended,
        "interventions": interventions,
        "conflicts": conflicts,
        "skills": [skill.to_dict() for skill in skills],
        "preferences": config.get("preferences", {}),
        "privacy": {
            "store_turn_text": bool(privacy.get("store_turn_text", False)),
            "show_turn_text": bool(privacy.get("show_turn_text", False)),
        },
        "network": {
            "enabled": bool(config.get("network", {}).get("enabled", False)),
            "tooltip": NETWORK_TOOLTIP,
        },
    }


def write_report(state: dict[str, Any], cwd: Path | None = None) -> tuple[Path, Path, Path]:
    ensure_state_dir(cwd)
    state_file = state_path(cwd)
    report_file = report_path(cwd)
    dashboard_file = dashboard_path(cwd)
    write_json(state_file, state)
    save_interventions(list(state.get("interventions") or []), cwd)
    report_file.write_text(render_markdown(state), encoding="utf-8")
    dashboard_file.write_text(render_dashboard(state), encoding="utf-8")
    return report_file, state_file, dashboard_file


def render_markdown(state: dict[str, Any]) -> str:
    evidence_counts = _evidence_counts(state.get("evidence", []), state.get("suggested", []))
    lines = [
        "# SkillSense Report",
        "",
        _accuracy_notice(),
        "",
        f"Prompt: {state.get('prompt') or 'unknown'}",
        f"Updated: {state.get('updated_at') or 'unknown'}",
        "",
        "## Status",
        "",
    ]
    for status in ["loaded", "read", "invoked", "inferred", "suggested"]:
        lines.append(f"- {status}: {evidence_counts.get(status, 0)}")
    lines.extend(["", "## Turn Timeline", ""])
    lines.extend(_turn_lines(state.get("turns", [])))
    lines.extend(["", "## Evidence Timeline", ""])
    lines.extend(_evidence_lines(state.get("evidence", [])))
    lines.extend(["", "## Intervention Queue", ""])
    lines.extend(_intervention_lines(state.get("interventions", [])))
    lines.extend(["", "## Suggested But Not Detected", ""])
    lines.extend(_recommendation_lines(state.get("suggested", [])))
    lines.extend(["", "## Recommended Skills Or Tools", ""])
    lines.extend(_recommendation_lines(state.get("recommended", [])))
    lines.extend(["", "## Policy Settings", ""])
    lines.extend(_preference_lines(state.get("preferences", {})))
    lines.extend(["", "## Conflicts", ""])
    conflicts = state.get("conflicts", [])
    if conflicts:
        for conflict in conflicts:
            skills = " / ".join(conflict.get("skills", []))
            overlap = ", ".join(conflict.get("overlap", []))
            lines.append(f"- {skills}: {conflict.get('reason')} ({overlap})")
    else:
        lines.append("- none")
    lines.extend(["", "## Skill Cards", ""])
    for skill in state.get("skills", []):
        lines.extend(_skill_card(skill))
    return "\n".join(lines) + "\n"


def render_dashboard(state: dict[str, Any]) -> str:
    counts = _evidence_counts(state.get("evidence", []), state.get("suggested", []))
    skills = state.get("skills", [])
    project_skills, global_skills = _split_skills_by_scope(skills)
    project_cards = "\n".join(_dashboard_skill_card(skill) for skill in project_skills[:12])
    global_cards = "\n".join(_dashboard_skill_card(skill) for skill in global_skills[:24])
    suggested = "\n".join(
        _dashboard_recommendation(item, note="not confirmed usage") for item in state.get("suggested", [])
    ) or _empty_note("No suggested skills.")
    recommended = "\n".join(_dashboard_recommendation(item) for item in state.get("recommended", [])) or _empty_note(
        "No recommended tools."
    )
    interventions = _dashboard_interventions(state.get("interventions", []))
    preferences = _dashboard_preferences(state.get("preferences", {}))
    privacy_note = _dashboard_privacy(state.get("privacy", {}))
    project_conflicts, global_conflicts = _split_conflicts(state.get("conflicts", []))
    project_conflict_html = "\n".join(_dashboard_conflict(item) for item in project_conflicts[:5]) or _empty_note(
        "No project conflicts detected."
    )
    global_conflict_html = "\n".join(_dashboard_conflict(item) for item in global_conflicts[:20]) or _empty_note(
        "No global conflicts detected."
    )
    evidence_groups = _group_evidence(state.get("evidence", []))
    invoked_html = "\n".join(_dashboard_evidence(item) for item in evidence_groups["invoked"][:10]) or _empty_note(
        "No confirmed invocation events detected. This usually means the platform did not expose explicit skill invocation logs."
    )
    read_html = "\n".join(_dashboard_evidence(item) for item in evidence_groups["read"][:10]) or _empty_note(
        "No confirmed SKILL.md reads detected."
    )
    loaded_html = "\n".join(_dashboard_evidence(item) for item in evidence_groups["loaded"][:30]) or _empty_note(
        "No loaded skill listings detected."
    )
    turns_html = _dashboard_turns(state.get("turns", []), state.get("suggested", []), state.get("conflicts", []))
    adapter_capabilities = _dashboard_adapter_capabilities(state.get("evidence", []))
    network = state.get("network", {})
    network_enabled = bool(network.get("enabled"))
    network_label = "enabled" if network_enabled else "disabled"
    updated_at = state.get("updated_at") or "unknown"
    monitor_section = _collapsible_panel(
        "live-monitor",
        "live_monitor_title",
        "Live Skill Monitor",
        f"""
      <div class="turn-controls">
        <label>
          <span data-i18n="turn_limit_label">Visible turns</span>
          <input id="turn-limit" type="number" min="1" max="200" step="1" value="20">
        </label>
        <span class="meta" id="turn-limit-status"></span>
      </div>
      <details class="fold" data-detail-key="live-status-help">
        <summary><span data-i18n="live_status_help_title">How to read this monitor</span></summary>
        <p class="subtle" data-i18n="live_turn_status_note">Run skillsense serve to watch each agent turn update from local logs. Loaded/read/invoked are evidence states; suggested is not confirmed usage.</p>
        <h3 class="section-gap" data-i18n="adapter_capability_title">Adapter Capability</h3>
        <p class="subtle" data-i18n="adapter_capability_note">SkillSense only shows invoked when the platform exposes an explicit invocation event.</p>
        {adapter_capabilities}
      </details>
      {turns_html}
""",
    )
    evidence_section = _collapsible_panel(
        "evidence-timeline",
        "evidence_timeline_title",
        "Evidence Timeline",
        f"""
      <p class="subtle" data-i18n="evidence_timeline_note">Invoked means explicit platform usage. Read means a SKILL.md was opened. Loaded only means the skill was visible to the agent.</p>
      <h3 data-i18n="invoked_title">Invoked</h3>
      {invoked_html}
      <h3 class="section-gap" data-i18n="read_title">Read</h3>
      {read_html}
      <details class="fold" data-detail-key="loaded-skill-listings">
        <summary><span data-i18n="loaded_skill_listings">Loaded skill listings</span> ({len(evidence_groups["loaded"])})</summary>
        <p class="subtle" data-i18n="loaded_note">Loaded is availability evidence, not usage evidence.</p>
        {loaded_html}
      </details>
""",
        collapsed=True,
    )
    supporting_section = _collapsible_panel(
        "supporting-insights",
        "supporting_insights_title",
        "Supporting Insights",
        f"""
      <p class="subtle" data-i18n="supporting_insights_note">Suggestions, project recommendations, and conflicts are supporting signals. They help explain what may be useful or confusing, but they are not the core live evidence stream.</p>
      <details class="fold" data-detail-key="suggested">
        <summary><span data-i18n="suggested_title">Suggested</span>{_info_tooltip("suggested_title_tooltip")}</summary>
        {suggested}
      </details>
      <details class="fold" data-detail-key="recommended">
        <summary><span data-i18n="recommended_title">Recommended</span>{_info_tooltip("recommended_title_tooltip")}</summary>
        {recommended}
      </details>
      <details class="fold" data-detail-key="project-conflicts">
        <summary><span data-i18n="project_conflicts_title">Project Conflicts</span>{_info_tooltip("project_conflicts_title_tooltip")}</summary>
        <p class="subtle" data-i18n="conflicts_note">Trigger overlap, not actual usage.</p>
        {project_conflict_html}
        <details class="fold" data-detail-key="global-conflicts">
          <summary><span data-i18n="global_conflicts">Global conflicts</span> ({len(global_conflicts)})</summary>
          {global_conflict_html}
        </details>
      </details>
""",
        collapsed=True,
    )
    local_index_section = _collapsible_panel(
        "local-skill-index",
        "local_skill_index_title",
        "Local Skill Index",
        f"""
      <p class="subtle" data-i18n="local_skill_index_note">Project and example skills are shown first. Global skills are folded because they are available locally but may not belong to this project.</p>
      <div class="skills-grid">
        {project_cards or _empty_note("No project or example skills indexed.")}
      </div>
      <details class="fold" data-detail-key="global-skills">
        <summary><span data-i18n="global_skills">Global skills</span> ({len(global_skills)})</summary>
        <div class="skills-grid">
          {global_cards or _empty_note("No global skills indexed.")}
        </div>
      </details>
""",
        collapsed=True,
    )
    intervention_section = _collapsible_panel(
        "intervention-queue",
        "intervention_queue_title",
        "Intervention Queue",
        f"""
      <p class="subtle" data-i18n="intervention_queue_note">Potential skill conflicts or repair suggestions. SkillSense only proposes changes; it does not edit SKILL.md without approval.</p>
      {interventions}
""",
        collapsed=True,
    )
    advanced_section = _collapsible_panel(
        "advanced-settings",
        "advanced_settings_title",
        "Advanced Settings",
        f"""
      <details class="fold" data-detail-key="policy-settings">
        <summary><span data-i18n="policy_settings_title">Policy Settings</span>{_info_tooltip("policy_settings_title_tooltip")}</summary>
        {preferences}
      </details>
      <details class="fold" data-detail-key="privacy-settings">
        <summary><span data-i18n="privacy_settings_title">Privacy Settings</span>{_info_tooltip("privacy_settings_title_tooltip")}</summary>
        {privacy_note}
      </details>
""",
        collapsed=True,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SkillSense Dashboard</title>
  <style>
    :root {{
      --bg: #f7fbfa;
      --surface: rgba(255, 255, 255, 0.9);
      --soft: rgba(247, 252, 251, 0.92);
      --line: #cfe1df;
      --ink: #1d2d35;
      --muted: #60747b;
      --teal: #45a895;
      --blue: #5d87ca;
      --amber: #bc8840;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: radial-gradient(circle at 15% 0%, rgba(222, 245, 241, 0.72), transparent 32%), var(--bg);
      font-family: "Segoe UI", Arial, sans-serif;
      letter-spacing: 0;
    }}
    .shell {{
      width: min(1180px, calc(100% - 40px));
      margin: 0 auto;
      padding: 48px 0;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      margin-bottom: 28px;
    }}
    .top-actions {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 10px;
    }}
    .language-control {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }}
    .language-control select {{
      height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.78);
      color: var(--ink);
      font: inherit;
    }}
    .language-control select {{ padding: 0 8px; }}
    [data-i18n], .i18n-text {{ white-space: pre-line; }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 34px; line-height: 1.1; }}
    h2 {{ font-size: 22px; margin-bottom: 14px; }}
    h3 {{ font-size: 17px; margin-bottom: 8px; }}
    .subtle {{ color: var(--muted); margin-top: 8px; }}
    .network {{
      color: var(--muted);
      font-size: 14px;
      margin-top: 6px;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .network-toggle {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.78);
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      padding: 3px 8px;
      cursor: pointer;
    }}
    .network-toggle:disabled {{ color: var(--muted); cursor: wait; }}
    .live-status {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
    .info {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      margin-left: 6px;
      border-radius: 50%;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.72);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      cursor: help;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .metric, .panel, .skill-card, .item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: 0 18px 42px rgba(42, 83, 86, 0.08);
    }}
    .metric {{ padding: 18px; min-height: 112px; }}
    .metric-label {{
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 14px;
    }}
    .metric-name {{ display: block; }}
    .metric strong {{ display: block; margin-top: 14px; font-size: 32px; line-height: 1; }}
    .loaded strong, .read strong {{ color: var(--teal); }}
    .invoked strong, .recommended strong {{ color: var(--amber); }}
    .inferred strong {{ color: #55aaa0; }}
    .suggested strong {{ color: var(--blue); }}
    .panel {{ padding: 24px; margin-bottom: 18px; }}
    .panel-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 14px;
    }}
    .panel-header h2 {{
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 0;
    }}
    .panel-toggle {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.76);
      color: var(--muted);
      font: inherit;
      font-size: 13px;
      padding: 5px 9px;
      cursor: pointer;
    }}
    .panel-body {{
      overflow: hidden;
      max-height: 99999px;
      opacity: 1;
      transform: translateY(0);
      transition: max-height 260ms ease, opacity 180ms ease, transform 180ms ease;
    }}
    .collapsible-panel.collapsed .panel-body {{
      max-height: 0;
      opacity: 0;
      transform: translateY(-8px);
    }}
    .item {{ padding: 16px; margin-top: 12px; background: var(--soft); box-shadow: none; }}
    .item-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }}
    .confidence {{ color: var(--teal); font-weight: 700; }}
    .reasons {{ color: var(--muted); margin-top: 8px; font-size: 14px; line-height: 1.45; }}
    .reasons .i18n-text {{ display: block; margin-top: 6px; }}
    .section-gap {{ margin-top: 22px; }}
    .skills-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .skill-card {{ padding: 16px; box-shadow: none; background: var(--soft); }}
    .meta {{ color: var(--muted); font-size: 13px; line-height: 1.5; margin-top: 8px; }}
    .tags {{ color: var(--teal); font-size: 13px; margin-top: 10px; }}
    .capability-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .capability .meta {{ margin-top: 8px; }}
    .intervention {{ border-left: 3px solid var(--amber); }}
    .intervention-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .action-button {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.76);
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      padding: 5px 9px;
      cursor: pointer;
    }}
    details.action-button {{ display: inline-block; }}
    details.action-button summary {{ list-style: none; cursor: pointer; }}
    details.action-button summary::-webkit-details-marker {{ display: none; }}
    .proposal {{
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
      white-space: pre-wrap;
    }}
    .fold, .turn {{ margin-top: 14px; }}
    .fold summary, .turn summary {{ color: var(--muted); cursor: pointer; }}
    .turn summary strong {{ color: var(--ink); }}
    .trigger-diagnostics {{
      margin-top: 12px;
      padding-top: 6px;
    }}
    .turn-text {{
      margin-top: 12px;
      padding: 12px;
      border-radius: 8px;
      background: rgba(230, 242, 240, 0.62);
      color: var(--ink);
      line-height: 1.48;
      overflow-wrap: anywhere;
    }}
    .badge {{
      display: inline-block;
      margin-left: 8px;
      padding: 2px 6px;
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .turn-summary {{
      white-space: pre-line;
      line-height: 1.35;
      text-align: left;
      vertical-align: middle;
    }}
    .turn-controls {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .turn-controls label {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    .turn-controls input {{
      width: 82px;
      height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.78);
      color: var(--ink);
      font: inherit;
      padding: 0 8px;
    }}
    code {{
      display: inline-block;
      max-width: 100%;
      overflow-wrap: anywhere;
      padding: 2px 4px;
      border-radius: 4px;
      background: rgba(224, 239, 237, 0.72);
    }}
    @media (max-width: 920px) {{
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .skills-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 560px) {{
      .topbar {{ display: block; }}
      .metrics {{ grid-template-columns: 1fr; }}
      .shell {{ width: min(100% - 24px, 1180px); padding: 28px 0; }}
      h1 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <main class="shell" data-updated-at="{html.escape(str(updated_at), quote=True)}">
    <header class="topbar">
      <div>
        <h1>SkillSense Dashboard</h1>
        <p class="subtle" data-i18n="subtitle">Local-first skill observability and recommendations.</p>
        <p class="subtle"><span data-i18n="updated">Updated</span>: <span data-local-time="{html.escape(str(updated_at), quote=True)}">{html.escape(str(updated_at))}</span></p>
        <p class="live-status" id="live-status" data-i18n="live_static">Live: static file mode. Run skillsense serve for smooth updates.</p>
      </div>
      <div class="top-actions">
        <label class="language-control">
          <span data-i18n="language">Language</span>
          <select id="language-select" aria-label="Dashboard language">
            <option value="en">English</option>
            <option value="zh">中文</option>
            <option value="ja">日本語</option>
            <option value="ko">한국어</option>
            <option value="es">Español</option>
            <option value="fr">Français</option>
          </select>
        </label>
        <div class="network" data-network-enabled="{str(network_enabled).lower()}">
          <span data-i18n="network">Network</span>:
          <strong id="network-state">{html.escape(network_label)}</strong>
          <button id="network-toggle" class="network-toggle" type="button">Enable</button>
          <span class="info" data-tooltip="network_tooltip" title="{html.escape(network.get('tooltip', NETWORK_TOOLTIP))}" aria-label="{html.escape(network.get('tooltip', NETWORK_TOOLTIP))}">!</span>
        </div>
      </div>
    </header>

    <section class="metrics" aria-label="Skill state counts">
      {_metric("loaded", counts["loaded"])}
      {_metric("read", counts["read"])}
      {_metric("invoked", counts["invoked"])}
      {_metric("inferred", counts["inferred"])}
      {_metric("suggested", counts["suggested"])}
    </section>

    {monitor_section}
    {evidence_section}

    {intervention_section}
    {supporting_section}
    {local_index_section}
    {advanced_section}
  </main>
  <script>
    (() => {{
      const translations = {{
        en: {{
          subtitle: "Live per-turn skill status from local agent logs.",
          updated: "Updated",
          live_static: "Live: static file mode. Run skillsense serve for smooth updates.",
          live_polling: "Live: polling every 2s without full-page reload.",
          live_waiting: "Live: waiting for local server.",
          live_updated: "Live: updated",
          language: "Language",
          network: "Network",
          network_enabled: "enabled",
          network_disabled: "disabled",
          network_enable: "Enable",
          network_disable: "Disable",
          network_saving: "Saving...",
          network_updated: "Network setting updated",
          network_update_failed: "Network setting update failed",
          network_serve_required: "Run skillsense serve to change network settings from the dashboard.",
          network_tooltip: "Networking is optional and disabled by default. When enabled, it may fetch repo stars, maintenance status, or remote metadata. Core scan, suggest, status, and report features stay local.",
          metric_loaded_tooltip: "The agent platform made this skill visible in context. This is availability, not proof of use.",
          metric_read_tooltip: "Local logs show a SKILL.md was opened. Stronger than loaded, but still not a confirmed invocation.",
          metric_invoked_tooltip: "The platform explicitly logged a skill invocation. This is the strongest usage evidence.",
          metric_inferred_tooltip: "SkillSense only guessed from traces such as output, commands, or file changes. Treat it as possible, not confirmed.",
          metric_suggested_tooltip: "SkillSense thinks the prompt should consider this skill, but no usage evidence was detected.",
          live_monitor_title_tooltip: "Core feature: a live per-turn view of which skills were visible, read, invoked, missed, or unclear.",
          evidence_timeline_title_tooltip: "A chronological evidence log. Use it to trace where loaded/read/invoked came from.",
          suggested_title_tooltip: "Skills that match the current prompt but are not confirmed as used.",
          recommended_title_tooltip: "Project-level suggestions for skills or tools that may be useful but are not obvious in the index.",
          project_conflicts_title_tooltip: "Trigger keyword overlap. This is a risk signal, not proof that an error happened.",
          local_skill_index_title_tooltip: "All skills found on this machine. Being indexed does not mean the agent used them this turn.",
          intervention_queue_title_tooltip: "Actionable repair suggestions. SkillSense proposes changes but does not edit SKILL.md without approval.",
          supporting_insights_title_tooltip: "Secondary signals. Useful for context, but not the main live evidence stream.",
          advanced_settings_title_tooltip: "Low-priority local settings. These are folded so the live monitor stays focused.",
          policy_settings_title_tooltip: "Recommendation-layer preferences only. These are not platform-level hard blocks.",
          privacy_settings_title_tooltip: "Controls whether turn text is saved or shown locally. Evidence can work without saving chat text.",
          trigger_diagnostics_title: "Trigger Diagnostics",
          trigger_diagnostics_tooltip: "A small black box for this turn: what was detected, what may have been missed, and what could be confused.",
          trigger_diagnostics_note: "This uses only local evidence and the local skill index. It does not call an LLM.",
          detected_evidence_label: "Detected evidence",
          missed_candidates_label: "Missed candidates",
          possible_confusion_label: "Possible confusion",
          expand_panel: "Expand",
          collapse_panel: "Collapse",
          live_monitor_title: "Live Skill Monitor",
          live_status_help_title: "How to read this monitor",
          turn_limit_label: "Visible turns",
          skill_path_label: "Path",
          skill_repo_label: "Repo",
          skill_stars_label: "Stars",
          skill_maintenance_label: "Maintenance",
          scope_project: "project",
          scope_example: "example",
          scope_user_global: "global",
          scope_unknown: "unknown",
          value_unknown: "unknown",
          maintenance_unknown: "unknown",
          maintenance_active: "active",
          maintenance_quiet: "quiet",
          maintenance_stale: "stale",
          maintenance_archived: "archived",
          live_turn_status_title: "Live Turn Skill Status",
          live_turn_status_note: "Run skillsense serve to watch each agent turn update from local logs. Loaded/read/invoked are evidence states; suggested is not confirmed usage.",
          adapter_capability_title: "Adapter Capability",
          adapter_capability_note: "SkillSense only shows invoked when the platform exposes an explicit invocation event.",
          intervention_queue_title: "Intervention Queue",
          intervention_queue_note: "Potential skill conflicts or repair suggestions. SkillSense only proposes changes; it does not edit SKILL.md without approval.",
          intervention_status_label: "Status",
          intervention_skills_label: "Skills",
          intervention_reason_label: "Issue",
          intervention_impact_label: "Impact",
          intervention_evidence_label: "Evidence",
          intervention_proposal_label: "Proposal",
          view_proposal: "View proposal",
          apply_after_review: "Apply after review",
          dismiss: "Dismiss",
          apply_confirm: "Apply this reviewed change to the target SKILL.md?",
          intervention_updated: "Intervention updated",
          intervention_failed: "Intervention update failed",
          intervention_serve_required: "Run skillsense serve to update interventions from the dashboard.",
          supporting_insights_title: "Supporting Insights",
          supporting_insights_note: "Suggestions, project recommendations, and conflicts are supporting signals. They help explain what may be useful or confusing, but they are not the core live evidence stream.",
          policy_settings_title: "Policy Settings",
          advanced_settings_title: "Advanced Settings",
          privacy_settings_title: "Privacy Settings",
          suggested_title: "Suggested",
          recommended_title: "Recommended",
          preferences_title: "Preferences",
          project_conflicts_title: "Project Conflicts",
          conflicts_note: "Trigger overlap, not actual usage.",
          global_conflicts: "Global conflicts",
          turn_timeline_title: "Turn Timeline",
          turn_timeline_note: "Open a turn to see which loaded/read/invoked evidence is tied to that user message. Missing evidence means SkillSense did not find confirmed proof in local logs.",
          evidence_timeline_title: "Evidence Timeline",
          evidence_timeline_note: "Invoked means explicit platform usage. Read means a SKILL.md was opened. Loaded only means the skill was visible to the agent.",
          invoked_title: "Invoked",
          read_title: "Read",
          loaded_skill_listings: "Loaded skill listings",
          loaded_note: "Loaded is availability evidence, not usage evidence.",
          local_skill_index_title: "Local Skill Index",
          local_skill_index_note: "Project and example skills are shown first. Global skills are folded because they are available locally but may not belong to this project.",
          global_skills: "Global skills",
          metric_loaded: "loaded",
          metric_read: "read",
          metric_invoked: "invoked",
          metric_inferred: "inferred",
          metric_suggested: "suggested",
        }},
        zh: {{
          subtitle: "来自本地 Agent 日志的实时逐轮 skill 状态。",
          updated: "更新时间",
          live_static: "实时：静态文件模式。运行 skillsense serve 可获得丝滑刷新。",
          live_polling: "实时：每 2 秒轻量轮询，不整页刷新。",
          live_waiting: "实时：等待本地服务。",
          live_updated: "实时：已更新",
          language: "界面语言",
          network: "联网",
          network_enabled: "已开启",
          network_disabled: "已关闭",
          network_enable: "开启",
          network_disable: "关闭",
          network_saving: "保存中...",
          network_updated: "联网设置已更新",
          network_update_failed: "联网设置更新失败",
          network_serve_required: "请运行 skillsense serve 后再从 dashboard 修改联网设置。",
          network_tooltip: "联网是可选功能，默认关闭。开启后可用于获取 repo stars、维护状态或远程 metadata。scan、suggest、status、report 等核心功能仍然本地运行。",
          metric_loaded_tooltip: "平台把这个 skill 放进 Agent 可见范围。它表示“看得见”，不代表真的用了。",
          metric_read_tooltip: "本地日志显示 Agent 打开过某个 SKILL.md。它比已加载更强，但仍不等于明确调用。",
          metric_invoked_tooltip: "平台明确记录了 skill 调用事件。这是最强的使用证据。",
          metric_inferred_tooltip: "没有真实调用日志，只能从输出、命令或文件变化推测，所以叫疑似。",
          metric_suggested_tooltip: "SkillSense 认为当前请求应该考虑这个 skill，但没有检测到使用证据。",
          live_monitor_title_tooltip: "核心功能：实时按轮次查看哪些 skill 可见、被读取、被调用、可能漏掉或不确定。",
          evidence_timeline_title_tooltip: "按时间列出证据来源，用来追溯 loaded/read/invoked 是从哪里来的。",
          suggested_title_tooltip: "和当前 prompt 相关、但没有被确认使用的候选 skill。",
          recommended_title_tooltip: "根据项目结构推荐可能需要补充的 skill 或工具。",
          project_conflicts_title_tooltip: "这里只表示触发词重叠风险，不代表已经导致错误。",
          local_skill_index_title_tooltip: "本机扫描到的 skill 清单。出现在这里不代表本轮用了它。",
          intervention_queue_title_tooltip: "需要用户处理的修复建议。SkillSense 只建议，不会静默修改 SKILL.md。",
          supporting_insights_title_tooltip: "辅助信号。它们提供上下文，但不是实时证据主线。",
          advanced_settings_title_tooltip: "低优先级本地设置。默认折叠，让实时观测保持干净。",
          policy_settings_title_tooltip: "只影响 SkillSense 的推荐层，不是平台级强制拦截。",
          privacy_settings_title_tooltip: "控制是否在本地保存或显示轮次正文。不保存聊天正文也能看证据。",
          trigger_diagnostics_title: "触发诊断",
          trigger_diagnostics_tooltip: "这一轮的小黑匣子：看到了什么、可能漏了什么、哪些触发词可能混淆。",
          trigger_diagnostics_note: "这里只使用本地证据和本地 skill 索引，不调用 LLM。",
          detected_evidence_label: "检测到的证据",
          missed_candidates_label: "可能漏掉的候选",
          possible_confusion_label: "可能混淆",
          expand_panel: "展开",
          collapse_panel: "收起",
          live_monitor_title: "实时 Skill 观测",
          live_status_help_title: "如何阅读这个监测区",
          turn_limit_label: "显示轮数",
          skill_path_label: "路径",
          skill_repo_label: "仓库",
          skill_stars_label: "星标",
          skill_maintenance_label: "维护状态",
          scope_project: "项目内",
          scope_example: "示例",
          scope_user_global: "全局",
          scope_unknown: "未知",
          value_unknown: "未知",
          maintenance_unknown: "未知",
          maintenance_active: "活跃",
          maintenance_quiet: "较少更新",
          maintenance_stale: "长期未更新",
          maintenance_archived: "已归档",
          live_turn_status_title: "实时轮次 Skill 状态",
          live_turn_status_note: "运行 skillsense serve 后，可以从本地日志实时查看每一轮 Agent 的 skill 状态。Loaded/read/invoked 是证据状态；suggested 不是确认使用。",
          adapter_capability_title: "适配器能力",
          adapter_capability_note: "只有平台暴露明确调用事件时，SkillSense 才会显示已调用。",
          intervention_queue_title: "修复建议队列",
          intervention_queue_note: "这里显示潜在 skill 冲突和修复建议。SkillSense 只生成建议；没有用户确认不会修改 SKILL.md。",
          intervention_status_label: "状态",
          intervention_skills_label: "相关 skills",
          intervention_reason_label: "问题",
          intervention_impact_label: "影响",
          intervention_evidence_label: "证据",
          intervention_proposal_label: "建议方案",
          view_proposal: "查看方案",
          apply_after_review: "确认后应用",
          dismiss: "忽略",
          apply_confirm: "确认把这个已审阅的修改写入目标 SKILL.md 吗？",
          intervention_updated: "修复建议已更新",
          intervention_failed: "修复建议更新失败",
          intervention_serve_required: "请运行 skillsense serve 后再从 dashboard 更新修复建议。",
          supporting_insights_title: "辅助洞察",
          supporting_insights_note: "建议、项目推荐和冲突分析只是辅助信号。它们帮助解释什么可能有用或容易混淆，但不是核心实时证据流。",
          policy_settings_title: "策略设置",
          advanced_settings_title: "高级设置",
          privacy_settings_title: "隐私设置",
          suggested_title: "建议考虑",
          recommended_title: "项目推荐",
          preferences_title: "本地偏好",
          project_conflicts_title: "项目内冲突",
          conflicts_note: "这里只表示触发词重叠，不代表实际使用。",
          global_conflicts: "全局冲突",
          turn_timeline_title: "轮次时间线",
          turn_timeline_note: "展开某一轮可查看与该轮绑定的 loaded/read/invoked 证据。没有证据表示 SkillSense 没在本地日志里找到确认记录。",
          evidence_timeline_title: "证据时间线",
          evidence_timeline_note: "Invoked 表示平台明确记录调用；Read 表示打开过 SKILL.md；Loaded 只表示该 skill 对 Agent 可见。",
          invoked_title: "已调用",
          read_title: "已读取",
          loaded_skill_listings: "已加载 skill 列表",
          loaded_note: "Loaded 是可见性证据，不是使用证据。",
          local_skill_index_title: "本地 Skill 索引",
          local_skill_index_note: "项目内和示例 skills 优先显示；全局 skills 默认折叠，因为它们未必属于当前项目。",
          global_skills: "全局 skills",
          metric_loaded: "已加载",
          metric_read: "已读取",
          metric_invoked: "已调用",
          metric_inferred: "疑似",
          metric_suggested: "建议",
        }},
        ja: {{
          subtitle: "ローカル Agent ログから見るターンごとの live skill 状態。",
          updated: "更新時刻",
          live_static: "ライブ: 静的ファイルモード。滑らかな更新には skillsense serve を実行してください。",
          live_polling: "ライブ: 2 秒ごとに軽量ポーリングし、ページ全体は再読み込みしません。",
          live_waiting: "ライブ: ローカルサーバーを待機中。",
          live_updated: "ライブ: 更新済み",
          language: "表示言語",
          network: "ネットワーク",
          network_enabled: "有効",
          network_disabled: "無効",
          network_enable: "有効化",
          network_disable: "無効化",
          network_saving: "保存中...",
          network_updated: "ネットワーク設定を更新しました",
          network_update_failed: "ネットワーク設定の更新に失敗しました",
          network_serve_required: "dashboard から変更するには skillsense serve を実行してください。",
          network_tooltip: "ネットワークは任意で、既定では無効です。有効にすると repo stars、メンテナンス状態、リモート metadata の取得に使えます。scan、suggest、status、report などの中核機能はローカルで動作します。",
          metric_loaded_tooltip: "この skill が Agent から見える状態です。利用の証拠ではありません。",
          metric_read_tooltip: "SKILL.md が開かれたことをローカルログで確認しました。呼び出し確定ではありません。",
          metric_invoked_tooltip: "プラットフォームが明示的な skill 呼び出しを記録した状態です。",
          metric_inferred_tooltip: "出力、コマンド、ファイル変更からの推測です。確定ではありません。",
          metric_suggested_tooltip: "この prompt で検討すべき候補ですが、使用証拠はありません。",
          live_monitor_title_tooltip: "中心機能です。各ターンで skill が見えたか、読まれたか、呼び出されたかを見ます。",
          evidence_timeline_title_tooltip: "loaded/read/invoked の根拠を時間順に追跡します。",
          suggested_title_tooltip: "現在の prompt に合うが、使用確認はされていない候補です。",
          recommended_title_tooltip: "プロジェクト構成から役立ちそうな skill や tool を提案します。",
          project_conflicts_title_tooltip: "trigger keyword の重複リスクです。エラー発生の証明ではありません。",
          local_skill_index_title_tooltip: "このマシンで見つかった skill 一覧です。本ターンで使われたとは限りません。",
          intervention_queue_title_tooltip: "修復提案です。承認なしに SKILL.md は変更しません。",
          supporting_insights_title_tooltip: "補助的なシグナルです。文脈には役立ちますが、live evidence の主軸ではありません。",
          advanced_settings_title_tooltip: "低優先度のローカル設定です。live monitor を見やすくするため折りたたみます。",
          policy_settings_title_tooltip: "SkillSense の推薦だけに効く設定です。プラットフォームの強制ブロックではありません。",
          privacy_settings_title_tooltip: "ターン本文をローカル保存または表示するかを制御します。本文なしでも証拠は使えます。",
          trigger_diagnostics_title: "Trigger 診断",
          trigger_diagnostics_tooltip: "このターンの小さなブラックボックスです。検出、見逃し候補、混同リスクを示します。",
          trigger_diagnostics_note: "ローカル証拠とローカル skill index だけを使います。LLM は呼びません。",
          detected_evidence_label: "検出された証拠",
          missed_candidates_label: "見逃し候補",
          possible_confusion_label: "混同の可能性",
          expand_panel: "展開",
          collapse_panel: "閉じる",
          live_monitor_title: "Live Skill モニター",
          live_status_help_title: "このモニターの読み方",
          turn_limit_label: "表示ターン数",
          skill_path_label: "パス",
          skill_repo_label: "リポジトリ",
          skill_stars_label: "スター",
          skill_maintenance_label: "メンテナンス",
          scope_project: "プロジェクト",
          scope_example: "サンプル",
          scope_user_global: "グローバル",
          scope_unknown: "不明",
          value_unknown: "不明",
          maintenance_unknown: "不明",
          maintenance_active: "アクティブ",
          maintenance_quiet: "更新少なめ",
          maintenance_stale: "長期未更新",
          maintenance_archived: "アーカイブ済み",
          live_turn_status_title: "ライブのターン別 Skill 状態",
          live_turn_status_note: "skillsense serve を実行すると、ローカルログから各 Agent ターンの skill 状態を更新して確認できます。Loaded/read/invoked は証拠状態で、suggested は確認済み使用ではありません。",
          adapter_capability_title: "アダプター機能",
          adapter_capability_note: "SkillSense は、プラットフォームが明示的な呼び出しイベントを公開した場合のみ invoked を表示します。",
          intervention_queue_title: "修復提案キュー",
          intervention_queue_note: "潜在的な skill 競合や修復提案を表示します。SkillSense は提案のみを生成し、承認なしに SKILL.md を編集しません。",
          intervention_status_label: "状態",
          intervention_skills_label: "関連 skills",
          intervention_reason_label: "問題",
          intervention_impact_label: "影響",
          intervention_evidence_label: "証拠",
          intervention_proposal_label: "提案",
          view_proposal: "提案を見る",
          apply_after_review: "確認後に適用",
          dismiss: "無視",
          apply_confirm: "確認済みの変更を対象の SKILL.md に適用しますか？",
          intervention_updated: "修復提案を更新しました",
          intervention_failed: "修復提案の更新に失敗しました",
          intervention_serve_required: "dashboard から修復提案を更新するには skillsense serve を実行してください。",
          supporting_insights_title: "補助インサイト",
          supporting_insights_note: "候補、プロジェクト推薦、競合分析は補助的なシグナルです。役立つ可能性や混同リスクを説明しますが、中心の live evidence stream ではありません。",
          policy_settings_title: "ポリシー設定",
          advanced_settings_title: "詳細設定",
          privacy_settings_title: "プライバシー設定",
          suggested_title: "検討候補",
          recommended_title: "プロジェクト推薦",
          preferences_title: "ローカル設定",
          project_conflicts_title: "プロジェクト内の競合",
          conflicts_note: "これはトリガー語の重複であり、実際の使用を意味しません。",
          global_conflicts: "グローバル競合",
          turn_timeline_title: "ターン履歴",
          turn_timeline_note: "ターンを開くと、そのユーザーメッセージに紐づく loaded/read/invoked 証拠を確認できます。証拠がない場合、SkillSense はローカルログで確認記録を見つけていません。",
          evidence_timeline_title: "証拠タイムライン",
          evidence_timeline_note: "Invoked は明示的な使用イベント、Read は SKILL.md の読み取り、Loaded はその skill が Agent から見えていたことだけを示します。",
          invoked_title: "呼び出し済み",
          read_title: "読み取り済み",
          loaded_skill_listings: "読み込まれた skill 一覧",
          loaded_note: "Loaded は可視性の証拠であり、使用証拠ではありません。",
          local_skill_index_title: "ローカル Skill インデックス",
          local_skill_index_note: "プロジェクトとサンプルの skills を先に表示します。グローバル skills は現在のプロジェクトに属さない場合があるため折りたたみます。",
          global_skills: "グローバル skills",
          metric_loaded: "読み込み済み",
          metric_read: "読み取り済み",
          metric_invoked: "呼び出し済み",
          metric_inferred: "推定",
          metric_suggested: "候補",
        }},
        ko: {{
          subtitle: "로컬 Agent 로그에서 보는 턴별 live skill 상태.",
          updated: "업데이트 시간",
          live_static: "실시간: 정적 파일 모드입니다. 부드러운 업데이트에는 skillsense serve를 실행하세요.",
          live_polling: "실시간: 2초마다 가볍게 폴링하며 전체 페이지를 새로고침하지 않습니다.",
          live_waiting: "실시간: 로컬 서버를 기다리는 중입니다.",
          live_updated: "실시간: 업데이트됨",
          language: "표시 언어",
          network: "네트워크",
          network_enabled: "켜짐",
          network_disabled: "꺼짐",
          network_enable: "켜기",
          network_disable: "끄기",
          network_saving: "저장 중...",
          network_updated: "네트워크 설정이 업데이트됨",
          network_update_failed: "네트워크 설정 업데이트 실패",
          network_serve_required: "dashboard에서 변경하려면 skillsense serve를 실행하세요.",
          network_tooltip: "네트워크는 선택 기능이며 기본값은 꺼짐입니다. 켜면 repo stars, 유지보수 상태, 원격 metadata를 가져오는 데 사용할 수 있습니다. scan, suggest, status, report 같은 핵심 기능은 계속 로컬에서 실행됩니다.",
          metric_loaded_tooltip: "플랫폼이 이 skill을 Agent가 볼 수 있게 했습니다. 사용 증거는 아닙니다.",
          metric_read_tooltip: "로컬 로그에 SKILL.md를 연 기록이 있습니다. loaded보다 강하지만 명시적 호출은 아닙니다.",
          metric_invoked_tooltip: "플랫폼이 skill 호출 이벤트를 명시적으로 기록했습니다. 가장 강한 사용 증거입니다.",
          metric_inferred_tooltip: "출력, 명령, 파일 변경 같은 흔적으로 추정한 것입니다. 확인된 사용은 아닙니다.",
          metric_suggested_tooltip: "현재 요청에서 고려할 만한 skill이지만 사용 증거는 없습니다.",
          live_monitor_title_tooltip: "핵심 기능입니다. 턴마다 어떤 skill이 보였고, 읽혔고, 호출됐고, 놓쳤을 수 있는지 봅니다.",
          evidence_timeline_title_tooltip: "loaded/read/invoked 증거가 어디서 왔는지 시간순으로 보여줍니다.",
          suggested_title_tooltip: "현재 prompt와 관련 있지만 사용이 확인되지 않은 후보입니다.",
          recommended_title_tooltip: "프로젝트 구조상 추가하면 유용할 수 있는 skill 또는 tool입니다.",
          project_conflicts_title_tooltip: "trigger keyword 중복 위험입니다. 실제 오류가 발생했다는 뜻은 아닙니다.",
          local_skill_index_title_tooltip: "이 컴퓨터에서 찾은 skill 목록입니다. 여기 있다고 이번 턴에 사용됐다는 뜻은 아닙니다.",
          intervention_queue_title_tooltip: "수정 제안입니다. 승인 없이 SKILL.md를 수정하지 않습니다.",
          supporting_insights_title_tooltip: "보조 신호입니다. 맥락을 설명하지만 핵심 실시간 증거 흐름은 아닙니다.",
          advanced_settings_title_tooltip: "우선순위가 낮은 로컬 설정입니다. 실시간 모니터가 깔끔하도록 접어 둡니다.",
          policy_settings_title_tooltip: "SkillSense 추천층에만 적용됩니다. 플랫폼 수준 강제 차단은 아닙니다.",
          privacy_settings_title_tooltip: "턴 본문을 로컬에 저장하거나 표시할지 제어합니다. 본문 없이도 증거는 볼 수 있습니다.",
          trigger_diagnostics_title: "트리거 진단",
          trigger_diagnostics_tooltip: "이 턴의 작은 블랙박스입니다. 감지된 것, 놓쳤을 수 있는 것, 혼동 가능성을 보여줍니다.",
          trigger_diagnostics_note: "로컬 증거와 로컬 skill index만 사용합니다. LLM을 호출하지 않습니다.",
          detected_evidence_label: "감지된 증거",
          missed_candidates_label: "놓쳤을 수 있는 후보",
          possible_confusion_label: "혼동 가능성",
          expand_panel: "펼치기",
          collapse_panel: "접기",
          live_monitor_title: "실시간 Skill 모니터",
          live_status_help_title: "이 모니터 읽는 법",
          turn_limit_label: "표시할 턴 수",
          skill_path_label: "경로",
          skill_repo_label: "저장소",
          skill_stars_label: "스타",
          skill_maintenance_label: "유지보수",
          scope_project: "프로젝트",
          scope_example: "예시",
          scope_user_global: "전역",
          scope_unknown: "알 수 없음",
          value_unknown: "알 수 없음",
          maintenance_unknown: "알 수 없음",
          maintenance_active: "활발",
          maintenance_quiet: "업데이트 적음",
          maintenance_stale: "오래됨",
          maintenance_archived: "보관됨",
          live_turn_status_title: "실시간 턴별 Skill 상태",
          live_turn_status_note: "skillsense serve를 실행하면 로컬 로그에서 각 Agent 턴의 skill 상태를 갱신해 볼 수 있습니다. Loaded/read/invoked는 증거 상태이며, suggested는 확인된 사용이 아닙니다.",
          adapter_capability_title: "어댑터 기능",
          adapter_capability_note: "플랫폼이 명시적인 호출 이벤트를 노출할 때만 SkillSense가 invoked를 표시합니다.",
          intervention_queue_title: "수정 제안 큐",
          intervention_queue_note: "잠재적인 skill 충돌과 수정 제안을 표시합니다. SkillSense는 제안만 만들며 승인 없이 SKILL.md를 편집하지 않습니다.",
          intervention_status_label: "상태",
          intervention_skills_label: "관련 skills",
          intervention_reason_label: "문제",
          intervention_impact_label: "영향",
          intervention_evidence_label: "증거",
          intervention_proposal_label: "제안",
          view_proposal: "제안 보기",
          apply_after_review: "검토 후 적용",
          dismiss: "무시",
          apply_confirm: "검토한 변경을 대상 SKILL.md에 적용할까요?",
          intervention_updated: "수정 제안이 업데이트되었습니다",
          intervention_failed: "수정 제안 업데이트에 실패했습니다",
          intervention_serve_required: "dashboard에서 수정 제안을 업데이트하려면 skillsense serve를 실행하세요.",
          supporting_insights_title: "보조 인사이트",
          supporting_insights_note: "제안, 프로젝트 추천, 충돌 분석은 보조 신호입니다. 유용하거나 혼동될 수 있는 것을 설명하지만 핵심 실시간 증거 흐름은 아닙니다.",
          policy_settings_title: "정책 설정",
          advanced_settings_title: "고급 설정",
          privacy_settings_title: "개인정보 설정",
          suggested_title: "검토 제안",
          recommended_title: "프로젝트 추천",
          preferences_title: "로컬 기본 설정",
          project_conflicts_title: "프로젝트 내 충돌",
          conflicts_note: "이는 트리거 단어의 중복이며 실제 사용을 뜻하지 않습니다.",
          global_conflicts: "전역 충돌",
          turn_timeline_title: "턴 타임라인",
          turn_timeline_note: "턴을 열면 해당 사용자 메시지에 연결된 loaded/read/invoked 증거를 볼 수 있습니다. 증거가 없으면 SkillSense가 로컬 로그에서 확인 기록을 찾지 못했다는 뜻입니다.",
          evidence_timeline_title: "증거 타임라인",
          evidence_timeline_note: "Invoked는 명시적 사용 이벤트, Read는 SKILL.md 읽기, Loaded는 해당 skill이 Agent에 보였다는 뜻입니다.",
          invoked_title: "호출됨",
          read_title: "읽음",
          loaded_skill_listings: "로드된 skill 목록",
          loaded_note: "Loaded는 가시성 증거이며 사용 증거가 아닙니다.",
          local_skill_index_title: "로컬 Skill 인덱스",
          local_skill_index_note: "프로젝트 및 예제 skills를 먼저 표시합니다. 전역 skills는 현재 프로젝트에 속하지 않을 수 있어 접어 둡니다.",
          global_skills: "전역 skills",
          metric_loaded: "로드됨",
          metric_read: "읽음",
          metric_invoked: "호출됨",
          metric_inferred: "추정",
          metric_suggested: "제안",
        }},
        es: {{
          subtitle: "Estado live de skills por turno desde logs locales del Agent.",
          updated: "Actualizado",
          live_static: "En vivo: modo de archivo estático. Ejecuta skillsense serve para actualizaciones suaves.",
          live_polling: "En vivo: sondeo ligero cada 2 s sin recargar toda la página.",
          live_waiting: "En vivo: esperando el servidor local.",
          live_updated: "En vivo: actualizado",
          language: "Idioma",
          network: "Red",
          network_enabled: "activada",
          network_disabled: "desactivada",
          network_enable: "Activar",
          network_disable: "Desactivar",
          network_saving: "Guardando...",
          network_updated: "Configuración de red actualizada",
          network_update_failed: "No se pudo actualizar la red",
          network_serve_required: "Ejecuta skillsense serve para cambiar la red desde el dashboard.",
          network_tooltip: "La red es opcional y está desactivada por defecto. Al activarla, puede obtener repo stars, estado de mantenimiento o metadata remota. Las funciones centrales scan, suggest, status y report siguen siendo locales.",
          metric_loaded_tooltip: "La plataforma hizo visible este skill para el Agent. Es disponibilidad, no prueba de uso.",
          metric_read_tooltip: "Los logs locales muestran que se abrió SKILL.md. Es más fuerte que loaded, pero no confirma una invocación.",
          metric_invoked_tooltip: "La plataforma registró explícitamente una invocación del skill. Es la evidencia más fuerte.",
          metric_inferred_tooltip: "SkillSense solo lo dedujo por salidas, comandos o cambios de archivos. No está confirmado.",
          metric_suggested_tooltip: "SkillSense cree que este prompt debería considerar el skill, pero no encontró evidencia de uso.",
          live_monitor_title_tooltip: "Función central: vista live por turno de qué skills fueron visibles, leídos, invocados, omitidos o dudosos.",
          evidence_timeline_title_tooltip: "Log cronológico para rastrear de dónde vienen loaded/read/invoked.",
          suggested_title_tooltip: "Skills que encajan con el prompt actual, pero no están confirmados como usados.",
          recommended_title_tooltip: "Skills o herramientas que podrían ayudar según la estructura del proyecto.",
          project_conflicts_title_tooltip: "Riesgo por solapamiento de trigger keywords. No prueba que haya ocurrido un error.",
          local_skill_index_title_tooltip: "Skills encontrados en esta máquina. Estar indexado no significa que se usó en este turno.",
          intervention_queue_title_tooltip: "Sugerencias accionables. SkillSense propone cambios, pero no edita SKILL.md sin aprobación.",
          supporting_insights_title_tooltip: "Señales secundarias. Dan contexto, pero no son el flujo principal de evidencia live.",
          advanced_settings_title_tooltip: "Ajustes locales de baja prioridad. Se pliegan para mantener el monitor live enfocado.",
          policy_settings_title_tooltip: "Preferencias solo para la capa de recomendaciones. No son bloqueos de plataforma.",
          privacy_settings_title_tooltip: "Controla si el texto de los turnos se guarda o se muestra localmente. La evidencia funciona sin guardar el chat.",
          trigger_diagnostics_title: "Diagnóstico de disparo",
          trigger_diagnostics_tooltip: "Caja negra pequeña del turno: qué se detectó, qué pudo faltar y qué pudo confundirse.",
          trigger_diagnostics_note: "Usa solo evidencia local y el índice local de skills. No llama a un LLM.",
          detected_evidence_label: "Evidencia detectada",
          missed_candidates_label: "Candidatos omitidos",
          possible_confusion_label: "Posible confusión",
          expand_panel: "Expandir",
          collapse_panel: "Contraer",
          live_monitor_title: "Monitor live de Skills",
          live_status_help_title: "Cómo leer este monitor",
          turn_limit_label: "Turnos visibles",
          skill_path_label: "Ruta",
          skill_repo_label: "Repositorio",
          skill_stars_label: "Estrellas",
          skill_maintenance_label: "Mantenimiento",
          scope_project: "proyecto",
          scope_example: "ejemplo",
          scope_user_global: "global",
          scope_unknown: "desconocido",
          value_unknown: "desconocido",
          maintenance_unknown: "desconocido",
          maintenance_active: "activo",
          maintenance_quiet: "poca actividad",
          maintenance_stale: "sin actividad reciente",
          maintenance_archived: "archivado",
          live_turn_status_title: "Estado live de skills por turno",
          live_turn_status_note: "Ejecuta skillsense serve para ver cómo se actualiza cada turno del Agent desde los logs locales. Loaded/read/invoked son estados de evidencia; suggested no es uso confirmado.",
          adapter_capability_title: "Capacidad del adaptador",
          adapter_capability_note: "SkillSense solo muestra invoked cuando la plataforma expone un evento explícito de invocación.",
          intervention_queue_title: "Cola de intervención",
          intervention_queue_note: "Muestra posibles conflictos de skills o propuestas de reparación. SkillSense solo propone cambios; no edita SKILL.md sin aprobación.",
          intervention_status_label: "Estado",
          intervention_skills_label: "Skills relacionados",
          intervention_reason_label: "Problema",
          intervention_impact_label: "Impacto",
          intervention_evidence_label: "Evidencia",
          intervention_proposal_label: "Propuesta",
          view_proposal: "Ver propuesta",
          apply_after_review: "Aplicar tras revisar",
          dismiss: "Descartar",
          apply_confirm: "¿Aplicar este cambio revisado al SKILL.md objetivo?",
          intervention_updated: "Intervención actualizada",
          intervention_failed: "No se pudo actualizar la intervención",
          intervention_serve_required: "Ejecuta skillsense serve para actualizar intervenciones desde el dashboard.",
          supporting_insights_title: "Insights de apoyo",
          supporting_insights_note: "Las sugerencias, recomendaciones del proyecto y conflictos son señales de apoyo. Ayudan a explicar qué puede ser útil o confuso, pero no son el flujo principal de evidencia live.",
          policy_settings_title: "Ajustes de política",
          advanced_settings_title: "Ajustes avanzados",
          privacy_settings_title: "Ajustes de privacidad",
          suggested_title: "Sugeridos",
          recommended_title: "Recomendados para el proyecto",
          preferences_title: "Preferencias locales",
          project_conflicts_title: "Conflictos del proyecto",
          conflicts_note: "Esto indica solapamiento de disparadores, no uso real.",
          global_conflicts: "Conflictos globales",
          turn_timeline_title: "Línea de tiempo por turno",
          turn_timeline_note: "Abre un turno para ver la evidencia loaded/read/invoked asociada a ese mensaje. Si no hay evidencia, SkillSense no encontró confirmación en los logs locales.",
          evidence_timeline_title: "Línea de tiempo de evidencia",
          evidence_timeline_note: "Invoked significa uso explícito; Read significa que se abrió SKILL.md; Loaded solo significa que el skill era visible para el Agent.",
          invoked_title: "Invocado",
          read_title: "Leído",
          loaded_skill_listings: "Listados de skills cargados",
          loaded_note: "Loaded es evidencia de disponibilidad, no de uso.",
          local_skill_index_title: "Índice local de Skills",
          local_skill_index_note: "Primero se muestran los skills del proyecto y los ejemplos. Los globales se pliegan porque pueden no pertenecer a este proyecto.",
          global_skills: "Skills globales",
          metric_loaded: "cargados",
          metric_read: "leídos",
          metric_invoked: "invocados",
          metric_inferred: "inferidos",
          metric_suggested: "sugeridos",
        }},
        fr: {{
          subtitle: "Statut live des skills par tour depuis les logs locaux de l’Agent.",
          updated: "Mis à jour",
          live_static: "Direct : mode fichier statique. Lancez skillsense serve pour des mises à jour fluides.",
          live_polling: "Direct : interrogation légère toutes les 2 s sans rechargement complet.",
          live_waiting: "Direct : attente du serveur local.",
          live_updated: "Direct : mis à jour",
          language: "Langue",
          network: "Réseau",
          network_enabled: "activé",
          network_disabled: "désactivé",
          network_enable: "Activer",
          network_disable: "Désactiver",
          network_saving: "Enregistrement...",
          network_updated: "Paramètre réseau mis à jour",
          network_update_failed: "Échec de la mise à jour réseau",
          network_serve_required: "Lancez skillsense serve pour modifier le réseau depuis le dashboard.",
          network_tooltip: "Le réseau est optionnel et désactivé par défaut. Une fois activé, il peut récupérer les repo stars, l’état de maintenance ou des metadata distantes. Les fonctions centrales scan, suggest, status et report restent locales.",
          metric_loaded_tooltip: "La plateforme a rendu ce skill visible pour l’Agent. C’est une disponibilité, pas une preuve d’usage.",
          metric_read_tooltip: "Les logs locaux montrent qu’un SKILL.md a été ouvert. C’est plus fort que loaded, mais pas une invocation confirmée.",
          metric_invoked_tooltip: "La plateforme a enregistré explicitement une invocation du skill. C’est la preuve la plus forte.",
          metric_inferred_tooltip: "SkillSense l’a seulement déduit à partir de sorties, commandes ou changements de fichiers. Ce n’est pas confirmé.",
          metric_suggested_tooltip: "SkillSense pense que ce prompt devrait considérer ce skill, mais n’a trouvé aucune preuve d’usage.",
          live_monitor_title_tooltip: "Fonction centrale : vue live par tour des skills visibles, lus, invoqués, manqués ou incertains.",
          evidence_timeline_title_tooltip: "Journal chronologique pour retracer l’origine des preuves loaded/read/invoked.",
          suggested_title_tooltip: "Skills qui correspondent au prompt actuel, sans usage confirmé.",
          recommended_title_tooltip: "Skills ou outils potentiellement utiles selon la structure du projet.",
          project_conflicts_title_tooltip: "Risque de chevauchement des trigger keywords. Ce n’est pas une preuve d’erreur.",
          local_skill_index_title_tooltip: "Skills trouvés sur cette machine. Être indexé ne signifie pas être utilisé dans ce tour.",
          intervention_queue_title_tooltip: "Suggestions de réparation. SkillSense propose, mais ne modifie pas SKILL.md sans approbation.",
          supporting_insights_title_tooltip: "Signaux secondaires. Ils donnent du contexte, mais ne sont pas le flux principal de preuves live.",
          advanced_settings_title_tooltip: "Paramètres locaux de faible priorité. Ils restent repliés pour garder le moniteur live concentré.",
          policy_settings_title_tooltip: "Préférences de la couche de recommandation seulement. Ce ne sont pas des blocages plateforme.",
          privacy_settings_title_tooltip: "Contrôle si le texte des tours est enregistré ou affiché localement. Les preuves fonctionnent sans enregistrer le chat.",
          trigger_diagnostics_title: "Diagnostic de déclenchement",
          trigger_diagnostics_tooltip: "Petite boîte noire du tour : ce qui est détecté, possiblement manqué ou confus.",
          trigger_diagnostics_note: "Utilise seulement les preuves locales et l’index local des skills. N’appelle pas de LLM.",
          detected_evidence_label: "Preuves détectées",
          missed_candidates_label: "Candidats manqués",
          possible_confusion_label: "Confusion possible",
          expand_panel: "Déplier",
          collapse_panel: "Replier",
          live_monitor_title: "Moniteur live des Skills",
          live_status_help_title: "Comment lire ce moniteur",
          turn_limit_label: "Tours visibles",
          skill_path_label: "Chemin",
          skill_repo_label: "Dépôt",
          skill_stars_label: "Étoiles",
          skill_maintenance_label: "Maintenance",
          scope_project: "projet",
          scope_example: "exemple",
          scope_user_global: "global",
          scope_unknown: "inconnu",
          value_unknown: "inconnu",
          maintenance_unknown: "inconnu",
          maintenance_active: "actif",
          maintenance_quiet: "peu actif",
          maintenance_stale: "inactif depuis longtemps",
          maintenance_archived: "archivé",
          live_turn_status_title: "Statut live des skills par tour",
          live_turn_status_note: "Lancez skillsense serve pour voir chaque tour de l’Agent se mettre à jour depuis les logs locaux. Loaded/read/invoked sont des états de preuve; suggested n’est pas une utilisation confirmée.",
          adapter_capability_title: "Capacité de l’adapter",
          adapter_capability_note: "SkillSense n’affiche invoked que si la plateforme expose un événement d’invocation explicite.",
          intervention_queue_title: "File d’intervention",
          intervention_queue_note: "Affiche les conflits de skills potentiels et les propositions de réparation. SkillSense propose seulement; il ne modifie pas SKILL.md sans approbation.",
          intervention_status_label: "Statut",
          intervention_skills_label: "Skills liés",
          intervention_reason_label: "Problème",
          intervention_impact_label: "Impact",
          intervention_evidence_label: "Preuve",
          intervention_proposal_label: "Proposition",
          view_proposal: "Voir la proposition",
          apply_after_review: "Appliquer après revue",
          dismiss: "Ignorer",
          apply_confirm: "Appliquer ce changement relu au SKILL.md cible ?",
          intervention_updated: "Intervention mise à jour",
          intervention_failed: "Échec de la mise à jour de l’intervention",
          intervention_serve_required: "Lancez skillsense serve pour mettre à jour les interventions depuis le dashboard.",
          supporting_insights_title: "Insights de soutien",
          supporting_insights_note: "Les suggestions, recommandations de projet et conflits sont des signaux de soutien. Ils aident à expliquer ce qui peut être utile ou ambigu, mais ne sont pas le flux principal de preuves live.",
          policy_settings_title: "Paramètres de politique",
          advanced_settings_title: "Paramètres avancés",
          privacy_settings_title: "Paramètres de confidentialité",
          suggested_title: "Suggestions",
          recommended_title: "Recommandations du projet",
          preferences_title: "Préférences locales",
          project_conflicts_title: "Conflits du projet",
          conflicts_note: "Cela indique un chevauchement de déclencheurs, pas une utilisation réelle.",
          global_conflicts: "Conflits globaux",
          turn_timeline_title: "Chronologie des tours",
          turn_timeline_note: "Ouvrez un tour pour voir les preuves loaded/read/invoked associées au message. Sans preuve, SkillSense n’a trouvé aucune confirmation dans les logs locaux.",
          evidence_timeline_title: "Chronologie des preuves",
          evidence_timeline_note: "Invoked signifie un événement explicite; Read signifie que SKILL.md a été ouvert; Loaded signifie seulement que le skill était visible pour l’Agent.",
          invoked_title: "Invoqué",
          read_title: "Lu",
          loaded_skill_listings: "Listes de skills chargées",
          loaded_note: "Loaded est une preuve de visibilité, pas une preuve d’utilisation.",
          local_skill_index_title: "Index local des Skills",
          local_skill_index_note: "Les skills du projet et les exemples sont affichés d’abord. Les skills globaux sont repliés car ils peuvent ne pas appartenir à ce projet.",
          global_skills: "Skills globaux",
          metric_loaded: "chargés",
          metric_read: "lus",
          metric_invoked: "invoqués",
          metric_inferred: "déduits",
          metric_suggested: "suggérés",
        }},
      }};
      const getLanguage = () => localStorage.getItem("skillsense.dashboard.language") || "en";
      const localText = (key, language = getLanguage()) => (translations[language] || translations.en)[key] || translations.en[key] || key;
      const t = (key) => {{
        const language = getLanguage();
        const english = translations.en[key] || key;
        if (language === "en") return english;
        const local = localText(key, language);
        return local === english ? english : local + "\\n" + english;
      }};
      const td = (key) => localText(key, getLanguage());
      const localizedText = (node) => {{
        const language = getLanguage();
        const english = node.dataset.en || node.textContent || "";
        if (language === "en") return english;
        const local = node.dataset[language] || english;
        return local === english ? english : local + "\\n" + english;
      }};
      const turnSummaryText = (node) => {{
        const language = getLanguage();
        const counts = {{
          invoked: Number(node.dataset.invokedCount || 0),
          read: Number(node.dataset.readCount || 0),
          loaded: Number(node.dataset.loadedCount || 0),
        }};
        const english = `${{counts.invoked}} ${{translations.en.metric_invoked}} / ${{counts.read}} ${{translations.en.metric_read}} / ${{counts.loaded}} ${{translations.en.metric_loaded}}`;
        if (language === "en") return english;
        const local = `${{counts.invoked}} ${{localText("metric_invoked", language)}} / ${{counts.read}} ${{localText("metric_read", language)}} / ${{counts.loaded}} ${{localText("metric_loaded", language)}}`;
        return local === english ? english : local + "\\n" + english;
      }};
      const applyNetworkText = () => {{
        const root = document.querySelector(".network");
        if (!root) return;
        const enabled = root.dataset.networkEnabled === "true";
        const state = document.getElementById("network-state");
        const button = document.getElementById("network-toggle");
        if (state) state.textContent = t(enabled ? "network_enabled" : "network_disabled");
        if (button) button.textContent = t(enabled ? "network_disable" : "network_enable");
      }};
      const applyLanguage = () => {{
        const language = getLanguage();
        const langAttrs = {{ en: "en", zh: "zh-CN", ja: "ja", ko: "ko", es: "es", fr: "fr" }};
        document.documentElement.lang = langAttrs[language] || "en";
        document.querySelectorAll("[data-i18n]").forEach((node) => {{
          const key = node.getAttribute("data-i18n");
          if (key && ((translations[language] || {{}})[key] || translations.en[key])) {{
            node.textContent = t(key);
          }}
        }});
        document.querySelectorAll("[data-i18n-direct]").forEach((node) => {{
          const key = node.getAttribute("data-i18n-direct");
          if (key && ((translations[language] || {{}})[key] || translations.en[key])) {{
            node.textContent = td(key);
          }}
        }});
        document.querySelectorAll(".i18n-text").forEach((node) => {{
          node.textContent = localizedText(node);
        }});
        document.querySelectorAll(".turn-summary").forEach((node) => {{
          node.textContent = turnSummaryText(node);
        }});
        document.querySelectorAll("[data-tooltip]").forEach((node) => {{
          const key = node.getAttribute("data-tooltip");
          if (key && ((translations[language] || {{}})[key] || translations.en[key])) {{
            const text = td(key);
            node.setAttribute("title", text);
            node.setAttribute("aria-label", text);
          }}
        }});
        applyNetworkText();
        if (typeof syncPanelToggles === "function") syncPanelToggles();
        const select = document.getElementById("language-select");
        if (select) select.value = language;
      }};
      const bindLanguage = () => {{
        const select = document.getElementById("language-select");
        const save = () => {{
          if (select) localStorage.setItem("skillsense.dashboard.language", select.value);
          applyLanguage();
          if (location.protocol.startsWith("http")) setStatus(t("live_polling"));
        }};
        if (select && !select.dataset.bound) {{
          select.dataset.bound = "true";
          select.addEventListener("change", save);
        }}
      }};
      const bindNetwork = () => {{
        const button = document.getElementById("network-toggle");
        if (!button || button.dataset.bound) return;
        button.dataset.bound = "true";
        button.addEventListener("click", async () => {{
          if (!location.protocol.startsWith("http")) {{
            setStatus(t("network_serve_required"));
            return;
          }}
          const root = document.querySelector(".network");
          if (!root) return;
          const next = root.dataset.networkEnabled !== "true";
          button.disabled = true;
          button.textContent = t("network_saving");
          try {{
            const response = await fetch("/api/network", {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ enabled: next }}),
            }});
            if (!response.ok) throw new Error("network update failed");
            const data = await response.json();
            root.dataset.networkEnabled = data?.network?.enabled ? "true" : "false";
            applyNetworkText();
            setStatus(t("network_updated"));
          }} catch (_error) {{
            applyNetworkText();
            setStatus(t("network_update_failed"));
          }} finally {{
            button.disabled = false;
          }}
        }});
      }};
      const bindInterventions = () => {{
        document.querySelectorAll(".intervention-action").forEach((button) => {{
          if (button.dataset.bound) return;
          button.dataset.bound = "true";
          button.addEventListener("click", async () => {{
            if (!location.protocol.startsWith("http")) {{
              setStatus(t("intervention_serve_required"));
              return;
            }}
            const id = button.dataset.id || "";
            const action = button.dataset.action || "";
            if (!id || !action) return;
            if (action === "apply" && !window.confirm(t("apply_confirm"))) return;
            button.disabled = true;
            try {{
              const response = await fetch(`/api/interventions/${{encodeURIComponent(id)}}/${{action}}`, {{
                method: "POST",
              }});
              if (!response.ok) throw new Error("intervention update failed");
              const data = await response.json();
              const card = button.closest(".intervention");
              const status = card?.querySelector(".intervention-status");
              if (status) status.textContent = action === "dismiss" ? t("dismiss") : t("intervention_updated");
              setStatus(data?.message || t("intervention_updated"));
              refreshDashboard();
            }} catch (_error) {{
              setStatus(t("intervention_failed"));
            }} finally {{
              button.disabled = false;
            }}
          }});
        }});
      }};
      const panelStoreKey = "skillsense.dashboard.collapsedPanels";
      const readCollapsedPanels = () => {{
        const raw = localStorage.getItem(panelStoreKey);
        if (!raw) return null;
        try {{ return new Set(JSON.parse(raw)); }} catch (_error) {{ return null; }}
      }};
      const saveCollapsedPanels = () => {{
        const keys = Array.from(document.querySelectorAll(".collapsible-panel.collapsed"))
          .map((panel) => panel.dataset.panelKey)
          .filter(Boolean);
        localStorage.setItem(panelStoreKey, JSON.stringify(keys));
      }};
      const syncPanelToggle = (panel) => {{
        const button = panel.querySelector(".panel-toggle");
        if (button) button.textContent = td(panel.classList.contains("collapsed") ? "expand_panel" : "collapse_panel");
      }};
      const syncPanelToggles = () => {{
        document.querySelectorAll(".collapsible-panel").forEach(syncPanelToggle);
      }};
      const bindPanels = () => {{
        const stored = readCollapsedPanels();
        document.querySelectorAll(".collapsible-panel").forEach((panel) => {{
          const key = panel.dataset.panelKey || "";
          if (stored) panel.classList.toggle("collapsed", stored.has(key));
          const button = panel.querySelector(".panel-toggle");
          if (button && !button.dataset.bound) {{
            button.dataset.bound = "true";
            button.addEventListener("click", () => {{
              panel.classList.toggle("collapsed");
              syncPanelToggle(panel);
              saveCollapsedPanels();
            }});
          }}
          syncPanelToggle(panel);
        }});
      }};
      const turnLimitKey = "skillsense.dashboard.turnLimit";
      const applyTurnLimit = () => {{
        const input = document.getElementById("turn-limit");
        const status = document.getElementById("turn-limit-status");
        const turns = Array.from(document.querySelectorAll(".turn[data-turn-index]"));
        if (!input || !turns.length) return;
        const stored = localStorage.getItem(turnLimitKey);
        if (stored && document.activeElement !== input) input.value = stored;
        const limit = Math.max(1, Math.min(200, Number(input.value || 20)));
        turns.forEach((turn, index) => {{
          turn.hidden = index >= limit;
        }});
        if (status) status.textContent = `${{Math.min(limit, turns.length)}} / ${{turns.length}}`;
      }};
      const bindTurnLimit = () => {{
        const input = document.getElementById("turn-limit");
        if (!input || input.dataset.bound) {{
          applyTurnLimit();
          return;
        }}
        input.dataset.bound = "true";
        input.addEventListener("input", () => {{
          localStorage.setItem(turnLimitKey, input.value || "20");
          applyTurnLimit();
        }});
        applyTurnLimit();
      }};
      const detailKey = (node) => node.dataset.detailKey || (node.querySelector("summary")?.textContent || "");
      const captureOpenDetails = () => new Set(
        Array.from(document.querySelectorAll("details[open]")).map(detailKey).filter(Boolean)
      );
      const restoreOpenDetails = (keys) => {{
        document.querySelectorAll("details").forEach((node) => {{
          const key = detailKey(node);
          if (key && keys.has(key)) node.open = true;
        }});
      }};
      const formatLocalTimeValue = (raw) => {{
        const date = raw ? new Date(raw) : null;
        if (!date || Number.isNaN(date.getTime())) return raw || "";
        return date.toLocaleString(undefined, {{
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          timeZoneName: "short",
        }});
      }};
      const formatLocalTimes = () => {{
        document.querySelectorAll("[data-local-time]").forEach((node) => {{
          const raw = node.getAttribute("data-local-time");
          node.textContent = formatLocalTimeValue(raw);
        }});
      }};
      const hasSelection = () => {{
        const selection = window.getSelection && window.getSelection();
        return Boolean(selection && !selection.isCollapsed && selection.toString().trim());
      }};
      const interactiveTags = new Set(["INPUT", "TEXTAREA", "SELECT", "BUTTON"]);
      let busyUntil = 0;
      const markBusy = () => {{
        busyUntil = Date.now() + 1200;
      }};
      ["pointerdown", "keydown", "wheel"].forEach((eventName) => {{
        document.addEventListener(eventName, markBusy, {{ passive: true }});
      }});
      const isUserBusy = () => {{
        const active = document.activeElement;
        return Date.now() < busyUntil || hasSelection() || Boolean(active && interactiveTags.has(active.tagName));
      }};
      const setStatus = (text) => {{
        const status = document.getElementById("live-status");
        if (status) status.textContent = text;
      }};
      applyLanguage();
      formatLocalTimes();
      bindLanguage();
      bindNetwork();
      bindInterventions();
      bindPanels();
      bindTurnLimit();
      if (!location.protocol.startsWith("http")) return;
      let lastUpdated = "{html.escape(str(updated_at))}";
      setStatus(t("live_polling"));
      async function refreshDashboard() {{
        try {{
          if (isUserBusy()) return;
          const response = await fetch("dashboard.html?ts=" + Date.now(), {{ cache: "no-store" }});
          if (!response.ok) return;
          const text = await response.text();
          const doc = new DOMParser().parseFromString(text, "text/html");
          const incoming = doc.querySelector("main.shell");
          const current = document.querySelector("main.shell");
          const openDetails = captureOpenDetails();
          const scrollX = window.scrollX;
          const scrollY = window.scrollY;
          const incomingUpdated = incoming?.dataset.updatedAt || "";
          if (incoming && current && incomingUpdated && incomingUpdated !== lastUpdated) {{
            if (isUserBusy()) return;
            current.innerHTML = incoming.innerHTML;
            lastUpdated = incomingUpdated;
            applyLanguage();
            formatLocalTimes();
            bindLanguage();
            bindNetwork();
            bindInterventions();
            bindPanels();
            bindTurnLimit();
            restoreOpenDetails(openDetails);
            window.scrollTo(scrollX, scrollY);
            setStatus(t("live_updated") + " " + formatLocalTimeValue(lastUpdated));
          }}
        }} catch (_error) {{
          setStatus(t("live_waiting"));
        }}
      }}
      setInterval(refreshDashboard, 2000);
    }})();
  </script>
</body>
</html>
"""


def _accuracy_notice() -> str:
    return (
        "> Accuracy Notice: If the platform does not expose real skill invocation logs, "
        "SkillSense cannot know with 100% certainty whether a skill was used. "
        "It clearly separates confirmed usage from inferred usage."
    )


def _attach_evidence_to_turns(
    turns: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for turn in turns:
        item = dict(turn)
        item["evidence"] = []
        key = (str(item.get("platform") or ""), str(item.get("turn_id") or ""))
        if key[1]:
            by_key[key] = item
            result.append(item)
    for item in evidence:
        turn_id = str(item.get("turn_id") or "")
        if not turn_id:
            continue
        key = (str(item.get("platform") or ""), turn_id)
        turn = by_key.get(key)
        if turn is None:
            turn = {
                "turn_id": turn_id,
                "platform": item.get("platform") or "unknown",
                "timestamp": item.get("timestamp") or "",
                "user_message": "",
                "assistant_summary": "",
                "evidence": [],
            }
            by_key[key] = turn
            result.append(turn)
        turn["evidence"].append(item)
    return sorted(result, key=lambda item: str(item.get("timestamp") or ""), reverse=True)


def _apply_turn_privacy(turns: list[dict[str, Any]], privacy: dict[str, Any]) -> list[dict[str, Any]]:
    store_text = bool(privacy.get("store_turn_text", False))
    show_text = bool(privacy.get("show_turn_text", False))
    result = []
    for turn in turns:
        item = dict(turn)
        if not store_text:
            item["user_message"] = ""
            item["assistant_summary"] = ""
            item["text_hidden_reason"] = "Turn text is not stored by privacy.store_turn_text=false."
        elif not show_text:
            item["text_hidden_reason"] = "Turn text is stored but hidden by privacy.show_turn_text=false."
        result.append(item)
    return result


def _recommendation_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    lines = []
    for item in items:
        confidence = item.get("confidence", "unknown")
        lines.append(f"- {item.get('name')} ({item.get('status')}, confidence: {confidence})")
        for reason in item.get("reasons", []):
            lines.append(f"  - why: {reason}")
    return lines


def _turn_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    lines = []
    for item in items[:40]:
        evidence = item.get("evidence", [])
        summary = _turn_evidence_summary_badge(evidence)
        lines.append(f"- {item.get('platform')} / {item.get('turn_id') or 'unknown'}: {summary}")
        if item.get("user_message"):
            lines.append(f"  - user: {item.get('user_message')}")
        for evidence_item in evidence[:8]:
            lines.append(
                f"  - {evidence_item.get('event_type')} / {evidence_item.get('skill_name')} "
                f"({evidence_item.get('certainty')})"
            )
    return lines


def _preference_lines(preferences: dict[str, Any]) -> list[str]:
    if not preferences:
        return ["- none"]
    lines = []
    for key in ["prefer", "mute", "ask_before"]:
        values = preferences.get(key, [])
        lines.append(f"- {key}: {', '.join(values) if values else 'none'}")
    lines.append("- note: mute affects SkillSense suggestions; it is not platform-level blocking.")
    return lines


def _evidence_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    lines = []
    for item in items[:50]:
        lines.append(
            f"- {item.get('event_type')} / {item.get('skill_name')} "
            f"({item.get('platform')}, {item.get('source')}, turn: {item.get('turn_id') or 'unknown'}, "
            f"message: {item.get('message_id') or 'unknown'})"
        )
    return lines


def _intervention_lines(items: list[dict[str, Any]]) -> list[str]:
    open_items = [item for item in items if item.get("status") == "open"]
    if not open_items:
        return ["- none"]
    lines = []
    for item in open_items[:30]:
        skills = ", ".join(item.get("skills", []) or ["unknown"])
        lines.append(
            f"- {item.get('id')} [{item.get('severity')}] {item.get('type')} "
            f"({skills}): {item.get('reason')}"
        )
        proposal = item.get("proposal") or {}
        if proposal.get("summary"):
            lines.append(f"  - proposal: {proposal.get('summary')}")
    return lines


def _evidence_counts(evidence: list[dict[str, Any]], suggested: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"loaded": 0, "read": 0, "invoked": 0, "inferred": 0, "suggested": len(suggested)}
    for item in evidence:
        event_type = item.get("event_type")
        if event_type in counts:
            counts[event_type] += 1
    return counts


def _skill_card(skill: dict[str, Any]) -> list[str]:
    rewrite = rewrite_description(SkillProxy(skill))
    keywords = ", ".join(skill.get("keywords", []) or ["unknown"])
    aliases = ", ".join(skill.get("trigger_aliases", []) or ["unknown"])
    return [
        f"### {skill.get('name')}",
        "",
        f"- Purpose: {skill.get('summary') or skill.get('description') or 'unknown'}",
        f"- When to use: {skill.get('description') or 'unknown'}",
        "- When not to use: when the task is unrelated or the platform did not load this skill",
        f"- Trigger keywords: {keywords}",
        f"- Trigger aliases: {aliases}",
        f"- Risk tags: {', '.join(skill.get('risk_tags', []) or ['none'])}",
        f"- Local path: `{skill.get('path')}`",
        f"- Repo: {skill.get('repo_url') or 'unknown'}",
        f"- Stars: {skill.get('stars', 'unknown')}",
        f"- Maintenance: {skill.get('maintenance', 'unknown')}",
        f"- Description rewrite suggestion: {rewrite}",
        "",
    ]


def _metric(name: str, count: int) -> str:
    return f"""
      <article class="metric {html.escape(name)}">
        <div class="metric-label">
          <span class="metric-name" data-i18n="metric_{html.escape(name)}">{html.escape(name)}</span>
          {_info_tooltip(f"metric_{name}_tooltip")}
        </div>
        <strong>{count}</strong>
      </article>
"""


def _info_tooltip(key: str) -> str:
    return (
        f'<span class="info" data-tooltip="{html.escape(key, quote=True)}" '
        f'title="{html.escape(key, quote=True)}" aria-label="{html.escape(key, quote=True)}">!</span>'
    )


def _collapsible_panel(
    key: str,
    title_key: str,
    title: str,
    body: str,
    collapsed: bool = False,
) -> str:
    collapsed_class = " collapsed" if collapsed else ""
    return f"""
    <section class="panel collapsible-panel{collapsed_class}" data-panel-key="{html.escape(key, quote=True)}">
      <header class="panel-header">
        <h2><span data-i18n="{html.escape(title_key, quote=True)}">{html.escape(title)}</span>{_info_tooltip(f"{title_key}_tooltip")}</h2>
        <button class="panel-toggle" type="button" data-i18n-direct="collapse_panel">Collapse</button>
      </header>
      <div class="panel-body">
        {body}
      </div>
    </section>
"""


def _dashboard_recommendation(item: dict[str, Any], note: str = "") -> str:
    confidence = item.get("confidence", "unknown")
    reason_items = item.get("reasons", [])
    reasons = "".join(_reason_line(str(reason)) for reason in reason_items) or _poly_text(
        {
            "en": "No reason recorded.",
            "zh": "未记录原因。",
            "ja": "理由は記録されていません。",
            "ko": "기록된 이유가 없습니다.",
            "es": "No hay motivo registrado.",
            "fr": "Aucune raison enregistrée.",
        }
    )
    note_html = f'<span class="badge">{_poly_text(_localized_note(note))}</span>' if note else ""
    title = _localized_recommendation_name(str(item.get("name", "unknown")))
    return f"""
      <article class="item">
        <div class="item-head">
          <h3>{title}{note_html}</h3>
          <span class="confidence">{html.escape(str(confidence))}</span>
        </div>
        <div class="reasons">{reasons}</div>
      </article>
"""


def _dashboard_interventions(items: list[dict[str, Any]]) -> str:
    open_items = [item for item in items if item.get("status") == "open"]
    if not open_items:
        return (
            '<p class="subtle">'
            + _poly_text(
                {
                    "en": "No interventions detected. SkillSense did not find skill conflict risks that require action.",
                    "zh": "未发现需要处理的修复建议。SkillSense 没有检测到需要用户干预的 skill 冲突风险。",
                    "ja": "対応が必要な修復提案は見つかりませんでした。SkillSense はユーザー介入が必要な skill 競合リスクを検出していません。",
                    "ko": "처리할 수정 제안이 없습니다. SkillSense가 사용자 개입이 필요한 skill 충돌 위험을 감지하지 않았습니다.",
                    "es": "No se detectaron intervenciones. SkillSense no encontró riesgos de conflicto de skills que requieran acción.",
                    "fr": "Aucune intervention détectée. SkillSense n’a trouvé aucun risque de conflit de skills nécessitant une action.",
                }
            )
            + "</p>"
        )
    return "\n".join(_dashboard_intervention(item) for item in open_items[:10])


def _dashboard_intervention(item: dict[str, Any]) -> str:
    item_id = html.escape(str(item.get("id") or "unknown"), quote=True)
    skills = ", ".join(str(skill) for skill in item.get("skills", []) or ["unknown"])
    proposal = item.get("proposal") or {}
    evidence_lines = "".join(_dashboard_intervention_evidence(entry) for entry in item.get("evidence", [])[:3])
    if not evidence_lines:
        evidence_lines = (
            '<p class="meta">'
            + _poly_text(
                {
                    "en": "No direct evidence attached.",
                    "zh": "没有绑定直接证据。",
                    "ja": "直接の証拠は紐づいていません。",
                    "ko": "연결된 직접 증거가 없습니다.",
                    "es": "No hay evidencia directa adjunta.",
                    "fr": "Aucune preuve directe associée.",
                }
            )
            + "</p>"
        )
    diff = html.escape(str(proposal.get("preview_diff") or ""))
    diff_html = f'<pre class="proposal">{diff}</pre>' if diff else ""
    target = proposal.get("target_path")
    target_html = (
        f'<p class="meta"><strong>Target:</strong> <code>{html.escape(str(target))}</code></p>' if target else ""
    )
    return f"""
      <article class="item intervention" data-intervention-id="{item_id}">
        <div class="item-head">
          <h3>{_poly_text(_intervention_type_label(str(item.get("type") or "unknown")))}
            <span class="badge">{_poly_text(_severity_label(str(item.get("severity") or "unknown")))}</span>
          </h3>
          <span class="badge">{item_id}</span>
        </div>
        <p class="meta"><strong data-i18n="intervention_status_label">Status</strong>: <span class="intervention-status">{_poly_text(_status_label(str(item.get("status") or "open")))}</span></p>
        <p class="meta"><strong data-i18n="intervention_skills_label">Skills</strong>: {html.escape(skills)}</p>
        <p class="meta"><strong data-i18n="intervention_reason_label">Issue</strong>: {html.escape(str(item.get("reason") or "unknown"))}</p>
        <p class="meta"><strong data-i18n="intervention_impact_label">Impact</strong>: {html.escape(str(item.get("impact") or "unknown"))}</p>
        <div class="proposal">
          <strong data-i18n="intervention_evidence_label">Evidence</strong>
          {evidence_lines}
        </div>
        <div class="intervention-actions">
          <details class="action-button" data-detail-key="intervention-proposal-{item_id}">
            <summary data-i18n="view_proposal">View proposal</summary>
            <div class="proposal">
              <p class="meta"><strong data-i18n="intervention_proposal_label">Proposal</strong>: {html.escape(str(proposal.get("summary") or proposal.get("title") or "Review this item."))}</p>
              {target_html}
              {diff_html}
            </div>
          </details>
          <button class="action-button intervention-action" type="button" data-action="apply" data-id="{item_id}" data-i18n="apply_after_review">Apply after review</button>
          <button class="action-button intervention-action" type="button" data-action="dismiss" data-id="{item_id}" data-i18n="dismiss">Dismiss</button>
        </div>
      </article>
"""


def _dashboard_intervention_evidence(entry: dict[str, Any]) -> str:
    text = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    return f'<p class="meta"><code>{html.escape(text[:360])}</code></p>'


def _intervention_type_label(item_type: str) -> dict[str, str]:
    labels = {
        "conflict_risk": {
            "en": "Conflict risk",
            "zh": "冲突风险",
            "ja": "競合リスク",
            "ko": "충돌 위험",
            "es": "Riesgo de conflicto",
            "fr": "Risque de conflit",
        },
        "wrong_skill_risk": {
            "en": "Wrong skill risk",
            "zh": "疑似读错 skill",
            "ja": "誤った skill のリスク",
            "ko": "잘못된 skill 위험",
            "es": "Riesgo de skill incorrecto",
            "fr": "Risque de mauvais skill",
        },
        "missed_skill_risk": {
            "en": "Missed skill risk",
            "zh": "疑似漏用 skill",
            "ja": "見逃された skill のリスク",
            "ko": "누락된 skill 위험",
            "es": "Riesgo de skill omitido",
            "fr": "Risque de skill manqué",
        },
        "description_too_broad": {
            "en": "Description too broad",
            "zh": "描述过宽",
            "ja": "説明が広すぎる",
            "ko": "설명이 너무 넓음",
            "es": "Descripción demasiado amplia",
            "fr": "Description trop large",
        },
        "description_too_narrow": {
            "en": "Description too narrow",
            "zh": "描述过窄",
            "ja": "説明が狭すぎる",
            "ko": "설명이 너무 좁음",
            "es": "Descripción demasiado estrecha",
            "fr": "Description trop étroite",
        },
        "answer_error_signal": {
            "en": "Answer error signal",
            "zh": "回答报错迹象",
            "ja": "回答エラーの兆候",
            "ko": "답변 오류 신호",
            "es": "Señal de error en la respuesta",
            "fr": "Signal d’erreur dans la réponse",
        },
    }
    return labels.get(item_type, {"en": item_type, "zh": item_type, "ja": item_type, "ko": item_type, "es": item_type, "fr": item_type})


def _severity_label(severity: str) -> dict[str, str]:
    labels = {
        "high": {"en": "high", "zh": "高", "ja": "高", "ko": "높음", "es": "alta", "fr": "élevée"},
        "medium": {"en": "medium", "zh": "中", "ja": "中", "ko": "보통", "es": "media", "fr": "moyenne"},
        "low": {"en": "low", "zh": "低", "ja": "低", "ko": "낮음", "es": "baja", "fr": "faible"},
    }
    return labels.get(severity, {"en": severity, "zh": severity, "ja": severity, "ko": severity, "es": severity, "fr": severity})


def _status_label(status: str) -> dict[str, str]:
    labels = {
        "open": {"en": "open", "zh": "待处理", "ja": "未対応", "ko": "열림", "es": "abierta", "fr": "ouverte"},
        "dismissed": {"en": "dismissed", "zh": "已忽略", "ja": "却下済み", "ko": "무시됨", "es": "descartada", "fr": "ignorée"},
        "applied": {"en": "applied", "zh": "已应用", "ja": "適用済み", "ko": "적용됨", "es": "aplicada", "fr": "appliquée"},
    }
    return labels.get(status, {"en": status, "zh": status, "ja": status, "ko": status, "es": status, "fr": status})


def _dashboard_preferences(preferences: dict[str, Any]) -> str:
    rows = []
    labels = {
        "prefer": {"en": "prefer", "zh": "优先推荐", "ja": "優先", "ko": "우선 추천", "es": "preferir", "fr": "préférer"},
        "mute": {"en": "mute", "zh": "不再推荐", "ja": "ミュート", "ko": "추천 숨김", "es": "silenciar", "fr": "masquer"},
        "ask_before": {
            "en": "ask_before",
            "zh": "使用前询问",
            "ja": "使用前に確認",
            "ko": "사용 전 확인",
            "es": "preguntar antes",
            "fr": "demander avant",
        },
    }
    for key in ["prefer", "mute", "ask_before"]:
        values = preferences.get(key, [])
        label = html.escape(", ".join(values)) if values else _poly_text(
            {"en": "none", "zh": "无", "ja": "なし", "ko": "없음", "es": "ninguno", "fr": "aucun"}
        )
        rows.append(f'<p class="meta"><strong>{_poly_text(labels[key])}:</strong> {label}</p>')
    rows.append(
        '<p class="subtle">'
        + _poly_text(
            {
                "en": "Mute only affects SkillSense suggestions. It is not a platform-level block until an adapter supports enforcement.",
                "zh": "不再推荐只影响 SkillSense 建议层，不是平台级硬拦截。",
                "ja": "ミュートは SkillSense の提案だけに影響します。adapter が対応するまではプラットフォームレベルのブロックではありません。",
                "ko": "추천 숨김은 SkillSense 제안에만 영향을 줍니다. 어댑터가 지원하기 전까지는 플랫폼 수준 차단이 아닙니다.",
                "es": "Silenciar solo afecta las sugerencias de SkillSense. No es un bloqueo de plataforma hasta que un adaptador lo admita.",
                "fr": "Masquer n’affecte que les suggestions SkillSense. Ce n’est pas un blocage de plateforme tant qu’un adapter ne le prend pas en charge.",
            }
        )
        + "</p>"
    )
    return "\n".join(rows)


def _poly_text(values: dict[str, str]) -> str:
    attrs = " ".join(f'data-{key}="{html.escape(value, quote=True)}"' for key, value in values.items())
    return f'<span class="i18n-text" {attrs}>{html.escape(values.get("en", ""))}</span>'


def _simple_localized(key: str) -> dict[str, str]:
    values = {
        "no_detected_evidence": {
            "en": "none",
            "zh": "无",
            "ja": "なし",
            "ko": "없음",
            "es": "ninguna",
            "fr": "aucune",
        },
        "no_missed_candidates": {
            "en": "none",
            "zh": "无",
            "ja": "なし",
            "ko": "없음",
            "es": "ninguno",
            "fr": "aucun",
        },
        "no_possible_confusion": {
            "en": "none found",
            "zh": "未发现",
            "ja": "見つかりません",
            "ko": "찾지 못함",
            "es": "no se encontró",
            "fr": "aucune trouvée",
        },
    }
    return values.get(key, {"en": key, "zh": key, "ja": key, "ko": key, "es": key, "fr": key})


def _reason_line(reason: str) -> str:
    return _poly_text(_localized_reason(reason))


def _localized_note(note: str) -> dict[str, str]:
    if note == "not confirmed usage":
        return {
            "en": "not confirmed usage",
            "zh": "未确认使用",
            "ja": "使用未確認",
            "ko": "사용 확인 안 됨",
            "es": "uso no confirmado",
            "fr": "utilisation non confirmée",
        }
    return {"en": note, "zh": note, "ja": note, "ko": note, "es": note, "fr": note}


def _localized_recommendation_name(name: str) -> str:
    if name == "Testing workflow skill":
        return _poly_text(
            {
                "en": "Testing workflow skill",
                "zh": "测试工作流 skill",
                "ja": "テストワークフロー skill",
                "ko": "테스트 워크플로 skill",
                "es": "skill de flujo de pruebas",
                "fr": "skill de workflow de test",
            }
        )
    if name == "README validation skill":
        return _poly_text(
            {
                "en": "README validation skill",
                "zh": "README 验证 skill",
                "ja": "README 検証 skill",
                "ko": "README 검증 skill",
                "es": "skill de validación de README",
                "fr": "skill de validation README",
            }
        )
    return html.escape(name)


def _localized_reason(reason: str) -> dict[str, str]:
    if reason.startswith("prompt overlaps trigger terms:"):
        detail = reason.split(":", 1)[1].strip()
        return {
            "en": reason,
            "zh": f"提示词匹配触发词：{detail}",
            "ja": f"プロンプトがトリガー語に一致：{detail}",
            "ko": f"프롬프트가 트리거 단어와 일치: {detail}",
            "es": f"El prompt coincide con disparadores: {detail}",
            "fr": f"Le prompt correspond aux déclencheurs : {detail}",
        }
    if reason.startswith("prompt intent matches "):
        detail = reason.removeprefix("prompt intent matches ").strip()
        return {
            "en": reason,
            "zh": f"提示意图匹配：{detail}",
            "ja": f"プロンプトの意図が一致：{detail}",
            "ko": f"프롬프트 의도가 일치: {detail}",
            "es": f"La intención del prompt coincide: {detail}",
            "fr": f"L’intention du prompt correspond : {detail}",
        }
    if reason == "project contains README.md":
        return {
            "en": reason,
            "zh": "项目包含 README.md",
            "ja": "プロジェクトに README.md があります",
            "ko": "프로젝트에 README.md가 있습니다",
            "es": "El proyecto contiene README.md",
            "fr": "Le projet contient README.md",
        }
    if reason == "Chinese prompt matches generated trigger aliases":
        return {
            "en": reason,
            "zh": "中文提示词匹配生成的触发别名",
            "ja": "中国語のプロンプトが生成されたトリガー別名に一致",
            "ko": "중국어 프롬프트가 생성된 트리거 별칭과 일치",
            "es": "El prompt chino coincide con alias de disparo generados",
            "fr": "Le prompt chinois correspond aux alias de déclenchement générés",
        }
    if reason == "project has tests/ but no obvious testing skill is indexed":
        return {
            "en": reason,
            "zh": "项目有 tests/，但未索引明显的测试 skill",
            "ja": "プロジェクトに tests/ がありますが、明確なテスト skill は索引されていません",
            "ko": "프로젝트에 tests/가 있지만 명확한 테스트 skill이 인덱싱되지 않았습니다",
            "es": "El proyecto tiene tests/, pero no hay un skill de pruebas evidente indexado",
            "fr": "Le projet contient tests/, mais aucun skill de test évident n’est indexé",
        }
    if reason == "user preference boosts this skill":
        return {
            "en": reason,
            "zh": "本地偏好提升了该 skill",
            "ja": "ローカル設定によりこの skill が優先されます",
            "ko": "로컬 기본 설정이 이 skill을 우선합니다",
            "es": "La preferencia local aumenta este skill",
            "fr": "La préférence locale augmente ce skill",
        }
    return {"en": reason, "zh": reason, "ja": reason, "ko": reason, "es": reason, "fr": reason}


def _dashboard_privacy(privacy: dict[str, Any]) -> str:
    store_text = bool(privacy.get("store_turn_text", False))
    show_text = bool(privacy.get("show_turn_text", False))
    return (
        '<p class="meta"><strong>'
        + _poly_text(
            {
                "en": "privacy.store_turn_text",
                "zh": "保存轮次正文",
                "ja": "ターン本文を保存",
                "ko": "턴 본문 저장",
                "es": "guardar texto del turno",
                "fr": "enregistrer le texte du tour",
            }
        )
        + ":</strong> "
        f"{html.escape(str(store_text).lower())}</p>"
        '<p class="meta"><strong>'
        + _poly_text(
            {
                "en": "privacy.show_turn_text",
                "zh": "显示轮次正文",
                "ja": "ターン本文を表示",
                "ko": "턴 본문 표시",
                "es": "mostrar texto del turno",
                "fr": "afficher le texte du tour",
            }
        )
        + ":</strong> "
        f"{html.escape(str(show_text).lower())}</p>"
    )


def _dashboard_conflict(item: dict[str, Any]) -> str:
    names = " / ".join(item.get("skills", []))
    overlap = ", ".join(item.get("overlap", []))
    detail = f"{item.get('reason', 'overlap detected')}: {overlap}" if overlap else item.get("reason", "overlap detected")
    return f"""
      <article class="item">
        <h3>{html.escape(names or "unknown")}</h3>
        <p class="reasons">{html.escape(detail)}</p>
      </article>
"""


def _dashboard_adapter_capabilities(evidence: list[dict[str, Any]]) -> str:
    counts: dict[str, dict[str, int]] = {}
    for item in evidence:
        platform = str(item.get("platform") or "unknown")
        event_type = str(item.get("event_type") or "")
        platform_counts = counts.setdefault(platform, {"loaded": 0, "read": 0, "invoked": 0})
        if event_type in platform_counts:
            platform_counts[event_type] += 1
    generic_counts = {"loaded": 0, "read": 0, "invoked": 0}
    for platform, platform_counts in counts.items():
        if platform in {"codex", "claude_code"}:
            continue
        for key in generic_counts:
            generic_counts[key] += platform_counts.get(key, 0)
    return f"""
      <div class="capability-grid">
        {_adapter_capability_card("Codex local logs", counts.get("codex", {}))}
        {_adapter_capability_card("Claude Code local logs", counts.get("claude_code", {}))}
        {_adapter_capability_card("Generic JSONL / other agents", generic_counts)}
      </div>
"""


def _adapter_capability_card(name: str, counts: dict[str, int]) -> str:
    invoked_observed = counts.get("invoked", 0) > 0
    return f"""
      <article class="item capability">
        <h3>{html.escape(name)}</h3>
        <p class="meta">{_capability_line("loaded", "supported")}</p>
        <p class="meta">{_capability_line("read", "supported")}</p>
        <p class="meta">{_capability_line("invoked", "observed" if invoked_observed else "explicit_only")}</p>
      </article>
"""


def _capability_line(kind: str, status: str) -> str:
    labels = {
        "loaded": {
            "en": "Loaded detection",
            "zh": "已加载检测",
            "ja": "Loaded 検出",
            "ko": "Loaded 감지",
            "es": "Detección loaded",
            "fr": "Détection loaded",
        },
        "read": {
            "en": "Read detection",
            "zh": "已读取检测",
            "ja": "Read 検出",
            "ko": "Read 감지",
            "es": "Detección read",
            "fr": "Détection read",
        },
        "invoked": {
            "en": "Invoked detection",
            "zh": "已调用检测",
            "ja": "Invoked 検出",
            "ko": "Invoked 감지",
            "es": "Detección invoked",
            "fr": "Détection invoked",
        },
    }
    statuses = {
        "supported": {
            "en": "supported",
            "zh": "支持",
            "ja": "対応",
            "ko": "지원됨",
            "es": "compatible",
            "fr": "pris en charge",
        },
        "observed": {
            "en": "observed in current logs",
            "zh": "当前日志已观察到",
            "ja": "現在のログで観測済み",
            "ko": "현재 로그에서 관찰됨",
            "es": "observado en los logs actuales",
            "fr": "observé dans les logs actuels",
        },
        "explicit_only": {
            "en": "requires explicit platform event; not observed in current logs",
            "zh": "需要平台暴露明确调用事件；当前日志未观察到",
            "ja": "明示的なプラットフォームイベントが必要。現在のログでは未観測",
            "ko": "명시적인 플랫폼 이벤트가 필요하며 현재 로그에서는 관찰되지 않음",
            "es": "requiere un evento explícito de la plataforma; no observado en los logs actuales",
            "fr": "nécessite un événement explicite de la plateforme; non observé dans les logs actuels",
        },
    }
    values = {}
    for lang, label in labels[kind].items():
        values[lang] = f"{label}: {statuses[status][lang]}"
    return _poly_text(values)


def _empty_note(message: str) -> str:
    return f'<p class="subtle">{html.escape(message)}</p>'


def _local_time_html(value: str) -> str:
    if not value:
        return "unknown"
    return f'<span data-local-time="{html.escape(value, quote=True)}">{html.escape(value)}</span>'


def _dashboard_turns(
    items: list[dict[str, Any]], suggested: list[dict[str, Any]], conflicts: list[dict[str, Any]]
) -> str:
    if not items:
        return _empty_note("No turns detected from local logs.")
    html_items = []
    for index, item in enumerate(items[:200]):
        evidence = item.get("evidence", [])
        open_attr = ""
        detail_key = f"turn-{item.get('platform', 'unknown')}-{item.get('turn_id') or 'unknown'}"
        title = f"{item.get('platform', 'unknown')} / {item.get('turn_id') or 'unknown'}"
        summary = _turn_evidence_summary_badge(evidence)
        hidden_reason = item.get("text_hidden_reason", "")
        user_message = _clip_text(item.get("user_message") or hidden_reason or "No user message captured in local logs.")
        assistant_summary = _clip_text(
            item.get("assistant_summary") or hidden_reason or "No assistant summary captured."
        )
        evidence_html = "\n".join(_dashboard_evidence(evidence_item) for evidence_item in evidence[:8]) or _empty_note(
            "No turn-bound loaded/read/invoked evidence."
        )
        diagnostics_html = _dashboard_trigger_diagnostics(evidence, suggested, conflicts, detail_key)
        html_items.append(
            f"""
      <details class="turn"{open_attr} data-detail-key="{html.escape(detail_key)}" data-turn-index="{index}">
        <summary><strong>{html.escape(title)}</strong>{summary}</summary>
        <p class="meta">timestamp: {_local_time_html(str(item.get('timestamp') or ''))}</p>
        <p class="turn-text"><strong>User:</strong> {html.escape(str(user_message))}</p>
        <p class="turn-text"><strong>Assistant:</strong> {html.escape(str(assistant_summary))}</p>
        {diagnostics_html}
        {evidence_html}
      </details>
"""
        )
    return "\n".join(html_items)


def _dashboard_trigger_diagnostics(
    evidence: list[dict[str, Any]],
    suggested: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    detail_key: str,
) -> str:
    detected = [
        item
        for item in evidence
        if item.get("event_type") in {"loaded", "read", "invoked"}
    ]
    detected_names = {str(item.get("skill_name") or "") for item in detected if item.get("skill_name")}
    suggested_names = [str(item.get("name") or "") for item in suggested if item.get("name")]
    missed = [name for name in suggested_names if name not in detected_names][:6]
    confusion = _diagnostic_conflicts(conflicts, detected_names | set(missed))
    detected_text = ", ".join(
        f"{item.get('event_type', 'unknown')} / {item.get('skill_name', 'unknown')}" for item in detected[:8]
    )
    missed_text = ", ".join(missed)
    confusion_text = "; ".join(confusion)
    return f"""
        <details class="fold trigger-diagnostics" data-detail-key="trigger-diagnostics-{html.escape(detail_key, quote=True)}">
          <summary><span data-i18n="trigger_diagnostics_title">Trigger Diagnostics</span>{_info_tooltip("trigger_diagnostics_tooltip")}</summary>
          <p class="meta"><strong data-i18n="detected_evidence_label">Detected evidence</strong>: {html.escape(detected_text) if detected_text else _poly_text(_simple_localized("no_detected_evidence"))}</p>
          <p class="meta"><strong data-i18n="missed_candidates_label">Missed candidates</strong>: {html.escape(missed_text) if missed_text else _poly_text(_simple_localized("no_missed_candidates"))}</p>
          <p class="meta"><strong data-i18n="possible_confusion_label">Possible confusion</strong>: {html.escape(confusion_text) if confusion_text else _poly_text(_simple_localized("no_possible_confusion"))}</p>
          <p class="subtle" data-i18n="trigger_diagnostics_note">This uses only local evidence and the local skill index. It does not call an LLM.</p>
        </details>
"""


def _diagnostic_conflicts(conflicts: list[dict[str, Any]], names: set[str]) -> list[str]:
    if not names:
        return []
    result: list[str] = []
    for item in conflicts:
        skills = [str(name) for name in item.get("skills", [])]
        if not names.intersection(skills):
            continue
        overlap = ", ".join(str(term) for term in item.get("overlap", [])[:5])
        if overlap:
            result.append(f"{' / '.join(skills)}: {overlap}")
        else:
            result.append(" / ".join(skills))
        if len(result) >= 3:
            break
    return result


def _turn_evidence_summary(evidence: list[dict[str, Any]]) -> str:
    counts = _turn_evidence_counts(evidence)
    return f'{counts["invoked"]} invoked / {counts["read"]} read / {counts["loaded"]} loaded'


def _turn_evidence_summary_badge(evidence: list[dict[str, Any]]) -> str:
    counts = _turn_evidence_counts(evidence)
    text = f'{counts["invoked"]} invoked / {counts["read"]} read / {counts["loaded"]} loaded'
    return (
        '<span class="badge turn-summary" '
        f'data-invoked-count="{counts["invoked"]}" '
        f'data-read-count="{counts["read"]}" '
        f'data-loaded-count="{counts["loaded"]}">'
        f"{html.escape(text)}</span>"
    )


def _turn_evidence_counts(evidence: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"invoked": 0, "read": 0, "loaded": 0, "inferred": 0}
    for item in evidence:
        event_type = item.get("event_type")
        if event_type in counts:
            counts[event_type] += 1
    return counts


def _clip_text(value: str, limit: int = 520) -> str:
    text = " ".join(str(value).split())
    if _looks_mojibake(text):
        return "Hidden: this log entry appears to contain mojibake from an older shell encoding issue. The raw text remains in state.json."
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _looks_mojibake(text: str) -> bool:
    if "\ufffd" in text:
        return True
    rare_cjk = sum(1 for char in text if "\u9300" <= char <= "\u9fff")
    return rare_cjk >= 2


def _dashboard_evidence(item: dict[str, Any]) -> str:
    title = f"{item.get('event_type', 'unknown')} / {item.get('skill_name', 'unknown')}"
    meta = (
        f"{item.get('platform', 'unknown')} - {item.get('source', 'unknown')} - "
        f"turn {item.get('turn_id') or 'unknown'} - message {item.get('message_id') or 'unknown'}"
    )
    snippet = item.get("snippet") or "No snippet recorded."
    return f"""
      <article class="item">
        <div class="item-head">
          <h3>{html.escape(title)}</h3>
          <span class="confidence">{html.escape(str(item.get('certainty', 'unknown')))}</span>
        </div>
        <p class="meta">{html.escape(meta)}</p>
        <p class="reasons">{html.escape(snippet)}</p>
      </article>
"""


def _group_evidence(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"invoked": [], "read": [], "loaded": [], "inferred": []}
    for item in items:
        event_type = item.get("event_type")
        if event_type in groups:
            groups[event_type].append(item)
    return groups


def _split_conflicts(conflicts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    project: list[dict[str, Any]] = []
    global_items: list[dict[str, Any]] = []
    for item in conflicts:
        scopes = item.get("scopes", [])
        if scopes and all(scope in {"project", "example"} for scope in scopes):
            project.append(item)
        else:
            global_items.append(item)
    return project, global_items


def _split_skills_by_scope(skills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    project: list[dict[str, Any]] = []
    global_items: list[dict[str, Any]] = []
    for skill in skills:
        if skill.get("scope") in {"project", "example"}:
            project.append(skill)
        else:
            global_items.append(skill)
    return project, global_items


def _dashboard_skill_card(skill: dict[str, Any]) -> str:
    keywords = ", ".join(skill.get("keywords", []) or ["unknown"])
    scope = skill.get("scope", "unknown")
    scope_key = f"scope_{scope}" if scope in {"project", "example", "user_global", "unknown"} else "scope_unknown"
    stars = str(skill.get("stars", "unknown"))
    maintenance = str(skill.get("maintenance", "unknown"))
    maintenance_key = (
        f"maintenance_{maintenance}" if maintenance in {"unknown", "active", "quiet", "stale", "archived"} else ""
    )
    repo = html.escape(skill.get("repo_url") or "unknown")
    stars_html = html.escape(stars) if stars != "unknown" else '<span data-i18n-direct="value_unknown">unknown</span>'
    maintenance_html = (
        f'<span data-i18n-direct="{maintenance_key}">{html.escape(maintenance)}</span>'
        if maintenance_key
        else html.escape(maintenance)
    )
    return f"""
      <article class="skill-card">
        <h3>{html.escape(skill.get('name', 'unknown'))}<span class="badge" data-i18n-direct="{html.escape(scope_key)}">{html.escape(scope)}</span></h3>
        <p>{html.escape(skill.get('summary') or skill.get('description') or 'unknown')}</p>
        <p class="tags">{html.escape(keywords)}</p>
        <p class="meta"><strong data-i18n-direct="skill_path_label">Path</strong>: <code>{html.escape(skill.get('path', ''))}</code></p>
        <p class="meta"><strong data-i18n-direct="skill_repo_label">Repo</strong>: {repo}</p>
        <p class="meta"><strong data-i18n-direct="skill_stars_label">Stars</strong>: {stars_html} &middot; <strong data-i18n-direct="skill_maintenance_label">Maintenance</strong>: {maintenance_html}</p>
      </article>
"""


class SkillProxy(Skill):
    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(
            name=data.get("name", ""),
            description=data.get("description", ""),
            path=data.get("path", ""),
            platform=data.get("platform", "generic"),
            keywords=data.get("keywords", []),
            language=data.get("language", "unknown"),
            repo_url=data.get("repo_url", ""),
            summary=data.get("summary", ""),
            risk_tags=data.get("risk_tags", []),
            trigger_aliases=data.get("trigger_aliases", []),
            stars=data.get("stars", "unknown"),
            maintenance=data.get("maintenance", "unknown"),
        )
