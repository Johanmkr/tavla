"""Milestone 5: capture, log, task done — core ops and CLI."""

from __future__ import annotations

import datetime as dt

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import ops
from tavla.core.entities import TaskStatus
from tavla.core.errors import EXIT_INVALID, EXIT_NOT_FOUND, ValidationError
from tavla.core.store import Content

runner = CliRunner()
TODAY = dt.date(2026, 9, 25)
NOW = dt.datetime(2026, 9, 25, 14, 5)  # noqa: DTZ001 — log.md stores naive local time


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


@pytest.fixture
def run(git_content, monkeypatch):
    monkeypatch.setattr("tavla.core.dates.local_today", lambda: TODAY)
    monkeypatch.setattr("tavla.core.dates.local_now", lambda: NOW)

    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(git_content), *args])

    return _run


def _head(git, repo) -> str:
    return git(repo, "log", "-1", "--format=%s").strip()


def _clean(git, repo) -> bool:
    return git(repo, "status", "--porcelain") == ""


# --- capture -------------------------------------------------------------------


def test_capture_appends_and_commits(content, git):
    ops.capture(content, "  Try\n  tempering   ")
    assert (
        (content.root / "inbox.md")
        .read_text()
        .endswith("- Email advisor about the conference budget\n- Try tempering\n")
    )
    assert [i.text for i in content.inbox()][-1] == "Try tempering"
    assert _head(git, content.root) == "inbox: capture Try tempering"
    assert _clean(git, content.root)


def test_capture_handles_missing_trailing_newline(content):
    (content.root / "inbox.md").write_text("# Inbox\n- a")
    ops.capture(content, "b")
    assert (content.root / "inbox.md").read_text() == "# Inbox\n- a\n- b\n"


def test_capture_recreates_missing_inbox(content):
    (content.root / "inbox.md").unlink()
    ops.capture(content, "x")
    assert (content.root / "inbox.md").read_text() == "# Inbox\n\n- x\n"


def test_capture_long_text_truncated_in_commit_only(content, git):
    text = "word " * 30
    ops.capture(content, text)
    subject = _head(git, content.root)
    assert subject.endswith("…") and len(subject) <= len("inbox: capture ") + 50
    assert text.strip() in (content.root / "inbox.md").read_text()


def test_capture_empty_rejected(content):
    with pytest.raises(ValidationError):
        ops.capture(content, "   ")


def test_cli_capture_joins_words(run, git_content, git):
    result = run("capture", "read", "the", "NUTS", "paper")
    assert result.exit_code == 0, result.output
    assert "Captured: read the NUTS paper" in result.output
    assert (git_content / "inbox.md").read_text().endswith("- read the NUTS paper\n")


# --- log -----------------------------------------------------------------------


def test_append_log(content, git):
    project = content.project("project-a")
    entry = ops.append_log(content, project, "Sampler converges now", now=NOW)
    assert (entry.date, entry.time) == (TODAY, dt.time(14, 5))
    assert (
        (project.path / "log.md")
        .read_text()
        .endswith("- 2026-09-25 14:05: Sampler converges now\n")
    )
    assert content.log(project)[-1].text == "Sampler converges now"
    assert _head(git, content.root) == "log: project-a: Sampler converges now"
    assert _clean(git, content.root)


def test_append_log_creates_file_for_subproject(content):
    project = content.project("ablations")
    assert not (project.path / "log.md").exists()
    ops.append_log(content, project, "first", now=NOW)
    assert (project.path / "log.md").read_text() == "# Log\n\n- 2026-09-25 14:05: first\n"


def test_log_counts_as_activity_for_status(content):
    from tavla.core import queries

    ops.append_log(content, content.project("ablations"), "back on it", now=NOW)
    content.refresh()
    assert queries.status(content, today=TODAY).stale == []


def test_cli_log(run, git_content):
    result = run("log", "abl", "grid", "running")
    assert result.exit_code == 0, result.output
    assert "Logged to ablations: grid running" in result.output


def test_cli_log_unknown_project(run):
    assert run("log", "nope", "x").exit_code == EXIT_NOT_FOUND


def test_cli_log_requires_text(run):
    assert run("log", "project-a").exit_code != 0


# --- task done -------------------------------------------------------------------


def test_complete_task_edits_only_status_and_updated(content, git):
    task = content.task("write-intro")
    before = task.path.read_text()
    done = ops.complete_task(content, task, today=TODAY)
    assert done.status == TaskStatus.DONE
    assert done.updated == TODAY
    after = task.path.read_text()
    changed = [
        (a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b
    ]
    assert changed == [
        ("status: doing", "status: done"),
        ("updated: 2026-09-20", "updated: 2026-09-25"),
    ]
    assert _head(git, content.root) == "task: done write-intro"
    assert _clean(git, content.root)


def test_complete_task_already_done_is_noop(content, git):
    assert ops.complete_task(content, content.task("setup-env"), today=TODAY) is None
    assert _head(git, content.root) == "initial"


def test_done_task_leaves_next(content):
    from tavla.core import queries

    ops.complete_task(content, content.task("write-intro"), today=TODAY)
    assert "write-intro" not in [t.id for t in queries.next_tasks(content)]


def test_cli_task_done(run, git_content, git):
    result = run("task", "done", "write-i")
    assert result.exit_code == 0, result.output
    assert "Done: write-intro (Write introduction section)" in result.output
    assert "2 of 3 subtasks were still unchecked" in result.output
    assert _head(git, git_content) == "task: done write-intro"


def test_cli_task_done_twice(run):
    run("task", "done", "write-intro")
    result = run("task", "done", "write-intro")
    assert result.exit_code == 0
    assert "already done" in result.output


def test_cli_task_done_ambiguous(run):
    assert run("task", "done", "write-").exit_code == EXIT_INVALID


# --- the Tier 1 definition of done, end to end ------------------------------------


def test_tier1_end_to_end(tmp_path, git):
    content = tmp_path / "c"

    def tavla(*args):
        result = runner.invoke(app, ["--content-dir", str(content), *args])
        assert result.exit_code == 0, result.output
        return result.output

    tavla("init")
    tavla("capture", "idea: adaptive tempering")
    tavla("project", "add", "Thesis", "--priority", "high")
    tavla("task", "add", "Draft chapter 1", "-p", "thesis", "--priority", "high", "--id", "ch1")
    tavla("task", "add", "Draft chapter 2", "-p", "thesis", "--id", "ch2")
    assert tavla("next").splitlines()[1].startswith("ch1")
    tavla("log", "thesis", "outline agreed with advisor")
    tavla("task", "done", "ch1")
    assert [line.split()[0] for line in tavla("next").splitlines()[1:]] == ["ch2"]
    assert git(content, "log", "--format=%s").splitlines() == [
        "task: done ch1",
        "log: thesis: outline agreed with advisor",
        "task: add ch2",
        "task: add ch1",
        "project: add thesis",
        "inbox: capture idea: adaptive tempering",
        "init: content repo",
    ]
    assert git(content, "status", "--porcelain") == ""
