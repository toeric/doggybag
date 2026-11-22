"""桌面通知。目前只支援 macOS；其他平台靜靜略過。"""

from __future__ import annotations

import subprocess
import sys

_SCRIPT = [
    "-e", "on run argv",
    "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
    "-e", "end run",
]


def notify(message: str, title: str = "doggybag") -> None:
    if sys.platform != "darwin":
        return
    try:
        # 文字用參數傳入，不拼進 AppleScript 字串
        subprocess.run(
            ["osascript", *_SCRIPT, message, title],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
