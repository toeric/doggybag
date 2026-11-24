---
# Writes tests for the least-tested file. Allowed to change files.
when: idle and behind
in: ~/path/to/your/repo
access: edit
cooldown: 1d
timeout: 45m
enabled: false
---
Find the source file in this repository that has the least test coverage.

Write tests for it in the existing tests folder, following the style of the
tests that are already there. Only add or change files inside the tests folder.
End with a list of the files you touched.
