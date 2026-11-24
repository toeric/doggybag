import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from waddlebag import cli, editing, launchd, mascot, runner, state  # noqa: E402
from waddlebag.conditions import ConditionError, Context, evaluate, parse_when  # noqa: E402
from waddlebag.tasks import discover, ignored, load_task  # noqa: E402
from waddlebag.ui import UI  # noqa: E402
from waddlebag.usage import FIVE_HOURS, ONE_WEEK, Usage, UsageError, Window, parse_usage  # noqa: E402

TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 11, 22, 15, 0, tzinfo=TPE)
QUIET = state.Config(notify=False)

# real output captured on 2026-11-22 from Claude Code 2.1.330
REAL_OUTPUT = """You are currently using your subscription to power your Claude Code usage

Current session: 23% used · resets Nov 22 at 6pm (Asia/Taipei)
Current week (all models): 3% used · resets Nov 28 at 9pm (Asia/Taipei)
Current week (Fable): 3% used · resets Nov 28 at 9pm (Asia/Taipei)

What's contributing to your usage?
"""


def make_usage(five_used=23, five_left=timedelta(hours=3), week_used=3, week_left=timedelta(days=6)):
    five = Window(five_used, NOW + five_left if five_left is not None else None, FIVE_HOURS)
    return Usage(five, Window(week_used, NOW + week_left, ONE_WEEK), "")


class ParseUsage(unittest.TestCase):
    def test_real_output(self):
        u = parse_usage(REAL_OUTPUT, NOW)
        self.assertEqual(u.five_hour.used, 23)
        self.assertEqual(u.five_hour.resets_at, datetime(2026, 11, 22, 18, 0, tzinfo=TPE))
        self.assertEqual(u.week.used, 3)
        self.assertEqual(u.week.resets_at, datetime(2026, 11, 28, 21, 0, tzinfo=TPE))
        self.assertEqual(u.five_hour.resets_in(NOW), timedelta(hours=3))

    def test_time_without_date_means_next_occurrence(self):
        u = parse_usage("Current session: 5% used · resets 2:30am (Asia/Taipei)\n"
                        "Current week (all models): 9% used · resets Nov 28 at 9pm (Asia/Taipei)", NOW)
        self.assertEqual(u.five_hour.resets_at, datetime(2026, 11, 23, 2, 30, tzinfo=TPE))

    def test_reset_across_new_year(self):
        now = datetime(2026, 12, 30, 12, 0, tzinfo=TPE)
        u = parse_usage("Current week (all models): 9% used · resets Jan 2 at 9pm (Asia/Taipei)", now)
        self.assertEqual(u.week.resets_at.year, 2027)

    def test_missing_session_line_is_inactive_window(self):
        u = parse_usage("Current week (all models): 9% used · resets Nov 28 at 9pm (Asia/Taipei)", NOW)
        self.assertEqual(u.five_hour.remaining, 100)
        self.assertIsNone(u.five_hour.resets_in(NOW))
        self.assertIsNone(u.five_hour.behind(NOW))

    def test_unrecognised_output_raises(self):
        with self.assertRaises(UsageError):
            parse_usage("Please log in", NOW)

    def test_behind(self):
        # 3 hours left in the 5-hour window: 40% of the time gone, 23% used -> 17 behind
        self.assertAlmostEqual(make_usage().five_hour.behind(NOW), 17.0)


class Conditions(unittest.TestCase):
    def ctx(self, idle=timedelta(minutes=5), **kw):
        return Context(make_usage(**kw), idle, NOW)

    def test_and(self):
        clauses = parse_when("5h.resets_in <= 60m and 5h.remaining >= 30")
        self.assertFalse(evaluate(clauses, self.ctx())[0])  # still 3 hours to go
        self.assertTrue(evaluate(clauses, self.ctx(five_left=timedelta(minutes=40)))[0])
        self.assertFalse(
            evaluate(clauses, self.ctx(five_left=timedelta(minutes=40), five_used=80))[0]
        )

    def test_idle_and_behind(self):
        clauses = parse_when("idle >= 60m and week.behind >= 10")
        # 6 days left in the week: about 14% of the time gone, 3% used -> about 11 behind
        self.assertTrue(evaluate(clauses, self.ctx(idle=timedelta(hours=2)))[0])
        self.assertFalse(evaluate(clauses, self.ctx(idle=timedelta(minutes=10)))[0])

    def test_inactive_window_is_never_true(self):
        ok, detail = evaluate(parse_when("5h.resets_in <= 60m"), self.ctx(five_left=None))
        self.assertFalse(ok)
        self.assertIn("no 5-hour window is open", detail)

    def test_percent_sign_is_optional(self):
        self.assertEqual(parse_when("week.remaining >= 40%")[0].value, 40)

    def test_durations_can_combine_units_the_way_status_prints_them(self):
        from waddlebag.conditions import format_duration, parse_duration

        self.assertEqual(parse_when("idle >= 5h10m")[0].value, timedelta(hours=5, minutes=10))
        for text in ("45m", "6h", "1.5d", "5h10m", "2d6h"):
            self.assertEqual(parse_duration(format_duration(parse_duration(text))), parse_duration(text), text)
        for text in ("10m5h", "5h5h", "5", "h"):
            with self.assertRaises(ConditionError, msg=text):
                parse_duration(text)

    def test_bad_conditions(self):
        for text in ("tokens > 5", "idle >= soon", "5h.remaining >= lots", "5h.remaining"):
            with self.assertRaises(ConditionError, msg=text):
                parse_when(text)


class Presets(unittest.TestCase):
    def test_presets_expand(self):
        self.assertEqual(
            [str(c) for c in parse_when("leftover")],
            ["5h.resets_in <= 1h", "5h.remaining >= 30%"],
        )
        self.assertEqual([str(c) for c in parse_when("idle")], ["idle >= 1h"])
        self.assertEqual([str(c) for c in parse_when("behind")], ["week.behind >= 20%"])

    def test_presets_combine_with_and_and_with_expressions(self):
        self.assertEqual(len(parse_when("idle and behind")), 2)
        self.assertEqual(len(parse_when("Leftover and week.remaining >= 50")), 3)

    def test_idle_with_operator_is_still_a_plain_condition(self):
        self.assertEqual(str(parse_when("idle >= 3h")[0]), "idle >= 3h")

    def test_unknown_word_mentions_presets(self):
        with self.assertRaises(ConditionError) as cm:
            parse_when("sometimes")
        self.assertIn("leftover", str(cm.exception))


class Idle(unittest.TestCase):
    def test_idle_grows_until_usage_rises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(state.update_idle(root, make_usage(), NOW), timedelta(0))
            later = NOW + timedelta(minutes=30)
            self.assertEqual(state.update_idle(root, make_usage(), later), timedelta(minutes=30))
            # usage went up -> idle resets to zero
            busy = NOW + timedelta(minutes=40)
            self.assertEqual(state.update_idle(root, make_usage(five_used=25), busy), timedelta(0))

    def test_state_is_replaced_in_one_step(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            state.update_idle(root, make_usage(week_used=3), NOW)
            before = (root / "state.json").read_text()
            # a crash while the new version is being written leaves the old one whole
            with mock.patch.object(state.os, "fsync", side_effect=OSError("power cut")):
                with self.assertRaises(OSError):
                    state.update_idle(root, make_usage(week_used=9), NOW + timedelta(minutes=10))
            self.assertEqual((root / "state.json").read_text(), before)

    def test_reset_time_wobble_is_not_a_new_window(self):
        # same window, reset time moves from 6:00pm to 5:59pm: must not count as activity
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            state.update_idle(root, make_usage(), NOW)
            later = NOW + timedelta(minutes=30)
            wobbled = make_usage(five_left=timedelta(hours=3) - timedelta(minutes=1))
            self.assertEqual(state.update_idle(root, wobbled, later), timedelta(minutes=30))

    def test_new_window_with_usage_is_activity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            state.update_idle(root, make_usage(five_used=80), NOW)
            later = NOW + timedelta(hours=4)
            fresh = make_usage(five_used=2, five_left=timedelta(hours=8))
            self.assertEqual(state.update_idle(root, fresh, later), timedelta(0))

    def test_week_reset_is_not_activity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            state.update_idle(root, make_usage(week_used=60), NOW)
            later = NOW + timedelta(hours=1)
            self.assertEqual(
                state.update_idle(root, make_usage(week_used=0), later), timedelta(hours=1)
            )


class TaskCase(unittest.TestCase):
    """A temporary ~/.waddlebag plus a helper for writing task files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tasks").mkdir()
        self.work = self.root / "repo"
        self.work.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, name="10-task.md"):
        p = self.root / "tasks" / name
        p.write_text(text)
        return load_task(p)

    def ctx(self, **kw):
        return Context(make_usage(**kw), timedelta(hours=2), NOW)

    def live_ctx(self):
        return Context(make_usage(), timedelta(hours=2), runner.now_local())


class Cards(TaskCase):
    def test_settings_and_body(self):
        t = self.write(
            "---\n# a comment\nwhen: leftover\nwhen: idle\n"
            f"in: {self.work}\ntools: Read, Edit\nmodel: haiku\ncooldown: 2h\ntimeout: 20m\n"
            "enabled: false\n---\nReview the latest commits.\n\nSecond paragraph.\n"
        )
        self.assertIsNone(t.error)
        self.assertEqual(t.body, "Review the latest commits.\n\nSecond paragraph.")
        self.assertEqual(len(t.whens), 2)
        self.assertEqual(t.cwd, self.work)
        self.assertEqual(t.cooldown, timedelta(hours=2))
        self.assertEqual(t.timeout, timedelta(minutes=20))
        self.assertFalse(t.enabled)

    def test_claude_is_the_default_and_reads_only(self):
        t = self.write("---\nwhen: idle\n---\nSay hi.\n")
        self.assertEqual(
            t.command("claude"), ["claude", "-p", "--allowedTools", "Read(./**)", "Grep(./**)", "Glob(./**)"]
        )
        self.assertEqual(t.cwd, self.root / "tasks")

    def test_tools_and_model_go_to_claude(self):
        t = self.write("---\ntools: Read, Edit\nmodel: haiku\n---\nSay hi.\n")
        self.assertEqual(
            t.command("/bin/claude"),
            ["/bin/claude", "-p", "--model", "haiku", "--allowedTools", "Read", "Edit"],
        )

    def test_tools_none(self):
        self.assertEqual(self.write("---\ntools: none\n---\nSay hi.\n").command("claude"), ["claude", "-p"])

    def test_run_replaces_claude(self):
        t = self.write("---\nwhen: idle\nrun: python3 ~/agents/a.py --fast | tee out.txt\n---\nDo it.\n")
        self.assertIsNone(t.error)
        self.assertEqual(t.command("claude"), ["/bin/sh", "-c", "python3 ~/agents/a.py --fast | tee out.txt"])

    def test_run_needs_no_body(self):
        t = self.write("---\nwhen: idle\nrun: ./nightly.sh\n---\n")
        self.assertIsNone(t.error)
        self.assertEqual(t.body, "")

    def test_a_comment_can_follow_a_setting(self):
        t = self.write(
            f"---\nin: {self.work}   # where Claude works\nwhen: idle  # nobody around\n"
            "access: edit # may change files\n---\n# A heading for Claude\nDo it. # not a comment\n"
        )
        self.assertIsNone(t.error)
        self.assertEqual((t.cwd, t.access), (self.work, "edit"))
        self.assertEqual(t.body, "# A heading for Claude\nDo it. # not a comment")
        self.assertIn("cannot read the line", self.write("---\nwhen: # nothing\n---\nx\n").error)

    def test_access_says_how_much_claude_may_do(self):
        tools = lambda text: self.write(text).command("claude")[3:]
        self.assertEqual(tools("---\naccess: read\n---\nx\n"), ["Read(./**)", "Grep(./**)", "Glob(./**)"])
        self.assertEqual(tools("---\naccess: edit\n---\nx\n")[-1], "Edit(./**)")
        self.assertEqual(tools("---\naccess: Full\n---\nx\n")[-2:], ["Edit(./**)", "Bash"])
        self.assertFalse(self.write("---\naccess: read\n---\nx\n").may_change_files)
        self.assertTrue(self.write("---\naccess: edit\n---\nx\n").may_change_files)

    def test_access_errors_and_warning(self):
        self.assertIn("read, edit, full", self.write("---\naccess: write\n---\nx\n").error)
        self.assertIn("not both", self.write("---\naccess: edit\ntools: Read\n---\nx\n").error)
        self.assertIn("only apply when Claude", self.write("---\naccess: read\nrun: ./a.sh\n---\n").error)
        self.assertIn("any command", self.write("---\naccess: full\n---\nx\n").warning)
        self.assertIsNone(self.write("---\naccess: edit\n---\nx\n").warning)

    def test_run_with_claude_only_settings_is_an_error(self):
        self.assertIn("only apply when Claude", self.write("---\nrun: ./a.sh\ntools: Read\n---\n").error)
        self.assertIn("only apply when Claude", self.write("---\nrun: ./a.sh\nmodel: haiku\n---\n").error)

    def test_tilde_in_folder(self):
        self.assertEqual(self.write("---\nin: ~/x\n---\nHi\n").workdir, Path.home() / "x")

    def test_file_without_settings_is_readable(self):
        t = self.write("Just a prompt.\n")
        self.assertIsNone(t.error)
        self.assertEqual(t.whens, [])

    def test_errors(self):
        self.assertIn("nothing to do", self.write("---\nwhen: idle\n---\n\n").error)
        self.assertIn("never closed", self.write("---\nwhen: idle\n").error)
        self.assertIn("expected `key: value`", self.write("---\nwhen: idle\nSay hi.\n").error)
        self.assertIn("unknown setting", self.write("---\nwhne: idle\n---\nHi\n").error)
        self.assertIn("true or false", self.write("---\nenabled: maybe\n---\nHi\n").error)
        self.assertIn("unknown signal", self.write("---\nwhen: nonsense >= 1\n---\nHi\n").error)

    def test_only_md_files_are_tasks(self):
        self.write("---\nwhen: idle\n---\nHi\n", name="20-b.md")
        self.write("---\nwhen: idle\n---\nHi\n", name="10-a.md")
        (self.root / "tasks" / "old-script.sh").write_text("#!/bin/sh\n")
        (self.root / "tasks" / ".hidden.md").write_text("x")
        (self.root / "tasks" / "examples").mkdir()
        (self.root / "tasks" / "examples" / "x.md").write_text("x")
        self.assertEqual([t.name for t in discover(self.root / "tasks")], ["10-a.md", "20-b.md"])
        self.assertEqual([p.name for p in ignored(self.root / "tasks")], ["old-script.sh"])


class Deciding(TaskCase):
    def decide(self, text, ctx=None, force=False):
        return runner.decide(self.write(text), ctx or self.ctx(), QUIET, self.root, force=force)

    def test_runs_when_condition_holds(self):
        self.assertTrue(self.decide("---\nwhen: idle >= 60m\n---\nHi\n").run)

    def test_any_when_line_is_enough(self):
        self.assertTrue(self.decide("---\nwhen: idle >= 9h\nwhen: 5h.remaining >= 50\n---\nHi\n").run)

    def test_no_condition_needs_you_but_runs_by_hand(self):
        d = self.decide("Hi\n")
        self.assertEqual((d.run, d.kind), (False, "needs you"))
        self.assertIn("add a `when:` line", d.headline)
        self.assertTrue(self.decide("Hi\n", force=True).run)

    def test_error_is_reported(self):
        d = self.decide("---\nwhen: nonsense >= 1\n---\nHi\n", force=True)
        self.assertFalse(d.run)
        self.assertEqual(d.kind, "needs you")
        self.assertIn("unknown signal", d.detail)

    def test_reserve_blocks(self):
        d = self.decide("---\nwhen: idle\n---\nHi\n", self.ctx(five_used=95))
        self.assertFalse(d.run)
        self.assertIn("saving your last 10%", d.headline)

    def test_switched_off_waits_but_can_be_run_by_hand(self):
        text = "---\nwhen: idle\nenabled: false\n---\nHi\n"
        d = self.decide(text)
        self.assertFalse(d.run)
        self.assertEqual((d.kind, d.headline), ("off", "off"))
        self.assertTrue(self.decide(text, force=True).run)

    def test_missing_folder_is_reported_for_any_task_even_by_hand(self):
        for text in ("---\nwhen: idle\nin: /no/such\n---\nHi\n", "---\nwhen: idle\nin: /no/such\nrun: ./a.sh\n---\n"):
            d = self.decide(text, force=True)
            self.assertFalse(d.run)
            self.assertIn("the `in:` folder /no/such doesn't exist", d.headline)

    def test_switched_off_job_with_missing_folder_is_just_off(self):
        # the starter job after setup: switched off, folder still the placeholder
        text = "---\nwhen: leftover\nin: /no/such\nenabled: false\n---\nHi\n"
        d = self.decide(text)
        self.assertEqual((d.kind, d.headline), ("off", "off"))
        self.assertIn("doesn't exist", self.decide(text, force=True).headline)

    def test_cooldown_blocks_but_exit_75_does_not(self):
        text = "---\nwhen: idle\ncooldown: 6h\n---\nHi\n"
        ended = (NOW - timedelta(hours=1)).timestamp()
        state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": 0, "stopped": None})
        self.assertIn("again in 5h", self.decide(text).headline)
        state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": 75, "stopped": None})
        self.assertTrue(self.decide(text).run)

    def test_failures_retry_sooner_and_reserve_stops_do_not_rest(self):
        text = "---\nwhen: idle\ncooldown: 6h\n---\nHi\n"
        ended = (NOW - timedelta(minutes=30)).timestamp()
        for exit_code, stopped in ((1, None), (-15, "timeout")):
            state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": exit_code, "stopped": stopped})
            self.assertIn("again in 30m", self.decide(text).headline)
        state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": -15, "stopped": "reserve"})
        self.assertTrue(self.decide(text).run)
        long_ago = (NOW - timedelta(hours=2)).timestamp()
        state.record_run(self.root, {"task": "10-task.md", "ended": long_ago, "exit": 1, "stopped": None})
        self.assertTrue(self.decide(text).run)


class GivingUp(TaskCase):
    TEXT = "---\nwhen: idle\ncooldown: 1m\n---\nx\n"

    def run_ended(self, ago, **entry):
        state.record_run(self.root, {"task": "10-task.md", "ended": time.time() - ago, **entry})

    def test_three_failures_in_a_row_wait_for_you(self):
        import os
        t = self.write(self.TEXT)
        os.utime(t.path, (time.time() - 10000, time.time() - 10000))
        self.run_ended(9000, exit=1)
        self.run_ended(8000, stopped="timeout", exit=-15)
        self.run_ended(7500, exit=75)  # had nothing to do: doesn't count, doesn't reset
        self.run_ended(7000, exit=None, stopped="interrupted")
        d = runner.decide(t, self.live_ctx(), QUIET, self.root)
        self.assertEqual((d.run, d.kind), (False, "needs you"))
        self.assertIn("3 times in a row", d.headline)
        # running it by hand is still possible
        self.assertTrue(runner.decide(t, self.live_ctx(), QUIET, self.root, force=True).run)
        # saving the file says "try again"
        os.utime(t.path, None)
        self.assertTrue(runner.decide(t, self.live_ctx(), QUIET, self.root).run)

    def test_a_good_run_resets_the_count(self):
        import os
        t = self.write(self.TEXT)
        os.utime(t.path, (time.time() - 10000, time.time() - 10000))
        self.run_ended(9000, exit=1)
        self.run_ended(8500, exit=1)
        self.run_ended(8000, exit=0)
        self.run_ended(7000, exit=1)
        self.run_ended(6000, exit=1)
        self.assertEqual(runner.failures_in_a_row(self.root, t), 2)
        self.assertTrue(runner.decide(t, self.live_ctx(), QUIET, self.root).run)


class Executing(TaskCase):
    def execute(self, task, cfg=QUIET, out=None):
        ui = UI(write=out or (lambda s: None), fancy=False)
        return runner.execute(task, self.live_ctx(), "test", cfg, self.root, ui)

    def test_body_reaches_claude_on_stdin_in_the_right_folder(self):
        # a fake claude that prints its arguments, working folder and stdin
        fake = self.root / "fake-claude"
        fake.write_text('#!/bin/sh\necho "args=$*"\necho "cwd=$(pwd -P)"\necho "stdin=$(cat)"\n')
        fake.chmod(0o755)
        t = self.write(f"---\nwhen: idle\nin: {self.work}\n---\n- Do the thing\n")
        entry = self.execute(t, state.Config(notify=False, claude=str(fake)))
        log = Path(entry["log"]).read_text()
        self.assertEqual(entry["exit"], 0)
        self.assertIn("args=-p --allowedTools Read(./**) Grep(./**) Glob(./**)", log)
        self.assertIn(f"cwd={self.work.resolve()}", log)
        self.assertIn("stdin=- Do the thing", log)

    def test_run_gets_body_folder_and_env_and_its_exit_code_is_recorded(self):
        lines = []
        t = self.write(
            f"---\nwhen: idle\nin: {self.work}\n"
            'run: echo "stdin=$(cat) cwd=$(pwd -P) left=$WADDLEBAG_5H_REMAINING task=$WADDLEBAG_TASK"; exit 3\n'
            "---\nInstructions for my agent\n"
        )
        entry = self.execute(t, out=lines.append)
        log = Path(entry["log"]).read_text()
        self.assertEqual(entry["exit"], 3)
        self.assertIn("stdin=Instructions for my agent", log)
        self.assertIn(f"cwd={self.work.resolve()}", log)
        self.assertIn("left=77 task=10-task.md", log)
        self.assertEqual(state.last_run(self.root, "10-task.md")["exit"], 3)
        self.assertIn("Packing up 10-task", lines[0])
        self.assertTrue(any("didn't work out (exit 3" in line for line in lines))

    def test_run_without_body_sees_empty_input(self):
        t = self.write('---\nwhen: idle\nrun: echo "got=[$(cat)]"\n---\n')
        self.assertIn("got=[]", Path(self.execute(t)["log"]).read_text())

    def test_timeout_stops_the_whole_process_group(self):
        t = self.write("---\nwhen: idle\ntimeout: 0.02m\nrun: sleep 60 & wait\n---\n")
        entry = self.execute(t)
        self.assertEqual(entry["stopped"], "timeout")
        self.assertLess(entry["ended"] - entry["started"], 20)

    def test_running_task_is_noted_and_cleared_when_it_ends(self):
        t = self.write(f"---\nwhen: idle\nin: {self.work}\nrun: cat '{self.root}/running.json'\n---\n")
        entry = self.execute(t)
        self.assertIn('"task": "10-task.md"', Path(entry["log"]).read_text())
        self.assertIsNone(state.left_running(self.root))

    def test_a_run_cut_short_is_recorded_and_retried_later(self):
        t = self.write(f"---\nwhen: idle\nin: {self.work}\ntools: Read, Edit\n---\nFix it\n")
        log = self.root / "logs" / "10-task-20261124-100000.log"
        log.parent.mkdir()
        log.write_text("half of an answer\n")
        started = runner.now_local().timestamp() - 600
        state.mark_running(self.root, {
            "task": t.name, "reason": "idle", "started": started, "beat": started + 300,
            "pid": 999999, "log": str(log), "folder": str(self.work), "may_change_files": t.may_change_files,
        })
        lines = []
        entry = runner.record_cut_short(self.root, QUIET, UI(write=lines.append, fancy=False))
        self.assertEqual(entry["stopped"], "interrupted")
        self.assertEqual(entry["ended"], started + 300)
        self.assertIsNone(state.left_running(self.root))
        self.assertEqual(state.last_run(self.root, t.name)["stopped"], "interrupted")
        self.assertIn("cut short", log.read_text())
        self.assertTrue(any("git status" in line for line in lines))
        # retried after an hour, like a failure, not after the full cooldown
        self.assertEqual(runner.rest_after(entry, timedelta(hours=5)), runner.RETRY_AFTER_FAILURE)
        self.assertIsNone(runner.record_cut_short(self.root, QUIET, UI(write=lines.append, fancy=False)))

    def test_only_tasks_that_can_change_files_say_so(self):
        self.assertFalse(self.write("---\nwhen: idle\n---\nx\n").may_change_files)
        self.assertTrue(self.write("---\nwhen: idle\ntools: Read, Bash(git:*)\n---\nx\n").may_change_files)
        self.assertTrue(self.write("---\nwhen: idle\nrun: ./x.sh\n---\n").may_change_files)

    def test_stopping_waddlebag_stops_its_task(self):
        import os, signal, subprocess, time
        fake = self.root / "fake-claude"
        fake.write_text("#!/bin/sh\necho 'Current session: 23% used · resets 11pm (UTC)'\n"
                        "echo 'Current week (all models): 3% used · resets Nov 28 at 9pm (UTC)'\n")
        fake.chmod(0o755)
        pidfile = self.root / "task.pid"
        self.write(f"---\nwhen: 5h.used >= 0\nin: {self.work}\nrun: echo $$ > '{pidfile}'; exec sleep 60\n---\n")
        (self.root / "config.toml").write_text("notify = false\nmascot = false\n")
        env = dict(os.environ, WADDLEBAG_HOME=str(self.root), WADDLEBAG_CLAUDE=str(fake),
                   PYTHONPATH=str(Path(__file__).resolve().parent.parent / "src"))
        proc = subprocess.Popen([sys.executable, "-m", "waddlebag", "run"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.1)
        task_pid = int(pidfile.read_text())
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("stopped too", out)
        with self.assertRaises(ProcessLookupError):
            os.kill(task_pid, 0)
        # the run is recorded as cut short at the next check
        self.assertIsNotNone(state.left_running(self.root))

    def test_launchd_waits_for_the_task_to_be_stopped(self):
        data = launchd.build_plist(self.root, 10, None)
        self.assertGreater(data["ExitTimeOut"], runner.KILL_GRACE)

    def test_running_only_while_a_run_holds_the_lock(self):
        state.mark_running(self.root, {"task": "10-task.md", "started": 0})
        self.assertIsNone(runner.running_now(self.root))  # a leftover from a run that was cut short
        with runner.single_instance(self.root):
            self.assertEqual(runner.running_now(self.root)["task"], "10-task.md")
            t = self.write("---\nwhen: idle\n---\nx\n")
            self.assertEqual(runner.quick_state(t, self.root), "running")

    def test_only_one_run_at_a_time(self):
        with runner.single_instance(self.root) as first:
            self.assertTrue(first)
            with runner.single_instance(self.root) as second:
                self.assertFalse(second)


class Offline(TaskCase):
    def setUp(self):
        super().setUp()
        from unittest import mock
        (self.root / "config.toml").write_text("notify = false\nmascot = false\n")
        self.patches = [mock.patch.object(runner, "OFFLINE_RETRY", 0)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def cycle(self, fetch):
        from unittest import mock
        lines = []
        with mock.patch.object(runner, "fetch_usage", fetch), mock.patch.object(sys.stdout, "isatty", lambda: False):
            code = runner.run_cycle(self.root, ui=UI(write=lines.append, fancy=False))
        return code, lines

    def test_offline_is_a_quiet_skip_said_once(self):
        from waddlebag.usage import Offline as NoNetwork

        def fetch(claude=None):
            raise NoNetwork("no network")

        code, lines = self.cycle(fetch)
        self.assertEqual(code, 0)
        self.assertTrue(any("No network" in line for line in lines))
        code, lines = self.cycle(fetch)
        self.assertEqual((code, lines), (0, []))
        code, lines = self.cycle(lambda claude=None: make_usage())
        self.assertEqual(code, 0)
        self.assertIn("Back online.", lines)

    def test_tries_once_more_before_giving_up(self):
        from waddlebag.usage import Offline as NoNetwork
        calls = []

        def fetch(claude=None):
            calls.append(1)
            if len(calls) == 1:
                raise NoNetwork("no network")
            return make_usage()

        code, lines = self.cycle(fetch)
        self.assertEqual((code, len(calls)), (0, 2))
        self.assertFalse(any("No network" in line for line in lines))

    def test_other_problems_are_still_failures(self):
        def fetch(claude=None):
            raise UsageError("could not find the weekly usage line")

        code, lines = self.cycle(fetch)
        self.assertEqual(code, 1)

    def test_checks_failing_for_an_hour_are_told_once(self):
        from unittest import mock

        def fetch(claude=None):
            raise UsageError("not logged in")

        told = []
        cfg = state.Config(notify=True, mascot=False)
        with mock.patch.object(runner, "notify", told.append), mock.patch.object(state, "load_config", lambda root: cfg):
            self.cycle(fetch)
            self.assertEqual(told, [])  # not yet: it may fix itself
            self.assertEqual(state.failing(self.root)["why"], "not logged in")
            later = runner.now_local() + timedelta(hours=1, minutes=1)
            with mock.patch.object(runner, "now_local", lambda: later):
                self.cycle(fetch)
                self.cycle(fetch)
            self.assertEqual(len(told), 1)
            self.cycle(lambda claude=None: make_usage())
        self.assertIsNone(state.failing(self.root))

    def test_a_failed_read_is_offline_only_when_the_network_is_down(self):
        from unittest import mock
        from waddlebag import usage
        fake = self.root / "fake-claude"
        fake.write_text("#!/bin/sh\nexit 1\n")
        fake.chmod(0o755)
        with mock.patch.object(usage, "online", lambda timeout=3: False):
            with self.assertRaises(usage.Offline):
                usage.fetch_usage(str(fake))
        with mock.patch.object(usage, "online", lambda timeout=3: True):
            with self.assertRaises(UsageError) as e:
                usage.fetch_usage(str(fake))
            self.assertNotIsInstance(e.exception, usage.Offline)


class Packing(TaskCase):
    def template(self, example=None):
        return editing.new_template("todo", self.work, example)

    def fill(self, text, settings=None, body="Find the TODOs."):
        if settings:
            text = text.replace("when: leftover", settings)
        return text.replace(editing.PLACEHOLDER, body)

    def loop(self, *contents, answers=("e",)):
        """Run the edit loop with an editor that writes each of `contents` in turn."""
        said, asked, seen = [], list(answers), []

        def editor(path):
            seen.append(path.read_text())
            path.write_text(contents[len(seen) - 1])

        result = editing.edit_loop(self.template(), "todo", ask=lambda q: asked.pop(0), say=said.append, editor=editor)
        return result, said, seen

    def test_template_points_at_the_current_folder_and_reads_only(self):
        task, problem = editing.check(editing.clean(self.fill(self.template())), "todo")
        self.assertIsNone(problem)
        self.assertEqual((task.cwd, task.access, task.enabled), (self.work, "read", True))
        self.assertEqual(task.body, "Find the TODOs.")

    def test_saving_drops_the_help_but_not_the_text_for_claude(self):
        cleaned = editing.clean(self.fill(self.template(), body="# Heading\nDo it."))
        self.assertTrue(cleaned.startswith("---\nin: "))
        self.assertNotIn("# model:", cleaned)
        self.assertIn("# where Claude works", cleaned)  # a comment after a setting stays
        self.assertTrue(cleaned.endswith("---\n# Heading\nDo it.\n"))

    def test_untouched_template_asks_for_the_text(self):
        self.assertIn("what Claude should do", editing.check(editing.clean(self.template()), "todo")[1])

    def test_a_good_task_is_returned(self):
        result, said, _ = self.loop(self.fill(self.template()))
        self.assertEqual(said, [])
        self.assertEqual(result[1].body, "Find the TODOs.")

    def test_empty_file_cancels(self):
        self.assertIsNone(self.loop("")[0])

    def test_a_problem_can_be_edited_again_with_the_problem_shown(self):
        bad = self.fill(self.template(), settings="when: leftovr")
        result, said, seen = self.loop(bad, self.fill(self.template()))
        self.assertIn("leftovr", said[0])
        self.assertTrue(seen[1].startswith("# ! "))
        self.assertIsNotNone(result)

    def test_a_problem_can_be_discarded(self):
        result, said, _ = self.loop(self.fill(self.template(), settings="when: leftovr"), answers=("d",))
        self.assertIsNone(result)

    def test_missing_folder_and_missing_when_are_problems(self):
        text = self.fill(self.template()).replace(str(self.work), "/no/such/folder")
        self.assertIn("can't find the folder", editing.check(editing.clean(text), "todo")[1])
        text = self.fill(self.template()).replace("when: leftover", "")
        self.assertIn("`when:`", editing.check(editing.clean(text), "todo")[1])

    def test_names(self):
        self.assertEqual(editing.check_name("todo-triage", self.root / "tasks"), self.root / "tasks" / "todo-triage.md")
        with self.assertRaises(editing.EditError):
            editing.check_name("../evil", self.root / "tasks")
        self.write("x", name="taken.md")
        with self.assertRaises(editing.EditError) as e:
            editing.check_name("taken", self.root / "tasks")
        self.assertIn("waddlebag edit taken", str(e.exception))

    def test_every_example_makes_a_good_task_without_its_placeholder_folder(self):
        for name in editing.examples():
            task, problem = editing.check(editing.clean(self.template(name)), "todo")
            self.assertIsNone(problem, name)
            self.assertEqual(task.cwd, self.work, name)
            self.assertTrue(task.enabled, name)
        with self.assertRaises(editing.EditError):
            self.template("no-such-example")

    def test_full_access_warns(self):
        task, _ = editing.check(editing.clean(self.fill(self.template()).replace("access: read", "access: full")), "todo")
        self.assertIn("any command", task.warning)

    def test_pack_command_uses_your_editor_and_writes_the_task(self):
        import os
        from unittest import mock
        script = self.root / "editor.sh"
        filled = self.root / "filled.md"
        filled.write_text(self.fill(self.template()))
        script.write_text(f"#!/bin/sh\ncp '{filled}' \"$1\"\n")
        script.chmod(0o755)
        env = {"WADDLEBAG_HOME": str(self.root), "VISUAL": str(script)}
        out = []
        with mock.patch.dict(os.environ, env), mock.patch.object(Path, "cwd", lambda: self.work), \
                mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))):
            self.assertEqual(cli.main(["pack", "todo"]), 0)
            self.assertEqual(cli.main(["pack", "todo"]), 1)  # the name is taken now
        saved = load_task(self.root / "tasks" / "todo.md")
        self.assertIsNone(saved.error)
        self.assertEqual(saved.cwd, self.work)
        self.assertFalse(any(p.name.startswith(".") for p in (self.root / "tasks").iterdir()))


class EditingTasks(TaskCase):
    def edit(self, argv, editor_text=None, answers=()):
        import os
        from unittest import mock
        script = self.root / "editor.sh"
        if editor_text is None:
            script.write_text("#!/bin/sh\ntrue\n")  # closes without saving
        else:
            new = self.root / "new.md"
            new.write_text(editor_text)
            script.write_text(f"#!/bin/sh\ncp '{new}' \"$1\"\n")
        script.chmod(0o755)
        asked, out = list(answers), []
        with mock.patch.dict(os.environ, {"WADDLEBAG_HOME": str(self.root), "VISUAL": str(script)}), \
                mock.patch.object(cli, "_ask", lambda q: asked.pop(0) if asked else "d"), \
                mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))):
            code = cli.main(argv)
        return code, "\n".join(out)

    def test_edit_saves_a_good_change(self):
        self.write(f"---\nin: {self.work}\nwhen: idle\n---\nOld text\n", name="todo.md")
        code, out = self.edit(["edit", "todo"], f"# help\n---\nin: {self.work}\nwhen: leftover\n---\nNew text\n")
        self.assertEqual(code, 0)
        self.assertIn("Saved todo", out)
        self.assertEqual(load_task(self.root / "tasks" / "todo.md").body, "New text")

    def test_closing_without_saving_changes_nothing(self):
        text = f"---\nin: {self.work}\nwhen: idle\n---\nOld text\n"
        self.write(text, name="todo.md")
        code, out = self.edit(["edit", "todo"])
        self.assertEqual((code, (self.root / "tasks" / "todo.md").read_text()), (0, text))
        self.assertIn("as it was", out)

    def test_a_bad_change_is_never_saved(self):
        text = f"---\nin: {self.work}\nwhen: idle\n---\nOld text\n"
        self.write(text, name="todo.md")
        code, out = self.edit(["edit", "todo"], "---\nwhen: nonsense\n---\nx\n", answers=("d",))
        self.assertEqual((self.root / "tasks" / "todo.md").read_text(), text)
        self.assertIn("nonsense", out)

    def test_pick_from_a_list(self):
        self.write(f"---\nin: {self.work}\nwhen: idle\n---\nA\n", name="alpha.md")
        self.write(f"---\nin: {self.work}\nwhen: idle\nenabled: false\n---\nB\n", name="beta.md")
        code, out = self.edit(["edit"], f"---\nin: {self.work}\nwhen: behind\n---\nB2\n", answers=("2",))
        self.assertIn("1) alpha", out)
        self.assertIn("off", out)
        self.assertEqual(load_task(self.root / "tasks" / "beta.md").body, "B2")

    def test_unknown_task(self):
        self.write(f"---\nwhen: idle\n---\nA\n", name="alpha.md")
        self.assertEqual(self.edit(["edit", "nope"])[0], 1)


class SetupHints(TaskCase):
    def test_no_hint_when_waddlebag_is_on_path(self):
        from unittest import mock
        with mock.patch.object(cli.shutil, "which", lambda name: "/usr/local/bin/waddlebag"):
            self.assertIsNone(cli.path_hint())

    def test_hint_names_the_folder_and_the_shell_file(self):
        import os
        from unittest import mock
        bin_dir = Path.home() / "Library" / "Python" / "3.13" / "bin"
        with mock.patch.object(cli.shutil, "which", lambda name: None), \
                mock.patch.object(cli, "_script_dir", lambda: bin_dir), \
                mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            hint = cli.path_hint()
        self.assertIn("~/.zshrc", hint[0])
        self.assertEqual(hint[1], '  export PATH="$HOME/Library/Python/3.13/bin:$PATH"')
        self.assertEqual(hint[2], "then run: source ~/.zshrc")

    def test_no_hint_without_an_installed_command(self):
        from unittest import mock
        with mock.patch.object(cli.shutil, "which", lambda name: None), mock.patch.object(cli, "_script_dir", lambda: None):
            self.assertIsNone(cli.path_hint())

    def test_a_folder_macos_refused_is_named(self):
        log = self.root / "waddlebag.log"
        log.write_text("Traceback...\nPermissionError: [Errno 1] Operation not permitted: "
                       "'/Users/me/Documents/proj/.venv/pyvenv.cfg'\n")
        self.assertEqual(cli._blocked_folder(log), "/Users/me/Documents/proj/.venv/pyvenv.cfg")
        log.write_text("PermissionError: Operation not permitted: 'x'\nNo network, so I'm skipping this round.\n")
        self.assertIsNone(cli._blocked_folder(log))  # an old failure, not the last thing said


class InstallScript(unittest.TestCase):
    def test_install_script_is_valid_sh(self):
        import subprocess
        script = Path(__file__).resolve().parent.parent / "install.sh"
        self.assertEqual(subprocess.run(["sh", "-n", str(script)]).returncode, 0)


class Examples(unittest.TestCase):
    def test_every_example_card_is_valid(self):
        examples = resources.files("waddlebag").joinpath("examples")
        cards = [item for item in examples.iterdir() if item.name.endswith(".md")]
        self.assertGreaterEqual(len(cards), 5)
        for item in cards:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / item.name
                p.write_text(item.read_text())
                t = load_task(p)
                self.assertIsNone(t.error, item.name)
                self.assertTrue(t.whens, item.name)

    def test_examples_all_have_the_same_shape(self):
        examples = resources.files("waddlebag").joinpath("examples")
        names = sorted(item.name for item in examples.iterdir() if item.is_file())
        self.assertTrue(all(n.endswith(".md") for n in names), names)
        for item in examples.iterdir():
            lines = item.read_text().splitlines()
            self.assertEqual(lines[0], "---", item.name)
            self.assertTrue(lines[1].startswith("# "), item.name)
            self.assertTrue(lines[2].startswith("when: "), item.name)
            closing = lines.index("---", 1)
            settings = lines[2:closing]
            # pack gives an example your folder, and saving it means it is on
            self.assertFalse(any(l.startswith(("in:", "enabled:")) for l in settings), item.name)
            # apart from the first description line, the settings block has no comments or blank lines
            self.assertTrue(all(l and not l.startswith("#") for l in settings), item.name)


class PlainWords(unittest.TestCase):
    def say(self, when, **kw):
        idle = kw.pop("idle", timedelta(minutes=5))
        return evaluate(parse_when(when), Context(make_usage(**kw), idle, NOW))

    def test_waiting_names_the_first_thing_missing(self):
        self.assertEqual(
            self.say("leftover"),
            (False, "the 5-hour window resets in 3h, I go in the last 1h"),
        )
        self.assertEqual(
            self.say("leftover", five_left=timedelta(minutes=40), five_used=90),
            (False, "only 10% left in the 5-hour window, I want 30%"),
        )
        self.assertEqual(self.say("idle"), (False, "quota was used 5m ago, I wait for 1h of quiet"))
        self.assertEqual(
            self.say("behind"),
            (False, "you're keeping pace this week (11 behind, I go at 20)"),
        )

    def test_ready_lists_everything_that_holds(self):
        self.assertEqual(
            self.say("leftover", five_left=timedelta(minutes=42), five_used=40),
            (True, "the 5-hour window resets in 42m · 60% left"),
        )
        self.assertEqual(self.say("idle", idle=timedelta(hours=2)), (True, "quiet for 2h"))

    def test_uncommon_conditions_are_shown_as_written(self):
        self.assertEqual(self.say("5h.used <= 20"), (False, "5h.used <= 20% (now 23%)"))


class Penguin(unittest.TestCase):
    def test_every_pose_is_a_clean_grid(self):
        self.assertEqual(set(mascot.SPRITES), {"happy", "look", "fish", "sleep", "sad", "alarm"})
        for name, grid in mascot.SPRITES.items():
            self.assertEqual({len(row) for row in grid}, {mascot.WIDTH}, name)
            self.assertEqual(len(grid) % 2, 0, name)
            self.assertLessEqual({c for row in grid for c in row} - {"."}, set(mascot.PALETTE), name)

    def strip(self, text):
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def test_render_is_two_pixel_rows_per_line_and_always_the_same_width(self):
        for truecolor in (True, False):
            for name, grid in mascot.SPRITES.items():
                lines = mascot.render(name, truecolor)
                self.assertEqual(len(lines), len(grid) // 2, name)
                for line in lines:
                    self.assertEqual(len(self.strip(line)), mascot.WIDTH, name)

    def test_plain_mode_prints_only_the_words(self):
        lines = []
        ui = UI(write=lines.append, fancy=False)
        ui.say("happy", ui.green("Packed!"), ui.dim("second line"))
        self.assertEqual(lines, ["Packed!", "second line"])
        self.assertEqual(ui.bar(40), "████░░░░░░")

    def test_fancy_mode_puts_the_words_beside_the_penguin(self):
        lines = []
        ui = UI(write=lines.append, fancy=True)
        ui.say("fish", "Packing up a.md", "because you asked")
        height = len(mascot.SPRITES["fish"]) // 2
        self.assertEqual(len(lines), height + 2)  # a blank line, the picture, a blank line
        self.assertEqual((lines[0], lines[-1]), ("", ""))
        plain = [self.strip(line) for line in lines[1:-1]]
        self.assertEqual(sum("Packing up a.md" in line for line in plain), 1)
        with_text = [line for line in plain if line.strip() and len(line) > mascot.WIDTH]
        for line in with_text:
            self.assertEqual(line[mascot.WIDTH:mascot.WIDTH + 2], "  ")

    def test_mascot_can_be_switched_off_while_keeping_colour(self):
        lines = []
        ui = UI(write=lines.append, fancy=True, mascot_on=False)
        ui.say("happy", "hello")
        self.assertEqual(lines, ["hello"])


class Schedule(unittest.TestCase):
    def test_plist_is_valid_and_escaped(self):
        data = launchd.build_plist(Path("/tmp/a&b"), 10, "/opt/tools/claude")
        text = launchd.render_plist(data)
        self.assertIn("<integer>600</integer>", text)
        self.assertIn("/tmp/a&amp;b/logs/waddlebag.log", text)
        self.assertIn("<false/>", text)
        self.assertIn("/opt/tools", data["EnvironmentVariables"]["PATH"])

    def test_starts_the_python_interpreter_even_when_the_script_exists(self):
        # starting the script gets the scheduled run refused by macOS privacy protection (#30)
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            python = Path(d) / "python"
            script = Path(d) / "waddlebag"
            script.write_text("#!/bin/sh\n")
            script.chmod(0o755)
            with mock.patch.object(sys, "executable", str(python)):
                self.assertEqual(launchd.program(), [str(python), "-m", "waddlebag", "run"])

    def test_reads_the_last_exit_code(self):
        from subprocess import CompletedProcess
        from unittest import mock

        printed = "gui/501/com.waddlebag.agent = {\n\truns = 15\n\tlast exit code = 1\n}\n"
        with mock.patch.object(launchd, "_launchctl", return_value=CompletedProcess([], 0, printed, "")):
            self.assertEqual(launchd.last_exit(), 1)
        with mock.patch.object(launchd, "_launchctl", return_value=CompletedProcess([], 0, "runs = 0\n", "")):
            self.assertIsNone(launchd.last_exit())


class Housekeeping(unittest.TestCase):
    def test_only_the_newest_logs_of_that_task_are_kept(self):
        with tempfile.TemporaryDirectory() as d:
            logs = Path(d)
            for i in range(5):
                (logs / f"10-todo-2026112{i}-120000.log").write_text("")
            other = logs / "10-todo-triage-20260101-120000.log"  # a different task whose name starts the same
            other.write_text("")
            state.prune_logs(logs, "10-todo", keep=2)
            self.assertEqual(
                sorted(p.name for p in logs.iterdir()),
                ["10-todo-20261123-120000.log", "10-todo-20261124-120000.log", other.name],
            )

    def test_run_history_is_trimmed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for i in range(2 * state.KEEP_RUNS + 1):
                state.record_run(root, {"task": "a.md", "ended": i})
            lines = (root / "runs.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), state.KEEP_RUNS)
            self.assertEqual(state.last_run(root, "a.md")["ended"], 2 * state.KEEP_RUNS)


class Logs(unittest.TestCase):
    def logs(self, *argv):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest import mock

        from waddlebag import cli

        out = StringIO()
        with mock.patch.dict("os.environ", {"WADDLEBAG_HOME": self.root}), redirect_stdout(out):
            code = cli.main(["logs", *argv])
        return code, out.getvalue()

    def test_lists_runs_and_shows_the_latest_answer(self):
        with tempfile.TemporaryDirectory() as d:
            self.root = d
            self.assertEqual(self.logs(), (0, "Nothing has run yet.\n"))
            for i, answer in enumerate(("old answer", "new answer")):
                log = Path(d) / f"a-{i}.log"
                log.write_text(answer + "\n")
                start = NOW.timestamp() + i * 3600
                state.record_run(
                    Path(d),
                    {"task": "10-a.md", "started": start, "ended": start + 60, "exit": 0, "log": str(log)},
                )
            code, out = self.logs()
            self.assertEqual(code, 0)
            self.assertEqual(out.count("10-a  done in 1m"), 2)
            code, out = self.logs("10-a")
            self.assertEqual(code, 0)
            self.assertIn("new answer", out)
            self.assertNotIn("old answer", out)
            self.assertEqual(self.logs("nope")[0], 1)


class Settings(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text(text, encoding="utf-8")
            return state.load_config(Path(d))

    def test_default_file_loads(self):
        self.assertEqual(self.load(state.DEFAULT_CONFIG), state.Config())

    def test_values_are_read(self):
        cfg = self.load("reserve_5h = 20.5\nmascot = false\ninterval_minutes = 5\n")
        self.assertEqual((cfg.reserve_5h, cfg.mascot, cfg.interval_minutes), (20.5, False, 5))

    def test_broken_files_say_what_is_wrong(self):
        cases = {
            "reserve_5h = \n": "line 1",
            'interval_minutes = "ten"\n': "`interval_minutes` should be a whole number",
            "interval_minutes = 0\n": "`interval_minutes`",
            "reserve_week = 150\n": "`reserve_week` should be a number from 0 to 100",
            "reserve_5h = true\n": "`reserve_5h`",
            'notify = "yes"\n': "`notify` should be true or false",
            "intervall_minutes = 5\n": "unknown setting `intervall_minutes`",
        }
        for text, message in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(state.ConfigError) as cm:
                    self.load(text)
                self.assertIn(message, str(cm.exception))

    def test_commands_report_a_broken_file_without_a_traceback(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest import mock

        from waddlebag import cli

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text('interval_minutes = "ten"\n', encoding="utf-8")
            out = StringIO()
            with mock.patch.dict("os.environ", {"WADDLEBAG_HOME": d}), redirect_stdout(out):
                for command in ("status", "run"):
                    self.assertEqual(cli.main([command]), 1)
            self.assertIn("`interval_minutes` should be a whole number", out.getvalue())


if __name__ == "__main__":
    unittest.main()
