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


def test_project_add_subproject(run, git_content, git):
    result = run("project", "add", "Sensitivity study", "-p", "project-a")
    assert result.exit_code == 0, result.output
    assert "Added project sensitivity-study under project-a" in result.output
    assert Content.open(git_content).project("sensitivity-study").parent == "project-a"
    assert _head(git, git_content) == "project: add sensitivity-study under project-a"


def test_project_edit_parent(run, git_content, git):
    result = run("project", "edit", "project-b", "--parent", "project-a", "--priority", "high")
    assert result.exit_code == 0, result.output
    assert "Moved project project-b under project-a" in result.output
    assert "Saved project project-b" in result.output
    project = Content.open(git_content).project("project-b")
    assert (project.parent, project.priority) == ("project-a", "high")
    subjects = git(git_content, "log", "-2", "--format=%s").splitlines()
    assert subjects == [
        "project: edit project-b (priority)",
        "project: move project-b under project-a",
    ]

    result = run("project", "edit", "project-b", "-p", "none")
    assert result.exit_code == 0, result.output
    assert "Moved project project-b to top level" in result.output
    assert Content.open(git_content).project("project-b").parent is None


def test_project_edit_parent_unchanged(run, git_content, git):
    before = _head(git, git_content)
    result = run("project", "edit", "ablations", "-p", "project-a")
    assert result.exit_code == 0, result.output
    assert "No changes." in result.output
    assert _head(git, git_content) == before


def test_project_edit_parent_cycle_rejected(run):
    result = run("project", "edit", "project-a", "-p", "ablations")
    assert result.exit_code == EXIT_INVALID
    assert "inside it" in result.output


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


# --- subtasks, notes, drop, undo, deliverables ---------------------------------------


def test_task_check_lists_then_ticks(run, git_content, git):
    result = run("task", "check", "draft-r")
    assert result.exit_code == 0, result.output
    assert "1. [x] Collect MCMC papers" in result.output
    assert "2. [ ] Write two paragraphs" in result.output

    result = run("task", "check", "draft-r", "two")
    assert result.exit_code == 0, result.output
    assert "2. [x] Write two paragraphs" in result.output
    assert "tv task done draft-related-work" in result.output
    assert _head(git, git_content) == "task: check draft-related-work: Write two paragraphs"


def test_task_check_unknown_subtask(run):
    assert run("task", "check", "draft-r", "9").exit_code == EXIT_NOT_FOUND


def test_task_uncheck_already_unchecked(run, git_content, git):
    before = _head(git, git_content)
    result = run("task", "uncheck", "draft-r", "2")
    assert result.exit_code == 0, result.output
    assert "Already unchecked." in result.output
    assert _head(git, git_content) == before


def test_task_subtask_and_note(run, git_content):
    assert run("task", "subtask", "draft-r", "Write", "the", "end").exit_code == 0
    result = run("task", "note", "draft-r", "Found two more papers")
    assert result.exit_code == 0, result.output
    assert "Noted on draft-related-work: Found two more papers" in result.output
    task = Content.open(git_content).task("draft-r")
    assert task.subtasks[-1].text == "Write the end"
    assert ": Found two more papers\n" in task.path.read_text()


def test_goal_note(run, git_content, git):
    result = run("goal", "note", "write-intro", "shorter please")
    assert result.exit_code == 0, result.output
    assert _head(git, git_content) == "goal: note write-intro: shorter please"


def test_task_drop_asks_first(run, git_content, git):
    before = _head(git, git_content)
    result = runner.invoke(
        app, ["--content-dir", str(git_content), "task", "drop", "fix-plot"], input="n\n"
    )
    assert result.exit_code != 0
    assert _head(git, git_content) == before

    result = runner.invoke(
        app, ["--content-dir", str(git_content), "task", "drop", "fix-plot"], input="y\n"
    )
    assert result.exit_code == 0, result.output
    assert _head(git, git_content) == "task: drop fix-plot-colors"


def test_task_drop_refused_before_asking(run):
    result = run("task", "drop", "draft-r", "--yes")
    assert result.exit_code == EXIT_INVALID
    assert "get-feedback-from-advisor" in result.output
    assert "?" not in result.output  # no confirmation question


def test_goal_drop(run, git_content, git):
    assert run("goal", "add", "Scratch", "-p", "project-b").exit_code == 0
    result = run("goal", "drop", "scratch", "-y")
    assert result.exit_code == 0, result.output
    assert _head(git, git_content) == "goal: drop scratch"


def test_undo(run, git_content, git):
    assert run("task", "drop", "fix-plot", "-y").exit_code == 0
    result = run("undo", "-n")
    assert "Would undo: task: drop fix-plot-colors" in result.output
    assert _head(git, git_content) == "task: drop fix-plot-colors"

    result = run("undo")
    assert result.exit_code == 0, result.output
    assert "Undoing: task: drop fix-plot-colors" in result.output
    assert Content.open(git_content).task("fix-plot-colors")
    assert run("undo").output == "Nothing to undo.\n"


def test_deliverable_lifecycle(run, git_content, git):
    result = run(
        "deliverable", "add", "Group talk", "-p", "project-b", "--kind", "slides",
        "--deadline", "02.10.2026", "--coauthors", "ann,bob",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "Added deliverable group-talk to project-b" in result.output

    result = run("deliverable", "edit", "group", "--status", "accepted", "--coauthors", "-bob")
    assert result.exit_code == 0, result.output
    d = Content.open(git_content).deliverable("group-talk")
    assert (d.status, d.coauthors, d.deadline) == ("accepted", ["ann"], dt.date(2026, 10, 2))

    listed = run("deliverable", "list").output
    assert "neurips-paper" in listed and "group-talk" not in listed  # accepted: hidden
    assert "group-talk" in run("deliverable", "list", "--all").output
    assert "coauthors: ann" in run("deliverable", "show", "group").output

    assert run("deliverable", "drop", "group", "-y").exit_code == 0
    assert _head(git, git_content) == "deliverable: drop group-talk"


def test_deliverable_edit_in_editor(run, git_content, editor):
    editor(("status: drafting", "status: submitted"))
    result = run("deliverable", "edit", "neurips")
    assert result.exit_code == 0, result.output
    assert Content.open(git_content).deliverable("neurips").status == "submitted"
