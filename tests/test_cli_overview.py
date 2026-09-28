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
    lines = result.output.splitlines()
    rows = lines[1:4]
    assert [r.split()[0] for r in rows] == [
        "draft-related-work",
        "wait-for-cluster-allocation",
        "fix-plot-colors",
    ]
    assert "(in 6d)" in rows[0] and "1/2" in rows[0] and "write-intro" in rows[0]
    assert "get-feedback" not in result.output  # waiting on draft-related-work
    assert "Goals with no tasks yet (1)" in result.output
    assert "write-methods  [med]  [project-a]  Write methods section  due 2026-10-15" in (
        result.output
    )


def test_next_limit(run):
    result = run("next", "-n", "1")
    assert "fix-plot-colors" not in result.output
    assert "2 more" in result.output


def test_next_filters(run):
    assert "fix-plot-colors" not in run("next", "--priority", "med").output
    out = run("next", "-p", "project-b").output
    assert "No open tasks." in out and "write-review" in out


def test_next_json(run):
    data = json.loads(run("next", "--json").output)
    assert data["tasks"][0]["id"] == "draft-related-work"
    assert [g["id"] for g in data["goals_without_tasks"]] == ["write-methods"]


def test_next_nothing(run):
    assert "Nothing to do." in run("next", "-p", "project-c").output


def test_status(run):
    result = run("status")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "tavla status — 2026-09-25" in out
    assert "2 active projects · 4 open tasks (0 doing) · 0 blocked" in out
    assert "ablations  last activity 2026-08-01 (55d ago)" in out
    assert "get-feedback-from-advisor  [project-a]  Get feedback from advisor  (after draft" in out
    assert "write-intro  2026-10-01 (in 6d)  [project-a]  1/3 tasks" in out
    assert "draft-related-work  2026-10-01 (in 6d)" in out
    assert "Deliverable deadlines within 30 days (0)" in out
    assert "2 ideas in the inbox" in out


def test_status_deadline_days(run):
    assert "neurips-paper  2027-05-15 (in 232d)" in run("status", "--deadline-days", "365").output


def test_status_json(run):
    data = json.loads(run("status", "--json").output)
    assert data["today"] == "2026-09-25"
    assert data["stale"][0]["project"]["id"] == "ablations"
    assert data["waiting"][0]["id"] == "get-feedback-from-advisor"
    assert data["inbox"] == 2
