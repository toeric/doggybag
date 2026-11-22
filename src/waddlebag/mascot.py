"""The penguin.

Each pose is a small pixel drawing. A terminal cell is about twice as tall as it is wide,
so one cell shows two pixels, one above the other, using a half-block character whose
foreground and background colours are set separately.
"""

from __future__ import annotations

WIDTH = 20

# one letter per colour; '.' is transparent
PALETTE = {
    "F": (74, 163, 223),
    "G": (201, 206, 214),
    "H": (169, 113, 58),
    "K": (40, 34, 30),
    "N": (70, 82, 110),
    "O": (245, 160, 60),
    "P": (255, 140, 160),
    "R": (232, 93, 76),
    "S": (47, 127, 192),
    "W": (255, 244, 224),
    "Y": (255, 217, 90),
    "Z": (140, 170, 220),
    "f": (207, 234, 255),
}

SPRITES = {
    # a job finished, or setup went well
    "happy": (
        "...R.....Y......P...",
        ".Z....NNNNNNNN....Y.",
        ".....NNNNNNNNNN.R...",
        "..Y.NNWWWNNWWWNN..Z.",
        "....NWWKWWWWKWWN....",
        "....NWKWKWWKWKWN....",
        ".N..NWPWWOOWWPWN..N.",
        ".NN.NNWWWOOWWWNN.NN.",
        "..NNNWWWWWWWWWWNNN..",
        "....NWWWWWWWWWWN....",
        ".....NWWWWWWWWN.....",
        "......NWWWWWWN......",
        ".....OOO....OOO.....",
        "....................",
    ),
    # reading the quota
    "look": (
        "....................",
        "......NNNNNGGGN.....",
        ".....NNNNNGfffG.....",
        "....NNWWWGWffffG....",
        "....NWWKWGffKKfG....",
        "....NWWWOGffKKfG....",
        "....NNWWOOGfffGH....",
        "....NWWWWWWGGGNHH...",
        "...NNWWWWWWWWWWNHH..",
        "..NNNWWWWWWWWWWNNHH.",
        "..NN.NWWWWWWWWN.NNN.",
        "......NWWWWWWN......",
        ".....OOO....OOO.....",
        "....................",
    ),
    # starting a job: a fish carried home by the tail
    "fish": (
        "....................",
        "....NNNNNNNN........",
        "...NNNNNNNNNN.......",
        "..NNWWWNNWWWNN......",
        "..NWWKWWWWKWWN......",
        "..NWPWWOOWWPWN..S.S.",
        "..NNWWWOOWWWNNNNNS..",
        ".NNNWWWWWWWWNNN..F..",
        "NNNWWWWWWWWWWN..FFF.",
        "NN.NWWWWWWWWN...FfF.",
        "...NWWWWWWWWN...FKF.",
        "....NWWWWWWN.....F..",
        "...OOO....OOO.......",
        "....................",
    ),
    # nothing to do
    "sleep": (
        "....................",
        ".............ZZZ....",
        "..............Z.....",
        ".............ZZZ....",
        "..........ZZ........",
        "...........Z........",
        ".......NNNNNN.......",
        ".....NNNNNNNNNN.....",
        "...NNNWWWNNWWWNNN...",
        ".NNNNWKKWWWWKKWNNNN.",
        "NNNNNWWWWOOWWWWNNNNN",
        ".OO.NNWWWOOWWWNN.OO.",
    ),
    # something went wrong
    "sad": (
        "....................",
        "......NNNNNNNN......",
        ".....NNNNNNNNNN.....",
        "....NNWWWNNWWWNN....",
        "....NWKKWWWWKKWN....",
        "....NWZWWOOWWZWN....",
        "....NNZWWOOWWZNN....",
        "....NWZWWWWWWZWN....",
        "...NNWZWWWWWWZWNN...",
        "...NNWZWWWWWWZWNN...",
        "...N.NZWWWWWWZN.N...",
        "......NWWWWWWN......",
        "..ZZZZOOOZZZZOOOZZ..",
        "...ZZZZZZZZZZZZZZ...",
    ),
    # a job had to be dropped
    "alarm": (
        "....................",
        ".Z....NNNNNNNN....Z.",
        ".....NNNNNNNNNN.....",
        "..Z.NNWWWNNWWWNN.Z..",
        "....NWKWWWWWWKWN....",
        "NN..NWWKWWWWKWWN..NN",
        "NNN.NWKWWOOWWKWN.NNN",
        ".NNNNNWWWOOWWWNNNNN.",
        "...NNWWWWWWWWWWNN...",
        "....NWWWWWWWWWWN....",
        ".....NWWWWWWWWN.....",
        "......NWWWWWWN......",
        "....OOO......OOO....",
        "....................",
    ),
}

_RESET = "\x1b[0m"


def _code(rgb: tuple[int, int, int], background: bool, truecolor: bool) -> str:
    kind = 48 if background else 38
    if truecolor:
        return f"\x1b[{kind};2;{rgb[0]};{rgb[1]};{rgb[2]}m"
    # fall back to the 6x6x6 colour cube that 256-colour terminals share
    r, g, b = (round(v / 255 * 5) for v in rgb)
    return f"\x1b[{kind};5;{16 + 36 * r + 6 * g + b}m"


def render(name: str, truecolor: bool = True) -> list[str]:
    """Return the pose as terminal lines, two pixel rows per line."""
    grid = SPRITES[name]
    out = []
    for y in range(0, len(grid), 2):
        line = ""
        for top_char, bottom_char in zip(grid[y], grid[y + 1]):
            top, bottom = PALETTE.get(top_char), PALETTE.get(bottom_char)
            if top is None and bottom is None:
                line += " "
            elif bottom is None:
                line += _code(top, False, truecolor) + "\u2580" + _RESET
            elif top is None:
                line += _code(bottom, False, truecolor) + "\u2584" + _RESET
            else:
                line += _code(top, False, truecolor) + _code(bottom, True, truecolor) + "\u2580" + _RESET
        out.append(line)
    return out
