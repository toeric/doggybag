---
# Runs after an hour with nobody using Claude, if the week is also behind.
when: idle and behind
in: ~/path/to/your/repo

# This task changes files, so it also gets Edit and Write.
tools: Read, Grep, Glob, Edit, Write

cooldown: 1d
timeout: 45m
---
Find the source file in this repository that has the least test coverage.

Write tests for it in the existing tests folder, following the style of the
tests that are already there. Only add or change files inside the tests folder.
End with a list of the files you touched.
