"""決定哪些 task 該跑，並執行它們。

doggybag 不知道一個 task 會花多少額度，所以唯一的煞車是：
task 執行期間持續讀額度，低於保留線就中止，也不再開下一個。
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
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
from .usage import Usage, UsageError, fetch_usage, find_claude

EXIT_NOTHING_TO_DO = 75  # 指令回報「現在沒事可做」：不算失敗，也不進 cooldown
WATCH_INTERVAL = 300  # 執行期間每隔幾秒重讀一次額度
KILL_GRACE = 30  # SIGTERM 之後等幾秒才 SIGKILL


def now_local() -> datetime:
    return datetime.now().astimezone()


@dataclass
class Decision:
    run: bool
    reason: str


def reserve_problem(usage: Usage, cfg: state.Config) -> str | None:
    if usage.five_hour.remaining < cfg.reserve_5h:
        return f"5h quota is down to {usage.five_hour.remaining}% (reserve {cfg.reserve_5h:g}%)"
    if usage.week.remaining < cfg.reserve_week:
        return f"weekly quota is down to {usage.week.remaining}% (reserve {cfg.reserve_week:g}%)"
    return None


def decide(
    task: Task, ctx: Context, cfg: state.Config, root: Path, force: bool = False
) -> Decision:
    if task.error:
        return Decision(False, f"header error: {task.error}")
    if not task.cwd.is_dir():
        return Decision(False, f"folder not found: {task.cwd} (set `in:` to a folder that exists)")
    if force:
        return Decision(True, "run by hand")
    if not task.enabled:
        return Decision(False, "switched off (enabled: false)")
    if not task.whens:
        return Decision(False, "no `when:` condition, only runs by hand")

    previous = state.last_run(root, task.name)
    if previous and previous.get("exit") != EXIT_NOTHING_TO_DO:
        since = ctx.now.timestamp() - previous["ended"]
        left = task.cooldown.total_seconds() - since
        if left > 0:
            return Decision(False, f"cooling down for another {format_duration(timedelta(seconds=left))}")

    problem = reserve_problem(ctx.usage, cfg)
    if problem:
        return Decision(False, problem)

    failed = []
    for clauses in task.whens:
        ok, detail = evaluate(clauses, ctx)
        if ok:
            return Decision(True, detail)
        failed.append(detail)
    return Decision(False, " | or: ".join(failed))


@contextmanager
def single_instance(root: Path):
    """同一時間只允許一個 doggybag run。拿不到鎖時 yield False。"""
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


def execute(task: Task, ctx: Context, reason: str, cfg: state.Config, root: Path, out) -> dict:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = ctx.now
    log_path = logs / f"{task.path.stem}-{started:%Y%m%d-%H%M%S}.log"
    if not task.run and not find_claude(cfg.claude):
        raise UsageError("`claude` not found on PATH")

    env = dict(os.environ)
    env.update(
        DOGGYBAG_TASK=task.name,
        DOGGYBAG_REASON=reason,
        DOGGYBAG_5H_REMAINING=str(ctx.usage.five_hour.remaining),
        DOGGYBAG_WEEK_REMAINING=str(ctx.usage.week.remaining),
        DOGGYBAG_LOG=str(log_path),
    )
    for key, window in (("5H", ctx.usage.five_hour), ("WEEK", ctx.usage.week)):
        if window.resets_at:
            env[f"DOGGYBAG_{key}_RESETS_AT"] = str(int(window.resets_at.timestamp()))

    out(f"🥡 packing up {task.name}: {reason}")
    if cfg.notify:
        notify(f"Packing up {task.name}")

    stopped = None
    with open(log_path, "wb") as log, tempfile.TemporaryFile() as prompt_file:
        # 內文走 stdin：不會被當成指令的參數解讀，長度也不受限。
        # 內文是空的時候，指令會直接讀到結尾。
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
                start_new_session=True,  # 自己一個 process group，中止時連子程序一起停
            )
        except OSError as e:
            log.write(f"doggybag: could not start: {e}\n".encode())
            proc = None

        if proc is not None:
            deadline = time.monotonic() + task.timeout.total_seconds()
            next_watch = time.monotonic() + WATCH_INTERVAL
            try:
                while proc.poll() is None:
                    time.sleep(2)
                    if time.monotonic() >= deadline:
                        stopped = f"timeout after {format_duration(task.timeout)}"
                    elif time.monotonic() >= next_watch:
                        next_watch = time.monotonic() + WATCH_INTERVAL
                        try:
                            stopped = reserve_problem(fetch_usage(cfg.claude), cfg)
                        except UsageError:
                            pass  # 讀不到就下次再看，不因此中止 task
                    if stopped:
                        _stop(proc)
            except BaseException:
                # doggybag 自己被中止時，不留下還在跑的 task
                _stop(proc)
                raise

    ended = now_local()
    code = proc.returncode if proc is not None else 127
    entry = {
        "task": task.name,
        "reason": reason,
        "started": started.timestamp(),
        "ended": ended.timestamp(),
        "exit": code,
        "stopped": stopped,
        "log": str(log_path),
    }
    state.record_run(root, entry)

    took = format_duration(ended - started)
    if stopped:
        summary = f"stopped {task.name} after {took}: {stopped}"
    elif code == 0:
        summary = f"finished {task.name} in {took}"
    elif code == EXIT_NOTHING_TO_DO:
        summary = f"{task.name} had nothing to do"
    else:
        summary = f"{task.name} failed with exit {code} after {took} (log: {log_path})"
    out(f"   {summary}")
    if cfg.notify and code != EXIT_NOTHING_TO_DO:
        notify(summary[0].upper() + summary[1:])
    return entry


def run_cycle(root: Path, only: str | None = None, out=print) -> int:
    """檢查一輪。only 有值時只跑那個 task，而且不看條件。回傳 exit code。"""
    cfg = state.load_config(root)
    with single_instance(root) as acquired:
        if not acquired:
            out("another doggybag run is in progress; skipping")
            return 0
        try:
            usage = fetch_usage(cfg.claude)
        except UsageError as e:
            out(f"could not read quota: {e}")
            return 1
        now = now_local()
        ctx = Context(usage, state.update_idle(root, usage, now), now)

        tasks = discover(root / "tasks")
        if only:
            tasks = [t for t in tasks if only in (t.name, t.path.stem)]
            if not tasks:
                out(f"no task named '{only}' in {root / 'tasks'}")
                return 1

        ran = 0
        for task in tasks:
            decision = decide(task, ctx, cfg, root, force=bool(only))
            if not decision.run:
                if only:
                    out(f"cannot run {task.name}: {decision.reason}")
                    return 1
                continue
            entry = execute(task, ctx, decision.reason, cfg, root, out)
            ran += 1
            if entry["stopped"] and "quota" in entry["stopped"]:
                break
            # task 跑完額度變了，下一個 task 要用新的數字判斷
            try:
                usage = fetch_usage(cfg.claude)
            except UsageError as e:
                out(f"could not re-read quota, stopping this round: {e}")
                break
            now = now_local()
            ctx = Context(usage, state.update_idle(root, usage, now), now)

        if ran == 0 and not only:
            out("nothing to pack up right now")
        return 0
