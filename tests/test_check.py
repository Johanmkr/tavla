from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import check
from tavla.core.errors import EXIT_INVALID
from tavla.core.store import Content

runner = CliRunner()


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


def _hand_edit(path, old, new, git=None, root=None):
    path.write_text(path.read_text().replace(old, new))
    if git is not None:
        git(root, "commit", "-qam", "hand edit")


def _messages(content) -> list[tuple[str, str]]:
    return [
        (p.path.relative_to(content.root).as_posix(), p.message)
        for p in check.find_problems(content)
    ]


def test_fixture_has_no_problems(content):
    assert check.find_problems(content) == []


def test_project_mismatch_is_fixable(content):
    goal = content.goal("write-intro")
    _hand_edit(goal.path, "project: project-a", "project: project-b")
    [problem] = check.find_problems(content)
    assert problem.fixable
    assert problem.message == "project: says project-b, but the file is in project project-a"


def test_unknown_project_is_reset_by_fix(content, git):
    goal = content.goal("write-intro")
    _hand_edit(goal.path, "project: project-a", "project: nope", git, content.root)
    [problem] = check.find_problems(content)
    assert problem.fix == "reset"
    assert "unknown project 'nope'" in problem.message
    assert check.fix(content) == (["Set project: of goal write-intro to project-a"], [])
    assert "project: project-a" in goal.path.read_text()
    assert check.find_problems(content) == []


def test_broken_file_does_not_hide_other_problems(content):
    _hand_edit(content.goal("setup-env").path, "status: done", "status: wip")
    _hand_edit(content.task("fix-plot").path, "project: project-a", "project: project-b")
    messages = _messages(content)
    assert len(messages) == 2
    assert messages[0][0] == "projects/project-a/goals/setup-env.md"
    assert "status" in messages[0][1]
    assert messages[1][0].endswith("tasks/fix-plot-colors.md")


def test_task_links_and_duplicate_ids(content):
    _hand_edit(
        content.task("fix-plot").path, "project: project-a", "project: project-a\ngoal: gone"
    )
    _hand_edit(content.goal("write-methods").path, "id: write-methods", "id: write-intro")
    messages = [m for _, m in _messages(content)]
    assert "unknown goal 'gone'" in messages
    assert any(m.startswith("id 'write-intro' is already used by") for m in messages)


def test_fix_moves_goal_with_its_tasks(content, git):
    _hand_edit(
        content.goal("write-intro").path,
        "project: project-a",
        "project: project-b",
        git,
        content.root,
    )
    fixed, failed = check.fix(content)
    assert fixed == ["Moved goal write-intro to project project-b"]
    assert failed == []
    assert content.goal("write-intro").project == "project-b"
    assert content.task("draft-related-work").project == "project-b"
    assert check.find_problems(content) == []
    assert git(content.root, "log", "-1", "--format=%s").strip() == (
        "goal: move write-intro -> project project-b"
    )
    assert git(content.root, "status", "--porcelain") == ""


def test_fix_reports_task_that_cannot_leave_its_goal(content, git):
    task = content.task("draft-related-work")
    _hand_edit(task.path, "project: project-a", "project: project-b", git, content.root)
    fixed, failed = check.fix(content)
    assert fixed == []
    [problem] = failed
    assert "goal 'write-intro' is in project project-a, not project-b" in problem.message
    assert task.path.exists()


def test_cli_check(git_content, content, git):
    args = ["--content-dir", str(git_content), "check"]
    assert "No problems found." in runner.invoke(app, args).output

    _hand_edit(content.task("fix-plot").path, "project: project-a", "project: project-c")
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_INVALID
    assert "project: says project-c" in result.output
    assert "tv check --fix" in result.output

    result = runner.invoke(app, [*args, "--fix"])
    assert result.exit_code == 0, result.output
    assert "Moved task fix-plot-colors to project project-c" in result.output
    assert Content.open(git_content).task("fix-plot").project == "project-c"
