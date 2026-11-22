---
# Finds places where the README no longer matches the code.
when: behind
in: ~/path/to/your/repo
cooldown: 1d
enabled: false
---
Compare README.md with the code in this repository.

List every place where the README describes something the code no longer does:
commands, options, file paths, or behaviour. Quote the README line and say what
the code does instead. If everything matches, say so in one line.
