"""doggybag 的本機狀態：設定、閒置追蹤、執行紀錄。全部放在 ~/.doggybag/。"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .usage import Usage

DEFAULT_CONFIG = """\
# doggybag settings

# Never start a task, and stop a running one, when less than this much quota is left (%).
reserve_5h = 10
reserve_week = 5

# Desktop notification when a task starts and when it finishes.
notify = true

# How often the scheduler checks, in minutes. Run `doggybag setup` again after changing it.
interval_minutes = 10
"""


RESET_JITTER_SECONDS = 15 * 60


def home() -> Path:
    return Path(os.environ.get("DOGGYBAG_HOME") or Path.home() / ".doggybag")


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
    """記下這次的用量，回傳「多久沒有人消耗額度」。

    doggybag 只在每次檢查時看得到用量，所以閒置時間是從「上一次看到用量增加」算起。
    用量的解析度是 1%，很小的消耗看不出來。
    """
    path = root / "state.json"
    state = _read_json(path)
    prev = state.get("sample")
    five_reset = usage.five_hour.resets_at.timestamp() if usage.five_hour.resets_at else None

    active = prev is None
    if prev is not None:
        prev_reset = prev.get("five_reset")
        # /usage 顯示的 reset 時間會有一分鐘左右的誤差（同一個窗口有時顯示 6pm、有時 5:59pm），
        # 所以差距夠大才算是新的窗口
        new_window = five_reset is not None and (
            prev_reset is None or abs(five_reset - prev_reset) > RESET_JITTER_SECONDS
        )
        active = (
            usage.week.used > prev["week_used"]
            or usage.five_hour.used > prev["five_used"]
            # 新的 5 小時窗口只會因為有人送出訊息而開始
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
    """這個 task 最近一次的執行紀錄。"""
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
