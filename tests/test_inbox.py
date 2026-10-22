"""Inbox triage: each decision is one commit that removes the item and
creates what it became."""

from __future__ import annotations

from pathlib import Path

import pytest

from tavla.core import demo, ideas, inbox, todos
from tavla.core.errors import ValidationError
from tavla.core.store import Content


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "demo"
    demo.create(root)
    content = Content.open(root)
    todos.add(content, "Book the dentist")
    todos.add(content, "Draft the methods intro #writing")
    return root


def last_commit(git, root: Path) -> str:
    return git(root, "log", "-1", "--format=%s").strip()


def changed_files(git, root: Path) -> set[str]:
    return set(git(root, "show", "--name-only", "--format=", "HEAD").split())


def test_items_by_kind(repo):
    content = Content.open(repo)
    assert [i.text for i in inbox.items(content, "todo")] == [
        "Book the dentist",
        "Draft the methods intro #writing",
    ]
    assert len(inbox.items(content, "idea")) == 3
    assert all(i.where != "inbox" for i in inbox.items(content, "filed"))
    assert inbox.counts(content)["todo"] == 2


def test_chore_to_task_is_one_commit_with_the_tags(repo, git):
    content = Content.open(repo)
    item = inbox.items(content, "todo")[1]
    task = inbox.to_task(content, item, "Draft the intro", goal=content.goal("write-up"))
    assert task.goal == "write-up" and task.tags == ["writing"]
    assert [t.text for t in todos.read(Content.open(repo))] == ["Book the dentist"]
    assert "todo.md" in changed_files(git, repo)


def test_idea_to_goal_project_and_subtask(repo):
    content = Content.open(repo)
    first, second, third = inbox.items(content, "idea")
    goal = inbox.to_goal(content, first, "Tempering", content.project("thesis"))
    assert goal.project == "thesis"
    content = Content.open(repo)
    project = inbox.to_project(content, second, "Travel grant", content.project("thesis"))
    assert project.parent == "thesis"
    content = Content.open(repo)
    task = content.tasks()[0]
    before = task.subtasks_total
    after = inbox.to_subtask(content, third, "Check ArviZ ESS", task)
    assert after.subtasks_total == before + 1
    assert inbox.items(Content.open(repo), "idea") == []


def test_file_a_chore_under_a_project_for_later(repo, git):
    content = Content.open(repo)
    item = inbox.items(content, "todo")[0]
    inbox.file_under(content, item, ideas.resolve_scope(content, "thesis"))
    texts = [r.idea.text for r in ideas.read(ideas.resolve_scope(Content.open(repo), "thesis"))]
    assert "Book the dentist" in texts
    assert last_commit(git, repo) == "todo: file under thesis: Book the dentist"


def test_finish_ticks_a_chore_and_removes_an_idea(repo, git):
    content = Content.open(repo)
    inbox.finish(content, inbox.items(content, "todo")[0])
    assert todos.read(Content.open(repo))[0].done
    inbox.finish(content, inbox.items(content, "idea")[0])
    assert last_commit(git, repo).startswith("idea: done inbox:")


def test_a_failed_decision_puts_the_item_back(repo, git):
    content = Content.open(repo)
    item = inbox.items(content, "todo")[0]
    head = last_commit(git, repo)
    with pytest.raises(ValidationError):
        inbox.to_goal(content, item, "", content.project("thesis"))  # empty title
    assert len(inbox.items(Content.open(repo), "todo")) == 2
    assert last_commit(git, repo) == head


def test_a_stale_item_is_refused(repo):
    content = Content.open(repo)
    item = inbox.items(content, "todo")[0]
    inbox.drop(content, item)
    with pytest.raises(ValidationError):
        inbox.drop(Content.open(repo), item)
