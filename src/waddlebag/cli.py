"""The commands: setup, status, pack, run, logs."""

from __future__ import annotations

import argparse
import os
import shutil
import sysconfig
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, editing, launchd, state
from .conditions import Context, format_duration
from .runner import EXIT_NOTHING_TO_DO, decide, now_local, quick_state, run_cycle, running_now
from .tasks import discover, ignored
from .ui import UI, short
from .usage import UsageError, Window, fetch_usage, find_claude

# the four states: does the task need you? Only "!" does
_MARKS = {"running": "▶", "waiting": "○", "needs you": "!", "off": "–"}


def _window_line(ui: UI, label: str, w: Window, now: datetime) -> str:
    head = f"{label:<5} {ui.bar(w.used)} {w.used:>3}% used"
    if w.resets_at is None:
        return head + ui.dim(" · no window open")
    return head + ui.dim(f" · resets in {format_duration(w.resets_in(now))}")


def _outcome(previous: dict) -> str:
    started = previous.get("started", previous["ended"])
    took = format_duration(datetime.fromtimestamp(previous["ended"]) - datetime.fromtimestamp(started))
    code = previous.get("exit")
    if previous.get("stopped") == "interrupted":
        what = "cut short (the Mac shut down, or I was stopped)"
    elif previous.get("stopped") == "reserve":
        what = "dropped to save your quota"
    elif previous.get("stopped") == "timeout":
        what = "dropped at its time limit"
    elif code == 0:
        what = f"done in {took}"
    elif code == EXIT_NOTHING_TO_DO:
        what = "had nothing to do"
    else:
        what = f"didn't work out (exit {code})"
    return what


def _stem(task_file: str) -> str:
    return Path(task_file).stem


def _when(previous: dict) -> str:
    return datetime.fromtimestamp(previous["ended"]).strftime("%b %d %H:%M")


def _last_time(previous: dict) -> str:
    # the command to type, not the log's path: the path is a detail
    return f"last time ({_when(previous)}): {_outcome(previous)} → waddlebag logs {_stem(previous['task'])}"


def _script_dir() -> Path | None:
    """The folder this install put the `waddlebag` command in, if it can be found."""
    candidates = [Path(sys.executable).parent, Path(sysconfig.get_path("scripts"))]
    try:
        candidates.append(Path(sysconfig.get_path("scripts", f"{os.name}_user")))
    except KeyError:
        pass
    return next((d for d in candidates if (d / "waddlebag").exists()), None)


def _shell_rc() -> str:
    shell = Path(os.environ.get("SHELL", "")).name
    return {"zsh": "~/.zshrc", "bash": "~/.bash_profile"}.get(shell, "~/.profile")


def path_hint() -> list[str] | None:
    """What to add to the shell's startup file when `waddlebag` is not on PATH. None when it is."""
    if shutil.which("waddlebag"):
        return None
    folder = _script_dir()
    if folder is None:
        return None  # run some other way (python -m, a checkout): nothing useful to suggest
    try:
        shown = "$HOME/" + str(folder.relative_to(Path.home()))
    except ValueError:
        shown = str(folder)
    rc = _shell_rc()
    return [
        "`waddlebag` isn't on your PATH yet. Add this line to " + rc + ":",
        f'  export PATH="{shown}:$PATH"',
        f"then run: source {rc}",
    ]


# what macOS prints when its privacy protection keeps the schedule out of a folder (#30)
_BLOCKED = "Operation not permitted"


def _blocked_folder(log: Path) -> str | None:
    """The protected path the last scheduled check was refused, from the end of its log."""
    try:
        with open(log, "rb") as f:
            f.seek(max(0, log.stat().st_size - 4000))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    last = tail.rstrip().splitlines()[-1:] or [""]
    if _BLOCKED not in last[0]:
        return None
    return last[0].split(":", 2)[-1].strip().strip("'")


def _ui(root) -> UI:
    try:
        return UI(mascot_on=state.load_config(root).mascot)
    except Exception:
        return UI()  # a broken config file should not stop us from saying so


def cmd_setup(args) -> int:
    root = state.home()
    ui = _ui(root)
    if args.uninstall:
        removed = launchd.uninstall() if sys.platform == "darwin" else False
        ui.say(
            "sleep",
            "Okay, I'll stop checking." if removed else "I wasn't checking on a schedule.",
            ui.dim(f"Your tasks are still in {short(root)}"),
        )
        return 0

    tasks_dir = root / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    config = root / "config.toml"
    if not config.exists():
        config.write_text(state.DEFAULT_CONFIG, encoding="utf-8")

    cfg = state.load_config(root)
    claude = find_claude(cfg.claude)
    if not claude:
        ui.say("sad", ui.red("I can't find Claude Code."), "Install it, log in, then call me again.")
        return 1
    try:
        fetch_usage(claude)
    except UsageError as e:
        ui.say("sad", ui.red("I found Claude Code but couldn't read your quota."), ui.dim(str(e)))
        return 1

    ok = ui.green("✓")
    steps = [
        f"{ok} found Claude Code",
        f"{ok} I can read your quota",
        f"{ok} made your folder        {ui.dim(short(root))}",
    ]

    if args.no_schedule:
        steps.append(ui.dim("· not checking on my own (--no-schedule). Call `waddlebag run` when you want me."))
    elif sys.platform == "darwin":
        try:
            launchd.install(root, cfg.interval_minutes, claude)
        except RuntimeError as e:
            ui.say("sad", ui.red("I couldn't set up the schedule."), ui.dim(str(e)))
            return 1
        steps.append(f"{ok} I'll check every {cfg.interval_minutes} minutes while this Mac is awake")
        steps.append(ui.dim("  (macOS may tell you \"python\" can run in the background: that's this schedule)"))
    else:
        steps.append(ui.dim("· I can only schedule myself on macOS for now. Add this to cron:"))
        steps.append(ui.dim(f"    */{cfg.interval_minutes} * * * * {sys.executable} -m waddlebag run"))

    ui.say("happy", ui.bold("waddlebag"), ui.dim("take home what you couldn't finish"))
    ui.line("waddling around...")
    for step in steps:
        ui.line(f"  {step}")
    hint = path_hint()
    if hint:
        ui.line()
        ui.line(ui.yellow(f"! {hint[0]}"))
        for line in hint[1:]:
            ui.line(line)
    ui.line()
    if discover(tasks_dir):
        ui.line(f"{ui.bold('All set!')} `waddlebag status` shows what I'm waiting for.")
    else:
        ui.line(f"{ui.bold('All set!')} Now hand me a task. Go to a project and pack one:")
        ui.line("  cd <your project> && waddlebag pack <name>")
        ui.line(ui.dim(f"  or start from an example: waddlebag pack <name> --from todo-triage"))
        ui.line(ui.dim(f"  examples: {', '.join(sorted(editing.examples()))}"))
    return 0


def cmd_status(args) -> int:
    root = state.home()
    ui = _ui(root)
    cfg = state.load_config(root)
    try:
        usage = fetch_usage(cfg.claude)
    except UsageError as e:
        ui.say("sad", ui.red("I couldn't read your quota."), ui.dim(str(e)))
        return 1
    now = now_local()
    idle = state.update_idle(root, usage, now)
    ctx = Context(usage, idle, now)

    failed = None  # exit code of the last scheduled run, when it failed
    if sys.platform == "darwin" and not launchd.is_installed():
        checking = "not checking on my own (run `waddlebag setup`)"
    elif sys.platform == "darwin" and not launchd.is_loaded():
        checking = ui.yellow(
            "my schedule is switched off: turn on \"python\" in Login Items, or run `waddlebag setup`"
        )
    else:
        checking = f"I check every {cfg.interval_minutes} minutes"
        if sys.platform == "darwin" and launchd.last_exit() not in (None, 0):
            failed = launchd.last_exit()
    ui.say(
        "look",
        "checking your quota...",
        "",
        _window_line(ui, "5h", usage.five_hour, now),
        _window_line(ui, "week", usage.week, now),
        ui.dim(f"quiet for {format_duration(idle)} · {checking}"),
        # the promise not to get in your way, said every time rather than only when it kicks in
        ui.dim(f"I always keep {cfg.reserve_5h:g}% of the 5h window and {cfg.reserve_week:g}% of the week for you"),
    )
    trouble = state.failing(root)
    if trouble:
        since = datetime.fromtimestamp(trouble["since"])
        ui.line(ui.yellow(f"! my checks have been failing since {since:%b %d %H:%M}: {trouble.get('why', '?')}"))
    elif failed is not None:
        log = root / "logs" / "waddlebag.log"
        ui.line(ui.yellow(f"! my last scheduled check failed (exit {failed}). What it said is in {short(log)}"))
        blocked = _blocked_folder(log)
        if blocked:
            ui.line(ui.yellow(f"  macOS kept the schedule out of {short(Path(blocked))}."))
            ui.line(ui.yellow("  Install waddlebag outside ~/Documents, ~/Desktop and ~/Downloads, then run `waddlebag setup`"))
    if (trouble or failed is not None) and ui.mascot_on:
        ui.line()  # plain mode adds its own blank line just below
    if not ui.mascot_on:
        ui.line()  # the penguin block ends with a blank line of its own

    tasks = discover(root / "tasks")
    if not tasks:
        ui.line("No tasks yet. Go to a project folder and hand me one: waddlebag pack <name>")
        ui.line(ui.dim("(or start from an example: waddlebag pack <name> --from todo-triage)"))
    width = max((len(t.path.stem) for t in tasks), default=0)
    now_running = running_now(root)
    for task in tasks:
        if now_running and now_running["task"] == task.name:
            took = format_duration(now - datetime.fromtimestamp(now_running["started"]).astimezone())
            ui.line(f"{ui.green(_MARKS['running'])} {task.path.stem:<{width}}    {ui.green(f'running for {took}')}")
            continue
        d = decide(task, ctx, cfg, root)
        mark, headline = _MARKS[d.kind], d.headline
        if d.kind == "needs you":
            mark, headline = ui.red(mark), ui.red(headline)
        elif d.run:
            mark, headline = ui.green(mark), ui.green(headline)
        else:
            mark = ui.dim(mark)
        ui.line(f"{mark} {task.path.stem:<{width}}    {headline}")
        if d.detail:
            ui.line(ui.dim(f"    {d.detail}"))
        previous = state.last_run(root, task.name)
        if previous:
            ui.line(ui.dim(f"    {_last_time(previous)}"))

    skipped = ignored(root / "tasks")
    if skipped:
        ui.line()
        ui.line(ui.dim(f"· ignoring {', '.join(p.name for p in skipped)}: a task is a .md file"))
    if tasks:
        # status is the one command to remember: the others are learned from here
        ui.line()
        ui.line(ui.dim("waddlebag pack <name>   hand me a new task"))
        ui.line(ui.dim("waddlebag edit <task>   change one, or switch it off"))
    return 0


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return "d"  # nobody to answer: keep nothing


def cmd_pack(args) -> int:
    root = state.home()
    ui = _ui(root)
    try:
        target = editing.check_name(args.name, root / "tasks")
        text = editing.new_template(args.name, Path.cwd(), args.example)
        result = editing.edit_loop(text, args.name, ask=_ask, say=lambda s: ui.line(ui.red(s)))
    except editing.EditError as e:
        ui.say("sad", ui.red(str(e)))
        return 1
    if result is None:
        ui.line("Nothing packed.")
        return 0
    cleaned, task = result
    editing.write_task(target, cleaned)
    ui.say("happy", f"{ui.green('Packed!')} {args.name}", ui.dim(short(target)))
    if task.warning:
        ui.line(ui.yellow(f"! {task.warning}"))
    ui.line(ui.dim(f"`waddlebag status` shows when it will run · `waddlebag run {args.name}` tries it now"))
    return 0


def _pick(ui: UI, tasks: list) -> object | None:
    width = max(len(t.path.stem) for t in tasks)
    ui.line("Which task?")
    for i, t in enumerate(tasks, start=1):
        ui.line(f"  {i}) {t.path.stem:<{width}}    {ui.dim(quick_state(t, state.home()))}")
    answer = _ask("> ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(tasks):
        return tasks[int(answer) - 1]
    return next((t for t in tasks if answer in (t.name, t.path.stem)), None)


def cmd_edit(args) -> int:
    root = state.home()
    ui = _ui(root)
    tasks = discover(root / "tasks")
    if not tasks:
        ui.line("No tasks yet. Go to a project folder and hand me one: waddlebag pack <name>")
        return 1
    if args.name:
        task = next((t for t in tasks if args.name in (t.name, t.path.stem)), None)
        if task is None:
            ui.say("sad", ui.red(f"I don't know a task called '{args.name}'."),
                   f"I have: {', '.join(t.path.stem for t in tasks)}")
            return 1
    else:
        task = _pick(ui, tasks)
        if task is None:
            ui.line("Nothing changed.")
            return 0
    name = task.path.stem
    try:
        result = editing.edit_loop(
            editing.edit_template(task.path), name, ask=_ask, say=lambda s: ui.line(ui.red(s)),
            unchanged_cancels=True,
        )
    except editing.EditError as e:
        ui.say("sad", ui.red(str(e)))
        return 1
    if result is None:
        ui.line(f"Nothing changed: {name} is as it was.")
        return 0
    cleaned, saved = result
    editing.write_task(task.path, cleaned)
    ui.say("happy", f"Saved {name}.", ui.dim(short(task.path)))
    if saved.warning:
        ui.line(ui.yellow(f"! {saved.warning}"))
    if quick_state(task, root) == "running":
        ui.line(ui.dim(f"{name} is running right now. Your changes apply from its next run."))
    return 0


def cmd_run(args) -> int:
    return run_cycle(state.home(), only=args.task)


def cmd_logs(args) -> int:
    root = state.home()
    ui = _ui(root)
    runs = state.runs(root)
    if args.task:
        mine = [r for r in runs if args.task in (r.get("task"), Path(r.get("task", "")).stem)]
        if not mine:
            ui.line(f"{args.task} hasn't run yet.")
            return 1
        last = mine[-1]
        log = Path(last.get("log", ""))
        ui.line(ui.dim(f"{_stem(last['task'])} · {_when(last)} · {_outcome(last)} · {short(log)}"))
        ui.line()
        try:
            ui.line(log.read_text(encoding="utf-8", errors="replace").rstrip())
        except OSError:
            ui.line(ui.red("The log file is gone."))
            return 1
        return 0

    if not runs:
        ui.line("Nothing has run yet.")
        return 0
    recent = runs[-args.count:][::-1]
    width = max(len(_stem(r.get("task", ""))) for r in recent)
    for r in recent:
        ui.line(f"{ui.dim(_when(r))}  {_stem(r.get('task', '?')):<{width}}  {_outcome(r)}")
    ui.line()
    ui.line(ui.dim("`waddlebag logs <task>` shows a task's latest answer"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="waddlebag",
        description="Run your own tasks on leftover Claude quota before it resets.",
    )
    parser.add_argument("--version", action="version", version=f"waddlebag {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="check Claude Code, create ~/.waddlebag, install the schedule")
    p.add_argument("--no-schedule", action="store_true", help="do everything except the schedule")
    p.add_argument("--uninstall", action="store_true", help="remove the schedule")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("status", help="show quota and what each task is waiting for")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("pack", help="hand over a new task: opens your editor on a template")
    p.add_argument("name", help="the task's name, like todo-triage")
    p.add_argument("--from", dest="example", metavar="EXAMPLE",
                   help="start from a built-in example: " + ", ".join(sorted(editing.examples())))
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("edit", help="change a task in your editor; with no name, pick one from a list")
    p.add_argument("name", nargs="?", help="the task to change")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("run", help="check once and run the tasks whose time has come")
    p.add_argument("task", nargs="?", help="run this one task now, whatever its when:")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("logs", help="list recent runs, or show a task's latest answer")
    p.add_argument("task", nargs="?", help="show this task's latest answer")
    p.add_argument("-n", dest="count", type=int, default=10, help="how many recent runs to list (default 10)")
    p.set_defaults(func=cmd_logs)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except state.ConfigError as e:
        ui = UI()
        ui.say("sad", ui.red(f"I can't read {short(state.home() / 'config.toml')}."), str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
