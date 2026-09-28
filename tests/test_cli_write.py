from __future__ import annotations

import datetime as dt

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import parsing
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
    assert "Added task sampler to project project-a" in result.output
    task = Content.open(git_content).task("sampler")
    assert task.due == local_today() + dt.timedelta(days=1)
    assert _head(git, git_content) == "task: add sampler"


def test_task_add_to_goal_with_deps(run, git_content):
    result = run("task", "add", "Polish", "-g", "write-i", "--after", "draft-r,get-f")
    assert result.exit_code == 0, result.output
    assert "Added task polish to goal write-intro" in result.output
    task = Content.open(git_content).task("polish")
    assert task.depends_on == ["draft-related-work", "get-feedback-from-advisor"]


def test_task_add_requires_goal_or_project(run):
    result = run("task", "add", "Orphan")
    assert result.exit_code != 0
    assert "-g" in result.output and "-p" in result.output


def test_goal_add(run, git_content, git):
    result = run("goal", "add", "Camera ready", "-p", "project-a", "--due", "06.11.2026")
    assert result.exit_code == 0, result.output
    assert "Added goal camera-ready to project-a" in result.output
    assert Content.open(git_content).goal("camera").due == dt.date(2026, 11, 6)
    assert _head(git, git_content) == "goal: add camera-ready"


def test_task_add_unknown_project(run):
    assert run("task", "add", "X", "-p", "nope").exit_code == EXIT_NOT_FOUND


def test_task_add_bad_due(run):
    result = run("task", "add", "X", "-p", "project-a", "--due", "someday")
    assert result.exit_code == EXIT_INVALID
    assert "invalid date" in result.output


def test_goal_edit(run, git_content, git, editor):
    calls = editor(("status: doing", "status: blocked"))
    result = run("goal", "edit", "write-i")
    assert result.exit_code == 0, result.output
    assert "Saved goal write-intro" in result.output
    assert calls.read_text().strip().endswith("goals/write-intro.md")
    assert Content.open(git_content).goal("write-intro").status == "blocked"
    assert _head(git, git_content) == "goal: edit write-intro"


def test_task_edit_in_editor(run, git_content, git, editor):
    editor(("- [ ] Write two", "- [x] Write two"))
    result = run("task", "edit", "draft-r")
    assert result.exit_code == 0, result.output
    assert Content.open(git_content).task("draft-r").subtasks_done == 2
    assert _head(git, git_content) == "task: edit draft-related-work"


def test_task_edit_no_changes(run, git_content, git, editor):
    editor()
    result = run("task", "edit", "fix-plot-colors")
    assert "No changes." in result.output
    assert _head(git, git_content) == "initial"


def test_edit_invalid_is_restored_without_tty(run, git_content, git, editor):
    path = git_content / "projects/project-a/goals/write-intro.md"
    before = path.read_text()
    editor(("status: doing", "status: wip"))
    result = run("goal", "edit", "write-intro")
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


def test_goal_edit_fields_skips_editor(run, git_content, git, editor):
    calls = editor()
    result = run(
        "goal",
        "edit",
        "write-i",
        "--due",
        "03.10.26",
        "--priority",
        "low",
        "--tags",
        "+new,-thesis",
    )
    assert result.exit_code == 0, result.output
    assert calls.read_text() == ""
    goal = Content.open(git_content).goal("write-intro")
    assert goal.due == dt.date(2026, 10, 3)
    assert goal.priority == "low"
    assert goal.tags == ["writing", "new"]
    assert goal.updated == local_today()
    assert _head(git, git_content) == "goal: edit write-intro (priority, due, tags)"


def test_goal_edit_clear_due_and_retitle(run, git_content, git):
    result = run("goal", "edit", "write-intro", "--due", "none", "--title", "Intro")
    assert result.exit_code == 0, result.output
    goal = Content.open(git_content).goal("write-intro")
    assert goal.due is None
    assert goal.title == "Intro"
    assert "# Intro\n" in goal.path.read_text()
    assert "## Updates" in goal.path.read_text()  # rest of the body untouched


def test_task_edit_same_value_is_noop(run, git_content, git):
    result = run("task", "edit", "fix-plot-colors", "--status", "todo")
    assert "No changes." in result.output
    assert _head(git, git_content) == "initial"


def test_task_edit_goal_and_deps(run, git_content, git):
    result = run("task", "edit", "fix-plot", "-g", "write-i", "--after", "+draft-r")
    assert result.exit_code == 0, result.output
    task = Content.open(git_content).task("fix-plot-colors")
    assert (task.goal, task.depends_on) == ("write-intro", ["draft-related-work"])
    assert _head(git, git_content) == "task: edit fix-plot-colors (goal, depends_on)"
    run("task", "edit", "fix-plot", "-g", "none", "--after", "-draft")
    task = Content.open(git_content).task("fix-plot-colors")
    assert (task.goal, task.depends_on) == (None, [])
    assert "depends_on" not in task.path.read_text()


def test_task_edit_priority_none_inherits(run, git_content):
    run("task", "edit", "draft-r", "--priority", "low")
    assert Content.open(git_content).task("draft-r").priority == "low"
    run("task", "edit", "draft-r", "--priority", "none")
    assert Content.open(git_content).task("draft-r").priority == "high"  # from its goal
    assert run("task", "edit", "draft-r", "--priority", "urgent").exit_code != 0


def test_task_edit_cycle_is_rejected(run, git_content, git):
    result = run("task", "edit", "draft-r", "--after", "get-f")
    assert result.exit_code == EXIT_INVALID
    assert "cycle" in result.output
    assert _head(git, git_content) == "initial"


def test_project_edit_fields(run, git_content, git):
    result = run("project", "edit", "project-b", "--status", "active", "--title", "Lit review")
    assert result.exit_code == 0, result.output
    project = Content.open(git_content).project("project-b")
    assert (project.status, project.title) == ("active", "Lit review")
    registry = parsing.read_yaml(git_content / "registry.yaml")
    assert {e["id"]: e["status"] for e in registry}["project-b"] == "active"
    assert _head(git, git_content) == "project: edit project-b (title, status)"


def test_missing_editor(run, monkeypatch):
    monkeypatch.setenv("EDITOR", "definitely-not-an-editor-xyz")
    result = run("task", "edit", "fix-plot-colors")
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
