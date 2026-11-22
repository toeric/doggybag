#!/usr/bin/env python3
# doggybag:
#   when: week.resets_in <= 1d and week.remaining >= 40
#   cooldown: 1d

"""A script that calls your own program instead of Claude Code.

Only work that goes through the logged-in `claude` command uses your
subscription quota. A program that uses an API key is billed separately,
so triggering it does not use up what is left.

doggybag passes these environment variables:
  DOGGYBAG_TASK             this file's name
  DOGGYBAG_REASON           why it was triggered
  DOGGYBAG_5H_REMAINING     percent left in the 5-hour window
  DOGGYBAG_WEEK_REMAINING   percent left in the week
  DOGGYBAG_5H_RESETS_AT     when the 5-hour window resets (epoch seconds)
  DOGGYBAG_WEEK_RESETS_AT   when the week resets (epoch seconds)

Exit code:
  0      done
  75     nothing to do right now (not a failure, and no cooldown)
  other  failed

If quota falls below the reserve, or the timeout passes, doggybag sends
SIGTERM and force-stops the program 30 seconds later.
"""

import os
import sys

remaining = int(os.environ.get("DOGGYBAG_WEEK_REMAINING", "0"))
print(f"triggered because: {os.environ.get('DOGGYBAG_REASON')}")
print(f"weekly quota left: {remaining}%")

# Call your own agent here.
sys.exit(75)
