# waddlebag reference

The details, for when you need them. The [README](../README.md) has the short version.

In the code and the commands, a job is called a *task*.

## What Claude is allowed to do

Nobody is there to click "allow" when a job runs, so Claude can only use the tools the job lists.

```yaml
tools: Read, Grep, Glob                 # the default: read and search only
tools: Read, Grep, Glob, Edit, Write    # may also change files
```

Leave `tools:` out and the job can only read.

## Handing the job to something else

By default the text of a job goes to Claude Code. Add `run:` and it goes to that command instead. Everything else about the job stays the same.

**Your own agent.** The text below the settings is what your program receives as its input:

```markdown
---
when: idle
in: ~/work/myrepo
run: python3 ~/agents/my_agent.py
---
Find the TODO comments and pick the five most worth fixing.
```

**A script that needs no instructions.** Leave the text out:

```markdown
---
when: leftover
in: ~/work/myrepo
run: ./scripts/nightly-review.sh
---
```

**A one-line pipeline.** `run:` is a shell command, so this works too:

```markdown
---
when: leftover
in: ~/work/myrepo
run: git log -3 --patch | claude -p "Review these commits. List anything risky."
---
```

Two things to know:

- `tools:` and `model:` are settings for Claude Code, so they cannot be combined with `run:`.
- Only the logged-in `claude` command uses your subscription quota. A program that calls the API with an API key is billed separately.

## Managing jobs

| To… | Do this |
|---|---|
| add a job | put a file in `~/.waddlebag/tasks/` |
| remove a job | delete the file |
| switch a job off for now | set `enabled: false` |
| change the order | rename the files; waddlebag goes through them in filename order |
| try a job right now | `waddlebag run 10-todo-triage` (ignores `when` and `enabled`) |

## Reading `waddlebag status`

| Mark | Meaning |
|---|---|
| `●` | ready: it would run right now |
| `○` | waiting for its conditions, or resting after a run |
| `–` | switched off, or it has no `when:` and only runs when you ask |
| `!` | something is wrong with the file, and the next line says what |

## Writing your own conditions

If `leftover`, `idle` and `behind` don't fit, write the numbers yourself. Combine conditions with `and`. With more than one `when:` line, any one line is enough.

```yaml
when: idle and behind
when: 5h.resets_in <= 30m and 5h.remaining >= 50
```

| I want to run it… | Write |
|---|---|
| in the last 30 minutes of the window, if half is left | `when: 5h.resets_in <= 30m and 5h.remaining >= 50` |
| after three idle hours | `when: idle >= 3h` |
| on the last day of the week, if a lot is left | `when: week.resets_in <= 1d and week.remaining >= 40` |

## Conditions

- Conditions joined by `and` on one line must all hold.
- With several `when:` lines, any one of them is enough.
- A task with no `when:` never runs automatically. Run it by hand with `waddlebag run <task>`.
- Tasks are checked in filename order and run one at a time.
- Only `.md` files directly inside `~/.waddlebag/tasks/` are tasks. Other files and subfolders are ignored.

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
Durations use `m`, `h` and `d`, alone or combined, largest first: `45m`, `6h`, `5h10m`, `2d6h`.

## All settings

| Setting | Meaning | If you leave it out |
|---|---|---|
| `when` | When to run. Can appear more than once | The task only runs by hand |
| `in` | The folder to work in | The tasks folder |
| `run` | A shell command that does the work in place of Claude Code | Claude Code does the work |
| `tools` | What Claude may do without asking. `none` allows nothing. Not with `run` | `Read, Grep, Glob` |
| `model` | Which Claude model to use. Not with `run` | Your Claude Code default |
| `cooldown` | How long before the task can trigger again after it is done. After a failure, a timeout or a run cut short it can try again after 1h (or the cooldown, if shorter); after the reserve brake stops it, right away | `5h` |
| `timeout` | The task is stopped if it runs longer than this | `1h` |
| `enabled` | Set to `false` to switch the task off | `true` |

## What a `run:` command receives

| What | Content |
|---|---|
| Standard input | The text below the settings |
| Working directory | The folder after `in:` |
| `WADDLEBAG_TASK` | The task's filename |
| `WADDLEBAG_REASON` | Why it was triggered |
| `WADDLEBAG_5H_REMAINING`, `WADDLEBAG_WEEK_REMAINING` | Percent left |
| `WADDLEBAG_5H_RESETS_AT`, `WADDLEBAG_WEEK_RESETS_AT` | Reset time (epoch seconds) |
| `WADDLEBAG_LOG` | Path of this run's log file |

The command reports back through its exit code: `0` means done, `75` means "nothing to do right now" (not a failure, and no cooldown), anything else is a failure.

Everything the command prints is written to `~/.waddlebag/logs/`. The newest 20 logs of each task are kept; older ones are deleted.

## The brake

waddlebag cannot know how much quota a task will use, so it re-reads your quota every 5 minutes while a task runs.
When the remaining quota falls below the reserve, it sends SIGTERM to the task (and force-stops it after 30 seconds), and starts no further tasks.

## When a run is cut short

If the Mac shuts down or waddlebag is stopped while a task runs, the next check records that run as "cut short" and the task tries again after 1h.
A task that may change files (it has `Edit`, `Write` or `Bash` in `tools:`, or a `run:` command) also sends a notification: check `git status` in its folder, it may be half-changed.

## When there is no network

A check that finds no network tries once more after 20 seconds, then skips the round quietly. It is not counted as a failed check, and the log gets one line when the network goes and one when it comes back.

## Settings file

`~/.waddlebag/config.toml`:

```toml
reserve_5h = 10      # keep at least 10% of the 5-hour window
reserve_week = 5     # keep at least 5% of the weekly limit
notify = true        # desktop notification when a task starts and finishes
mascot = true        # draw the penguin; false for text only
interval_minutes = 10
```

## Plain output

The penguin and the colours only appear when waddlebag is writing to a terminal. In a log file or a pipe the output is plain text. To force plain text in a terminal, set `NO_COLOR=1`.

## Known limitations

- **The computer must be awake.** The schedule does not run while a Mac sleeps.
- **macOS lists the schedule as a background item called "python".** After `setup`, macOS says "python" can run in the background: that is waddlebag's schedule. It has to start through the Python interpreter, or macOS privacy protection blocks it from folders such as `~/Documents`. Switching it off in System Settings → General → Login Items & Extensions stops the schedule, and `status` says so. `status` also warns when the last scheduled check failed.
- **Automatic scheduling is macOS-only for now.** On Linux, call `waddlebag run` from cron.
- **Quota comes from the text output of `claude -p "/usage"`.** That call uses no quota, and waddlebag never touches your login credentials, but parsing will break if the output format changes (last verified with Claude Code 2.1.330).
- **Usage has 1% resolution.** `idle` cannot see very small amounts of use.
- **`idle` only updates when waddlebag checks.** It is measured from the last time waddlebag saw usage go up.
- **With no 5-hour window in progress**, conditions on `5h.resets_in` and `5h.behind` are never true. What `/usage` prints in that state has not been verified yet.

## Development

```bash
python3 -m unittest discover -s tests
```

Set `WADDLEBAG_HOME` to move `~/.waddlebag` somewhere else for testing.
