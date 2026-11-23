"""Decide which tasks are due, and run them.

waddlebag cannot know how much quota a task will use, so its only brake is this:
keep reading the quota while a task runs, stop it below the reserve, and start no further tasks.
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import state
from .conditions import Context, evaluate, format_duration
from .notify import notify
from .tasks import Task, discover
from .ui import UI, short
from .usage import Usage, UsageError, fetch_usage, find_claude

EXIT_NOTHING_TO_DO = 75  # the command says "nothing to do right now": not a failure, and no cooldown
WATCH_INTERVAL = 300  # seconds between quota checks while a task runs
KILL_GRACE = 30  # seconds to wait after SIGTERM before SIGKILL
RETRY_AFTER_FAILURE = timedelta(hours=1)  # rest after a failure or timeout, if shorter than the cooldown


def now_local() -> datetime:
    return datetime.now().astimezone()


@dataclass
class Decision:
    """Whether a task runs now, and how to say so.

    kind is one of: ready, waiting, resting, off, problem.
    """

    run: bool
    kind: str
    headline: str
    detail: str = ""

    @property
    def text(self) -> str:
        return f"{self.headline} {self.detail}".strip()


def reserve_shortfall(usage: Usage, cfg: state.Config) -> tuple[int, float] | None:
    """(percent left, reserve) for the window that has fallen below its reserve, if any."""
    if usage.five_hour.remaining < cfg.reserve_5h:
        return usage.five_hour.remaining, cfg.reserve_5h
    if usage.week.remaining < cfg.reserve_week:
        return usage.week.remaining, cfg.reserve_week
    return None


def rest_after(previous: dict, cooldown: timedelta) -> timedelta | None:
    """How long a task rests after this run.

    Done: the full cooldown. Failed or timed out: retry sooner, the problem may be fixed by then.
    Nothing to do, or stopped by the reserve brake: no rest, it waits for its conditions and quota anyway.
    """
    if previous.get("exit") == EXIT_NOTHING_TO_DO or previous.get("stopped") == "reserve":
        return None
    if previous.get("exit") == 0 and not previous.get("stopped"):
        return cooldown
    return min(cooldown, RETRY_AFTER_FAILURE)


def decide(
    task: Task, ctx: Context, cfg: state.Config, root: Path, force: bool = False
) -> Decision:
    if task.error:
        return Decision(False, "problem", "I can't read this one", task.error)
    # a switched-off job is not checked further: the starter job is off and still has a placeholder folder
    if not task.enabled and not force:
        return Decision(False, "off", "switched off")
    if not task.cwd.is_dir():
        return Decision(
            False, "problem", f"I can't find the folder {short(task.cwd)}",
            "set `in:` to a folder that exists",
        )
    if force:
        return Decision(True, "ready", "", "because you asked")
    if not task.whens:
        return Decision(False, "off", f"only when you ask: waddlebag run {task.path.stem}")

    previous = state.last_run(root, task.name)
    rest = rest_after(previous, task.cooldown) if previous else None
    if rest:
        left = rest.total_seconds() - (ctx.now.timestamp() - previous["ended"])
        if left > 0:
            return Decision(False, "resting", f"resting, back in {format_duration(timedelta(seconds=left))}")

    short_of = reserve_shortfall(ctx.usage, cfg)
    if short_of:
        left, reserve = short_of
        return Decision(False, "waiting", f"waiting, I'm saving your last {reserve:g}%", f"{left}% left")

    waiting_for = []
    for clauses in task.whens:
        ok, detail = evaluate(clauses, ctx)
        if ok:
            return Decision(True, "ready", "ready, I'd pack this up right now", detail)
        waiting_for.append(detail)
    return Decision(False, "waiting", "waiting", "; or ".join(waiting_for))


@contextmanager
def single_instance(root: Path):
    """Allow only one `waddlebag run` at a time. Yields False when the lock is taken."""
    root.mkdir(parents=True, exist_ok=True)
    f = open(root / "lock", "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        f.close()


def _stop(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=KILL_GRACE)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def execute(task: Task, ctx: Context, reason: str, cfg: state.Config, root: Path, ui: UI) -> dict:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = ctx.now
    log_path = logs / f"{task.path.stem}-{started:%Y%m%d-%H%M%S}.log"
    if not task.run and not find_claude(cfg.claude):
        raise UsageError("`claude` not found on PATH")

    env = dict(os.environ)
    env.update(
        WADDLEBAG_TASK=task.name,
        WADDLEBAG_REASON=reason,
        WADDLEBAG_5H_REMAINING=str(ctx.usage.five_hour.remaining),
        WADDLEBAG_WEEK_REMAINING=str(ctx.usage.week.remaining),
        WADDLEBAG_LOG=str(log_path),
    )
    for key, window in (("5H", ctx.usage.five_hour), ("WEEK", ctx.usage.week)):
        if window.resets_at:
            env[f"WADDLEBAG_{key}_RESETS_AT"] = str(int(window.resets_at.timestamp()))

    name, title = task.name, task.path.stem
    ui.say("fish", f"Packing up {ui.bold(name)}", ui.dim(reason))
    if cfg.notify:
        notify(f"Packing up {title}")

    stopped = None  # "timeout" or "reserve"
    left = None  # percent left when the reserve brake fired
    with open(log_path, "wb") as log, tempfile.TemporaryFile() as prompt_file:
        # The body goes on stdin: it cannot be mistaken for an argument, and its length is not limited.
        # With an empty body the command simply reads end-of-file.
        prompt_file.write(task.body.encode("utf-8"))
        prompt_file.seek(0)
        try:
            proc = subprocess.Popen(
                task.command(find_claude(cfg.claude)),
                cwd=task.cwd,
                env=env,
                stdin=prompt_file,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # its own process group, so stopping it stops its children too
            )
        except OSError as e:
            log.write(f"waddlebag: could not start: {e}\n".encode())
            proc = None

        if proc is not None:
            deadline = time.monotonic() + task.timeout.total_seconds()
            next_watch = time.monotonic() + WATCH_INTERVAL
            try:
                while proc.poll() is None:
                    time.sleep(2)
                    if time.monotonic() >= deadline:
                        stopped = "timeout"
                    elif time.monotonic() >= next_watch:
                        next_watch = time.monotonic() + WATCH_INTERVAL
                        try:
                            short_of = reserve_shortfall(fetch_usage(cfg.claude), cfg)
                        except UsageError:
                            short_of = None  # unreadable this time: check again later, do not stop the task for it
                        if short_of:
                            stopped, left = "reserve", short_of[0]
                    if stopped:
                        _stop(proc)
            except BaseException:
                # if waddlebag itself is interrupted, do not leave the task running
                _stop(proc)
                raise

    ended = now_local()
    code = proc.returncode if proc is not None else 127
    entry = {
        "task": name,
        "reason": reason,
        "started": started.timestamp(),
        "ended": ended.timestamp(),
        "exit": code,
        "stopped": stopped,
        "log": str(log_path),
    }
    state.record_run(root, entry)
    state.prune_logs(logs, task.path.stem)

    took = format_duration(ended - started)
    where = ui.dim(f"→ {short(log_path)}")
    if stopped == "reserve":
        ui.say(
            "alarm",
            ui.yellow(f"Dropped {name} after {took}."),
            f"You're down to {left}% and I'm saving the rest for you.",
        )
        note = f"Dropped {title} to save your last {left}%"
    elif stopped == "timeout":
        ui.say(
            "alarm",
            ui.yellow(f"Dropped {name}."),
            f"It ran past its {format_duration(task.timeout)} limit.",
        )
        note = f"Dropped {title}: it ran past its {format_duration(task.timeout)} limit"
    elif code == 0:
        ui.say("happy", f"{ui.green('Packed!')} {name} is done ({took})", where)
        note = f"Packed! {title} is done ({took})"
    elif code == EXIT_NOTHING_TO_DO:
        ui.say("sleep", f"{name} had nothing to do.", ui.dim("I'll ask again next time."))
        note = None
    else:
        failed = ui.red(f"{name} didn't work out")
        ui.say("sad", f"{failed} (exit {code}, {took})", where)
        note = f"{title} didn't work out (exit {code})"
    if cfg.notify and note:
        notify(note)
    return entry


def run_cycle(root: Path, only: str | None = None, ui: UI | None = None) -> int:
    """Check once. With `only`, run just that task and ignore its conditions. Returns the exit code."""
    cfg = state.load_config(root)
    ui = ui or UI(mascot_on=cfg.mascot)
    with single_instance(root) as acquired:
        if not acquired:
            ui.say("sleep", "I'm already out on a job.", ui.dim("Skipping this round."))
            return 0
        try:
            usage = fetch_usage(cfg.claude)
        except UsageError as e:
            ui.say("sad", ui.red("I couldn't read your quota."), ui.dim(str(e)))
            return 1
        now = now_local()
        ctx = Context(usage, state.update_idle(root, usage, now), now)

        tasks = discover(root / "tasks")
        if only:
            known = ", ".join(t.path.stem for t in tasks) or "nothing yet"
            tasks = [t for t in tasks if only in (t.name, t.path.stem)]
            if not tasks:
                ui.say("sad", ui.red(f"I don't know a job called '{only}'."), f"I have: {known}")
                return 1

        ran = 0
        for task in tasks:
            decision = decide(task, ctx, cfg, root, force=bool(only))
            if not decision.run:
                if only:
                    ui.say("sad", ui.red(f"I can't run {task.name}."), decision.text)
                    return 1
                continue
            entry = execute(task, ctx, decision.detail, cfg, root, ui)
            ran += 1
            if entry["stopped"] == "reserve":
                break
            # the task changed the quota, so judge the next one against fresh numbers
            try:
                usage = fetch_usage(cfg.claude)
            except UsageError as e:
                ui.say("sad", ui.red("I couldn't re-read your quota, so I'm stopping here."), ui.dim(str(e)))
                break
            now = now_local()
            ctx = Context(usage, state.update_idle(root, usage, now), now)

        # only to a person: the scheduler's log would otherwise gain this line every 10 minutes
        if ran == 0 and not only and sys.stdout.isatty():
            ui.say("sleep", f"Nothing to pack up right now. {ui.blue('z z z')}")
        return 0
