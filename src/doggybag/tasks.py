"""找出 tasks/ 裡的 task，並讀取每個檔案自己帶的設定。一個檔案就是一個 task。

有兩種 task：

1. 任意可執行檔，設定寫在開頭的註解裡：

       #!/bin/bash
       # doggybag:
       #   when: leftover
       #   cooldown: 6h

2. `.md` 檔，內容就是要交給 Claude 的 prompt，設定寫在 frontmatter：

       ---
       when: leftover
       in: ~/work/myrepo
       ---
       Review the three most recent commits.
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
# prompt task 預設只能讀檔和搜尋；要改檔案得自己在 tools: 加上
DEFAULT_TOOLS = ["Read", "Grep", "Glob"]
_HEADER_SCAN_LINES = 60

_HEADER_RE = re.compile(r"^\s*(?P<prefix>#|//|--|;)\s*doggybag:\s*$", re.I)
_ITEM_RE = re.compile(r"^\s*(?P<key>[a-z_]+)\s*:\s*(?P<value>.*?)\s*$", re.I)

_SCRIPT_KEYS = ("when", "cooldown", "timeout", "enabled")
_PROMPT_KEYS = _SCRIPT_KEYS + ("in", "tools", "model")


@dataclass
class Task:
    path: Path
    whens: list[list[Clause]] = field(default_factory=list)
    cooldown: timedelta = DEFAULT_COOLDOWN
    timeout: timedelta = DEFAULT_TIMEOUT
    enabled: bool = True
    error: str | None = None
    # 以下只有 prompt task 會用到
    prompt: str | None = None
    workdir: Path | None = None
    tools: list[str] = field(default_factory=lambda: list(DEFAULT_TOOLS))
    model: str | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def is_prompt(self) -> bool:
        return self.prompt is not None

    @property
    def executable(self) -> bool:
        return self.is_prompt or os.access(self.path, os.X_OK)

    @property
    def cwd(self) -> Path:
        return self.workdir or self.path.parent

    def command(self, claude: str | None) -> list[str]:
        """要執行的指令。prompt task 的 prompt 走 stdin，不放在參數裡。"""
        if not self.is_prompt:
            return [str(self.path)]
        cmd = [claude or "claude", "-p"]
        if self.model:
            cmd += ["--model", self.model]
        if self.tools:
            cmd += ["--allowedTools", *self.tools]
        return cmd


def _parse_bool(value: str) -> bool:
    v = value.strip().lower()
    if v in ("true", "yes", "on"):
        return True
    if v in ("false", "no", "off"):
        return False
    raise ConditionError(f"'{value}' should be true or false")


def _apply(task: Task, items: list[tuple[str, str]], allowed: tuple[str, ...]) -> None:
    for key, value in items:
        key = key.lower()
        if key not in allowed:
            raise ConditionError(f"unknown setting '{key}' (known: {', '.join(allowed)})")
        if key == "when":
            task.whens.append(parse_when(value))
        elif key == "cooldown":
            task.cooldown = parse_duration(value)
        elif key == "timeout":
            task.timeout = parse_duration(value)
        elif key == "enabled":
            task.enabled = _parse_bool(value)
        elif key == "in":
            task.workdir = Path(value).expanduser()
        elif key == "tools":
            names = [t.strip() for t in value.split(",") if t.strip()]
            task.tools = [] if [n.lower() for n in names] == ["none"] else names
        elif key == "model":
            task.model = value


def script_settings(text: str) -> list[tuple[str, str]]:
    """讀出 script 開頭 `# doggybag:` 區塊裡的 key: value。"""
    lines = text.splitlines()[:_HEADER_SCAN_LINES]
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line)
        if not m:
            continue
        items = []
        prefix = re.compile(r"^\s*" + re.escape(m["prefix"]) + r"\s+(.*)$")
        for body in lines[i + 1 :]:
            inner = prefix.match(body)
            item = _ITEM_RE.match(inner[1]) if inner else None
            if not item or not item["value"]:
                break
            items.append((item["key"], item["value"]))
        return items
    return []


def prompt_settings(text: str) -> tuple[list[tuple[str, str]], str]:
    """把 .md 拆成 (frontmatter 的 key: value, prompt 本文)。沒有 frontmatter 也可以。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text.strip()
    items = []
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return items, "\n".join(lines[i + 1 :]).strip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = _ITEM_RE.match(line)
        if not item or not item["value"]:
            raise ConditionError(f"cannot read the line '{line.strip()}' (expected `key: value`)")
        items.append((item["key"], item["value"]))
    raise ConditionError("the settings block that starts with `---` is never closed")


def load_task(path: Path) -> Task:
    task = Task(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".md":
            items, body = prompt_settings(text)
            task.prompt = body
            _apply(task, items, _PROMPT_KEYS)
            if not body:
                raise ConditionError("the prompt is empty")
        else:
            _apply(task, script_settings(text), _SCRIPT_KEYS)
    except (OSError, ConditionError) as e:
        task.error = str(e)
    return task


def discover(tasks_dir: Path) -> list[Task]:
    """tasks/ 第一層的檔案，依檔名排序。子資料夾（例如 examples/）不會被掃描。"""
    if not tasks_dir.is_dir():
        return []
    files = sorted(
        p for p in tasks_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    return [load_task(p) for p in files]
