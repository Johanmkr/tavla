from __future__ import annotations

import datetime as dt
import json

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.cli.overview import relative

runner = CliRunner()
TODAY = dt.date(2026, 9, 25)


@pytest.fixture
def run(basic_content, monkeypatch):
    monkeypatch.setattr("tavla.core.dates.local_today", lambda: TODAY)

    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(basic_content), *args])

    return _run


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        (TODAY, "2026-09-25 (today)"),
        (dt.date(2026, 10, 1), "2026-10-01 (in 6d)"),
        (dt.date(2026, 9, 22), "2026-09-22 (3d overdue)"),
        (None, "-"),
    ],
)
def test_relative(date, expected):
    assert relative(date, TODAY) == expected


def test_next(run):
    result = run("next")
    assert result.exit_code == 0, result.output
    rows = result.output.splitlines()[1:]
    assert [r.split()[0] for r in rows] == ["write-intro", "write-methods"]
    assert "(in 6d)" in rows[0] and "1/3" in rows[0]


def test_next_limit(run):
    result = run("next", "-n", "1")
    assert "write-methods" not in result.output
    assert "1 more" in result.output


def test_next_filters(run):
    assert "write-methods" not in run("next", "--priority", "high").output
    assert "write-review" in run("next", "-p", "project-b").output


def test_next_json(run):
    data = json.loads(run("next", "--json").output)
    assert [t["id"] for t in data] == ["write-intro", "write-methods"]


def test_next_nothing(run):
    assert "Nothing to do." in run("next", "-p", "project-c").output


def test_status(run):
    result = run("status")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "tavla status — 2026-09-25" in out
    assert "2 active projects · 2 open tasks (1 doing) · 1 blocked" in out
    assert "ablations  last activity 2026-08-01 (55d ago)" in out
    assert "run-ablations" in out
    assert "write-intro  2026-10-01 (in 6d)" in out
    assert "Deliverable deadlines within 30 days (0)" in out


def test_status_deadline_days(run):
    assert "neurips-paper  2027-05-15 (in 232d)" in run("status", "--deadline-days", "365").output


def test_status_json(run):
    data = json.loads(run("status", "--json").output)
    assert data["today"] == "2026-09-25"
    assert data["stale"][0]["project"]["id"] == "ablations"
    assert data["blocked"][0]["id"] == "run-ablations"
