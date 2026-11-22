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
from doggybag.tasks import Task, _apply, discover, load_task, prompt_settings, script_settings  # noqa: E402
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


def parse_header(text):
    """把 script 開頭的設定套用到一個 Task 上，方便測試。"""
    task = Task(Path("x.sh"))
    _apply(task, script_settings(text), ("when", "cooldown", "timeout", "enabled"))
    return task


class Headers(unittest.TestCase):
    def test_shell_header(self):
        t = parse_header(
            "#!/bin/bash\n# doggybag:\n#   when: idle >= 60m\n#   when: 5h.remaining >= 50\n"
            "#   cooldown: 6h\n#   timeout: 20m\n\necho hi\n"
        )
        self.assertEqual(len(t.whens), 2)
        self.assertEqual(t.cooldown, timedelta(hours=6))
        self.assertEqual(t.timeout, timedelta(minutes=20))
        self.assertTrue(t.enabled)

    def test_other_comment_styles(self):
        self.assertEqual(len(parse_header("// doggybag:\n//   when: idle >= 1h\nconsole.log(1)\n").whens), 1)

    def test_no_header(self):
        self.assertEqual(parse_header("#!/bin/bash\necho hi\n").whens, [])

    def test_header_stops_at_first_other_line(self):
        t = parse_header("# doggybag:\n#   when: idle >= 1h\n\n#   when: idle >= 2h\n")
        self.assertEqual(len(t.whens), 1)

    def test_unknown_key(self):
        with self.assertRaises(ConditionError):
            parse_header("# doggybag:\n#   whenever: idle >= 1h\n")

    def test_enabled_false(self):
        self.assertFalse(parse_header("# doggybag:\n#   when: idle\n#   enabled: false\n").enabled)

    def test_script_cannot_use_prompt_only_settings(self):
        with self.assertRaises(ConditionError):
            parse_header("# doggybag:\n#   tools: Read\n")


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


PROMPT_FILE = """---
# a comment
when: leftover
when: idle
in: {workdir}
tools: Read, Edit
model: haiku
cooldown: 2h
enabled: false
---
Review the latest commits.

Second paragraph.
"""


class PromptTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tasks").mkdir()
        self.work = self.root / "repo"
        self.work.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, name="10-review.md"):
        p = self.root / "tasks" / name
        p.write_text(text)
        return load_task(p)

    def test_frontmatter_and_body(self):
        t = self.write(PROMPT_FILE.format(workdir=self.work))
        self.assertIsNone(t.error)
        self.assertTrue(t.is_prompt)
        self.assertEqual(t.prompt, "Review the latest commits.\n\nSecond paragraph.")
        self.assertEqual(len(t.whens), 2)
        self.assertEqual(t.cwd, self.work)
        self.assertEqual(t.cooldown, timedelta(hours=2))
        self.assertFalse(t.enabled)
        self.assertEqual(
            t.command("/bin/claude"),
            ["/bin/claude", "-p", "--model", "haiku", "--allowedTools", "Read", "Edit"],
        )

    def test_defaults_are_read_only_and_no_chmod_needed(self):
        t = self.write("---\nwhen: idle\n---\nSay hi.\n")
        self.assertTrue(t.executable)
        self.assertEqual(t.command("claude"), ["claude", "-p", "--allowedTools", "Read", "Grep", "Glob"])
        self.assertEqual(t.cwd, self.root / "tasks")

    def test_tools_none(self):
        t = self.write("---\ntools: none\n---\nSay hi.\n")
        self.assertEqual(t.command("claude"), ["claude", "-p"])

    def test_tilde_in_folder(self):
        t = self.write("---\nin: ~/somewhere\n---\nSay hi.\n")
        self.assertEqual(t.workdir, Path.home() / "somewhere")

    def test_plain_markdown_without_settings_only_runs_by_hand(self):
        t = self.write("Just a prompt.\n")
        self.assertIsNone(t.error)
        self.assertEqual(t.whens, [])

    def test_errors(self):
        self.assertIn("empty", self.write("---\nwhen: idle\n---\n\n").error)
        self.assertIn("never closed", self.write("---\nwhen: idle\n").error)
        self.assertIn("expected `key: value`", self.write("---\nwhen: idle\nSay hi.\n").error)
        self.assertIn("unknown setting", self.write("---\nwhne: idle\n---\nHi\n").error)
        self.assertIn("true or false", self.write("---\nenabled: maybe\n---\nHi\n").error)

    def ctx(self):
        return Context(make_usage(), timedelta(hours=2), NOW)

    def test_switched_off_waits_but_can_be_run_by_hand(self):
        t = self.write("---\nwhen: idle\nenabled: false\n---\nHi\n")
        cfg = state.Config(notify=False)
        d = runner.decide(t, self.ctx(), cfg, self.root)
        self.assertFalse(d.run)
        self.assertIn("switched off", d.reason)
        self.assertTrue(runner.decide(t, self.ctx(), cfg, self.root, force=True).run)

    def test_missing_folder_is_reported_even_by_hand(self):
        t = self.write("---\nwhen: idle\nin: /no/such/folder\n---\nHi\n")
        d = runner.decide(t, self.ctx(), state.Config(notify=False), self.root, force=True)
        self.assertFalse(d.run)
        self.assertIn("folder not found", d.reason)

    def test_prompt_reaches_the_command_on_stdin_in_the_right_folder(self):
        # 用一個假的 claude：把收到的參數、所在資料夾和 stdin 印出來
        fake = self.root / "fake-claude"
        fake.write_text('#!/bin/sh\necho "args=$*"\necho "cwd=$(pwd -P)"\necho "stdin=$(cat)"\n')
        fake.chmod(0o755)
        t = self.write(f"---\nwhen: idle\nin: {self.work}\n---\n- Do the thing\n")
        cfg = state.Config(notify=False, claude=str(fake))
        ctx = Context(make_usage(), timedelta(hours=2), runner.now_local())
        entry = runner.execute(t, ctx, "test", cfg, self.root, lambda s: None)
        log = Path(entry["log"]).read_text()
        self.assertEqual(entry["exit"], 0)
        self.assertIn("args=-p --allowedTools Read Grep Glob", log)
        self.assertIn(f"cwd={self.work.resolve()}", log)
        self.assertIn("stdin=- Do the thing", log)


class Setup(unittest.TestCase):
    def test_starter_template_is_valid_and_switched_off(self):
        from importlib import resources

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "10-review.md"
            p.write_text(resources.files("doggybag").joinpath("templates/review.md").read_text())
            t = load_task(p)
            self.assertIsNone(t.error)
            self.assertFalse(t.enabled)
            self.assertEqual(len(t.whens), 1)
            self.assertEqual(t.tools, ["Read", "Grep", "Glob"])

    def test_script_templates_are_valid(self):
        from importlib import resources

        for name in ("a-prompt.sh", "b-skill.sh", "c-own-program.py"):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / name
                p.write_text(resources.files("doggybag").joinpath(f"templates/{name}").read_text())
                t = load_task(p)
                self.assertIsNone(t.error, name)
                self.assertTrue(t.whens, name)


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
