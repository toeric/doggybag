---
# Hands the text below to your own program instead of Claude.
# own-agent.py, next to this file, shows what the program receives.
when: week.resets_in <= 1d and week.remaining >= 40
in: ~/path/to/your/repo
run: python3 ~/.doggybag/tasks/examples/own-agent.py
cooldown: 1d
---
Find the TODO comments in this repository and pick the five most worth fixing.
