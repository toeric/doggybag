---
# Uses run: to hand the text below to a program of your own.
when: week.resets_in <= 1d and week.remaining >= 40
in: ~/path/to/your/repo
run: python3 ~/agents/my_agent.py
cooldown: 1d
enabled: false
---
Find the TODO comments in this repository and pick the five most worth fixing.
