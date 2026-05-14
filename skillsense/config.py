from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


STATE_DIR = ".skillsense"
INDEX_FILE = "skills_index.json"
STATE_FILE = "state.json"
REPORT_FILE = "report.md"
DASHBOARD_FILE = "dashboard.html"
CONFIG_FILE = "config.json"
INTERVENTIONS_FILE = "interventions.json"
METADATA_CACHE_FILE = "metadata_cache.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "language": "auto",
    "network": {"enabled": False},
    "privacy": {"store_turn_text": False, "show_turn_text": False},
    "preferences": {"prefer": [], "mute": [], "ask_before": []},
}


def state_dir(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / STATE_DIR


def ensure_state_dir(cwd: Path | None = None) -> Path:
    path = state_dir(cwd)
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_path(cwd: Path | None = None) -> Path:
    return state_dir(cwd) / INDEX_FILE


def state_path(cwd: Path | None = None) -> Path:
    return state_dir(cwd) / STATE_FILE


def report_path(cwd: Path | None = None) -> Path:
    return state_dir(cwd) / REPORT_FILE


def dashboard_path(cwd: Path | None = None) -> Path:
    return state_dir(cwd) / DASHBOARD_FILE


def interventions_path(cwd: Path | None = None) -> Path:
    return state_dir(cwd) / INTERVENTIONS_FILE


def metadata_cache_path(cwd: Path | None = None) -> Path:
    return state_dir(cwd) / METADATA_CACHE_FILE


def config_path(cwd: Path | None = None) -> Path:
    return state_dir(cwd) / CONFIG_FILE


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return deepcopy(default)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_config(cwd: Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    saved = load_json(config_path(cwd), {})
    _merge(config, saved)
    return config


def save_config(config: dict[str, Any], cwd: Path | None = None) -> None:
    write_json(config_path(cwd), config)


def set_config_value(config: dict[str, Any], dotted_key: str, value: str) -> None:
    parts = dotted_key.split(".")
    target = config
    for part in parts[:-1]:
        next_value = target.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            target[part] = next_value
        target = next_value
    target[parts[-1]] = parse_value(value)


def parse_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _merge(base: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
