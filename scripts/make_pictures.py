"""Draw the README pictures in assets/ from the penguin in src/waddlebag/mascot.py.

Run it after changing the penguin:  python3 scripts/make_pictures.py
"""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from waddlebag import mascot  # noqa: E402

BG = "#1b1e24"
TEXT = "#d6dae0"
DIM = "#8a909a"
GREEN = "#8fd694"
ORANGE = "#f5a03c"
RED = "#f07178"
BAR_BG = "#3a3f48"
FONT = 'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"'


def hex_color(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def pixels(pose: str, x0: float, y0: float, w: float, h: float, overlap: float = 0.0) -> list[str]:
    """One rect per pixel. A little overlap hides the hairline gaps some viewers draw between rects."""
    out = []
    for y, row in enumerate(mascot.SPRITES[pose]):
        for x, ch in enumerate(row):
            if ch in mascot.PALETTE:
                out.append(
                    f'<rect x="{x0 + x * w:.1f}" y="{y0 + y * h:.1f}" width="{w + overlap:.1f}" '
                    f'height="{h + overlap:.1f}" fill="{hex_color(mascot.PALETTE[ch])}"/>'
                )
    return out


def svg(width: float, height: float, label: str, body: list[str], extra: str = "", radius: int = 12) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" width="{width:g}" '
        f'height="{height:g}" {extra}role="img" aria-label="{escape(label)}">\n'
        f'<rect width="{width:g}" height="{height:g}" rx="{radius}" fill="{BG}"/>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )


def logo() -> str:
    size, pad = 10, 20
    grid = mascot.SPRITES["fish"]
    width, height = mascot.WIDTH * size + 2 * pad, len(grid) * size + 2 * pad
    return svg(
        width, height, "A pixel penguin carrying a fish by the tail",
        pixels("fish", pad, pad, size, size), extra='shape-rendering="crispEdges" ', radius=24,
    )


def poses() -> str:
    names = [("look", "checking"), ("fish", "packing up"), ("happy", "packed!"),
             ("sleep", "nothing to do"), ("sad", "went wrong"), ("alarm", "dropped")]
    size, cell, top = 6, 146, 24
    art_h = len(mascot.SPRITES["happy"]) * size
    body = []
    for i, (pose, caption) in enumerate(names):
        centre = 9 + cell * i + cell / 2
        body += pixels(pose, centre - mascot.WIDTH * size / 2, top, size, size, overlap=0.3)
        body.append(f'<text x="{centre:g}" y="{top + art_h + 24}" fill="{DIM}" text-anchor="middle">{caption}</text>')
    return svg(cell * len(names) + 18, top + art_h + 40, "The six poses of the waddlebag penguin", body,
               extra=f'{FONT} font-size="12" ')


# -- the status screenshot: a tiny terminal --------------------------------------------------------
CW, LH, PAD = 8.4, 18, 22  # character width, line height, margin


def status() -> str:
    body: list[str] = []
    row = 0

    def text(col: float, line: int, s: str, color: str = TEXT) -> None:
        body.append(
            f'<text x="{PAD + col * CW:.1f}" y="{PAD + line * LH + 13:.1f}" fill="{color}" '
            f'xml:space="preserve">{escape(s)}</text>'
        )

    def bar(col: float, line: int, used: int) -> None:
        y = PAD + line * LH + 3
        body.append(f'<rect x="{PAD + col * CW:.1f}" y="{y:.1f}" width="{10 * CW:.1f}" height="12" fill="{BAR_BG}"/>')
        filled = round(used / 10)
        if filled:
            body.append(f'<rect x="{PAD + col * CW:.1f}" y="{y:.1f}" width="{filled * CW:.1f}" height="12" fill="{ORANGE}"/>')

    text(0, row, "$ waddlebag status", DIM)
    row += 2  # the blank line the penguin keeps above its head

    # the penguin block, laid out the way ui.say does it
    art_lines = len(mascot.SPRITES["look"]) // 2
    words = 8
    height = max(art_lines, words)
    art_top, text_top = (height - art_lines) // 2, (height - words) // 2
    body += pixels("look", PAD, PAD + (row + art_top) * LH, CW, LH / 2, overlap=0.3)
    tx = mascot.WIDTH + 2
    text(tx, row + text_top, "checking your quota...")
    for i, (label, used, resets) in enumerate((("5h", 40, "2h55m"), ("week", 5, "6d5h"))):
        line = row + text_top + 2 + i
        text(tx, line, f"{label:<5} ")
        bar(tx + 6, line, used)
        text(tx + 16, line, f" {used:>3}% used")
        text(tx + 26, line, f" · resets in {resets}", DIM)
    text(tx, row + text_top + 4, "quiet for 12m · I check every 10 minutes", DIM)
    text(tx, row + text_top + 5, "I always keep 10% of the 5h window and 5% of the week for you", DIM)
    text(tx, row + text_top + 7, "Last 7 days: 4 tasks done, about 9% of your week")
    row += height + 1  # and the blank line below it

    jobs = [
        ("▶", GREEN, "write-tests", [("running for 12m", GREEN)], None),
        ("○", GREEN, "todo-triage", [("waiting: starts at my next check (within 10 minutes)", GREEN)],
         "5h window resets in 42m (I go at ≤ 1h) · 60% left (I go at ≥ 30%)"),
        ("○", DIM, "docs-check", [("waiting: ran 1h ago, again in 4h", TEXT)],
         "last time (Nov 22 18:50): done in 4m → waddlebag logs docs-check"),
        ("!", RED, "review-commits", [("needs you: it didn't work 3 times in a row", RED)],
         "see why with `waddlebag logs review-commits`, then save the file to try again"),
        ("–", DIM, "old-idea", [("off", TEXT)], None),
    ]
    # every line counts for the width: the words beside the penguin as well as the task lines
    widest = tx + len("I always keep 10% of the 5h window and 5% of the week for you")
    for mark, colour, name, headline, detail in jobs:
        text(0, row, mark, colour)
        text(2, row, name)
        col = 2 + 16
        for part, part_colour in headline:
            text(col, row, part, part_colour)
            col += len(part)
        widest = max(widest, col)
        row += 1
        if detail:
            text(4, row, detail, DIM)
            widest = max(widest, 4 + len(detail))
            row += 1

    width = round(2 * PAD + (widest + 2) * CW)
    height = round(2 * PAD + row * LH - (LH - 13))
    return svg(width, height,
               "Terminal output of waddlebag status: a pixel penguin with a magnifying glass, "
               "two quota bars, and five tasks with their states: running, waiting, needs you and off",
               body, extra=f'{FONT} font-size="14" ')


def main() -> None:
    assets = ROOT / "assets"
    for name, make in (("penguin.svg", logo), ("poses.svg", poses), ("status.svg", status)):
        (assets / name).write_text(make(), encoding="utf-8")
        print(f"wrote assets/{name}")


if __name__ == "__main__":
    main()
