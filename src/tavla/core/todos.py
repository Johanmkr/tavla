"""Quick todos: small things outside any project, or captured in a hurry.

They live in ``todo.md`` at the root of the content repo, one checklist item
per line (a plain ``- text`` bullet counts as an open todo). A todo is
addressed by its number in the file (counting finished ones too, so the
numbers don't shift as you tick items off) or by a piece of its text.
Later you tick them off, drop them, or promote them to proper tasks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tavla.core import git_sync, ops, parsing
from tavla.core.entities import Goal, Idea, Project, Task
from tavla.core.errors import AmbiguousIdError, NotFoundError, ValidationError
from tavla.core.store import Content

TODO_FILE = "todo.md"
_HEADER = "# Todo\n\n"
_ITEM_RE = re.compile(r"^(\s*)[-*+]\s+(?:\[([ xX])\]\s+)?(.*\S)\s*$")


@dataclass
class Todo:
    number: int  # 1-based, over every item in the file
    line: int  # index into the file's lines
    text: str
    done: bool

    @property
    def tags(self) -> list[str]:
        return Idea(self.text).tags


def todo_path(content: Content) -> Path:
    return content.root / TODO_FILE


def read(content: Content) -> list[Todo]:
    path = todo_path(content)
    if not path.is_file():
        return []
    items = []
    for i, line in enumerate(path.read_text().splitlines()):
        m = _ITEM_RE.match(line)
        if m:
            items.append(Todo(len(items) + 1, i, m[3], (m[2] or " ") in "xX"))
    return items


def open_todos(content: Content) -> list[Todo]:
    return [t for t in read(content) if not t.done]


def resolve(content: Content, ref: str) -> Todo:
    """A todo by number, or by a piece of its text (open todos are matched
    first, so a finished todo with similar text doesn't get in the way)."""
    todos = read(content)
    ref = ref.strip()
    if ref.isdigit():
        n = int(ref)
        if not 1 <= n <= len(todos):
            raise NotFoundError(f"no todo {n} (there are {len(todos)})")
        return todos[n - 1]
    matches = [t for t in todos if ref and ref.lower() in t.text.lower()]
    if len(matches) > 1:
        matches = [t for t in matches if not t.done] or matches
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFoundError(f"no todo matching '{ref}'")
    raise AmbiguousIdError(ref, [f"{t.number}. {t.text}" for t in matches])


def add(content: Content, text: str) -> Todo:
    """Append an open todo and commit."""
    git_sync.require_repo(content.root)
    line = ops.one_line(text, "todo")
    path = todo_path(content)
    ops.append_line(path, f"- [ ] {line}", _HEADER)
    git_sync.commit(content.root, f"todo: add {ops.summary(line)}", [path])
    return read(content)[-1]


def _what(todos: list[Todo]) -> str:
    return ops.summary(todos[0].text) if len(todos) == 1 else f"{len(todos)} todos"


def set_done(content: Content, todos: Iterable[Todo], *, done: bool = True) -> list[Todo]:
    """Tick (or untick) todos and commit. Returns those that changed."""
    git_sync.require_repo(content.root)
    changed = list({t.number: t for t in todos if t.done != done}.values())
    if not changed:
        return []
    path = todo_path(content)
    lines = path.read_text().splitlines(keepends=True)
    mark = "x" if done else " "
    for t in changed:
        m = _ITEM_RE.match(lines[t.line])
        if m is None or m[3] != t.text:
            raise ValidationError(f"{path} changed on disk; try again")
        lines[t.line] = f"{m[1]}- [{mark}] {t.text}\n"
    path.write_text("".join(lines))
    verb = "done" if done else "reopen"
    git_sync.commit(content.root, f"todo: {verb} {_what(changed)}", [path])
    return changed


def remove(content: Content, todos: Iterable[Todo]) -> None:
    path = todo_path(content)
    text = path.read_text()
    for t in sorted(todos, key=lambda t: t.line, reverse=True):
        text = parsing.remove_line(text, t.line)
    path.write_text(text)


def drop(content: Content, todos: list[Todo]) -> None:
    """Delete todos (they stay in git history)."""
    git_sync.require_repo(content.root)
    remove(content, todos)
    git_sync.commit(content.root, f"todo: drop {_what(todos)}", [todo_path(content)])


def clear(content: Content) -> list[Todo]:
    """Remove every finished todo. Returns what was removed."""
    git_sync.require_repo(content.root)
    finished = [t for t in read(content) if t.done]
    if finished:
        remove(content, finished)
        git_sync.commit(content.root, f"todo: clear {len(finished)} done", [todo_path(content)])
    return finished


def promote(
    content: Content,
    todo: Todo,
    *,
    project: Project | None = None,
    goal: Goal | None = None,
    as_goal: bool = False,
) -> Goal | Task:
    """Turn a todo into a new task (under ``goal`` or loose in ``project``) or,
    with ``as_goal``, a new goal in ``project``. ``#tags`` become the new
    item's tags. The todo is removed in the same commit."""
    idea = Idea(todo.text)
    title = idea.text_without_tags() or todo.text
    path = todo_path(content)
    original = path.read_text()
    remove(content, [todo])
    try:
        if as_goal:
            if project is None:
                raise ValidationError("promoting to a goal needs a project")
            return ops.add_goal(content, title, project, tags=idea.tags, extra_paths=[path])
        return ops.add_task(content, title, project, goal=goal, tags=idea.tags, extra_paths=[path])
    except Exception:
        path.write_text(original)  # nothing was committed; put the todo back
        raise
