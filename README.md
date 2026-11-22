# doggybag 🥡

English · [繁體中文](README.zh-TW.md)

**Your Claude subscription quota resets whether you used it or not. doggybag spends what's left on jobs you choose, before it expires.**

## What it looks like

A job is one text file. This is a complete one:

```markdown
---
when: leftover
in: ~/work/myrepo
---
Find the TODO and FIXME comments in this repository.
Pick the five that are most worth fixing.
```

It says: *when my quota is about to reset with some left over, go to this folder and do this.*

Every job has the same three parts:

| Part | Answers | In the example |
|---|---|---|
| `when:` | When should it run? | when quota is about to reset with some left |
| `in:` | Where? | in `~/work/myrepo` |
| the text below | What should be done? | find the TODO comments |

doggybag checks your quota every 10 minutes. When the moment comes it hands the text to Claude Code, and saves the answer to a file. You don't have to be at your computer.

Want something other than Claude Code to do the work? Add one line, `run:`, and the text goes to that command instead. [More on that below.](#handing-the-job-to-something-else)

## Get started

You need macOS, Python 3.11+, and [Claude Code](https://claude.com/claude-code) logged in.

**1. Install**

```bash
uv tool install git+https://github.com/toeric/doggybag    # or: pipx install git+https://github.com/toeric/doggybag
doggybag setup
```

`setup` creates the folder `~/.doggybag/tasks/` and puts a first job in it, the one shown above. It is switched off until you edit it.

**2. Edit the first job**

```bash
open -e ~/.doggybag/tasks/10-todo-triage.md
```

Change the folder after `in:` to one of your own projects, and change `enabled: false` to `true`.

**3. Check**

```bash
doggybag status
```

```text
5h     60% left · resets in 2h55m (Sun 17:59) · +2 behind pace
week   95% left · resets in 6d5h (Sat 20:59) · +6 behind pace

· 10-todo-triage.md
    waiting: 5h.resets_in <= 1h (no, now 2h55m) and 5h.remaining >= 30% (yes, now 60%)
```

That's all. It will run by itself when the conditions hold. To see it work right now, run `doggybag run 10-todo-triage`.

## Example jobs

`setup` also copies these into `~/.doggybag/tasks/examples/`. To use one, copy it into `~/.doggybag/tasks/` and set the folder after `in:`.

| Example | What it does | Runs when | Changes your files? |
|---|---|---|---|
| [todo-triage.md](src/doggybag/examples/todo-triage.md) | Lists the five TODO comments most worth fixing | quota is about to reset with some left | No |
| [docs-check.md](src/doggybag/examples/docs-check.md) | Finds places where the README no longer matches the code | you are behind on the week | No |
| [write-tests.md](src/doggybag/examples/write-tests.md) | Writes tests for the least-tested file | nobody has used Claude for an hour, and you are behind on the week | Yes, in the tests folder |
| [run-skill.md](src/doggybag/examples/run-skill.md) | Runs one of your own Claude Code skills | nobody has used Claude for an hour | Depends on the skill |
| [review-commits.md](src/doggybag/examples/review-commits.md) | Uses `run:` to collect the latest commits and pipe them to Claude for review | quota is about to reset with some left | No |
| [own-agent.md](src/doggybag/examples/own-agent.md) | Uses `run:` to hand the text to a program of your own | the last day of the week, with a lot left | Up to your program |

## Where the answer goes

Everything a job prints is saved in `~/.doggybag/logs/`. `doggybag status` shows the file for each job's last run:

```text
· 10-todo-triage.md
    last run Nov 22 18:50 (exit 0) · output: ~/.doggybag/logs/10-todo-triage-20261122-185043.log
```

You also get a desktop notification when a job starts and when it finishes.

## When to run

One word is usually enough:

| Write | Runs when |
|---|---|
| `when: leftover` | the 5-hour window resets within an hour and at least 30% is left |
| `when: idle` | nobody has used Claude for an hour |
| `when: behind` | you are using your weekly quota slower than the week is passing |

Combine them with `and`. With more than one `when:` line, any one line is enough.

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
| add a job | put a file in `~/.doggybag/tasks/` |
| remove a job | delete the file |
| switch a job off for now | set `enabled: false` |
| change the order | rename the files; doggybag goes through them in filename order |
| try a job right now | `doggybag run 10-todo-triage` (ignores `when` and `enabled`) |

## The three commands

| Command | What it does |
|---|---|
| `doggybag setup` | Checks your environment and installs the schedule. `--no-schedule` skips the schedule, `--uninstall` removes it |
| `doggybag status` | Shows your quota, and whether each task would run right now and why |
| `doggybag run` | Checks once and runs the tasks that are due. `doggybag run <task>` runs that task now |

## Reference

The details, for when you need them. In the code and the commands a job is called a *task*.

### Conditions

- Conditions joined by `and` on one line must all hold.
- With several `when:` lines, any one of them is enough.
- A task with no `when:` never runs automatically. Run it by hand with `doggybag run <task>`.
- Tasks are checked in filename order and run one at a time.
- Only `.md` files directly inside `~/.doggybag/tasks/` are tasks. Other files and subfolders are ignored.

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

### All settings

| Setting | Meaning | If you leave it out |
|---|---|---|
| `when` | When to run. Can appear more than once | The task only runs by hand |
| `in` | The folder to work in | The tasks folder |
| `run` | A shell command that does the work in place of Claude Code | Claude Code does the work |
| `tools` | What Claude may do without asking. `none` allows nothing. Not with `run` | `Read, Grep, Glob` |
| `model` | Which Claude model to use. Not with `run` | Your Claude Code default |
| `cooldown` | How long before the task can trigger again after a run | `5h` |
| `timeout` | The task is stopped if it runs longer than this | `1h` |
| `enabled` | Set to `false` to switch the task off | `true` |

### What a `run:` command receives

| What | Content |
|---|---|
| Standard input | The text below the settings |
| Working directory | The folder after `in:` |
| `DOGGYBAG_TASK` | The task's filename |
| `DOGGYBAG_REASON` | Why it was triggered |
| `DOGGYBAG_5H_REMAINING`, `DOGGYBAG_WEEK_REMAINING` | Percent left |
| `DOGGYBAG_5H_RESETS_AT`, `DOGGYBAG_WEEK_RESETS_AT` | Reset time (epoch seconds) |
| `DOGGYBAG_LOG` | Path of this run's log file |

The command reports back through its exit code: `0` means done, `75` means "nothing to do right now" (not a failure, and no cooldown), anything else is a failure.

Everything the command prints is written to `~/.doggybag/logs/`.

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
