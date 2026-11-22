# doggybag 🥡

English · [繁體中文](README.zh-TW.md)

**Your Claude subscription quota resets whether you used it or not. doggybag runs your own scripts on what's left before it expires.**

1. You put tasks in a folder. A task is a text file with a prompt, or any script.
2. Each task says at the top when it should run.
3. doggybag checks your quota every 10 minutes and runs the ones that are due.

doggybag only decides *when*. What runs is up to you: a prompt, a skill, or your own program.

## Quick start

You need macOS, Python 3.11+, and [Claude Code](https://claude.com/claude-code) logged in.

```bash
# 1. Install and set up
uv tool install git+https://github.com/toeric/doggybag    # or: pipx install git+https://github.com/toeric/doggybag
doggybag setup

# 2. Open the first task that setup made for you
open -e ~/.doggybag/tasks/10-review.md

# 3. See what doggybag thinks
doggybag status
```

`setup` creates `~/.doggybag`, installs a schedule that checks every 10 minutes, and writes a first task for you. That task is switched off until you edit it:

```markdown
---
when: leftover
in: ~/path/to/your/repo
enabled: false
---
Review the three most recent commits in this repository.
List anything that looks risky, and say which file and line it is in.
```

Change three things: the folder after `in:`, the text of the prompt, and `enabled: false` to `true`. There is nothing to register: **a task is a file in `~/.doggybag/tasks/`.**

`status` tells you, for every task, whether it would run right now and why:

```text
5h     60% left · resets in 2h55m (Sun 17:59) · +2 behind pace
week   95% left · resets in 6d5h (Sat 20:59) · +6 behind pace

· 10-review.md
    waiting: 5h.resets_in <= 1h (no, now 2h55m) and 5h.remaining >= 30% (yes, now 60%)
```

## When to run

Most of the time one word is enough:

| Write | Runs when |
|---|---|
| `when: leftover` | the 5-hour window resets within an hour and at least 30% is left |
| `when: idle` | nobody has used Claude for an hour |
| `when: behind` | you are using your weekly quota slower than the week is passing |

You can combine them with `and`, and you can write more than one `when:` line. Any one line is enough to trigger the task.

```yaml
when: idle and behind
when: leftover
```

If the three words don't fit, write the numbers yourself:

| I want to run it… | Write |
|---|---|
| in the last 30 minutes of the window, if half is left | `when: 5h.resets_in <= 30m and 5h.remaining >= 50` |
| after three idle hours | `when: idle >= 3h` |
| on the last day of the week, if a lot is left | `when: week.resets_in <= 1d and week.remaining >= 40` |

The full list of signals is in the [reference](#reference).

## Two ways to write a task

### A prompt file

The simplest task is a `.md` file. The settings go between the `---` lines, and everything below is the prompt.

```markdown
---
when: leftover
in: ~/work/myrepo
tools: Read, Grep, Glob
---
Review the three most recent commits and list anything risky.
```

| Setting | Meaning | If you leave it out |
|---|---|---|
| `when` | When to run | The task only runs by hand |
| `in` | The folder Claude works in | The tasks folder |
| `tools` | What Claude may do without asking. `none` allows nothing | `Read, Grep, Glob` (read and search only) |
| `model` | Which model to use | Your Claude Code default |

To run one of your Claude Code skills, make the prompt `/my-skill`.

Nobody is there to click "allow" when doggybag runs a task, so Claude can only use the tools listed in `tools`. Add `Edit` and `Write` yourself if the task should change files.

### A script

When you need more than one prompt, use a script in any language. The settings go in a comment at the top, and the file must be executable (`chmod +x`).

```bash
#!/bin/bash
# doggybag:
#   when: leftover
#   cooldown: 6h

cd ~/work/myrepo
git pull
claude -p "Review the three most recent commits." --allowedTools "Read" "Grep" "Glob"
```

Only the logged-in `claude` command uses your subscription quota. A program that calls the API with an API key is billed separately.

`~/.doggybag/tasks/examples/` has an example of each: a prompt file, a script that runs a prompt, a script that runs a skill, and a script that calls your own program.

## Managing tasks

| To… | Do this |
|---|---|
| add a task | put a file in `~/.doggybag/tasks/` |
| remove a task | delete the file |
| switch a task off for now | set `enabled: false` |
| change the order | rename the files; doggybag goes through them in filename order |
| try a task right now | `doggybag run 10-review` (ignores `when` and `enabled`) |

## The three commands

| Command | What it does |
|---|---|
| `doggybag setup` | Checks your environment and installs the schedule. `--no-schedule` skips the schedule, `--uninstall` removes it |
| `doggybag status` | Shows your quota, and whether each task would run right now and why |
| `doggybag run` | Checks once and runs the tasks that are due. `doggybag run <task>` runs that task now |

## Reference

### Conditions

- Conditions joined by `and` on one line must all hold.
- With several `when:` lines, any one of them is enough.
- A task with no `when:` never runs automatically. Run it by hand with `doggybag run <task>`.
- Tasks are checked in filename order and run one at a time.
- In a script, the comment marker can be `#`, `//`, `--` or `;`.

The three words are short for:

| Word | Same as |
|---|---|
| `leftover` | `5h.resets_in <= 60m and 5h.remaining >= 30` |
| `idle` | `idle >= 60m` |
| `behind` | `week.behind >= 20` |

`5h` is the 5-hour window and `week` is the weekly limit.

| Signal | Meaning | Example |
|---|---|---|
| `5h.remaining`, `week.remaining` | Percent left | `week.remaining >= 40` |
| `5h.used`, `week.used` | Percent used | `5h.used <= 20` |
| `5h.resets_in`, `week.resets_in` | Time until reset | `5h.resets_in <= 60m` |
| `5h.behind`, `week.behind` | How many points your usage is behind the clock | `week.behind >= 20` |
| `idle` | How long since anyone used quota | `idle >= 60m` |

`behind` works like this: if 40% of the window's time has passed and you have used 10%, you are 30 behind.
Durations use `m`, `h` and `d`.

### Settings for every task

| Setting | Default | Meaning |
|---|---|---|
| `when` | none | When to run. Can appear more than once |
| `cooldown` | `5h` | How long before the task can trigger again after a run |
| `timeout` | `1h` | The task is stopped if it runs longer than this |
| `enabled` | `true` | Set to `false` to switch the task off |

Prompt files also take `in`, `tools` and `model`, described above.

### What doggybag gives a task

| Variable | Content |
|---|---|
| `DOGGYBAG_TASK` | The task's filename |
| `DOGGYBAG_REASON` | Why it was triggered |
| `DOGGYBAG_5H_REMAINING`, `DOGGYBAG_WEEK_REMAINING` | Percent left |
| `DOGGYBAG_5H_RESETS_AT`, `DOGGYBAG_WEEK_RESETS_AT` | Reset time (epoch seconds) |
| `DOGGYBAG_LOG` | Path of this run's log file |

A script reports back through its exit code: `0` means done, `75` means "nothing to do right now" (not a failure, and no cooldown), anything else is a failure.

Task output is written to `~/.doggybag/logs/`.

### The brake

doggybag cannot know how much quota a task will use, so it re-reads your quota every 5 minutes while a task runs.
When the remaining quota falls below the reserve, it sends SIGTERM to the task (and force-stops it after 30 seconds), and starts no further tasks.

The reserve is set in `~/.doggybag/config.toml`:

```toml
reserve_5h = 10      # keep at least 10% of the 5-hour window
reserve_week = 5     # keep at least 5% of the weekly limit
notify = true        # desktop notification when a task starts and finishes
interval_minutes = 10
```

### Known limitations

- **The computer must be awake.** The schedule does not run while a Mac sleeps.
- **Automatic scheduling is macOS-only for now.** On Linux, call `doggybag run` from cron.
- **Quota comes from the text output of `claude -p "/usage"`.** That call uses no quota, and doggybag never touches your login credentials, but parsing will break if the output format changes (last verified with Claude Code 2.1.330).
- **Usage has 1% resolution.** `idle` cannot see very small amounts of use.
- **`idle` only updates when doggybag checks.** It is measured from the last time doggybag saw usage go up.
- **With no 5-hour window in progress**, conditions on `5h.resets_in` and `5h.behind` are never true. What `/usage` prints in that state has not been verified yet.

## Development

```bash
python3 -m unittest discover -s tests
```

Set `DOGGYBAG_HOME` to move `~/.doggybag` somewhere else for testing.

## License

[MIT](LICENSE)
