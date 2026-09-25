from __future__ import annotations

import datetime as dt

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core.dates import local_today
from tavla.core.errors import EXIT_ERROR, EXIT_INVALID, EXIT_NOT_FOUND
from tavla.core.store import Content

runner = CliRunner()


@pytest.fixture
def run(git_content):
    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(git_content), *args])

    return _run


def _head(git, repo) -> str:
    return git(repo, "log", "-1", "--format=%s").strip()


def test_project_add(run, git_content, git):
    result = run("project", "add", "Thesis writing", "--priority", "high", "--tags", "phd, writing")
    assert result.exit_code == 0, result.output
    assert "Added project thesis-writing" in result.output
    project = Content.open(git_content).project("thesis-writing")
    assert project.tags == ["phd", "writing"]
    assert _head(git, git_content) == "project: add thesis-writing"


def test_project_add_invalid_priority(run):
    assert run("project", "add", "X", "--priority", "urgent").exit_code != 0


def test_task_add(run, git_content, git):
    result = run(
        "task", "add", "Fix sampler bug", "-p", "project-a", "--due", "tomorrow", "--id", "sampler"
    )
    assert result.exit_code == 0, result.output
    assert "Added task sampler to project-a" in result.output
    task = Content.open(git_content).task("sampler")
    assert task.due == local_today() + dt.timedelta(days=1)
    assert _head(git, git_content) == "task: add sampler"


def test_task_add_requires_project(run):
    result = run("task", "add", "Orphan")
    assert result.exit_code != 0
    assert "--project" in result.output


def test_task_add_unknown_project(run):
    assert run("task", "add", "X", "-p", "nope").exit_code == EXIT_NOT_FOUND


def test_task_add_bad_due(run):
    result = run("task", "add", "X", "-p", "project-a", "--due", "someday")
    assert result.exit_code == EXIT_INVALID
    assert "invalid date" in result.output


def test_task_edit(run, git_content, git, editor):
    calls = editor(("status: doing", "status: blocked"))
    result = run("task", "edit", "write-i")
    assert result.exit_code == 0, result.output
    assert "Saved task write-intro" in result.output
    assert calls.read_text().strip().endswith("write-intro.md")
    assert Content.open(git_content).task("write-intro").status == "blocked"
    assert _head(git, git_content) == "task: edit write-intro"


def test_task_edit_no_changes(run, git_content, git, editor):
    editor()
    result = run("task", "edit", "write-intro")
    assert "No changes." in result.output
    assert _head(git, git_content) == "initial"


def test_task_edit_invalid_is_restored_without_tty(run, git_content, git, editor):
    path = git_content / "projects/project-a/tasks/write-intro.md"
    before = path.read_text()
    editor(("status: doing", "status: wip"))
    result = run("task", "edit", "write-intro")
    assert result.exit_code == EXIT_INVALID
    assert "restored" in result.output
    assert path.read_text() == before
    assert _head(git, git_content) == "initial"


def test_project_edit(run, git_content, git, editor):
    editor(("priority: low", "priority: high"))
    result = run("project", "edit", "project-b")
    assert result.exit_code == 0, result.output
    assert Content.open(git_content).project("project-b").priority == "high"
    assert _head(git, git_content) == "project: edit project-b"


def test_missing_editor(run, monkeypatch):
    monkeypatch.setenv("EDITOR", "definitely-not-an-editor-xyz")
    result = run("task", "edit", "write-intro")
    assert result.exit_code == EXIT_ERROR
    assert "editor not found" in result.output


def test_init_then_add_end_to_end(tmp_path, git):
    content = tmp_path / "fresh"
    assert runner.invoke(app, ["init", "--content-dir", str(content)]).exit_code == 0
    base = ["--content-dir", str(content)]
    assert runner.invoke(app, [*base, "project", "add", "First project"]).exit_code == 0
    assert runner.invoke(app, [*base, "task", "add", "First task", "-p", "first"]).exit_code == 0
    assert git(content, "log", "--format=%s").splitlines() == [
        "task: add first-task",
        "project: add first-project",
        "init: content repo",
    ]
    listing = runner.invoke(app, [*base, "task", "list"]).output
    assert "first-task" in listing
