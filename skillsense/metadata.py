from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html import unescape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_json, metadata_cache_path, write_json
from .models import Skill


GITHUB_REPO_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s#?]+)")
CACHE_TTL_SECONDS = 24 * 60 * 60
FAILED_TTL_SECONDS = 5 * 60
FETCH_COOLDOWN_SECONDS = 5 * 60
MAX_FETCHES = 8


def enrich_skills_metadata(skills: list[Skill], config: dict[str, Any], cwd: Path | None = None) -> list[Skill]:
    if not config.get("network", {}).get("enabled"):
        return skills
    cwd = cwd or Path.cwd()
    cache = load_json(metadata_cache_path(cwd), {"repos": {}})
    repos = cache.setdefault("repos", {})
    can_fetch = _fetch_window_open(cache)
    fetched = 0
    changed = False
    for skill in skills:
        repo_key = _repo_key(skill.repo_url)
        if not repo_key:
            continue
        entry = repos.get(repo_key)
        if not _fresh(entry):
            if not can_fetch or fetched >= MAX_FETCHES:
                continue
            entry = _fetch_github_repo(repo_key)
            repos[repo_key] = entry
            fetched += 1
            changed = True
        skill.stars = str(entry.get("stars") or "unknown")
        skill.maintenance = str(entry.get("maintenance") or "unknown")
    if changed:
        cache["last_fetch_at"] = datetime.now(timezone.utc).isoformat()
        write_json(metadata_cache_path(cwd), cache)
    return skills


def _repo_key(url: str) -> str:
    match = GITHUB_REPO_RE.search(url or "")
    if not match:
        return ""
    owner = match.group(1).strip()
    repo = match.group(2).strip().removesuffix(".git")
    return f"{owner}/{repo}" if owner and repo else ""


def _fresh(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return False
    try:
        timestamp = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    if entry.get("stars") == "unknown" and entry.get("maintenance") == "unknown":
        return age < FAILED_TTL_SECONDS
    return age < CACHE_TTL_SECONDS


def _fetch_window_open(cache: dict[str, Any]) -> bool:
    last_fetch_at = cache.get("last_fetch_at")
    if not last_fetch_at:
        return True
    try:
        timestamp = datetime.fromisoformat(str(last_fetch_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - timestamp).total_seconds() >= FETCH_COOLDOWN_SECONDS


def _fetch_github_repo(repo_key: str) -> dict[str, str]:
    url = f"https://api.github.com/repos/{repo_key}"
    request = urllib.request.Request(url, headers={"User-Agent": "SkillSense/0.1"})
    now = datetime.now(timezone.utc).isoformat()
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return _fetch_github_html(repo_key, now)
    return {
        "stars": str(data.get("stargazers_count", "unknown")),
        "maintenance": _maintenance_state(data),
        "fetched_at": now,
    }


def _fetch_github_html(repo_key: str, fetched_at: str) -> dict[str, str]:
    url = f"https://github.com/{repo_key}"
    request = urllib.request.Request(url, headers={"User-Agent": "SkillSense/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.HTTPError, urllib.error.URLError):
        return {"stars": "unknown", "maintenance": "unknown", "fetched_at": fetched_at}
    return {
        "stars": _stars_from_html(text),
        "maintenance": _maintenance_from_html(text),
        "fetched_at": fetched_at,
    }


def _stars_from_html(text: str) -> str:
    match = re.search(r"<h3[^>]*>\s*Stars\s*</h3>.*?<strong[^>]*>(.*?)</strong>", text, re.DOTALL | re.IGNORECASE)
    return " ".join(unescape(match.group(1)).split()) if match else "unknown"


def _maintenance_from_html(text: str) -> str:
    match = re.search(r'datetime="([^"]+)"', text)
    if not match:
        return "unknown"
    return _maintenance_state({"pushed_at": match.group(1), "archived": False})


def _maintenance_state(data: dict[str, Any]) -> str:
    if data.get("archived"):
        return "archived"
    pushed_at = str(data.get("pushed_at") or "")
    if not pushed_at:
        return "unknown"
    try:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    age_days = (datetime.now(timezone.utc) - pushed).days
    if age_days <= 180:
        return "active"
    if age_days <= 730:
        return "quiet"
    return "stale"
