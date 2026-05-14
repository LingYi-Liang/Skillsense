from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import (
    config_path,
    dashboard_path,
    interventions_path,
    load_config,
    load_json,
    metadata_cache_path,
    report_path,
    save_config,
    set_config_value,
    state_path,
)
from .detector import why_not_used
from .evidence import collect_evidence, collect_turns
from .indexer import find_skill, load_index, save_index
from .interventions import apply_intervention, find_intervention, load_interventions, set_intervention_status
from .metadata import enrich_skills_metadata
from .recommender import rewrite_description, suggest_skills
from .reporter import build_state, write_report
from .scanner import scan_skills


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillsense", description="Local Agent Skills observability.")
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Scan local skills and write .skillsense/skills_index.json.")
    scan.set_defaults(func=cmd_scan)

    list_cmd = sub.add_parser("list", help="List indexed skills.")
    list_cmd.set_defaults(func=cmd_list)

    suggest = sub.add_parser("suggest", help="Suggest relevant skills for a user prompt.")
    suggest.add_argument("prompt")
    suggest.set_defaults(func=cmd_suggest)

    status = sub.add_parser("status", help="Print one quiet statusline-friendly line.")
    status.set_defaults(func=cmd_status)

    evidence = sub.add_parser("evidence", help="Show confirmed loaded/read/invoked evidence from local logs.")
    evidence.set_defaults(func=cmd_evidence)

    watch = sub.add_parser("watch", help="Refresh report and dashboard from local logs.")
    watch.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds.")
    watch.add_argument("--once", action="store_true", help="Refresh one time and exit.")
    watch.add_argument("--prompt", default="", help="Prompt to use for suggestions while watching.")
    watch.set_defaults(func=cmd_watch)

    serve = sub.add_parser("serve", help="Serve the dashboard locally with smooth polling updates.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--interval", type=float, default=2.0)
    serve.add_argument("--prompt", default="", help="Prompt to use for suggestions while serving.")
    serve.set_defaults(func=cmd_serve)

    reset_state = sub.add_parser("reset-state", help="Remove generated state/report/dashboard files.")
    reset_state.set_defaults(func=cmd_reset_state)

    report = sub.add_parser("report", help="Generate report.md, state.json, and dashboard.html.")
    report.set_defaults(func=cmd_report)

    diagnose = sub.add_parser("diagnose", help="Generate the intervention queue from current evidence.")
    diagnose.set_defaults(func=cmd_diagnose)

    interventions = sub.add_parser("interventions", help="List open SkillSense repair suggestions.")
    interventions.add_argument("--all", action="store_true", help="Include dismissed and applied interventions.")
    interventions.set_defaults(func=cmd_interventions)

    propose_fix = sub.add_parser("propose-fix", help="Show the proposed change for an intervention.")
    propose_fix.add_argument("intervention_id")
    propose_fix.set_defaults(func=cmd_propose_fix)

    apply_fix = sub.add_parser("apply-fix", help="Apply an intervention after explicit review.")
    apply_fix.add_argument("intervention_id")
    apply_fix.add_argument("--yes", action="store_true", help="Confirm that the proposed SKILL.md change should be written.")
    apply_fix.set_defaults(func=cmd_apply_fix)

    dismiss = sub.add_parser("dismiss", help="Dismiss an intervention.")
    dismiss.add_argument("intervention_id")
    dismiss.set_defaults(func=cmd_dismiss)

    why_not = sub.add_parser("why-not", help="Explain why a skill may not have triggered.")
    why_not.add_argument("skill_name")
    why_not.add_argument("prompt")
    why_not.set_defaults(func=cmd_why_not)

    rewrite = sub.add_parser("rewrite-description", help="Suggest a better skill description.")
    rewrite.add_argument("skill_name")
    rewrite.set_defaults(func=cmd_rewrite_description)

    mute = sub.add_parser("mute", help="Hide a skill from SkillSense suggestions.")
    mute.add_argument("skill_name")
    mute.set_defaults(func=lambda args: cmd_preference(args, "mute", True))

    unmute = sub.add_parser("unmute", help="Remove a skill from the SkillSense mute list.")
    unmute.add_argument("skill_name")
    unmute.set_defaults(func=lambda args: cmd_preference(args, "mute", False))

    prefer = sub.add_parser("prefer", help="Boost a skill in SkillSense suggestions.")
    prefer.add_argument("skill_name")
    prefer.set_defaults(func=lambda args: cmd_preference(args, "prefer", True))

    unprefer = sub.add_parser("unprefer", help="Remove a skill from the SkillSense prefer list.")
    unprefer.add_argument("skill_name")
    unprefer.set_defaults(func=lambda args: cmd_preference(args, "prefer", False))

    ask_before = sub.add_parser("ask-before", help="Record that a skill should ask before use when adapters support it.")
    ask_before.add_argument("skill_name")
    ask_before.set_defaults(func=lambda args: cmd_preference(args, "ask_before", True))

    no_ask_before = sub.add_parser("no-ask-before", help="Remove a skill from the ask-before list.")
    no_ask_before.add_argument("skill_name")
    no_ask_before.set_defaults(func=lambda args: cmd_preference(args, "ask_before", False))

    config = sub.add_parser("config", help="Get or set local SkillSense config.")
    config_sub = config.add_subparsers(dest="config_command")
    config_get = config_sub.add_parser("get")
    config_get.add_argument("key", nargs="?")
    config_get.set_defaults(func=cmd_config_get)
    config_set = config_sub.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_set.set_defaults(func=cmd_config_set)
    return parser


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def cmd_scan(_args: argparse.Namespace) -> int:
    skills = scan_skills()
    path = save_index(skills)
    print(f"Scanned {len(skills)} skills. Index: {path}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    skills = _index_or_scan()
    if not skills:
        print("No skills indexed.")
        return 0
    for skill in skills:
        keywords = ", ".join(skill.keywords[:6]) or "none"
        print(f"{skill.name} [{skill.platform}/{skill.scope}]")
        print(f"  path: {skill.path}")
        print(f"  description: {skill.description or 'unknown'}")
        print(f"  keywords: {keywords}")
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    config = load_config()
    skills = _index_or_scan()
    suggestions = suggest_skills(args.prompt, skills, config=config)
    evidence = collect_evidence(skills)
    turns = collect_turns()
    state = build_state(skills, suggestions, evidence=evidence, turns=turns, prompt=args.prompt, config=config)
    write_report(state)
    if not suggestions:
        print("No suggested skills.")
        return 0
    for item in suggestions:
        print(f"{item.name} - {item.status} - confidence {item.confidence:.2f}")
        for reason in item.reasons:
            print(f"  why: {reason}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    state = load_json(state_path(), {})
    counts = _status_counts(state)
    if not any(counts.values()):
        print("SkillSense - idle")
        return 0
    print("SkillSense - " + _format_counts(counts))
    return 0


def cmd_evidence(_args: argparse.Namespace) -> int:
    skills = _index_or_scan()
    evidence = collect_evidence(skills)
    if not evidence:
        print("No confirmed evidence detected.")
        return 0
    for item in evidence[:80]:
        print(f"{item.event_type} - {item.skill_name} - {item.platform} - {item.source}")
        if item.turn_id:
            print(f"  turn: {item.turn_id}")
        if item.message_id:
            print(f"  message: {item.message_id}")
        if item.path:
            print(f"  path: {item.path}")
        if item.snippet:
            print(f"  evidence: {item.snippet[:220]}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    interval = max(args.interval, 0.5)
    last_signature = ""
    try:
        while True:
            state, files = _refresh_report(prompt=args.prompt)
            signature = _state_signature(state)
            if args.once:
                print(f"Updated dashboard: {files[2]}")
                return 0
            if not last_signature:
                print(f"SkillSense watch - every {interval:g}s - dashboard: {files[2]}")
            elif signature != last_signature:
                print("SkillSense - " + _format_counts(_status_counts(state)))
            last_signature = signature
            time.sleep(interval)
    except KeyboardInterrupt:
        print("SkillSense watch stopped.")
        return 0


def cmd_serve(args: argparse.Namespace) -> int:
    interval = max(args.interval, 0.5)
    stop_event = threading.Event()
    refresh_lock = threading.Lock()

    def refresh() -> tuple[dict[str, Any], tuple[Path, Path, Path]]:
        with refresh_lock:
            return _refresh_report(prompt=args.prompt)

    def refresh_loop() -> None:
        while not stop_event.is_set():
            refresh()
            stop_event.wait(interval)

    refresh()
    thread = threading.Thread(target=refresh_loop, daemon=True)
    thread.start()
    handler = functools.partial(SkillSenseHTTPRequestHandler, directory=str(state_path().parent), refresh=refresh)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/dashboard.html"
    print(f"SkillSense serve - {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()
        print("SkillSense serve stopped.")
    return 0


def cmd_report(_args: argparse.Namespace) -> int:
    _state, files = _refresh_report()
    report_file, state_file, dashboard_file = files
    print(f"Report: {report_file}")
    print(f"State: {state_file}")
    print(f"Dashboard: {dashboard_file}")
    return 0


def cmd_diagnose(_args: argparse.Namespace) -> int:
    state, files = _refresh_report()
    items = state.get("interventions", [])
    open_count = sum(1 for item in items if item.get("status") == "open")
    print(f"Diagnosed {open_count} open interventions ({len(items)} total).")
    print(f"Interventions: {interventions_path()}")
    print(f"Dashboard: {files[2]}")
    return 0


def cmd_interventions(args: argparse.Namespace) -> int:
    _refresh_report()
    items = load_interventions()
    if not args.all:
        items = [item for item in items if item.get("status") == "open"]
    if not items:
        print("No interventions detected.")
        return 0
    for item in items:
        _print_intervention_summary(item)
    return 0


def cmd_propose_fix(args: argparse.Namespace) -> int:
    _refresh_report()
    item = find_intervention(args.intervention_id)
    if not item:
        print(f"Intervention not found: {args.intervention_id}")
        return 1
    _print_intervention_detail(item)
    return 0


def cmd_apply_fix(args: argparse.Namespace) -> int:
    _refresh_report()
    item = find_intervention(args.intervention_id)
    if not item:
        print(f"Intervention not found: {args.intervention_id}")
        return 1
    if not args.yes:
        print("Review required. Re-run with --yes to apply this change.")
        _print_intervention_detail(item)
        return 1
    ok, message = apply_intervention(args.intervention_id)
    _refresh_report()
    print(message)
    return 0 if ok else 1


def cmd_dismiss(args: argparse.Namespace) -> int:
    _refresh_report()
    if not set_intervention_status(args.intervention_id, "dismissed"):
        print(f"Intervention not found: {args.intervention_id}")
        return 1
    _refresh_report()
    print(f"Dismissed intervention {args.intervention_id}.")
    return 0


def cmd_reset_state(_args: argparse.Namespace) -> int:
    removed = []
    for path in [state_path(), report_path(), dashboard_path(), interventions_path(), metadata_cache_path()]:
        if path.exists():
            path.unlink()
            removed.append(path)
    if removed:
        print("Removed generated files:")
        for path in removed:
            print(f"  {path}")
    else:
        print("No generated state files to remove.")
    print("Kept config and skills_index.")
    return 0


def cmd_why_not(args: argparse.Namespace) -> int:
    skills = _index_or_scan()
    skill = find_skill(skills, args.skill_name)
    if not skill:
        print(f"Skill not found: {args.skill_name}")
        return 1
    print(f"Why '{skill.name}' may not have triggered:")
    for reason in why_not_used(skill, args.prompt):
        print(f"- {reason}")
    return 0


def cmd_rewrite_description(args: argparse.Namespace) -> int:
    skills = _index_or_scan()
    skill = find_skill(skills, args.skill_name)
    if not skill:
        print(f"Skill not found: {args.skill_name}")
        return 1
    print(rewrite_description(skill))
    return 0


def cmd_preference(args: argparse.Namespace, key: str, enabled: bool) -> int:
    config = load_config()
    preferences = config.setdefault("preferences", {})
    for name in ["prefer", "mute", "ask_before"]:
        preferences.setdefault(name, [])
    values = [str(item) for item in preferences.get(key, [])]
    if enabled and args.skill_name not in values:
        values.append(args.skill_name)
    if not enabled:
        values = [item for item in values if item != args.skill_name]
    preferences[key] = values
    if enabled and key == "mute":
        preferences["prefer"] = [item for item in preferences["prefer"] if item != args.skill_name]
    if enabled and key == "prefer":
        preferences["mute"] = [item for item in preferences["mute"] if item != args.skill_name]
    save_config(config)
    _refresh_report()
    action = "Added" if enabled else "Removed"
    print(f"{action} {args.skill_name} {'to' if enabled else 'from'} {key}.")
    if key in {"mute", "ask_before"}:
        print("Note: this is a SkillSense preference, not a platform-level hard block.")
    return 0


def cmd_config_get(args: argparse.Namespace) -> int:
    config = load_config()
    if not args.key:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0
    value = _get_nested(config, args.key)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    config = load_config()
    set_config_value(config, args.key, args.value)
    save_config(config)
    _refresh_report()
    print(f"Set {args.key} = {args.value}")
    print(f"Config: {config_path()}")
    return 0


def _print_intervention_summary(item: dict[str, Any]) -> None:
    skills = ", ".join(str(skill) for skill in item.get("skills", [])) or "unknown"
    print(
        f"{item.get('id')} - {item.get('type')} - {item.get('severity')} - "
        f"{item.get('status')} - {skills}"
    )
    print(f"  reason: {item.get('reason')}")


def _print_intervention_detail(item: dict[str, Any]) -> None:
    _print_intervention_summary(item)
    print(f"  impact: {item.get('impact')}")
    if item.get("turn_id"):
        print(f"  turn: {item.get('turn_id')}")
    proposal = item.get("proposal") or {}
    print(f"  proposal: {proposal.get('title') or 'Review suggestion'}")
    if proposal.get("summary"):
        print(f"  summary: {proposal.get('summary')}")
    if proposal.get("target_path"):
        print(f"  target: {proposal.get('target_path')}")
    if proposal.get("preview_diff"):
        print("  preview diff:")
        for line in str(proposal.get("preview_diff")).splitlines():
            print(f"    {line}")


def _refresh_report(prompt: str = "") -> tuple[dict[str, Any], tuple[Path, Path, Path]]:
    config = load_config()
    skills = _index_or_scan()
    skills = enrich_skills_metadata(skills, config)
    if config.get("network", {}).get("enabled"):
        save_index(skills)
    previous_state = load_json(state_path(), {})
    active_prompt = prompt or previous_state.get("prompt", "")
    suggestions = suggest_skills(active_prompt, skills, config=config) if active_prompt else []
    evidence = collect_evidence(skills)
    turns = collect_turns()
    state = build_state(skills, suggestions, evidence=evidence, turns=turns, prompt=active_prompt, config=config)
    if previous_state and _state_signature(state) == _state_signature(previous_state):
        state["updated_at"] = previous_state.get("updated_at", state.get("updated_at"))
    return state, write_report(state)


def _index_or_scan():
    skills = load_index()
    if skills:
        return skills
    skills = scan_skills()
    save_index(skills)
    return skills


def _get_nested(data: dict, dotted_key: str):
    value = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _status_counts(state: dict) -> dict[str, int]:
    counts = {"loaded": 0, "read": 0, "invoked": 0, "inferred": 0, "suggested": len(state.get("suggested", []))}
    for item in state.get("evidence", []):
        event_type = item.get("event_type")
        if event_type in counts:
            counts[event_type] += 1
    return counts


def _format_counts(counts: dict[str, int]) -> str:
    parts = [f"{count} {name}" for name, count in counts.items() if count]
    return " - ".join(parts) if parts else "idle"


def _state_signature(state: dict[str, Any]) -> str:
    compact = {
        "prompt": state.get("prompt", ""),
        "counts": _status_counts(state),
        "suggested": [
            {
                "name": item.get("name"),
                "confidence": item.get("confidence"),
                "reasons": item.get("reasons", []),
            }
            for item in state.get("suggested", [])
        ],
        "recommended": state.get("recommended", []),
        "skill_metadata": [
            {
                "name": item.get("name"),
                "stars": item.get("stars"),
                "maintenance": item.get("maintenance"),
            }
            for item in state.get("skills", [])[:80]
        ],
        "interventions": [
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "type": item.get("type"),
                "severity": item.get("severity"),
            }
            for item in state.get("interventions", [])
        ],
        "turns": [
            {
                "turn_id": turn.get("turn_id"),
                "evidence": [(item.get("event_type"), item.get("skill_name")) for item in turn.get("evidence", [])],
            }
            for turn in state.get("turns", [])[:20]
        ],
        "preferences": state.get("preferences", {}),
        "privacy": state.get("privacy", {}),
        "network": state.get("network", {}).get("enabled"),
    }
    return json.dumps(compact, ensure_ascii=False, sort_keys=True)


class SkillSenseHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, refresh: Any = None, **kwargs: Any) -> None:
        self.refresh = refresh
        super().__init__(*args, **kwargs)

    def do_POST(self) -> None:
        if self.path == "/api/network":
            self._handle_network_post()
            return
        if self.path.startswith("/api/interventions/"):
            self._handle_intervention_post()
            return
        self._json_response(404, {"error": "not found"})

    def _handle_network_post(self) -> None:
        try:
            payload = self._read_json_payload()
        except (ValueError, json.JSONDecodeError):
            self._json_response(400, {"error": "invalid json"})
            return
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            self._json_response(400, {"error": "enabled must be boolean"})
            return
        config = load_config()
        config.setdefault("network", {})["enabled"] = enabled
        save_config(config)
        if self.refresh:
            self.refresh()
        self._json_response(200, {"network": {"enabled": enabled}})

    def _handle_intervention_post(self) -> None:
        parts = [part for part in self.path.split("/") if part]
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "interventions":
            self._json_response(404, {"error": "not found"})
            return
        intervention_id, action = parts[2], parts[3]
        if action == "dismiss":
            ok = set_intervention_status(intervention_id, "dismissed")
            if ok and self.refresh:
                self.refresh()
            self._json_response(200 if ok else 404, {"ok": ok, "id": intervention_id, "status": "dismissed"})
            return
        if action == "apply":
            ok, message = apply_intervention(intervention_id)
            if self.refresh:
                self.refresh()
            self._json_response(200 if ok else 400, {"ok": ok, "id": intervention_id, "message": message})
            return
        self._json_response(404, {"error": "not found"})

    def _read_json_payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    raise SystemExit(main())
