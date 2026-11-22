"""找出 tasks/ 裡的 task。一個 `.md` 檔就是一個 task，格式只有一種：

    ---
    when: leftover
    in: ~/work/myrepo
    ---
    Find the TODO comments and pick the five most worth fixing.

doggybag 在 `when` 成立時，到 `in` 這個資料夾，把內文交給 `run` 的指令。
沒寫 `run` 就是交給 Claude Code。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from .conditions import Clause, ConditionError, parse_duration, parse_when

DEFAULT_COOLDOWN = timedelta(hours=5)
DEFAULT_TIMEOUT = timedelta(hours=1)
# 交給 Claude 時預設只能讀檔和搜尋；要改檔案得自己在 tools: 加上
DEFAULT_TOOLS = ["Read", "Grep", "Glob"]

_ITEM_RE = re.compile(r"^\s*(?P<key>[a-z_]+)\s*:\s*(?P<value>.*?)\s*$", re.I)
SETTINGS = ("when", "in", "run", "tools", "model", "cooldown", "timeout", "enabled")


@dataclass
class Task:
    path: Path
    body: str = ""
    whens: list[list[Clause]] = field(default_factory=list)
    workdir: Path | None = None
    run: str | None = None
    tools: list[str] | None = None
    model: str | None = None
    cooldown: timedelta = DEFAULT_COOLDOWN
    timeout: timedelta = DEFAULT_TIMEOUT
    enabled: bool = True
    error: str | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def cwd(self) -> Path:
        return self.workdir or self.path.parent

    def command(self, claude: str | None) -> list[str]:
        """要執行的指令。內文一律從 stdin 傳入，不放在參數裡。"""
        if self.run:
            # 交給 shell，使用者可以寫 ~、管線和參數
            return ["/bin/sh", "-c", self.run]
        cmd = [claude or "claude", "-p"]
        if self.model:
            cmd += ["--model", self.model]
        tools = DEFAULT_TOOLS if self.tools is None else self.tools
        if tools:
            cmd += ["--allowedTools", *tools]
        return cmd


def _parse_bool(value: str) -> bool:
    v = value.strip().lower()
    if v in ("true", "yes", "on"):
        return True
    if v in ("false", "no", "off"):
        return False
    raise ConditionError(f"'{value}' should be true or false")


def _apply(task: Task, items: list[tuple[str, str]]) -> None:
    for key, value in items:
        key = key.lower()
        if key == "when":
            task.whens.append(parse_when(value))
        elif key == "in":
            task.workdir = Path(value).expanduser()
        elif key == "run":
            task.run = value
        elif key == "tools":
            names = [t.strip() for t in value.split(",") if t.strip()]
            task.tools = [] if [n.lower() for n in names] == ["none"] else names
        elif key == "model":
            task.model = value
        elif key == "cooldown":
            task.cooldown = parse_duration(value)
        elif key == "timeout":
            task.timeout = parse_duration(value)
        elif key == "enabled":
            task.enabled = _parse_bool(value)
        else:
            raise ConditionError(f"unknown setting '{key}' (known: {', '.join(SETTINGS)})")


def split_card(text: str) -> tuple[list[tuple[str, str]], str]:
    """把檔案拆成 (設定的 key: value, 內文)。沒有設定區塊也可以。"""
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
        items, task.body = split_card(path.read_text(encoding="utf-8", errors="replace"))
        _apply(task, items)
        if task.run:
            if task.tools is not None or task.model is not None:
                raise ConditionError(
                    "`tools` and `model` only apply when Claude runs the task; "
                    "remove them, or remove `run`"
                )
        elif not task.body:
            raise ConditionError(
                "nothing to do: write what Claude should do below the settings, or add `run:`"
            )
    except (OSError, ConditionError) as e:
        task.error = str(e)
    return task


def _files(tasks_dir: Path) -> list[Path]:
    if not tasks_dir.is_dir():
        return []
    return sorted(p for p in tasks_dir.iterdir() if p.is_file() and not p.name.startswith("."))


def discover(tasks_dir: Path) -> list[Task]:
    """tasks/ 第一層的 .md 檔，依檔名排序。子資料夾（例如 examples/）不會被掃描。"""
    return [load_task(p) for p in _files(tasks_dir) if p.suffix.lower() == ".md"]


def ignored(tasks_dir: Path) -> list[Path]:
    """tasks/ 裡不是 .md 的檔案。它們不會被執行，status 會提醒使用者。"""
    return [p for p in _files(tasks_dir) if p.suffix.lower() != ".md"]
