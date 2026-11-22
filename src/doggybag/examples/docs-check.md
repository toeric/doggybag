---
# Runs when you are using your weekly quota slower than the week is passing.
when: behind
in: ~/path/to/your/repo
tools: Read, Grep, Glob
cooldown: 1d
---
Compare README.md with the code in this repository.

List every place where the README describes something the code no longer does:
commands, options, file paths, or behaviour. Quote the README line and say what
the code does instead. If everything matches, say so in one line.
