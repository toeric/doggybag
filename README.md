<p align="center">
  <img src="assets/penguin.svg" width="120" alt="A pixel penguin carrying a fish by the tail">
</p>

<h1 align="center">waddlebag</h1>

<p align="center">
  Your Claude subscription quota resets whether you used it or not.<br>
  waddlebag spends what's left on jobs you choose, before it expires.
</p>

<p align="center">
  <a href="https://github.com/toeric/waddlebag/actions/workflows/test.yml"><img src="https://github.com/toeric/waddlebag/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-macOS-lightgrey" alt="macOS">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license"></a>
</p>

## How it works

1. **You write a job.** A short text file: what Claude should do, in which folder, and when.
2. **waddlebag keeps an eye on your quota.** Every 10 minutes it reads `/usage`, which costs nothing.
3. **When the moment comes, it runs the job.** Say the 5-hour window resets in under an hour with 30% still unused: waddlebag hands your text to Claude Code and saves the answer.

It never goes below a reserve you set, and it stops a running job if your quota gets low.

<p align="center">
  <img src="assets/status.svg" width="720" alt="waddlebag status in a terminal: quota bars and a list of jobs with what each one is waiting for">
</p>

## Install

```bash
pip install git+https://github.com/toeric/waddlebag
waddlebag setup
```

You need macOS, Python 3.11+, and [Claude Code](https://claude.com/claude-code) logged in.
If `pip` refuses to install into your system Python, use `pipx install` or `uv tool install` with the same address.

## Write a job

A job is one Markdown file in `~/.waddlebag/tasks/`. `setup` leaves you a first one, switched off:

```markdown
---
when: leftover
in: ~/path/to/your/repo
enabled: false
---
Find the TODO and FIXME comments in this repository.
Pick the five that are most worth fixing.
```

Point `in:` at a folder, set `enabled: true`, and you are done. Answers land in `~/.waddlebag/logs/`.

| `when:` | Runs when |
|---|---|
| `leftover` | the 5-hour window resets within an hour and at least 30% is left |
| `idle` | nobody has used Claude for an hour |
| `behind` | you are using your weekly quota slower than the week is passing |

Or [write your own numbers](docs/reference.md#conditions).

## Commands

| Command | What it does |
|---|---|
| `waddlebag setup` | Checks your environment and starts the 10-minute schedule |
| `waddlebag status` | Shows your quota and what each job is waiting for |
| `waddlebag run` | Checks once, right now. `waddlebag run <job>` runs that job immediately |
| `waddlebag logs` | Lists recent runs. `waddlebag logs <job>` shows that job's latest answer |

## Examples

`setup` copies these into `~/.waddlebag/tasks/examples/`. Copy one up into `~/.waddlebag/tasks/` to use it.

| Example | What it does |
|---|---|
| [todo-triage](src/waddlebag/examples/todo-triage.md?plain=1) | Lists the five TODO comments most worth fixing |
| [docs-check](src/waddlebag/examples/docs-check.md?plain=1) | Finds places where the README no longer matches the code |
| [write-tests](src/waddlebag/examples/write-tests.md?plain=1) | Writes tests for the least-tested file |
| [run-skill](src/waddlebag/examples/run-skill.md?plain=1) | Runs one of your own Claude Code skills |
| [review-commits](src/waddlebag/examples/review-commits.md?plain=1) | Pipes the latest commits to Claude for review |
| [own-agent](src/waddlebag/examples/own-agent.md?plain=1) | Hands the job to a program of your own instead of Claude |

## Good to know

- **Jobs can only read, by default.** Nobody is there to click "allow", so Claude may only use the tools a job lists. Add `tools: Read, Grep, Glob, Edit, Write` to let a job change files.
- **Your own agent works too.** Add `run: python3 my_agent.py` and the text goes to that command instead of Claude Code.
- **The computer must be awake.** The schedule does not run while a Mac sleeps.

Everything else is in the [reference](docs/reference.md).

## License

[MIT](LICENSE)
