---
# Uses run: to hand the text below to a program of your own.
when: week.resets_in <= 1d and week.remaining >= 40
run: python3 ~/agents/my_agent.py
cooldown: 1d
---
Find the TODO comments in this repository and pick the five most worth fixing.
