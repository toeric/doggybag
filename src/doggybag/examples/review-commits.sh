#!/bin/bash
# doggybag:
#   when: leftover
#   cooldown: 6h
#   timeout: 30m

# A script, for when one prompt is not enough.
# This one collects the latest commits itself, hands them to Claude,
# and saves the answer where you will find it.
set -euo pipefail

cd "$HOME/path/to/your/repo"
mkdir -p "$HOME/doggybag-reports"
report="$HOME/doggybag-reports/review-$(date +%Y-%m-%d).md"

git log -3 --patch | claude -p "Review these commits. List anything that looks risky, with the file and line." > "$report"

echo "saved to $report"
