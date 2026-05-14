from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import interventions_path, load_json, write_json
from .models import Skill, SkillRecommendation
from .recommender import rewrite_description


ERROR_TERMS = [
    "error",
    "exception",
    "traceback",
    "failed",
    "cannot",
    "can't",
    "报错",
    "失败",
    "不能",
    "无法",
    "矛盾",
]


def build_interventions(
    skills: list[Skill],
    suggested: list[SkillRecommendation] | list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    cwd: Path | None = None,
) -> list[dict[str, Any]]:
    cwd = cwd or Path.cwd()
    by_name = {skill.name: skill for skill in skills}
    items: list[dict[str, Any]] = []
    items.extend(_conflict_risks(conflicts, by_name))
    items.extend(_description_risks(skills))
    items.extend(_missed_skill_risks(suggested, evidence))
    items.extend(_wrong_skill_risks(suggested, evidence, by_name))
    items.extend(_answer_error_signals(turns))
    items = _dedupe(items)
    return _merge_status(items, cwd)


def save_interventions(items: list[dict[str, Any]], cwd: Path | None = None) -> Path:
    path = interventions_path(cwd)
    write_json(path, {"interventions": items})
    return path


def load_interventions(cwd: Path | None = None) -> list[dict[str, Any]]:
    data = load_json(interventions_path(cwd), {"interventions": []})
    return list(data.get("interventions") or [])


def find_intervention(intervention_id: str, cwd: Path | None = None) -> dict[str, Any] | None:
    for item in load_interventions(cwd):
        if item.get("id") == intervention_id:
            return item
    return None


def set_intervention_status(intervention_id: str, status: str, cwd: Path | None = None) -> bool:
    items = load_interventions(cwd)
    found = False
    for item in items:
        if item.get("id") == intervention_id:
            item["status"] = status
            found = True
            break
    if found:
        save_interventions(items, cwd)
    return found


def apply_intervention(intervention_id: str, cwd: Path | None = None) -> tuple[bool, str]:
    cwd = cwd or Path.cwd()
    item = find_intervention(intervention_id, cwd)
    if not item:
        return False, f"Intervention not found: {intervention_id}"
    if item.get("status") == "applied":
        return False, "Intervention is already applied."
    proposal = item.get("proposal") or {}
    target_path = Path(str(proposal.get("target_path") or ""))
    replacement = str(proposal.get("suggested_description") or "")
    if not target_path or not replacement:
        return False, "This intervention has no applicable file change."
    if not _is_allowed_skill_file(target_path, cwd):
        return False, "Refusing to modify a file outside an explicit local skill directory."
    if not target_path.exists():
        return False, f"Target file does not exist: {target_path}"
    original = target_path.read_text(encoding="utf-8")
    updated = _replace_description(original, replacement)
    if updated == original:
        return False, "No description field was found to update."
    target_path.write_text(updated, encoding="utf-8")
    set_intervention_status(intervention_id, "applied", cwd)
    return True, f"Applied intervention {intervention_id} to {target_path}"


def _conflict_risks(conflicts: list[dict[str, Any]], by_name: dict[str, Skill]) -> list[dict[str, Any]]:
    items = []
    for conflict in conflicts:
        names = [str(name) for name in conflict.get("skills", [])]
        overlap = [str(term) for term in conflict.get("overlap", [])]
        if len(names) < 2:
            continue
        local_names = [
            name for name in names if by_name.get(name) and by_name[name].scope in {"project", "example"}
        ]
        if not local_names:
            continue
        skill = by_name.get(local_names[0])
        proposal = _proposal_for_skill(skill, "Narrow the description so it names the exact tasks this skill should handle.")
        items.append(
            _item(
                "conflict_risk",
                "medium",
                names,
                f"Trigger keywords overlap: {', '.join(overlap[:6])}",
                "Overlapping trigger terms can make adjacent skills compete for the same request.",
                proposal,
                evidence=[{"reason": conflict.get("reason", "trigger keywords overlap"), "overlap": overlap}],
            )
        )
        if len(items) >= 12:
            break
    return items


def _description_risks(skills: list[Skill]) -> list[dict[str, Any]]:
    items = []
    for skill in skills:
        if skill.scope not in {"project", "example"}:
            continue
        words = skill.description.split()
        if len(words) < 8:
            items.append(
                _item(
                    "description_too_broad",
                    "medium",
                    [skill.name],
                    "The skill description is very short or broad.",
                    "Broad descriptions can cause false positives or make the trigger behavior hard to predict.",
                    _proposal_for_skill(skill, "Replace the short description with a concrete trigger-focused description."),
                )
            )
        elif len(skill.keywords) <= 2:
            items.append(
                _item(
                    "description_too_narrow",
                    "low",
                    [skill.name],
                    "The skill has very few trigger keywords.",
                    "Narrow trigger coverage can make relevant requests miss this skill.",
                    _proposal_for_skill(skill, "Add clearer trigger terms and non-trigger boundaries."),
                )
            )
    return items[:12]


def _missed_skill_risks(
    suggested: list[SkillRecommendation] | list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    detected = {str(item.get("skill_name")) for item in evidence if item.get("event_type") in {"loaded", "read", "invoked"}}
    items = []
    for suggestion in suggested[:5]:
        data = suggestion.to_dict() if hasattr(suggestion, "to_dict") else dict(suggestion)
        name = str(data.get("name") or "")
        if name and name not in detected:
            items.append(
                _item(
                    "missed_skill_risk",
                    "medium",
                    [name],
                    "This skill was suggested for the prompt, but no local evidence was detected.",
                    "The agent may have missed a relevant skill, or the platform may not expose the needed evidence.",
                    _proposal_from_suggestion(data),
                    evidence=[{"suggestion_reasons": data.get("reasons", [])}],
                )
            )
    return items


def _wrong_skill_risks(
    suggested: list[SkillRecommendation] | list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    by_name: dict[str, Skill],
) -> list[dict[str, Any]]:
    suggested_names = {str((item.to_dict() if hasattr(item, "to_dict") else item).get("name") or "") for item in suggested}
    if not suggested_names:
        return []
    items = []
    for item in evidence:
        if item.get("event_type") != "read":
            continue
        name = str(item.get("skill_name") or "")
        if name and name not in suggested_names:
            skill = by_name.get(name)
            items.append(
                _item(
                    "wrong_skill_risk",
                    "medium",
                    [name],
                    "A SKILL.md was read, but it was not among the top suggested skills for the prompt.",
                    "This may indicate a mismatched trigger or a nearby skill competing with the intended one.",
                    _proposal_for_skill(skill, "Clarify when this skill should and should not trigger."),
                    turn_id=str(item.get("turn_id") or ""),
                    evidence=[item],
                )
            )
    return items[:5]


def _answer_error_signals(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for turn in turns[:20]:
        text = " ".join([str(turn.get("assistant_summary") or ""), str(turn.get("user_message") or "")]).lower()
        if text and any(term in text for term in ERROR_TERMS):
            items.append(
                _item(
                    "answer_error_signal",
                    "high",
                    [],
                    "The available turn text contains an error or failure signal.",
                    "If a skill was involved near this turn, review the evidence before changing any SKILL.md.",
                    {"title": "Review turn evidence", "summary": "Inspect the turn evidence and related skills before proposing a file change."},
                    turn_id=str(turn.get("turn_id") or ""),
                    evidence=[{"text": _clip(text)}],
                )
            )
    return items[:5]


def _proposal_for_skill(skill: Skill | None, summary: str) -> dict[str, Any]:
    if not skill:
        return {"title": "Review skill descriptions", "summary": summary}
    suggestion = rewrite_description(skill)
    proposal = {
        "title": f"Rewrite description for {skill.name}",
        "summary": summary,
        "target_path": skill.path,
        "suggested_description": suggestion,
    }
    proposal["preview_diff"] = _preview_diff(skill.description, suggestion)
    return proposal


def _proposal_from_suggestion(data: dict[str, Any]) -> dict[str, Any]:
    skill_data = data.get("skill") or {}
    skill = Skill.from_dict(skill_data) if skill_data else None
    return _proposal_for_skill(skill, "Improve this skill description so future matching is easier to explain.")


def _item(
    item_type: str,
    severity: str,
    skills: list[str],
    reason: str,
    impact: str,
    proposal: dict[str, Any],
    turn_id: str = "",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    seed = "|".join([item_type, ",".join(skills), turn_id, reason])
    return {
        "id": hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12],
        "type": item_type,
        "severity": severity,
        "skills": skills,
        "turn_id": turn_id,
        "evidence": evidence or [],
        "reason": reason,
        "impact": impact,
        "proposal": proposal,
        "requires_user_approval": True,
        "status": "open",
    }


def _merge_status(items: list[dict[str, Any]], cwd: Path) -> list[dict[str, Any]]:
    old = {item.get("id"): item for item in load_interventions(cwd)}
    for item in items:
        previous = old.get(item.get("id"))
        if previous and previous.get("status") in {"dismissed", "applied"}:
            item["status"] = previous["status"]
    return items


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        item_id = str(item.get("id"))
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return sorted(result, key=lambda item: (item.get("status") != "open", item.get("severity") != "high", item.get("type")))


def _preview_diff(original: str, suggestion: str) -> str:
    before = original or "<missing description>"
    return f"- description: {before}\n+ description: {suggestion}"


def _replace_description(text: str, replacement: str) -> str:
    pattern = re.compile(r"^(description:\s*)(.*)$", re.MULTILINE)
    return pattern.sub(lambda match: match.group(1) + replacement, text, count=1)


def _is_allowed_skill_file(path: Path, cwd: Path) -> bool:
    normalized = str(path.resolve()).replace("\\", "/").lower()
    cwd_normalized = str(cwd.resolve()).replace("\\", "/").lower()
    if normalized.startswith(cwd_normalized + "/skillsense/"):
        return False
    if path.name not in {"SKILL.md", "README.md"}:
        return False
    return any(marker in normalized for marker in ["/.codex/skills/", "/.claude/skills/", "/skills/"])


def _clip(text: str, limit: int = 240) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
