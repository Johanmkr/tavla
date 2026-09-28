"""Capture, log, and the goal/task lifecycle (start, done) — core ops and CLI."""

from __future__ import annotations

import datetime as dt

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import ideas, ops
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


def _capture(content, text):
    return ideas.add(content, ideas.scope_of(content, None), text)


# --- capture -------------------------------------------------------------------


def test_capture_appends_and_commits(content, git):
    _capture(content, "  Try\n  tempering   ")
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
    _capture(content, "b")
    assert (content.root / "inbox.md").read_text() == "# Inbox\n- a\n- b\n"


def test_capture_recreates_missing_inbox(content):
    (content.root / "inbox.md").unlink()
    _capture(content, "x")
    assert (content.root / "inbox.md").read_text() == "# Inbox\n\n- x\n"


def test_capture_long_text_truncated_in_commit_only(content, git):
    text = "word " * 30
    _capture(content, text)
    subject = _head(git, content.root)
    assert subject.endswith("…") and len(subject) <= len("inbox: capture ") + 50
    assert text.strip() in (content.root / "inbox.md").read_text()


def test_capture_empty_rejected(content):
    with pytest.raises(ValidationError):
        _capture(content, "   ")


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


# --- done -----------------------------------------------------------------------


def test_complete_edits_only_status_and_updated(content, git):
    goal = content.goal("write-intro")
    before = goal.path.read_text()
    done = ops.complete(content, goal, today=TODAY)
    assert done.status == TaskStatus.DONE
    assert done.updated == TODAY
    after = goal.path.read_text()
    changed = [
        (a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b
    ]
    assert changed == [
        ("status: doing", "status: done"),
        ("updated: 2026-09-20", "updated: 2026-09-25"),
    ]
    assert _head(git, content.root) == "goal: done write-intro"
    assert _clean(git, content.root)


def test_complete_already_done_is_noop(content, git):
    assert ops.complete(content, content.task("outline-structure"), today=TODAY) is None
    assert _head(git, content.root) == "initial"


def test_done_task_leaves_next_and_unblocks_dependents(content):
    from tavla.core import queries

    ops.complete(content, content.task("draft-related-work"), today=TODAY)
    ids = [t.id for t in queries.next_tasks(content)]
    assert "draft-related-work" not in ids
    assert "get-feedback-from-advisor" in ids


def test_cli_task_done(run, git_content, git):
    result = run("task", "done", "draft-r")
    assert result.exit_code == 0, result.output
    assert "Done: draft-related-work (Draft related work)" in result.output
    assert "1 of 2 subtasks were still unchecked" in result.output
    assert "Now unblocked: get-feedback-from-advisor" in result.output
    assert _head(git, git_content) == "task: done draft-related-work"


def test_cli_task_done_twice(run):
    run("task", "done", "fix-plot-colors")
    result = run("task", "done", "fix-plot-colors")
    assert result.exit_code == 0
    assert "already done" in result.output


def test_cli_task_done_ambiguous(run, git_content):
    run("task", "add", "Fix tests", "-p", "project-a")
    assert run("task", "done", "fix-").exit_code == EXIT_INVALID


def test_cli_goal_done_warns_about_open_tasks(run, git_content, git):
    result = run("goal", "done", "write-i")
    assert result.exit_code == 0, result.output
    assert "Done: write-intro (Write introduction section)" in result.output
    assert "2 of 3 tasks are not done" in result.output
    assert _head(git, git_content) == "goal: done write-intro"


# --- the definition of done, end to end -------------------------------------------


def test_end_to_end(tmp_path, git):
    content = tmp_path / "c"

    def tavla(*args):
        result = runner.invoke(app, ["--content-dir", str(content), *args])
        assert result.exit_code == 0, result.output
        return result.output

    tavla("init")
    tavla("capture", "idea: adaptive tempering #mcmc")
    tavla("project", "add", "Thesis", "--priority", "high")
    tavla("goal", "add", "Chapter 1", "-p", "thesis", "--priority", "high", "--id", "ch1")
    tavla("task", "add", "Outline", "-g", "ch1", "--id", "outline")
    tavla("task", "add", "Draft", "-g", "ch1", "--id", "draft", "--after", "out")
    tavla("task", "add", "Renew library card", "-p", "thesis", "--priority", "low", "--id", "card")
    assert [line.split()[0] for line in tavla("next").splitlines()[1:3]] == ["outline", "card"]
    tavla("log", "thesis", "outline agreed with advisor")
    tavla("task", "done", "outline")
    assert tavla("next").splitlines()[1].startswith("draft")
    tavla("idea", "promote", "tempering", "-g", "ch1")
    assert Content.open(content).task("idea-adaptive-tempering").tags == ["mcmc"]
    assert git(content, "log", "--format=%s").splitlines() == [
        "task: add idea-adaptive-tempering",
        "task: done outline",
        "log: thesis: outline agreed with advisor",
        "task: add card",
        "task: add draft",
        "task: add outline",
        "goal: add ch1",
        "project: add thesis",
        "inbox: capture idea: adaptive tempering #mcmc",
        "init: content repo",
    ]
    assert git(content, "status", "--porcelain") == ""


# --- start -----------------------------------------------------------------------


def test_start(content, git):
    started = ops.start(content, content.goal("write-methods"), today=TODAY)
    assert (started.status, started.updated) == (TaskStatus.DOING, TODAY)
    assert _head(git, content.root) == "goal: start write-methods"
    assert _clean(git, content.root)


def test_start_already_doing_is_noop(content, git):
    assert ops.start(content, content.goal("write-intro"), today=TODAY) is None
    assert _head(git, content.root) == "initial"


def test_cli_task_start(run, git_content, git):
    result = run("task", "start", "fix-p")
    assert result.exit_code == 0, result.output
    assert "Started: fix-plot-colors (Fix plot colors) — was todo" in result.output
    assert "already in progress" in run("task", "start", "fix-p").output


def test_cli_task_start_warns_when_waiting(run):
    result = run("task", "start", "get-f")
    assert result.exit_code == 0, result.output
    assert "still waiting on draft-related-work" in result.output


def test_cli_start_reopens_done_task(run, git_content):
    result = run("task", "start", "outline-structure")
    assert "was done" in result.output
    assert Content.open(git_content).task("outline-structure").status == TaskStatus.DOING


def test_cli_goal_start(run, git_content):
    result = run("goal", "start", "write-m")
    assert "Started: write-methods (Write methods section) — was todo" in result.output
