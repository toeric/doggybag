import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from doggybag import runner, state  # noqa: E402
from doggybag.conditions import ConditionError, Context, evaluate, parse_when  # noqa: E402
from doggybag.tasks import discover, parse_header  # noqa: E402
from doggybag.usage import FIVE_HOURS, ONE_WEEK, Usage, UsageError, Window, parse_usage  # noqa: E402

TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 11, 22, 15, 0, tzinfo=TPE)

# 2026-11-22 在 Claude Code 2.1.330 實際取得的輸出
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
        # 5 小時窗口剩 3 小時：時間過了 40%，用了 23% → 落後 17
        self.assertAlmostEqual(make_usage().five_hour.behind(NOW), 17.0)


class Conditions(unittest.TestCase):
    def ctx(self, idle=timedelta(minutes=5), **kw):
        return Context(make_usage(**kw), idle, NOW)

    def test_and(self):
        clauses = parse_when("5h.resets_in <= 60m and 5h.remaining >= 30")
        self.assertFalse(evaluate(clauses, self.ctx())[0])  # 還有 3 小時
        self.assertTrue(evaluate(clauses, self.ctx(five_left=timedelta(minutes=40)))[0])
        self.assertFalse(
            evaluate(clauses, self.ctx(five_left=timedelta(minutes=40), five_used=80))[0]
        )

    def test_idle_and_behind(self):
        clauses = parse_when("idle >= 60m and week.behind >= 10")
        # 週額度剩 6 天：時間過了約 14%，用了 3% → 落後約 11
        self.assertTrue(evaluate(clauses, self.ctx(idle=timedelta(hours=2)))[0])
        self.assertFalse(evaluate(clauses, self.ctx(idle=timedelta(minutes=10)))[0])

    def test_inactive_window_is_never_true(self):
        ok, detail = evaluate(parse_when("5h.resets_in <= 60m"), self.ctx(five_left=None))
        self.assertFalse(ok)
        self.assertIn("not active", detail)

    def test_percent_sign_is_optional(self):
        self.assertEqual(parse_when("week.remaining >= 40%")[0].value, 40)

    def test_bad_conditions(self):
        for text in ("tokens > 5", "idle >= soon", "5h.remaining >= lots", "5h.remaining"):
            with self.assertRaises(ConditionError, msg=text):
                parse_when(text)


class Headers(unittest.TestCase):
    def test_shell_header(self):
        h = parse_header(
            "#!/bin/bash\n# doggybag:\n#   when: idle >= 60m\n#   when: 5h.remaining >= 50\n"
            "#   cooldown: 6h\n#   timeout: 20m\n\necho hi\n"
        )
        self.assertEqual(len(h["whens"]), 2)
        self.assertEqual(h["cooldown"], timedelta(hours=6))
        self.assertEqual(h["timeout"], timedelta(minutes=20))

    def test_other_comment_styles(self):
        h = parse_header("// doggybag:\n//   when: idle >= 1h\nconsole.log(1)\n")
        self.assertEqual(len(h["whens"]), 1)

    def test_no_header(self):
        self.assertEqual(parse_header("#!/bin/bash\necho hi\n"), {"whens": []})

    def test_header_stops_at_first_other_line(self):
        h = parse_header("# doggybag:\n#   when: idle >= 1h\n\n#   when: idle >= 2h\n")
        self.assertEqual(len(h["whens"]), 1)

    def test_unknown_key(self):
        with self.assertRaises(ConditionError):
            parse_header("# doggybag:\n#   whenever: idle >= 1h\n")


class Idle(unittest.TestCase):
    def test_idle_grows_until_usage_rises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(state.update_idle(root, make_usage(), NOW), timedelta(0))
            later = NOW + timedelta(minutes=30)
            self.assertEqual(state.update_idle(root, make_usage(), later), timedelta(minutes=30))
            # 用量增加 → 閒置歸零
            busy = NOW + timedelta(minutes=40)
            self.assertEqual(state.update_idle(root, make_usage(five_used=25), busy), timedelta(0))

    def test_reset_time_wobble_is_not_a_new_window(self):
        # 同一個窗口，reset 時間從 6:00pm 變成 5:59pm，不應該被當成有人在用
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


class Deciding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tasks").mkdir()
        self.cfg = state.Config(notify=False)

    def tearDown(self):
        self.tmp.cleanup()

    def add_task(self, name, body, executable=True):
        p = self.root / "tasks" / name
        p.write_text(body)
        if executable:
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        return p

    def ctx(self, **kw):
        return Context(make_usage(**kw), timedelta(hours=2), NOW)

    def decide(self, ctx=None):
        task = discover(self.root / "tasks")[0]
        return runner.decide(task, ctx or self.ctx(), self.cfg, self.root)

    def test_runs_when_condition_holds(self):
        self.add_task("a.sh", "#!/bin/sh\n# doggybag:\n#   when: idle >= 60m\n")
        self.assertTrue(self.decide().run)

    def test_any_when_line_is_enough(self):
        self.add_task("a.sh", "#!/bin/sh\n# doggybag:\n#   when: idle >= 9h\n#   when: 5h.remaining >= 50\n")
        self.assertTrue(self.decide().run)

    def test_not_executable_is_disabled(self):
        self.add_task("a.sh", "#!/bin/sh\n# doggybag:\n#   when: idle >= 60m\n", executable=False)
        d = self.decide()
        self.assertFalse(d.run)
        self.assertIn("chmod", d.reason)

    def test_no_condition_never_runs_automatically(self):
        self.add_task("a.sh", "#!/bin/sh\necho hi\n")
        self.assertFalse(self.decide().run)

    def test_header_error_is_reported(self):
        self.add_task("a.sh", "#!/bin/sh\n# doggybag:\n#   when: nonsense >= 1\n")
        d = self.decide()
        self.assertFalse(d.run)
        self.assertIn("unknown signal", d.reason)

    def test_reserve_blocks(self):
        self.add_task("a.sh", "#!/bin/sh\n# doggybag:\n#   when: idle >= 60m\n")
        d = self.decide(self.ctx(five_used=95))
        self.assertFalse(d.run)
        self.assertIn("reserve", d.reason)

    def test_cooldown_blocks_but_exit_75_does_not(self):
        self.add_task("a.sh", "#!/bin/sh\n# doggybag:\n#   when: idle >= 60m\n#   cooldown: 6h\n")
        ended = (NOW - timedelta(hours=1)).timestamp()
        state.record_run(self.root, {"task": "a.sh", "ended": ended, "exit": 0, "stopped": None})
        self.assertIn("cooling down", self.decide().reason)
        state.record_run(self.root, {"task": "a.sh", "ended": ended, "exit": 75, "stopped": None})
        self.assertTrue(self.decide().run)


class Executing(unittest.TestCase):
    def test_runs_script_passes_env_and_records(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "tasks").mkdir()
            p = root / "tasks" / "10-hello.sh"
            p.write_text('#!/bin/sh\necho "left=$DOGGYBAG_5H_REMAINING task=$DOGGYBAG_TASK"\nexit 3\n')
            p.chmod(0o755)
            task = discover(root / "tasks")[0]
            ctx = Context(make_usage(), timedelta(0), runner.now_local())
            lines = []
            entry = runner.execute(task, ctx, "test", state.Config(notify=False), root, lines.append)
            self.assertEqual(entry["exit"], 3)
            self.assertIn("left=77 task=10-hello.sh", Path(entry["log"]).read_text())
            self.assertEqual(state.last_run(root, "10-hello.sh")["exit"], 3)
            self.assertTrue(any("failed with exit 3" in line for line in lines))

    def test_timeout_stops_the_whole_process_group(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "tasks").mkdir()
            p = root / "tasks" / "slow.sh"
            p.write_text("#!/bin/sh\n# doggybag:\n#   timeout: 0.02m\nsleep 60 &\nwait\n")
            p.chmod(0o755)
            task = discover(root / "tasks")[0]
            ctx = Context(make_usage(), timedelta(0), runner.now_local())
            entry = runner.execute(task, ctx, "test", state.Config(notify=False), root, lambda s: None)
            self.assertIn("timeout", entry["stopped"])
            self.assertLess(entry["ended"] - entry["started"], 20)

    def test_only_one_run_at_a_time(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with runner.single_instance(root) as first:
                self.assertTrue(first)
                with runner.single_instance(root) as second:
                    self.assertFalse(second)


class Schedule(unittest.TestCase):
    def test_plist_is_valid_and_escaped(self):
        from doggybag import launchd

        data = launchd.build_plist(Path("/tmp/a&b"), 10, "/opt/tools/claude")
        text = launchd.render_plist(data)
        self.assertIn("<integer>600</integer>", text)
        self.assertIn("/tmp/a&amp;b/logs/doggybag.log", text)
        self.assertIn("<false/>", text)
        self.assertIn("/opt/tools", data["EnvironmentVariables"]["PATH"])


if __name__ == "__main__":
    unittest.main()
