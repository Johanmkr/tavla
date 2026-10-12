"""Quick todos in todo.md: tv todo ..."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import todos
from tavla.core.errors import AmbiguousIdError, NotFoundError
from tavla.core.store import Content

runner = CliRunner()


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


@pytest.fixture
def run(git_content):
    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(git_content), *args])

    return _run


def _head(git, repo) -> str:
    return git(repo, "log", "-1", "--format=%s").strip()


def test_add_creates_file(content, git):
    assert todos.read(content) == []
    todo = todos.add(content, "  buy   cables #lab ")
    assert (todo.number, todo.text, todo.done, todo.tags) == (1, "buy cables #lab", False, ["lab"])
    assert todos.todo_path(content).read_text() == "# Todo\n\n- [ ] buy cables #lab\n"
    assert _head(git, content.root) == "todo: add buy cables #lab"


def test_read_hand_written_file(content):
    todos.todo_path(content).write_text(
        "# Todo\n\nsome prose\n- plain bullet\n- [x] finished\n  * [ ] nested\n"
    )
    items = todos.read(content)
    assert [(t.number, t.text, t.done) for t in items] == [
        (1, "plain bullet", False),
        (2, "finished", True),
        (3, "nested", False),
    ]
    assert [t.number for t in todos.open_todos(content)] == [1, 3]


def test_done_and_reopen_keep_numbers(content, git):
    for text in ("one", "two", "three"):
        todos.add(content, text)
    changed = todos.set_done(content, [todos.resolve(content, "2"), todos.resolve(content, "3")])
    assert [t.number for t in changed] == [2, 3]
    assert _head(git, content.root) == "todo: done 2 todos"
    assert [t.number for t in todos.open_todos(content)] == [1]
    assert todos.set_done(content, [todos.resolve(content, "2")]) == []
    todos.set_done(content, [todos.resolve(content, "two")], done=False)
    assert _head(git, content.root) == "todo: reopen two"
    assert [t.number for t in todos.open_todos(content)] == [1, 2]


def test_resolve(content):
    for text in ("email Ana", "email Bo"):
        todos.add(content, text)
    with pytest.raises(AmbiguousIdError):
        todos.resolve(content, "email")
    todos.set_done(content, [todos.resolve(content, "Bo")])
    assert todos.resolve(content, "email").text == "email Ana"  # open ones win
    with pytest.raises(NotFoundError):
        todos.resolve(content, "9")
    with pytest.raises(NotFoundError):
        todos.resolve(content, "milk")


def test_drop_and_clear(content, git):
    for text in ("a", "b", "c"):
        todos.add(content, text)
    todos.drop(content, [todos.resolve(content, "1"), todos.resolve(content, "3")])
    assert [t.text for t in todos.read(content)] == ["b"]
    todos.set_done(content, todos.read(content))
    assert [t.text for t in todos.clear(content)] == ["b"]
    assert _head(git, content.root) == "todo: clear 1 done"
    assert todos.clear(content) == []


def test_promote_to_task_and_goal(content, git):
    todos.add(content, "fix legend #plots")
    todos.add(content, "write a survey")
    task = todos.promote(
        content, todos.resolve(content, "legend"), project=content.project("project-a")
    )
    assert (task.id, task.tags) == ("fix-legend", ["plots"])
    assert _head(git, content.root) == "task: add fix-legend"
    goal = todos.promote(
        content,
        todos.resolve(content, "survey"),
        project=content.project("project-a"),
        as_goal=True,
    )
    assert goal.id == "write-a-survey"
    assert todos.read(content) == []
    assert git(content.root, "status", "--porcelain") == ""


def test_promote_failure_keeps_todo(content):
    todos.add(content, "something")
    with pytest.raises(Exception, match="needs a project"):
        todos.promote(content, todos.resolve(content, "1"), as_goal=True)
    assert [t.text for t in todos.read(content)] == ["something"]


# --- CLI -----------------------------------------------------------------------


def test_cli_todo_text_adds(run, git_content):
    result = run("todo", "buy", "milk")
    assert result.exit_code == 0, result.output
    assert "Added todo 1: buy milk" in result.output
    result = run("todo", "add", "list", "the", "cables")
    assert "Added todo 2: list the cables" in result.output
    result = run("todo")
    assert "1. [ ] buy milk" in result.output
    assert "2. [ ] list the cables" in result.output


def test_cli_todo_lifecycle(run, git_content):
    run("todo", "buy", "milk")
    run("todo", "call", "Bo")
    assert "1. [x] buy milk" in run("todo", "done", "1").output
    listing = run("todo").output
    assert "buy milk" not in listing and "1 done" in listing
    assert "1. [x] buy milk" in run("todo", "--all").output
    data = json.loads(run("todo", "list", "--json", "--all").output)
    assert [(d["number"], d["done"]) for d in data] == [(1, True), (2, False)]
    assert "1. [ ] buy milk" in run("todo", "reopen", "milk").output
    assert "Promoted to task call-bo" in run("todo", "promote", "Bo", "-p", "project-a").output
    assert "Dropped: buy milk" in run("todo", "drop", "1").output
    assert "No open todos" in run("todo").output


def test_cli_promote_needs_target(run):
    run("todo", "x")
    assert run("todo", "promote", "1").exit_code != 0


def test_status_counts_open_todos(run):
    run("todo", "a")
    run("todo", "b")
    assert "2 open todos" in run("status").output
