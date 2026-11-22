"""waddlebag's local state: settings, idle tracking and the run log. All of it lives in ~/.waddlebag/."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .usage import Usage

DEFAULT_CONFIG = """\
# waddlebag settings

# Never start a task, and stop a running one, when less than this much quota is left (%).
reserve_5h = 10
reserve_week = 5

# Desktop notification when a task starts and when it finishes.
notify = true

# How often the scheduler checks, in minutes. Run `waddlebag setup` again after changing it.
interval_minutes = 10
"""


RESET_JITTER_SECONDS = 15 * 60


def home() -> Path:
    return Path(os.environ.get("WADDLEBAG_HOME") or Path.home() / ".waddlebag")


@dataclass
class Config:
    reserve_5h: float = 10
    reserve_week: float = 5
    notify: bool = True
    interval_minutes: int = 10
    claude: str | None = None


def load_config(root: Path) -> Config:
    cfg = Config()
    path = root / "config.toml"
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in ("reserve_5h", "reserve_week", "notify", "interval_minutes", "claude"):
            if key in data:
                setattr(cfg, key, data[key])
    return cfg


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def update_idle(root: Path, usage: Usage, now: datetime) -> timedelta:
    """Record this usage sample and return how long nobody has used quota.

    waddlebag only sees usage when it checks, so idle time is measured from the last time it saw usage go up.
    Usage has 1% resolution, so very small amounts of use are invisible.
    """
    path = root / "state.json"
    state = _read_json(path)
    prev = state.get("sample")
    five_reset = usage.five_hour.resets_at.timestamp() if usage.five_hour.resets_at else None

    active = prev is None
    if prev is not None:
        prev_reset = prev.get("five_reset")
        # The reset time printed by /usage wobbles by about a minute (6pm, then 5:59pm, for the same window),
        # so only a large difference counts as a new window
        new_window = five_reset is not None and (
            prev_reset is None or abs(five_reset - prev_reset) > RESET_JITTER_SECONDS
        )
        active = (
            usage.week.used > prev["week_used"]
            or usage.five_hour.used > prev["five_used"]
            # a new 5-hour window only starts because somebody sent a message
            or (new_window and usage.five_hour.used > 0)
        )
    if active or "last_activity" not in state:
        state["last_activity"] = now.timestamp()

    state["sample"] = {
        "ts": now.timestamp(),
        "five_used": usage.five_hour.used,
        "five_reset": five_reset,
        "week_used": usage.week.used,
    }
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return timedelta(seconds=max(0.0, now.timestamp() - state["last_activity"]))


def record_run(root: Path, entry: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def last_run(root: Path, task_name: str) -> dict | None:
    """The most recent run of this task."""
    found = None
    try:
        with open(root / "runs.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("task") == task_name:
                    found = entry
    except OSError:
        return None
    return found
