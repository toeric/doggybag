"""三個指令：setup、status、run。"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from importlib import resources
from pathlib import Path

from . import __version__, launchd, state
from .conditions import Context, format_duration
from .runner import decide, now_local, run_cycle
from .tasks import discover
from .usage import Usage, UsageError, Window, fetch_usage, find_claude


def _window_line(label: str, w: Window, now: datetime) -> str:
    if w.resets_at is None:
        return f"{label}  {w.remaining:>3}% left · no active window"
    left = w.resets_in(now)
    return (
        f"{label}  {w.remaining:>3}% left · resets in {format_duration(left)}"
        f" ({w.resets_at.astimezone():%a %H:%M}) · {w.behind(now):+.0f} behind pace"
    )


def _print_usage(usage: Usage, now: datetime) -> None:
    print(_window_line("5h  ", usage.five_hour, now))
    print(_window_line("week", usage.week, now))


def cmd_setup(args) -> int:
    root = state.home()
    if args.uninstall:
        removed = launchd.uninstall() if sys.platform == "darwin" else False
        print("schedule removed" if removed else "no schedule was installed")
        print(f"your tasks and settings in {root} were left in place")
        return 0

    tasks_dir = root / "tasks"
    examples = tasks_dir / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)

    config = root / "config.toml"
    if not config.exists():
        config.write_text(state.DEFAULT_CONFIG, encoding="utf-8")
        print(f"wrote {config}")

    for item in resources.files("doggybag").joinpath("templates").iterdir():
        target = examples / item.name
        if not target.exists():
            with resources.as_file(item) as src:
                shutil.copyfile(src, target)  # 不帶執行權限，範例不會被誤跑
    print(f"example tasks are in {examples}")

    cfg = state.load_config(root)
    claude = find_claude(cfg.claude)
    if not claude:
        print("✗ `claude` was not found on PATH. Install Claude Code, log in, then run setup again.")
        return 1
    print(f"✓ found claude at {claude}")
    try:
        usage = fetch_usage(claude)
    except UsageError as e:
        print(f"✗ could not read your quota: {e}")
        return 1
    print("✓ quota is readable")
    _print_usage(usage, now_local())

    if args.no_schedule:
        print("schedule not installed (--no-schedule)")
    elif sys.platform == "darwin":
        try:
            launchd.install(root, cfg.interval_minutes, claude)
        except RuntimeError as e:
            print(f"✗ {e}")
            return 1
        print(f"✓ scheduled: checks every {cfg.interval_minutes} minutes while this Mac is awake")
    else:
        print("automatic scheduling is only set up on macOS for now. Add this to cron instead:")
        print(f"  */{cfg.interval_minutes} * * * * {sys.executable} -m doggybag run")

    print()
    print(f"Next: copy an example into {tasks_dir}, edit it, and `chmod +x` it.")
    print("Then `doggybag status` shows when it would run.")
    return 0


def cmd_status(args) -> int:
    root = state.home()
    cfg = state.load_config(root)
    try:
        usage = fetch_usage(cfg.claude)
    except UsageError as e:
        print(f"could not read quota: {e}")
        return 1
    now = now_local()
    idle = state.update_idle(root, usage, now)
    ctx = Context(usage, idle, now)

    _print_usage(usage, now)
    print(f"idle  no quota used for {format_duration(idle)} (as far as doggybag has seen)")
    if sys.platform == "darwin":
        scheduled = launchd.is_installed()
        print(
            f"schedule  every {cfg.interval_minutes} minutes"
            if scheduled
            else "schedule  not installed (run `doggybag setup`)"
        )
    print()

    tasks = discover(root / "tasks")
    if not tasks:
        print(f"no tasks yet. Put an executable script in {root / 'tasks'}")
        return 0
    for task in tasks:
        decision = decide(task, ctx, cfg, root)
        print(f"{'▶' if decision.run else '·'} {task.name}")
        print(f"    {'would run now' if decision.run else 'waiting'}: {decision.reason}")
        previous = state.last_run(root, task.name)
        if previous:
            when = datetime.fromtimestamp(previous["ended"]).strftime("%b %d %H:%M")
            how = previous["stopped"] or f"exit {previous['exit']}"
            print(f"    last run {when} ({how})")
    return 0


def cmd_run(args) -> int:
    return run_cycle(state.home(), only=args.task)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doggybag",
        description="Run your own scripts when Claude quota is about to go unused.",
    )
    parser.add_argument("--version", action="version", version=f"doggybag {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="check Claude Code, create ~/.doggybag, install the schedule")
    p.add_argument("--no-schedule", action="store_true", help="do everything except the schedule")
    p.add_argument("--uninstall", action="store_true", help="remove the schedule")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("status", help="show quota and why each task would or would not run")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="check once and run the tasks whose conditions hold")
    p.add_argument("task", nargs="?", help="run this one task now, ignoring its conditions")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
