---
# When to run: leftover, idle or behind (or your own numbers, see the README).
when: leftover

# The folder Claude works in.
in: ~/path/to/your/repo

# What Claude may do without asking. This task only reads.
tools: Read, Grep, Glob

cooldown: 6h

# Change to true when you are ready.
enabled: false
---
Find the TODO and FIXME comments in this repository.

Pick the five that are most worth fixing. For each one, give the file and line,
say in one sentence what is wrong, and say how much work a fix would be.
