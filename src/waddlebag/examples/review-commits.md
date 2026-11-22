---
# Uses run: to collect the latest commits and pipe them to Claude for review.
when: leftover
in: ~/path/to/your/repo
run: git log -3 --patch | claude -p "Review these commits. List anything that looks risky."
cooldown: 6h
enabled: false
---
