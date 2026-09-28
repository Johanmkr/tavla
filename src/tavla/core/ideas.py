"""Loose ideas: one line each, owned by the inbox, a project, a goal or a task.

- inbox: ``inbox.md`` (every non-heading line is an idea)
- project: ``ideas.md`` in the project directory (same format)
- goal/task: bullet lines under the ``## Ideas`` heading of its file

An idea is addressed by a *ref*: ``[SCOPE:]N`` or ``[SCOPE:]TEXT``, where SCOPE
is ``inbox`` (the default) or a project/goal/task id (prefixes work), N is its
1-based position in that scope, and TEXT a case-insensitive fragment that
matches exactly one idea there.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tavla.core import bootstrap, git_sync, ops, parsing
from tavla.core.entities import IDEAS_FILE, IDEAS_HEADING, Goal, Idea, Project, Task, idea_lines
from tavla.core.errors import AmbiguousIdError, NotFoundError, ValidationError
from tavla.core.queries import resolve_id
from tavla.core.store import Content

INBOX = "inbox"

Owner = Project | Goal | Task


@dataclass
class Scope:
    """Where a set of ideas lives."""

    kind: str  # inbox | project | goal | task
    id: str | None
    path: Path

    @property
    def label(self) -> str:
        return self.id or INBOX

    @property
    def in_section(self) -> bool:
        return self.kind in ("goal", "task")


@dataclass
class IdeaRef:
    scope: Scope
    number: int  # 1-based position within the scope
    line: int  # index into the file's lines
    idea: Idea

    @property
    def ref(self) -> str:
        return f"{self.scope.label}:{self.number}"


def scope_of(content: Content, owner: Owner | None) -> Scope:
    if owner is None:
        return Scope(INBOX, None, content.root / bootstrap.INBOX_FILE)
    if isinstance(owner, Project):
        return Scope("project", owner.id, owner.path / IDEAS_FILE)
    return Scope(ops.kind_of(owner), owner.id, owner.path)


def all_scopes(content: Content) -> list[Scope]:
    owners: list[Owner | None] = [None, *content.projects(), *content.goals(), *content.tasks()]
    return [scope_of(content, o) for o in owners]


def resolve_scope(content: Content, query: str) -> Scope:
    if query == INBOX:
        return scope_of(content, None)
    owners: list[Owner] = [*content.projects(), *content.goals(), *content.tasks()]
    return scope_of(content, resolve_id(query, owners, "project, goal or task"))


def read(scope: Scope) -> list[IdeaRef]:
    if not scope.path.is_file():
        return []
    text = scope.path.read_text()
    if scope.in_section:
        lines = parsing.section_bullets(text, IDEAS_HEADING)
    else:
        lines = idea_lines(text)
    return [IdeaRef(scope, n, i, Idea(t)) for n, (i, t) in enumerate(lines, start=1)]


def resolve(content: Content, ref: str) -> IdeaRef:
    """Resolve ``[SCOPE:]N`` / ``[SCOPE:]TEXT`` to one idea."""
    scope_query, sep, what = ref.partition(":")
    if not sep:
        scope_query, what = INBOX, ref
    scope = resolve_scope(content, scope_query.strip())
    ideas = read(scope)
    what = what.strip()
    if what.isdigit():
        n = int(what)
        if not 1 <= n <= len(ideas):
            raise NotFoundError(f"no idea {n} in {scope.label} (it has {len(ideas)})")
        return ideas[n - 1]
    matches = [r for r in ideas if what.lower() in r.idea.text.lower()] if what else []
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFoundError(f"no idea in {scope.label} matching '{what}'")
    raise AmbiguousIdError(what, [f"{r.ref}  {r.idea.text}" for r in matches])


# --- writes --------------------------------------------------------------------

_FILE_HEADERS = {INBOX: "# Inbox\n\n", "project": "# Ideas\n\n"}


def _insert(scope: Scope, text: str) -> None:
    if scope.in_section:
        scope.path.write_text(
            parsing.append_to_section(scope.path.read_text(), IDEAS_HEADING, f"- {text}")
        )
    else:
        ops.append_line(scope.path, f"- {text}", _FILE_HEADERS[scope.kind])


def _delete(ref: IdeaRef) -> None:
    ref.scope.path.write_text(parsing.remove_line(ref.scope.path.read_text(), ref.line))


def add(content: Content, scope: Scope, text: str) -> str:
    """Append an idea to ``scope`` and commit. Returns the normalized line."""
    git_sync.require_repo(content.root)
    line = ops.one_line(text, "idea")
    _insert(scope, line)
    message = (
        f"inbox: capture {ops.summary(line)}"
        if scope.kind == INBOX
        else f"idea: add to {scope.label}: {ops.summary(line)}"
    )
    git_sync.commit(content.root, message, [scope.path])
    return line


def move(content: Content, ref: IdeaRef, target: Scope) -> None:
    if target.path == ref.scope.path:
        raise ValidationError(f"idea is already in {target.label}")
    git_sync.require_repo(content.root)
    _delete(ref)
    _insert(target, ref.idea.text)
    git_sync.commit(
        content.root,
        f"idea: move {ref.scope.label} -> {target.label}: {ops.summary(ref.idea.text)}",
        [ref.scope.path, target.path],
    )


def drop(content: Content, ref: IdeaRef) -> None:
    git_sync.require_repo(content.root)
    _delete(ref)
    git_sync.commit(
        content.root,
        f"idea: drop from {ref.scope.label}: {ops.summary(ref.idea.text)}",
        [ref.scope.path],
    )


def promote(
    content: Content,
    ref: IdeaRef,
    *,
    project: Project | None = None,
    goal: Goal | None = None,
    as_goal: bool = False,
) -> Goal | Task:
    """Turn an idea into a new task (under ``goal`` or loose in ``project``) or,
    with ``as_goal``, a new goal in ``project``. ``#tags`` in the idea become
    the new item's tags. The idea is removed in the same commit."""
    title = ref.idea.text_without_tags() or ref.idea.text
    tags = ref.idea.tags
    original = ref.scope.path.read_text()
    _delete(ref)
    try:
        if as_goal:
            if project is None:
                raise ValidationError("promoting to a goal needs a project")
            item: Goal | Task = ops.add_goal(
                content, title, project, tags=tags, extra_paths=[ref.scope.path]
            )
        else:
            item = ops.add_task(
                content, title, project, goal=goal, tags=tags, extra_paths=[ref.scope.path]
            )
    except Exception:
        ref.scope.path.write_text(original)  # nothing was committed; put the idea back
        raise
    return item
