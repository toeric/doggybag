#!/bin/bash
# doggybag:
#   when: 5h.resets_in <= 60m and 5h.remaining >= 30
#   cooldown: 5h
#   timeout: 30m

# 範本 A：用 Claude Code 跑一段 prompt。
#
# doggybag 觸發時沒有人在電腦前，Claude 沒辦法問你「可以嗎」，
# 所以要用 --allowedTools 事先列出這個 task 可以用的工具。
# 下面只開放讀檔和搜尋；需要改檔案時再加上 Edit、Write，並限制在特定 repo 裡跑。
set -euo pipefail

cd "$HOME/path/to/your/repo"

claude -p "Review the three most recent commits and list anything that looks risky." \
  --allowedTools "Read" "Grep" "Glob"
