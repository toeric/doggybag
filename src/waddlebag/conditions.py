"""Parse and evaluate trigger conditions.

One `when:` line is a list of clauses joined by `and`. With several `when:` lines, any one line triggers the task.
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

# ready-made names for the common cases, so users need not write expressions
PRESETS = {
    "leftover": "5h.resets_in <= 60m and 5h.remaining >= 30",
    "idle": "idle >= 60m",
    "behind": "week.behind >= 20",
}

_CLAUSE_RE = re.compile(r"^\s*([a-z0-9_.]+)\s*(>=|<=|>|<)\s*(\S+)\s*$", re.I)
# one or more parts, largest unit first, each unit at most once: 45m, 6h, 1.5d, 5h10m, 2d6h
_DURATION_RE = re.compile(
    r"^(?=\d)(?:(?P<d>\d+(?:\.\d+)?)\s*d\s*)?(?:(?P<h>\d+(?:\.\d+)?)\s*h\s*)?(?:(?P<m>\d+(?:\.\d+)?)\s*m)?$",
    re.I,
)
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
    if not m or not any(m.groupdict().values()):
        raise ConditionError(f"'{text}' is not a duration (use e.g. 45m, 6h, 2d, 5h10m)")
    parts = {unit: float(value) for unit, value in m.groupdict().items() if value}
    return timedelta(days=parts.get("d", 0), hours=parts.get("h", 0), minutes=parts.get("m", 0))


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


_WINDOW = {"5h": "the 5-hour window", "week": "the week"}
_PACE = {"5h": "in this window", "week": "this week"}


def explain(clause: Clause, actual: float | timedelta | None, passed: bool) -> str:
    """Say in plain words how one clause stands right now."""
    if actual is None:
        return "no 5-hour window is open yet"
    window, _, field = clause.signal.partition(".")
    wants_at_least = clause.op in (">=", ">")
    target = clause.value

    if clause.signal == "idle" and wants_at_least:
        if passed:
            return f"quiet for {format_duration(actual)}"
        return f"quota was used {format_duration(actual)} ago, I wait for {format_duration(target)} of quiet"
    if field == "resets_in" and not wants_at_least:
        now = f"{_WINDOW[window]} resets in {format_duration(actual)}"
        return now if passed else f"{now}, I go in the last {format_duration(target)}"
    if field == "remaining" and wants_at_least:
        if passed:
            return f"{actual:.0f}% left"
        return f"only {actual:.0f}% left in {_WINDOW[window]}, I want {target:g}%"
    if field == "behind" and wants_at_least:
        if passed:
            return f"{actual:.0f} behind pace {_PACE[window]}"
        return f"you're keeping pace {_PACE[window]} ({actual:.0f} behind, I go at {target:g})"
    # anything less common: show the condition as written, with the current value
    return f"{clause} (now {_show(actual)})"


def evaluate(clauses: list[Clause], ctx: Context) -> tuple[bool, str]:
    """Return (holds, explanation).

    When every clause holds, the explanation lists them all. Otherwise it names the first
    clause that does not hold, which is what the task is waiting for.
    """
    holding = []
    for c in clauses:
        actual = ctx.value(c.signal)
        passed = actual is not None and _OPS[c.op](actual, c.value)
        if not passed:
            return False, explain(c, actual, False)
        holding.append(explain(c, actual, True))
    return True, " · ".join(holding)
