"""找出 tasks/ 裡的 task，並讀取寫在檔案開頭註解裡的條件。

一個檔案就是一個 task：

    #!/bin/bash
    # doggybag:
    #   when: 5h.resets_in <= 60m and 5h.remaining >= 30
    #   cooldown: 6h
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from .conditions import Clause, ConditionError, parse_duration, parse_when

DEFAULT_COOLDOWN = timedelta(hours=5)
DEFAULT_TIMEOUT = timedelta(hours=1)
_HEADER_SCAN_LINES = 60

_HEADER_RE = re.compile(r"^\s*(?P<prefix>#|//|--|;)\s*doggybag:\s*$", re.I)


@dataclass
class Task:
    path: Path
    whens: list[list[Clause]] = field(default_factory=list)
    cooldown: timedelta = DEFAULT_COOLDOWN
    timeout: timedelta = DEFAULT_TIMEOUT
    error: str | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def executable(self) -> bool:
        return os.access(self.path, os.X_OK)


def parse_header(text: str) -> dict:
    """回傳 {"whens": [...], "cooldown": ..., "timeout": ...}，只含檔案裡有寫的欄位。"""
    lines = text.splitlines()[:_HEADER_SCAN_LINES]
    out: dict = {"whens": []}
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line)
        if not m:
            continue
        item_re = re.compile(
            r"^\s*" + re.escape(m["prefix"]) + r"\s+(?P<key>[a-z_]+)\s*:\s*(?P<value>.+?)\s*$", re.I
        )
        for body in lines[i + 1 :]:
            item = item_re.match(body)
            if not item:
                break
            key, value = item["key"].lower(), item["value"]
            if key == "when":
                out["whens"].append(parse_when(value))
            elif key in ("cooldown", "timeout"):
                out[key] = parse_duration(value)
            else:
                raise ConditionError(f"unknown setting '{key}' (known: when, cooldown, timeout)")
        break
    return out


def load_task(path: Path) -> Task:
    task = Task(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = "".join(f.readline() for _ in range(_HEADER_SCAN_LINES))
        header = parse_header(head)
    except (OSError, ConditionError) as e:
        task.error = str(e)
        return task
    task.whens = header["whens"]
    task.cooldown = header.get("cooldown", DEFAULT_COOLDOWN)
    task.timeout = header.get("timeout", DEFAULT_TIMEOUT)
    return task


def discover(tasks_dir: Path) -> list[Task]:
    """tasks/ 第一層的檔案，依檔名排序。子資料夾（例如 examples/）不會被掃描。"""
    if not tasks_dir.is_dir():
        return []
    files = sorted(
        p for p in tasks_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    return [load_task(p) for p in files]
