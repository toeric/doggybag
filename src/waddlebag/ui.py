"""How waddlebag talks: the penguin beside a few lines of text, plus colours and quota bars.

When the output is not a terminal (a log file, a pipe) everything falls back to plain text.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import mascot

_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34", "orange": "38;5;214"}
BAR_CELLS = 10


def _wants_decoration(stream) -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("WADDLEBAG_PLAIN"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def short(path: str | Path) -> str:
    """Show a path with ~ for the home folder."""
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text == home or text.startswith(home + os.sep) else text


class UI:
    def __init__(self, write=None, fancy: bool | None = None, mascot_on: bool = True):
        stream = sys.stdout
        self._write = write or (lambda text: print(text, file=stream))
        self.fancy = _wants_decoration(stream) if fancy is None else fancy
        self.mascot_on = self.fancy and mascot_on
        self.truecolor = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")

    # -- text styling: no-ops in plain mode -------------------------------------------------
    def _style(self, name: str, text: str) -> str:
        return f"\x1b[{_CODES[name]}m{text}\x1b[0m" if self.fancy else text

    def bold(self, text: str) -> str:
        return self._style("bold", text)

    def dim(self, text: str) -> str:
        return self._style("dim", text)

    def red(self, text: str) -> str:
        return self._style("red", text)

    def green(self, text: str) -> str:
        return self._style("green", text)

    def yellow(self, text: str) -> str:
        return self._style("yellow", text)

    def blue(self, text: str) -> str:
        return self._style("blue", text)

    def bar(self, percent_left: float) -> str:
        filled = max(0, min(BAR_CELLS, round(percent_left / 100 * BAR_CELLS)))
        return self._style("orange", "█" * filled) + self.dim("░" * (BAR_CELLS - filled))

    # -- output ----------------------------------------------------------------------------
    def line(self, text: str = "") -> None:
        self._write(text)

    def say(self, pose: str, *lines: str) -> None:
        """Print the penguin in `pose` with `lines` beside it. Plain mode prints only the lines."""
        if not self.mascot_on:
            for text in lines:
                self._write(text)
            return
        art = mascot.render(pose, self.truecolor)
        height = max(len(art), len(lines))
        art_top = (height - len(art)) // 2
        text_top = (height - len(lines)) // 2
        for row in range(height):
            picture = art[row - art_top] if art_top <= row < art_top + len(art) else " " * mascot.WIDTH
            text = lines[row - text_top] if text_top <= row < text_top + len(lines) else ""
            self._write(f"{picture}  {text}" if text else picture)
        self._write("")
