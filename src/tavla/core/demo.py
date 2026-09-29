"""``tavla demo``: a playground content repo, filled with example content.

The content ships inside the package (``tavla/demo_content``). It was written
as if today were ``ANCHOR``; every date in it is moved by the same number of
days so that "due in 3 days", "overdue" and "stale" still hold whenever the
demo is created.
"""

from __future__ import annotations

import datetime as dt
import re
import shutil
from pathlib import Path

import tavla
from tavla.core import bootstrap, dates, git_sync
from tavla.core.errors import TavlaError

SOURCE = Path(tavla.__file__).parent / "demo_content"
ANCHOR = dt.date(2026, 9, 28)
MARKER = ".tavla-demo"  # marks a directory `demo --reset` may delete
_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def shift_dates(text: str, days: int) -> str:
    """Move every ``YYYY-MM-DD`` date in ``text`` by ``days``."""

    def move(m: re.Match[str]) -> str:
        try:
            date = dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return m[0]
        return (date + dt.timedelta(days=days)).isoformat()

    return _DATE.sub(move, text)


def exists(dest: Path) -> bool:
    return (dest / MARKER).is_file()


def create(dest: Path, *, reset: bool = False, today: dt.date | None = None) -> None:
    """Copy the demo content to ``dest`` (dates moved to ``today``), git-init
    it and commit. With ``reset``, an earlier demo there is replaced; any
    other existing directory is refused, so nothing real is ever deleted."""
    if dest.exists():
        if not exists(dest):
            raise TavlaError(f"{dest} already exists and isn't a tavla demo; pick another place")
        if not reset:
            raise TavlaError(f"a demo already exists at {dest}; use --reset to start over")
        shutil.rmtree(dest)
    days = ((today or dates.local_today()) - ANCHOR).days
    for src in sorted(SOURCE.rglob("*")):
        if src.is_file():
            target = dest / src.relative_to(SOURCE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(shift_dates(src.read_text(), days))
    (dest / bootstrap.LIBRARY_DIR).mkdir(exist_ok=True)
    (dest / bootstrap.LIBRARY_DIR / ".gitkeep").touch()
    (dest / MARKER).write_text("Created by `tavla demo`. Safe to delete.\n")
    git_sync.init_repo(dest)
    git_sync.commit(dest, "demo: example content")
