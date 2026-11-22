---
# `run:` replaces Claude with a command of your own.
# This one collects the latest commits itself and pipes them to Claude.
when: leftover
in: ~/path/to/your/repo
run: git log -3 --patch | claude -p "Review these commits. List anything that looks risky, with the file and line."
cooldown: 6h
---
