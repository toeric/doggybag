---
# When to run. Use leftover, idle or behind, or write your own (see the README).
when: leftover

# The folder Claude works in.
in: ~/path/to/your/repo

# What Claude may do without asking. Reading and searching only, by default.
tools: Read, Grep, Glob

cooldown: 6h

# Change to true when you are ready.
enabled: false
---
Review the three most recent commits in this repository.
List anything that looks risky, and say which file and line it is in.
