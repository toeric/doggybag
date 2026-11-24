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
from .usage import Offline, Usage, UsageError, fetch_usage, find_claude

EXIT_NOTHING_TO_DO = 75  # the command says "nothing to do right now": not a failure, and no cooldown
WATCH_INTERVAL = 300  # seconds between quota checks while a task runs
KILL_GRACE = 30  # seconds to wait after SIGTERM before SIGKILL
RETRY_AFTER_FAILURE = timedelta(hours=1)  # rest after a failure or timeout, if shorter than the cooldown
GIVE_UP_AFTER = 3  # failures in a row before a task stops retrying and waits for you
BEAT_INTERVAL = 60  # seconds between updates of running.json while a task runs
TELL_AFTER = timedelta(hours=1)  # checks failing this long get one desktop notification
OFFLINE_RETRY = 20  # seconds to wait before trying once more: right after wake the network is often not up yet


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

    Done: the full cooldown. Failed, timed out or cut short: retry sooner, the problem may be fixed by then.
    Nothing to do, or stopped by the reserve brake: no rest, it waits for its conditions and quota anyway.
    """
    if previous.get("exit") == EXIT_NOTHING_TO_DO or previous.get("stopped") == "reserve":
        return None
    if previous.get("exit") == 0 and not previous.get("stopped"):
        return cooldown
    return min(cooldown, RETRY_AFTER_FAILURE)


def failures_in_a_row(root: Path, task: Task) -> int:
    """Failed, timed-out or cut-short runs since the last good one.

    Only runs after the task file was last saved count: saving it is how you say "try again".
    Runs stopped by the reserve brake, or that had nothing to do, say nothing about the task and are skipped.
    """
    try:
        saved = task.path.stat().st_mtime
    except OSError:
        saved = 0
    count = 0
    for entry in reversed(state.runs(root)):
        if entry["task"] != task.name:
            continue
        if entry["ended"] < saved:
            break
        if entry.get("exit") == EXIT_NOTHING_TO_DO or entry.get("stopped") == "reserve":
            continue
        if entry.get("exit") == 0 and not entry.get("stopped"):
            break
        count += 1
    return count


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
        return Decision(
            False, "problem", "needs you: add a `when:` line",
            "say when I should run it, e.g. `when: leftover`",
        )

    failures = failures_in_a_row(root, task)
    if failures >= GIVE_UP_AFTER:
        return Decision(
            False, "problem", f"needs you: it didn't work {failures} times in a row",
            f"see why with `waddlebag logs {task.path.stem}`, then save the file to try again",
        )

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


class Stopped(BaseException):
    """waddlebag itself was told to stop (SIGTERM from launchd or logout, SIGHUP from a closed terminal)."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


@contextmanager
def stop_on_signals():
    """Turn SIGTERM and SIGHUP into Stopped, so a running task is stopped instead of left behind.

    Python's default for these signals ends the process at once, skipping all cleanup. The task runs in a
    session of its own, so it would keep going, with no reserve brake. Only the first signal raises: a second
    one while the task is being stopped must not cut that short.
    """
    raised = False

    def handler(signum, frame):
        nonlocal raised
        if not raised:
            raised = True
            raise Stopped(signum)

    previous = {sig: signal.signal(sig, handler) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


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
        # noted before the task starts, so there is no moment when it runs without a trace
        running = {
            "task": name,
            "reason": reason,
            "started": started.timestamp(),
            "beat": started.timestamp(),
            "pid": None,
            "log": str(log_path),
            "folder": str(task.cwd),
            "may_change_files": task.may_change_files,
        }
        state.mark_running(root, running)
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
            running["pid"] = proc.pid
            state.mark_running(root, running)
            deadline = time.monotonic() + task.timeout.total_seconds()
            next_watch = time.monotonic() + WATCH_INTERVAL
            next_beat = time.monotonic() + BEAT_INTERVAL
            try:
                while proc.poll() is None:
                    time.sleep(2)
                    if time.monotonic() >= next_beat:
                        # the last sign of life tells a later check roughly when a cut-short run ended
                        next_beat = time.monotonic() + BEAT_INTERVAL
                        running["beat"] = time.time()
                        state.mark_running(root, running)
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
                # if waddlebag itself is interrupted, do not leave the task running.
                # running.json stays, so the next check records this run as cut short; note when it ended.
                _stop(proc)
                running["beat"] = time.time()
                state.mark_running(root, running)
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
    state.clear_running(root)
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


def record_cut_short(root: Path, cfg: state.Config, ui: UI) -> dict | None:
    """Record the run that a shutdown, a crash or a kill cut short. Call only while holding the run lock."""
    left = state.left_running(root)
    if left is None:
        return None
    entry = {
        "task": left["task"],
        "reason": left.get("reason", ""),
        "started": left["started"],
        "ended": left.get("beat", left["started"]),
        "exit": None,
        "stopped": "interrupted",
        "log": left.get("log", ""),
    }
    log = Path(entry["log"])
    if entry["log"] and log.exists():
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write("\nwaddlebag: this run was cut short (the Mac shut down, or waddlebag was stopped)\n")
        except OSError:
            pass
    state.record_run(root, entry)
    state.clear_running(root)

    title = Path(entry["task"]).stem
    if left.get("may_change_files"):
        folder = short(Path(left.get("folder", "")))
        ui.say(
            "alarm",
            ui.yellow(f"{entry['task']} was cut short."),
            f"It may have left {folder} half-changed: check `git status` there.",
        )
        note = f"{title} was cut short. Check `git status` in {folder}"
    else:
        ui.say("sad", ui.yellow(f"{entry['task']} was cut short."), ui.dim("I'll try it again in a while."))
        note = None
    if cfg.notify and note:
        notify(note)
    return entry


def _keep_failing(root: Path, cfg: state.Config, why: str) -> None:
    """Note a failed check. Being logged out never fixes itself, so after an hour say so, once."""
    failing = state.note_failure(root, why, now_local())
    if failing["notified"] or now_local().timestamp() - failing["since"] < TELL_AFTER.total_seconds():
        return
    if cfg.notify:
        notify("waddlebag can't read your quota. Run `waddlebag status` to see why")
    state.mark_failure_notified(root)


def _read_quota(cfg: state.Config) -> Usage:
    try:
        return fetch_usage(cfg.claude)
    except Offline:
        time.sleep(OFFLINE_RETRY)
        return fetch_usage(cfg.claude)


def run_cycle(root: Path, only: str | None = None, ui: UI | None = None) -> int:
    """Check once. With `only`, run just that task and ignore its conditions. Returns the exit code."""
    cfg = state.load_config(root)
    ui = ui or UI(mascot_on=cfg.mascot)
    try:
        with stop_on_signals():
            return _run_cycle(root, cfg, ui, only)
    except Stopped as e:
        ui.say("sleep", f"Told to stop ({signal.Signals(e.signum).name}), so I stopped too.")
        # exit 0: being stopped is not a failed check, and `status` would otherwise warn about it
        return 0


def _run_cycle(root: Path, cfg: state.Config, ui: UI, only: str | None) -> int:
    with single_instance(root) as acquired:
        if not acquired:
            ui.say("sleep", "I'm already out on a job.", ui.dim("Skipping this round."))
            return 0
        # holding the lock means no other run is alive, so a task still noted as running was cut short
        record_cut_short(root, cfg, ui)
        try:
            usage = _read_quota(cfg)
        except Offline:
            # a quiet skip: one line when it starts, so the scheduler's log isn't filled every 10 minutes
            if state.set_offline(root, True) or sys.stdout.isatty():
                ui.say("sleep", "No network, so I'm skipping this round.", ui.dim("I'll look again next time."))
            return 0
        except UsageError as e:
            ui.say("sad", ui.red("I couldn't read your quota."), ui.dim(str(e)))
            _keep_failing(root, cfg, str(e))
            return 1
        if state.set_offline(root, False):
            ui.line("Back online.")
        state.clear_failure(root)
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
