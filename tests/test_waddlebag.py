import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from waddlebag import launchd, mascot, runner, state  # noqa: E402
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
        self.assertEqual(t.command("claude"), ["claude", "-p", "--allowedTools", "Read", "Grep", "Glob"])
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

    def test_run_with_claude_only_settings_is_an_error(self):
        self.assertIn("only apply when Claude", self.write("---\nrun: ./a.sh\ntools: Read\n---\n").error)
        self.assertIn("only apply when Claude", self.write("---\nrun: ./a.sh\nmodel: haiku\n---\n").error)

    def test_tilde_in_folder(self):
        self.assertEqual(self.write("---\nin: ~/x\n---\nHi\n").workdir, Path.home() / "x")

    def test_file_without_settings_only_runs_by_hand(self):
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

    def test_no_condition_never_runs_automatically(self):
        self.assertFalse(self.decide("Hi\n").run)
        self.assertTrue(self.decide("Hi\n", force=True).run)

    def test_error_is_reported(self):
        d = self.decide("---\nwhen: nonsense >= 1\n---\nHi\n", force=True)
        self.assertFalse(d.run)
        self.assertEqual(d.kind, "problem")
        self.assertIn("unknown signal", d.detail)

    def test_reserve_blocks(self):
        d = self.decide("---\nwhen: idle\n---\nHi\n", self.ctx(five_used=95))
        self.assertFalse(d.run)
        self.assertIn("saving your last 10%", d.headline)

    def test_switched_off_waits_but_can_be_run_by_hand(self):
        text = "---\nwhen: idle\nenabled: false\n---\nHi\n"
        d = self.decide(text)
        self.assertFalse(d.run)
        self.assertEqual((d.kind, d.headline), ("off", "switched off"))
        self.assertTrue(self.decide(text, force=True).run)

    def test_missing_folder_is_reported_for_any_task_even_by_hand(self):
        for text in ("---\nwhen: idle\nin: /no/such\n---\nHi\n", "---\nwhen: idle\nin: /no/such\nrun: ./a.sh\n---\n"):
            d = self.decide(text, force=True)
            self.assertFalse(d.run)
            self.assertIn("I can't find the folder /no/such", d.headline)

    def test_switched_off_job_with_missing_folder_is_just_off(self):
        # the starter job after setup: switched off, folder still the placeholder
        text = "---\nwhen: leftover\nin: /no/such\nenabled: false\n---\nHi\n"
        d = self.decide(text)
        self.assertEqual((d.kind, d.headline), ("off", "switched off"))
        self.assertIn("I can't find the folder", self.decide(text, force=True).headline)

    def test_cooldown_blocks_but_exit_75_does_not(self):
        text = "---\nwhen: idle\ncooldown: 6h\n---\nHi\n"
        ended = (NOW - timedelta(hours=1)).timestamp()
        state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": 0, "stopped": None})
        self.assertIn("resting, back in 5h", self.decide(text).headline)
        state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": 75, "stopped": None})
        self.assertTrue(self.decide(text).run)

    def test_failures_retry_sooner_and_reserve_stops_do_not_rest(self):
        text = "---\nwhen: idle\ncooldown: 6h\n---\nHi\n"
        ended = (NOW - timedelta(minutes=30)).timestamp()
        for exit_code, stopped in ((1, None), (-15, "timeout")):
            state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": exit_code, "stopped": stopped})
            self.assertIn("resting, back in 30m", self.decide(text).headline)
        state.record_run(self.root, {"task": "10-task.md", "ended": ended, "exit": -15, "stopped": "reserve"})
        self.assertTrue(self.decide(text).run)
        long_ago = (NOW - timedelta(hours=2)).timestamp()
        state.record_run(self.root, {"task": "10-task.md", "ended": long_ago, "exit": 1, "stopped": None})
        self.assertTrue(self.decide(text).run)


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
        self.assertIn("args=-p --allowedTools Read Grep Glob", log)
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
        self.assertIn("Packing up 10-task.md", lines[0])
        self.assertTrue(any("didn't work out (exit 3" in line for line in lines))

    def test_run_without_body_sees_empty_input(self):
        t = self.write('---\nwhen: idle\nrun: echo "got=[$(cat)]"\n---\n')
        self.assertIn("got=[]", Path(self.execute(t)["log"]).read_text())

    def test_timeout_stops_the_whole_process_group(self):
        t = self.write("---\nwhen: idle\ntimeout: 0.02m\nrun: sleep 60 & wait\n---\n")
        entry = self.execute(t)
        self.assertEqual(entry["stopped"], "timeout")
        self.assertLess(entry["ended"] - entry["started"], 20)

    def test_only_one_run_at_a_time(self):
        with runner.single_instance(self.root) as first:
            self.assertTrue(first)
            with runner.single_instance(self.root) as second:
                self.assertFalse(second)


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
            self.assertEqual(lines[3], "in: ~/path/to/your/repo", item.name)
            closing = lines.index("---", 1)
            self.assertEqual(lines[closing - 1], "enabled: false", item.name)
            # apart from the first description line, the settings block has no comments or blank lines
            self.assertTrue(all(l and not l.startswith("#") for l in lines[2:closing]), item.name)

    def test_starter_is_switched_off_and_reads_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "10-todo-triage.md"
            p.write_text(resources.files("waddlebag").joinpath("examples/todo-triage.md").read_text())
            t = load_task(p)
            self.assertFalse(t.enabled)
            self.assertEqual(t.command("claude")[-3:], ["Read", "Grep", "Glob"])


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

    def test_starts_the_waddlebag_script_when_installed(self):
        # macOS names the background item after this program, so it should not be plain python
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            python = Path(d) / "python"
            with mock.patch.object(sys, "executable", str(python)):
                self.assertEqual(launchd.program(), [str(python), "-m", "waddlebag", "run"])
                script = Path(d) / "waddlebag"
                script.write_text("#!/bin/sh\n")
                script.chmod(0o755)
                self.assertEqual(launchd.program(), [str(script), "run"])


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
            self.assertEqual(out.count("10-a.md  done in 1m"), 2)
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
