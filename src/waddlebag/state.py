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

# Draw the penguin in the terminal. Set to false for text only.
mascot = true

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
    mascot: bool = True
    interval_minutes: int = 10
    claude: str | None = None


class ConfigError(Exception):
    pass


# setting -> (accepted types, how to describe them)
_SETTINGS = {
    "reserve_5h": ((int, float), "a number from 0 to 100"),
    "reserve_week": ((int, float), "a number from 0 to 100"),
    "notify": ((bool,), "true or false"),
    "mascot": ((bool,), "true or false"),
    "interval_minutes": ((int,), "a whole number of minutes, at least 1"),
    "claude": ((str,), "the path to the claude command, in quotes"),
}


def _check(key: str, value) -> None:
    types, wanted = _SETTINGS[key]
    # TOML true/false are Python bools, and bool is a kind of int: don't let them pass as numbers
    ok = isinstance(value, types) and not (isinstance(value, bool) and bool not in types)
    if ok and key.startswith("reserve_"):
        ok = 0 <= value <= 100
    if ok and key == "interval_minutes":
        ok = value >= 1
    if not ok:
        raise ConfigError(f"`{key}` should be {wanted}, not {value!r}")


def load_config(root: Path) -> Config:
    """Read config.toml. Raises ConfigError with a one-line reason when it is broken."""
    cfg = Config()
    path = root / "config.toml"
    if not path.exists():
        return cfg
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(str(e)) from e
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"cannot read the file: {e}") from e
    for key, value in data.items():
        if key not in _SETTINGS:
            raise ConfigError(f"unknown setting `{key}` (known: {', '.join(_SETTINGS)})")
        _check(key, value)
        setattr(cfg, key, value)
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


def runs(root: Path) -> list[dict]:
    """Every recorded run, oldest first. Unreadable lines are skipped."""
    found = []
    try:
        with open(root / "runs.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and {"task", "ended"} <= entry.keys():
                    found.append(entry)
    except OSError:
        pass
    return found


def last_run(root: Path, task_name: str) -> dict | None:
    """The most recent run of this task."""
    mine = [entry for entry in runs(root) if entry["task"] == task_name]
    return mine[-1] if mine else None
