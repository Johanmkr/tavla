"""Catppuccin (Mocha) colours for task terminals (``tv work -t``).

Each task gets one of the accents, picked from a hash of its id so it keeps
the same colour every time; ``colour: mauve`` in the task's frontmatter
(``tv task edit ID --colour mauve``) picks one by hand.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

ACCENTS = {
    "rosewater": "#f5e0dc",
    "flamingo": "#f2cdcd",
    "pink": "#f5c2e7",
    "mauve": "#cba6f7",
    "red": "#f38ba8",
    "maroon": "#eba0ac",
    "peach": "#fab387",
    "yellow": "#f9e2af",
    "green": "#a6e3a1",
    "teal": "#94e2d5",
    "sky": "#89dceb",
    "sapphire": "#74c7ec",
    "blue": "#89b4fa",
    "lavender": "#b4befe",
}
BASE = "#1e1e2e"
TEXT = "#cdd6f4"
# How much of the accent goes into the background: enough to tell windows
# apart at a glance, little enough that text stays readable.
TINT = 0.16


@dataclass(frozen=True)
class Scheme:
    name: str
    accent: str  # cursor, selection, tab
    background: str  # the accent blended into the Catppuccin base
    foreground: str = TEXT


def default_name(task_id: str) -> str:
    """The accent a task gets when it doesn't name one: stable across runs."""
    names = list(ACCENTS)
    return names[hashlib.sha1(task_id.encode()).digest()[0] % len(names)]


def blend(colour: str, onto: str, amount: float) -> str:
    """``amount`` of ``colour`` over ``onto`` (both ``#rrggbb``)."""
    a = [int(colour[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(onto[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))


def scheme(task_id: str, name: str | None = None) -> Scheme:
    name = name or default_name(task_id)
    accent = ACCENTS[name]
    return Scheme(name, accent, blend(accent, BASE, TINT))
