#!/usr/bin/env python3
"""A stand-in for your own agent. It shows what doggybag hands to a `run:` command.

Only work that goes through the logged-in `claude` command uses your
subscription quota. A program that uses an API key is billed separately,
so triggering it does not use up what is left.

What the command receives:
  standard input            the text below the settings in the task file
  the working directory     the folder after `in:`
  DOGGYBAG_TASK             the task file's name
  DOGGYBAG_REASON           why it was triggered
  DOGGYBAG_5H_REMAINING     percent left in the 5-hour window
  DOGGYBAG_WEEK_REMAINING   percent left in the week
  DOGGYBAG_5H_RESETS_AT     when the 5-hour window resets (epoch seconds)
  DOGGYBAG_WEEK_RESETS_AT   when the week resets (epoch seconds)

What it reports back, through its exit code:
  0      done
  75     nothing to do right now (not a failure, and no cooldown)
  other  failed

If quota falls below the reserve, or the timeout passes, doggybag sends
SIGTERM and force-stops the command 30 seconds later.
"""

import os
import sys

instructions = sys.stdin.read()

print(f"task: {os.environ.get('DOGGYBAG_TASK')}")
print(f"triggered because: {os.environ.get('DOGGYBAG_REASON')}")
print(f"working in: {os.getcwd()}")
print(f"weekly quota left: {os.environ.get('DOGGYBAG_WEEK_REMAINING')}%")
print(f"instructions: {instructions.strip()}")

# Call your own agent here, passing it `instructions`.
sys.exit(75)
