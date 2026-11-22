# doggybag 🥡

English · [繁體中文](README.zh-TW.md)

When your Claude subscription quota is about to expire with some left over, doggybag runs your own scripts. Take home what you couldn't finish.

doggybag only decides *when* to run. What runs is up to you: a prompt, a skill, or your own program.

## Requirements

- macOS (automatic scheduling is macOS-only for now; on Linux, call `doggybag run` from cron)
- Python 3.11 or later
- [Claude Code](https://claude.com/claude-code), logged in

## Install

```bash
uv tool install .        # or: pipx install .
doggybag setup
```

`setup` checks Claude Code, creates `~/.doggybag/`, copies in the examples, and installs a schedule that checks every 10 minutes.

## Three commands

| Command | What it does |
|---|---|
| `doggybag setup` | Checks your environment and installs the schedule. `--no-schedule` skips the schedule, `--uninstall` removes it |
| `doggybag status` | Shows your quota, and whether each task would run right now and why |
| `doggybag run` | Checks once and runs the tasks whose conditions hold. `doggybag run <task>` runs that task now, ignoring its conditions |

## Writing a task

One file is one task. Put an executable file in `~/.doggybag/tasks/` and write its conditions in a comment at the top:

```bash
#!/bin/bash
# doggybag:
#   when: 5h.resets_in <= 60m and 5h.remaining >= 30
#   when: idle >= 60m and week.behind >= 20
#   cooldown: 6h
#   timeout: 30m

cd ~/work/myrepo
claude -p "Review the three most recent commits." --allowedTools "Read" "Grep" "Glob"
```

- Conditions joined by `and` on one line must all hold.
- With several `when:` lines, any one of them is enough.
- Tasks are checked in filename order and run one at a time.
- A task with no `when:` never runs automatically. Run it by hand with `doggybag run <task>`.
- To disable a task, remove its execute permission (`chmod -x`) or move it out of the folder.
- The comment marker can be `#`, `//`, `--` or `;`, so a task can be written in any language.

### Signals

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

### Other settings

| Setting | Default | Meaning |
|---|---|---|
| `cooldown` | `5h` | How long before the task can trigger again after a run |
| `timeout` | `1h` | The task is stopped if it runs longer than this |

### The contract between doggybag and a task

doggybag passes these environment variables:

| Variable | Content |
|---|---|
| `DOGGYBAG_TASK` | The task's filename |
| `DOGGYBAG_REASON` | Why it was triggered |
| `DOGGYBAG_5H_REMAINING`, `DOGGYBAG_WEEK_REMAINING` | Percent left |
| `DOGGYBAG_5H_RESETS_AT`, `DOGGYBAG_WEEK_RESETS_AT` | Reset time (epoch seconds) |
| `DOGGYBAG_LOG` | Path of this run's log file |

A task reports back through its exit code: `0` means done, `75` means "nothing to do right now" (not a failure, and no cooldown), anything else is a failure.

Task output is written to `~/.doggybag/logs/`.

## The brake

doggybag cannot know how much quota a task will use, so it re-reads your quota every 5 minutes while a task runs.
When the remaining quota falls below the reserve, it sends SIGTERM to the task (and force-stops it after 30 seconds), and starts no further tasks.

The reserve is set in `~/.doggybag/config.toml`:

```toml
reserve_5h = 10      # keep at least 10% of the 5-hour window
reserve_week = 5     # keep at least 5% of the weekly limit
notify = true        # desktop notification when a task starts and finishes
interval_minutes = 10
```

## Letting Claude work while nobody is there

When doggybag triggers a task you are usually away, so Claude cannot ask you for permission, and anything not allowed in advance is blocked.
List the tools a task may use with `--allowedTools`. The examples allow only reading and searching; add more yourself when a task needs to change files.

Only work that goes through the logged-in `claude` command uses your subscription quota. A program that uses an API key is billed separately.

## Known limitations

- **The computer must be awake.** The schedule does not run while a Mac sleeps.
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
