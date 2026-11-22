"""Desktop notifications. macOS only for now; other platforms are skipped silently."""

from __future__ import annotations

import subprocess
import sys

_SCRIPT = [
    "-e", "on run argv",
    "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
    "-e", "end run",
]


def notify(message: str, title: str = "waddlebag") -> None:
    if sys.platform != "darwin":
        return
    try:
        # pass the text as arguments, never spliced into the AppleScript source
        subprocess.run(
            ["osascript", *_SCRIPT, message, title],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
