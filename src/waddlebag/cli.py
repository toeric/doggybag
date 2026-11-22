"""The three commands: setup, status, run."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from importlib import resources

from . import __version__, launchd, state
from .conditions import Context, format_duration
from .runner import EXIT_NOTHING_TO_DO, decide, now_local, run_cycle
from .tasks import discover, ignored
from .ui import UI, short
from .usage import UsageError, Window, fetch_usage, find_claude

STARTER_EXAMPLE = "todo-triage.md"
STARTER_NAME = "10-todo-triage.md"

_MARKS = {"ready": "●", "waiting": "○", "resting": "○", "off": "–", "problem": "!"}


def _window_line(ui: UI, label: str, w: Window, now: datetime) -> str:
    head = f"{label:<5} {ui.bar(w.remaining)}  {w.remaining}% left"
    if w.resets_at is None:
        return head + ui.dim(" · no window open")
    return head + ui.dim(f" · resets in {format_duration(w.resets_in(now))}")


def _last_time(previous: dict) -> str:
    took = format_duration(datetime.fromtimestamp(previous["ended"]) - datetime.fromtimestamp(previous["started"]))
    if previous.get("stopped") == "reserve":
        what = "dropped to save your quota"
    elif previous.get("stopped") == "timeout":
        what = "dropped at its time limit"
    elif previous["exit"] == 0:
        what = f"done in {took}"
    elif previous["exit"] == EXIT_NOTHING_TO_DO:
        what = "had nothing to do"
    else:
        what = f"didn't work out (exit {previous['exit']})"
    when = datetime.fromtimestamp(previous["ended"]).strftime("%b %d %H:%M")
    return f"last time ({when}): {what} → {short(previous.get('log', '?'))}"


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
            ui.dim(f"Your jobs are still in {short(root)}"),
        )
        return 0

    tasks_dir = root / "tasks"
    examples = tasks_dir / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    config = root / "config.toml"
    if not config.exists():
        config.write_text(state.DEFAULT_CONFIG, encoding="utf-8")

    first_time = not discover(tasks_dir)
    shipped = resources.files("waddlebag").joinpath("examples")
    count = 0
    for item in shipped.iterdir():
        if not item.is_file():
            continue
        count += 1
        target = examples / item.name
        if not target.exists():
            with resources.as_file(item) as src:
                shutil.copyfile(src, target)  # examples/ is a subfolder, so these are never run from here
    starter = tasks_dir / STARTER_NAME
    if first_time:
        # on a fresh install, hand the user a first job to edit; it starts switched off
        with resources.as_file(shipped.joinpath(STARTER_EXAMPLE)) as src:
            shutil.copyfile(src, starter)

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
        f"{ok} left you {count} examples     {ui.dim(short(examples))}",
    ]
    if first_time:
        steps.append(f"{ok} wrote your first job    {ui.dim(short(starter) + ' (switched off)')}")

    if args.no_schedule:
        steps.append(ui.dim("· not checking on my own (--no-schedule). Call `waddlebag run` when you want me."))
    elif sys.platform == "darwin":
        try:
            launchd.install(root, cfg.interval_minutes, claude)
        except RuntimeError as e:
            ui.say("sad", ui.red("I couldn't set up the schedule."), ui.dim(str(e)))
            return 1
        steps.append(f"{ok} I'll check every {cfg.interval_minutes} minutes while this Mac is awake")
    else:
        steps.append(ui.dim("· I can only schedule myself on macOS for now. Add this to cron:"))
        steps.append(ui.dim(f"    */{cfg.interval_minutes} * * * * {sys.executable} -m waddlebag run"))

    ui.say("happy", ui.bold("waddlebag"), ui.dim("take home what you couldn't finish"))
    ui.line("waddling around...")
    for step in steps:
        ui.line(f"  {step}")
    ui.line()
    if starter.exists():
        ui.line(f"{ui.bold('All set!')} One thing left for you:")
        ui.line(f"  open {short(starter)}")
        ui.line("  set the folder after `in:` and change `enabled: false` to `true`")
    else:
        ui.line(f"{ui.bold('All set!')} `waddlebag status` shows what I'm waiting for.")
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

    if sys.platform == "darwin" and not launchd.is_installed():
        checking = "not checking on my own (run `waddlebag setup`)"
    else:
        checking = f"I check every {cfg.interval_minutes} minutes"
    ui.say(
        "look",
        "checking your quota...",
        "",
        _window_line(ui, "5h", usage.five_hour, now),
        _window_line(ui, "week", usage.week, now),
        ui.dim(f"quiet for {format_duration(idle)} · {checking}"),
    )
    if not ui.mascot_on:
        ui.line()  # the penguin block ends with a blank line of its own

    tasks = discover(root / "tasks")
    if not tasks:
        ui.line(f"No jobs yet. Put a .md file in {short(root / 'tasks')}")
        ui.line(ui.dim("(there are some to copy in the examples folder)"))
    width = max((len(t.name) for t in tasks), default=0)
    for task in tasks:
        d = decide(task, ctx, cfg, root)
        mark, headline = _MARKS[d.kind], d.headline
        if d.kind == "ready":
            mark, headline = ui.green(mark), ui.green("ready") + headline[len("ready"):]
        elif d.kind == "problem":
            mark, headline = ui.red(mark), ui.red(headline)
        else:
            mark = ui.dim(mark)
        ui.line(f"{mark} {task.name:<{width}}    {headline}")
        if d.detail:
            ui.line(ui.dim(f"    {d.detail}"))
        previous = state.last_run(root, task.name)
        if previous:
            ui.line(ui.dim(f"    {_last_time(previous)}"))

    skipped = ignored(root / "tasks")
    if skipped:
        ui.line()
        ui.line(ui.dim(f"· ignoring {', '.join(p.name for p in skipped)}: a job is a .md file"))
    return 0


def cmd_run(args) -> int:
    return run_cycle(state.home(), only=args.task)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="waddlebag",
        description="Run your own jobs on leftover Claude quota before it resets.",
    )
    parser.add_argument("--version", action="version", version=f"waddlebag {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="check Claude Code, create ~/.waddlebag, install the schedule")
    p.add_argument("--no-schedule", action="store_true", help="do everything except the schedule")
    p.add_argument("--uninstall", action="store_true", help="remove the schedule")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("status", help="show quota and why each job would or would not run")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="check once and run the jobs whose conditions hold")
    p.add_argument("task", nargs="?", help="run this one job now, ignoring its conditions")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
