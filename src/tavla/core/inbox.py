"""Triage: emptying the inbox one item at a time.

An item is an open chore (``todo.md``) or an idea: one in ``inbox.md``, or
one filed under a project, goal or task when those are reviewed. Chores and
ideas are gone through separately, one kind per pass. Every decision is one
commit that removes the item and creates whatever it became.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from tavla.core import git_sync, ideas, ops, todos
from tavla.core.entities import Goal, Idea, Project, Task
from tavla.core.errors import ValidationError
from tavla.core.store import Content

KINDS = ("todo", "idea", "filed")
NAMES = {"todo": "chores", "idea": "ideas", "filed": "filed ideas"}

T = TypeVar("T")


@dataclass
class Item:
    kind: str  # todo | idea | filed
    source: todos.Todo | ideas.IdeaRef

    @property
    def text(self) -> str:
        return self.source.text if isinstance(self.source, todos.Todo) else self.source.idea.text

    @property
    def where(self) -> str:
        """Where it lives now: ``todo.md``, ``inbox`` or the owner's id."""
        return todos.TODO_FILE if isinstance(self.source, todos.Todo) else self.source.scope.label

    @property
    def title(self) -> str:
        """The text without its ``#tags``: what a new task or goal is called."""
        return Idea(self.text).text_without_tags() or self.text

    @property
    def tags(self) -> list[str]:
        return Idea(self.text).tags


def items(content: Content, kind: str) -> list[Item]:
    """What a pass of ``kind`` goes through, in file order."""
    if kind == "todo":
        return [Item(kind, t) for t in todos.open_todos(content)]
    if kind == "idea":
        return [Item(kind, r) for r in ideas.read(ideas.scope_of(content, None))]
    if kind == "filed":
        scopes = ideas.all_scopes(content)[1:]  # every owner but the inbox
        return [Item(kind, r) for scope in scopes for r in ideas.read(scope)]
    raise ValueError(f"unknown kind: {kind}")


def counts(content: Content) -> dict[str, int]:
    return {kind: len(items(content, kind)) for kind in KINDS}


def fresh(content: Content, item: Item) -> Item:
    """``item`` as it is on disk now: at its place, or wherever its text moved
    to; refused if it is gone."""
    if isinstance(item.source, todos.Todo):
        number = item.source.number
        now_todos = todos.open_todos(content)
        for t in [*(t for t in now_todos if t.number == number), *now_todos]:
            if t.text == item.text:
                return Item(item.kind, t)
        raise ValidationError(f"{todos.TODO_FILE} changed on disk; try again")
    scope = item.source.scope
    now = ideas.read(scope)
    for r in [*(r for r in now if r.number == item.source.number), *now]:
        if r.idea.text == item.text:
            return Item(item.kind, r)
    raise ValidationError(f"the ideas in {scope.label} changed on disk; try again")


def _source_path(content: Content, item: Item) -> Path:
    if isinstance(item.source, todos.Todo):
        return todos.todo_path(content)
    return item.source.scope.path


def _remove(content: Content, item: Item) -> None:
    if isinstance(item.source, todos.Todo):
        todos.remove(content, [item.source])
    else:
        ideas.remove(item.source)


def _consume(content: Content, item: Item, make: Callable[[list[Path]], T]) -> T:
    """Remove ``item`` and run ``make`` (which commits, taking the extra paths
    to include); if it fails, the item is put back and nothing is committed."""
    git_sync.require_repo(content.root)
    item = fresh(content, item)
    path = _source_path(content, item)
    original = path.read_text()
    _remove(content, item)
    try:
        return make([path])
    except Exception:
        path.write_text(original)
        raise


def to_task(
    content: Content,
    item: Item,
    title: str,
    *,
    project: Project | None = None,
    goal: Goal | None = None,
) -> Task:
    return _consume(
        content,
        item,
        lambda extra: ops.add_task(
            content, title, project, goal=goal, tags=item.tags, extra_paths=extra
        ),
    )


def to_goal(content: Content, item: Item, title: str, project: Project) -> Goal:
    return _consume(
        content,
        item,
        lambda extra: ops.add_goal(content, title, project, tags=item.tags, extra_paths=extra),
    )


def to_project(content: Content, item: Item, title: str, parent: Project | None = None) -> Project:
    return _consume(
        content,
        item,
        lambda extra: ops.add_project(
            content, title, tags=item.tags, parent=parent, extra_paths=extra
        ),
    )


def to_subtask(content: Content, item: Item, title: str, task: Task) -> Task:
    return _consume(
        content, item, lambda extra: ops.add_subtask(content, task, title, extra_paths=extra)
    )


def file_under(content: Content, item: Item, scope: ideas.Scope) -> None:
    """Keep it for later as an idea of a project, goal or task."""
    item = fresh(content, item)
    if isinstance(item.source, ideas.IdeaRef):
        ideas.move(content, item.source, scope)
        return

    def insert(extra: list[Path]) -> None:
        ideas.insert(scope, item.text)
        git_sync.commit(
            content.root,
            f"todo: file under {scope.label}: {ops.summary(item.text)}",
            [*extra, scope.path],
        )

    _consume(content, item, insert)


def finish(content: Content, item: Item) -> None:
    """It was done already: a chore is ticked off, an idea removed."""
    item = fresh(content, item)
    if isinstance(item.source, todos.Todo):
        todos.set_done(content, [item.source])
    else:
        ideas.drop(content, item.source, done=True)


def drop(content: Content, item: Item) -> None:
    item = fresh(content, item)
    if isinstance(item.source, todos.Todo):
        todos.drop(content, [item.source])
    else:
        ideas.drop(content, item.source)
