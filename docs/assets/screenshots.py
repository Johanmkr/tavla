"""Screenshots of `tv ui` for the docs. From the repo root:

    uv run python docs/assets/screenshots.py

It opens the app headless on a throwaway `tavla demo` repo, puts the cursor
on a task, and saves tui-wide.svg (120 columns) and tui-narrow.svg (80).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from tavla.core import demo
from tavla.tui.app import TavlaApp

ASSETS = Path(__file__).parent
SHOTS = {"tui-wide.svg": (120, 34), "tui-narrow.svg": (80, 24)}
TASK = "run-baseline"


async def shoot(root: Path, name: str, size: tuple[int, int]) -> None:
    app = TavlaApp(root)
    app.title = "tv ui"
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        app.jump_to(TASK)
        await pilot.pause()
        await pilot.press("l")  # into the task column: the preview shows the task
        await pilot.pause(0.5)
        app.save_screenshot(name, path=str(ASSETS))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "demo"
        demo.create(root)
        for name, size in SHOTS.items():
            asyncio.run(shoot(root, name, size))
            print(f"wrote {ASSETS / name}")


if __name__ == "__main__":
    main()
