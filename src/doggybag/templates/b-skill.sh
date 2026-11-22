#!/bin/bash
# doggybag:
#   when: idle and behind
#   cooldown: 12h
#   timeout: 45m

# 範本 B：跑你自己寫的 Claude Code skill。
#
# skill 放在 repo 的 .claude/skills/<name>/SKILL.md，或 ~/.claude/skills/ 底下。
# 把 /my-skill 換成你的 skill 名稱。
set -euo pipefail

cd "$HOME/path/to/your/repo"

claude -p "/my-skill" --allowedTools "Read" "Grep" "Glob"
