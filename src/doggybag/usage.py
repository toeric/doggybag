"""讀取 Claude 訂閱額度。

來源是 `claude -p "/usage"`：headless 呼叫、不花額度，doggybag 本身不碰登入憑證。
輸出是給人看的文字，所以解析集中在這個檔案，格式改版時只需要改這裡。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FIVE_HOURS = timedelta(hours=5)
ONE_WEEK = timedelta(days=7)

_SESSION_RE = re.compile(r"Current session:\s*(\d+)%\s*used(?:\s*·\s*resets\s+(.+))?", re.I)
_WEEK_RE = re.compile(
    r"Current week \(all models\):\s*(\d+)%\s*used(?:\s*·\s*resets\s+(.+))?", re.I
)
_RESET_RE = re.compile(
    r"(?:(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:\s+at|,)?\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)"
    r"(?:\s*\((?P<tz>[^)]+)\))?",
    re.I,
)
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


class UsageError(Exception):
    pass


@dataclass
class Window:
    """一個額度窗口。resets_at 為 None 表示窗口尚未開始或讀不到 reset 時間。"""

    used: int
    resets_at: datetime | None
    length: timedelta

    @property
    def remaining(self) -> int:
        return max(0, 100 - self.used)

    def resets_in(self, now: datetime) -> timedelta | None:
        if self.resets_at is None:
            return None
        return max(timedelta(0), self.resets_at - now)

    def behind(self, now: datetime) -> float | None:
        """用量落後時間進度幾個百分點：時間過了 40%、只用 10%，就是 30。"""
        left = self.resets_in(now)
        if left is None:
            return None
        elapsed = 1 - min(1.0, left / self.length)
        return elapsed * 100 - self.used


@dataclass
class Usage:
    five_hour: Window
    week: Window
    raw: str


def parse_reset(text: str, now: datetime) -> datetime | None:
    """解析 "Nov 22 at 6pm (Asia/Taipei)" 或 "6pm (Asia/Taipei)"。"""
    m = _RESET_RE.search(text)
    if not m:
        return None
    tz = now.tzinfo
    if m["tz"]:
        try:
            tz = ZoneInfo(m["tz"].strip())
        except (ZoneInfoNotFoundError, ValueError):
            pass
    local_now = now.astimezone(tz)
    hour = int(m["hour"]) % 12 + (12 if m["ampm"].lower() == "pm" else 0)
    minute = int(m["minute"] or 0)

    if m["mon"]:
        month = _MONTHS.get(m["mon"][:3].lower())
        if month is None:
            return None
        try:
            when = local_now.replace(
                month=month, day=int(m["day"]), hour=hour, minute=minute, second=0, microsecond=0
            )
        except ValueError:
            return None
        # 沒有年份：reset 一定在未來，過去超過一天就視為明年
        if when < local_now - timedelta(days=1):
            when = when.replace(year=when.year + 1)
        return when

    when = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= local_now:
        when += timedelta(days=1)
    return when


def parse_usage(text: str, now: datetime) -> Usage:
    week_m = _WEEK_RE.search(text)
    if not week_m:
        raise UsageError("could not find the weekly usage line in `/usage` output")
    week = Window(int(week_m[1]), parse_reset(week_m[2] or "", now), ONE_WEEK)

    session_m = _SESSION_RE.search(text)
    if session_m:
        five = Window(int(session_m[1]), parse_reset(session_m[2] or "", now), FIVE_HOURS)
    else:
        # 沒有 session 那一行：視為 5 小時窗口尚未開始
        five = Window(0, None, FIVE_HOURS)
    return Usage(five, week, text)


def find_claude(configured: str | None = None) -> str | None:
    return configured or os.environ.get("DOGGYBAG_CLAUDE") or shutil.which("claude")


def fetch_usage(claude: str | None = None, now: datetime | None = None) -> Usage:
    binary = find_claude(claude)
    if not binary:
        raise UsageError("`claude` not found on PATH; install Claude Code and log in first")
    try:
        proc = subprocess.run(
            [binary, "-p", "/usage"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UsageError(f"could not run `claude -p /usage`: {e}") from e
    if proc.returncode != 0:
        raise UsageError(
            f"`claude -p /usage` exited with {proc.returncode}: {proc.stderr.strip()[:300]}"
        )
    return parse_usage(proc.stdout, now or datetime.now().astimezone())
