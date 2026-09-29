from __future__ import annotations

import datetime as dt

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import demo
from tavla.core.errors import TavlaError
from tavla.core.store import Content

runner = CliRunner()


def test_shift_dates():
    text = "due: 2026-09-28\n- 2026-02-27 14:10: note\nnot a date: 2026-13-45"
    assert demo.shift_dates(text, 3) == (
        "due: 2026-10-01\n- 2026-03-02 14:10: note\nnot a date: 2026-13-45"
    )


def test_create_moves_dates_to_today(tmp_path, git):
    dest = tmp_path / "demo"
    demo.create(dest, today=demo.ANCHOR + dt.timedelta(days=10))
    content = Content.open(dest)
    task = content.task("book-supervisor-meeting")
    assert task.due == dt.date(2026, 10, 12)  # 2026-10-02 in the source, plus 10 days
    assert git(dest, "status", "--porcelain") == ""
    assert "demo: example content" in git(dest, "log", "--oneline")


def test_create_refuses_to_replace_anything_but_a_demo(tmp_path):
    dest = tmp_path / "notes"
    dest.mkdir()
    (dest / "important.md").write_text("mine")
    with pytest.raises(TavlaError, match="isn't a tavla demo"):
        demo.create(dest, reset=True)
    assert (dest / "important.md").exists()


def test_create_twice_needs_reset(tmp_path):
    dest = tmp_path / "demo"
    demo.create(dest)
    (dest / "scribble.md").write_text("x")
    with pytest.raises(TavlaError, match="--reset"):
        demo.create(dest)
    demo.create(dest, reset=True)
    assert not (dest / "scribble.md").exists()


def test_cli_demo(tmp_path):
    dest = tmp_path / "demo"
    result = runner.invoke(app, ["demo", str(dest)])
    assert result.exit_code == 0, result.output
    assert f"export TAVLA_CONTENT_DIR={dest}" in result.output
    again = runner.invoke(app, ["demo", str(dest)])
    assert "already set up" in again.output
    # Write commands work in the demo.
    done = runner.invoke(app, ["--content-dir", str(dest), "task", "done", "draft-methods"])
    assert done.exit_code == 0, done.output
