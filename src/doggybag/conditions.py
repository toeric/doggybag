"""觸發條件的解析與判斷。

一行 `when:` 是用 `and` 串起來的幾個子句；一個 task 有多行 `when:` 時，任一行成立就觸發。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .usage import Usage

_DURATION_SIGNALS = {"5h.resets_in", "week.resets_in", "idle"}
_PERCENT_SIGNALS = {
    "5h.remaining",
    "5h.used",
    "5h.behind",
    "week.remaining",
    "week.used",
    "week.behind",
}
SIGNALS = sorted(_DURATION_SIGNALS | _PERCENT_SIGNALS)

# 常見情況的現成名稱，讓使用者不用自己寫運算式
PRESETS = {
    "leftover": "5h.resets_in <= 60m and 5h.remaining >= 30",
    "idle": "idle >= 60m",
    "behind": "week.behind >= 20",
}

_CLAUSE_RE = re.compile(r"^\s*([a-z0-9_.]+)\s*(>=|<=|>|<)\s*(\S+)\s*$", re.I)
_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(m|h|d)$", re.I)
_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


class ConditionError(Exception):
    pass


def parse_duration(text: str) -> timedelta:
    m = _DURATION_RE.match(text.strip())
    if not m:
        raise ConditionError(f"'{text}' is not a duration (use e.g. 45m, 6h, 2d)")
    return timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m[2].lower()]: float(m[1])})


def format_duration(d: timedelta) -> str:
    seconds = int(d.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"
    return f"{hours // 24}d{hours % 24}h"


@dataclass
class Clause:
    signal: str
    op: str
    value: float | timedelta

    def __str__(self) -> str:
        v = format_duration(self.value) if isinstance(self.value, timedelta) else f"{self.value:g}%"
        return f"{self.signal} {self.op} {v}"


@dataclass
class Context:
    usage: Usage
    idle: timedelta
    now: datetime

    def value(self, signal: str) -> float | timedelta | None:
        if signal == "idle":
            return self.idle
        window_name, _, field = signal.partition(".")
        window = self.usage.five_hour if window_name == "5h" else self.usage.week
        if field == "remaining":
            return float(window.remaining)
        if field == "used":
            return float(window.used)
        if field == "resets_in":
            return window.resets_in(self.now)
        return window.behind(self.now)


def parse_when(text: str) -> list[Clause]:
    clauses = []
    for part in re.split(r"\s+and\s+", text.strip(), flags=re.I):
        preset = PRESETS.get(part.strip().lower())
        if preset:
            clauses.extend(parse_when(preset))
            continue
        m = _CLAUSE_RE.match(part)
        if not m:
            raise ConditionError(
                f"cannot read condition '{part}' "
                f"(use {', '.join(PRESETS)}, or something like `5h.remaining >= 30`)"
            )
        signal = m[1].lower()
        if signal in _DURATION_SIGNALS:
            value: float | timedelta = parse_duration(m[3])
        elif signal in _PERCENT_SIGNALS:
            try:
                value = float(m[3].rstrip("%"))
            except ValueError:
                raise ConditionError(f"'{m[3]}' is not a percentage") from None
        else:
            raise ConditionError(f"unknown signal '{signal}' (known: {', '.join(SIGNALS)})")
        clauses.append(Clause(signal, m[2], value))
    return clauses


def _show(value: float | timedelta) -> str:
    return format_duration(value) if isinstance(value, timedelta) else f"{value:.0f}%"


def evaluate(clauses: list[Clause], ctx: Context) -> tuple[bool, str]:
    """回傳 (是否成立, 說明)。說明會列出每個子句目前的實際值。"""
    ok = True
    parts = []
    for c in clauses:
        actual = ctx.value(c.signal)
        if actual is None:
            ok = False
            parts.append(f"{c} (unknown: window not active)")
            continue
        passed = _OPS[c.op](actual, c.value)
        ok = ok and passed
        parts.append(f"{c} ({'yes' if passed else 'no'}, now {_show(actual)})")
    return ok, " and ".join(parts)
