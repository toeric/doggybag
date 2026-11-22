---
# Runs one of your own Claude Code skills.
# A skill lives in .claude/skills/<name>/SKILL.md in the repo, or in ~/.claude/skills/.
when: idle
in: ~/path/to/your/repo
tools: Read, Grep, Glob
cooldown: 12h
---
/my-skill
