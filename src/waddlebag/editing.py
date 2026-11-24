"""Handing over and changing tasks in your editor, the way `crontab -e` does.

The text you edit has help in `#` comments. Saving drops them, checks the task, and only then writes it to
~/.waddlebag/tasks/. A task that doesn't check out is never written: you edit it again or discard it.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Callable

from .tasks import Task, load_task, split_card

PLACEHOLDER = "Write what Claude should do here."
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")

HELP = """\
# Lines starting with # are removed when you save (except in your text at the bottom).
# Save and close to {verb} it. {cancel}
#
# when: tells me when to run it.
#   leftover   the 5-hour window resets within an hour and 30% or more is unused
#   idle       nobody has used Claude for an hour
#   behind     you are using this week's quota slower than the week is passing
#   or write your own, e.g.  idle >= 3h
# access: how much Claude may do, in the in: folder.
#   read   read and search, change nothing
#   edit   also change and add files, but run no commands
#   full   also run any command (tests, git, rm). Use with care
"""

ADVANCED = """\
# when: idle and behind     # also run on days you barely use Claude
# model: sonnet             # default: your Claude Code default
# timeout: 1h               # stop it if it runs longer
# cooldown: 5h              # wait this long before running it again
# run: python3 agent.py     # hand the text to your own program instead of Claude
# tools: Read(./**), WebSearch   # advanced: list Claude Code tools yourself instead of access
"""


class EditError(Exception):
    """Something to say before any editor opens: a bad name, an unknown example."""


def examples() -> dict[str, Path]:
    """The built-in examples, by name."""
    shipped = resources.files("waddlebag").joinpath("examples")
    return {Path(item.name).stem: item for item in shipped.iterdir() if item.name.endswith(".md")}


def check_name(name: str, tasks_dir: Path) -> Path:
    """Where a new task called `name` goes. Raises EditError for a bad or taken name."""
    if not NAME_RE.fullmatch(name):
        raise EditError(f"'{name}' can't be a task name: use letters, digits and -, like todo-triage")
    target = tasks_dir / f"{name}.md"
    if target.exists():
        raise EditError(f"there is already a task called {name}. Change it with `waddlebag edit {name}`")
    return target


def new_template(name: str, folder: Path, example: str | None = None) -> str:
    """The text `pack` opens: help, the settings with `in:` set to `folder`, and the text for Claude."""
    when, access, extra, body = "leftover", "read", [], PLACEHOLDER
    if example is not None:
        found = examples()
        if example not in found:
            raise EditError(f"I don't have an example called '{example}'. I have: {', '.join(sorted(found))}")
        items, body = split_card(found[example].read_text(encoding="utf-8"))
        # access: belongs to Claude, so an example with its own tools or command has none
        access = None if any(k in ("tools", "run") for k, _ in items) else "read"
        whens = []
        for key, value in items:
            if key == "when":
                whens.append(value)
            elif key == "access":
                access = value
            elif key not in ("in", "enabled"):  # the folder is yours, and saving it means it is on
                extra.append(f"{key}: {value}")
        when = whens[0] if whens else when
        extra = [f"when: {w}" for w in whens[1:]] + extra
    lines = [f"# New waddlebag task: {name}", HELP.format(verb="pack", cancel="Save it empty to cancel.").rstrip("\n"), "---"]
    lines.append(f"in: {_home_short(folder)}   # where Claude works (the folder you ran this in)")
    lines.append(f"when: {when}")
    if access:
        lines.append(f"access: {access}")
    lines += extra
    lines.append(ADVANCED.rstrip("\n"))
    lines += ["---", body, ""]
    return "\n".join(lines)


def edit_template(task_path: Path) -> str:
    """The text `edit` opens: the help, then the task as it is saved."""
    head = f"# Editing {task_path.stem}. To switch it off for now, add:   enabled: false\n"
    return head + HELP.format(verb="save", cancel="Close without saving to leave it as it was.") + \
        task_path.read_text(encoding="utf-8")


def clean(text: str) -> str:
    """Drop the help: comment lines before and inside the settings. The text for Claude is kept as it is."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    lines = lines[i:]
    if not lines:
        return ""
    if lines[0].strip() != "---":
        return "\n".join(lines).strip() + "\n"
    out = [lines[0]]
    for j, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            out += lines[j:]
            break
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    else:
        return "\n".join(out) + "\n"  # never closed: load_task says so
    return "\n".join(out).rstrip() + "\n"


def check(text: str, name: str) -> tuple[Task | None, str | None]:
    """Read cleaned text as the task `name`. Returns (task, None), or (None, what is wrong)."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        task = load_task(path)
        if task.error:
            return None, task.error
        if not task.run and task.body == PLACEHOLDER:
            return None, "write what Claude should do below the settings"
        if not task.whens:
            return None, "add a `when:` line, e.g. `when: leftover`"
        if task.workdir is None:
            return None, "add an `in:` line with the folder Claude should work in"
        if not task.cwd.is_dir():
            return None, f"I can't find the folder {task.cwd}: set `in:` to a folder that exists"
        return task, None


def editor_command() -> list[str]:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    return shlex.split(editor)


def open_editor(path: Path) -> None:
    """Open `path` in your editor and wait until you close it."""
    cmd = editor_command()
    try:
        code = subprocess.call([*cmd, str(path)])
    except OSError as e:
        raise EditError(f"I couldn't open your editor ({' '.join(cmd)}): {e}. Set $EDITOR") from e
    if code != 0:
        raise EditError(f"your editor ({' '.join(cmd)}) exited with {code}, so I saved nothing")


def write_task(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")  # a dotfile, so it is never taken for a task
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)


def edit_loop(
    text: str,
    name: str,
    ask: Callable[[str], str],
    say: Callable[[str], None],
    editor: Callable[[Path], None] = open_editor,
    unchanged_cancels: bool = False,
) -> tuple[str, Task] | None:
    """Edit `text` until it is a good task. Returns (clean text, task), or None when cancelled or discarded."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / f"{name}.md"  # the .md suffix gives the editor Markdown colours
        path.write_text(text, encoding="utf-8")
        while True:
            before = path.read_text(encoding="utf-8")
            editor(path)
            raw = path.read_text(encoding="utf-8")
            if unchanged_cancels and raw == before:
                return None
            cleaned = clean(raw)
            if not cleaned.strip():
                return None
            task, problem = check(cleaned, name)
            if task is not None:
                return cleaned, task
            say(f"✗ {name}: {problem}")
            answer = ask("(e)dit again / (d)iscard? [e] ").strip().lower()
            if answer.startswith("d"):
                return None
            # show what was wrong at the top, and keep everything they wrote
            body = re.sub(r"\A# ! .*\n", "", raw)
            path.write_text(f"# ! {problem}\n{body}", encoding="utf-8")


def _home_short(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)
