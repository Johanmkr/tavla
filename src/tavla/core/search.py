"""Search across everything: ``tavla find`` (and the log, newest first, for
``tavla log``)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

from tavla.core import ideas, todos
from tavla.core.entities import Goal, LogEntry, Project, Task
from tavla.core.store import Content

KINDS = ("project", "goal", "task", "deliverable", "idea", "todo", "log")


@dataclass
class Hit:
    kind: str  # one of KINDS
    ref: str  # what to pass to the matching command: an id, idea ref or todo number
    text: str  # the title, or the line itself
    project: str | None = None
    status: str | None = None
    match: str | None = None  # the body line that matched, when the title doesn't


def _words(query: str) -> list[str]:
    return query.casefold().split()


def _has_all(words: list[str], *texts: str | None) -> bool:
    haystack = " ".join(t for t in texts if t).casefold()
    return all(w in haystack for w in words)


def _matching_line(words: list[str], body: str) -> str | None:
    """The first body line (headings skipped) that contains any of ``words``."""
    for line in body.splitlines():
        stripped = line.strip().lstrip("-*").strip()
        if stripped and not stripped.startswith("#"):
            folded = stripped.casefold()
            if any(w in folded for w in words):
                return stripped
    return None


def _in_scope(content: Content, project: Project | None) -> set[str] | None:
    if project is None:
        return None
    return {project.id, *(p.id for p in content.descendants(project))}


def find(content: Content, query: str, *, project: Project | None = None) -> list[Hit]:
    """Everything whose text contains every word of ``query`` (any case):
    projects, goals, tasks and deliverables by id, title, tags and body; ideas,
    todos and log lines by their text. Finished items are included."""
    words = _words(query)
    if not words:
        return []
    wanted = _in_scope(content, project)

    def keep(project_id: str | None) -> bool:
        return wanted is None or project_id in wanted

    hits: list[Hit] = []
    for p in content.projects():
        if keep(p.id) and _has_all(words, p.id, p.title, " ".join(p.tags)):
            hits.append(Hit("project", p.id, p.title, p.parent, p.status.value))
    items: list[Goal | Task] = [*content.goals(), *content.tasks()]
    for item in items:
        if not keep(item.project):
            continue
        if _has_all(words, item.id, item.title, " ".join(item.tags), item.body):
            title_hit = _has_all(words, item.id, item.title, " ".join(item.tags))
            kind = "goal" if isinstance(item, Goal) else "task"
            hits.append(
                Hit(
                    kind,
                    item.id,
                    item.title,
                    item.project,
                    item.status.value,
                    None if title_hit else _matching_line(words, item.body),
                )
            )
    for d in content.deliverables():
        if keep(d.project) and _has_all(words, d.id, d.title, d.venue):
            hits.append(Hit("deliverable", d.id, d.title, d.project, d.status.value))
    # Ideas under goals and tasks are part of their body, found above.
    for scope in ideas.all_scopes(content):
        if scope.in_section or not keep(scope.id if scope.kind == "project" else None):
            continue
        for ref in ideas.read(scope):
            if _has_all(words, ref.idea.text):
                hits.append(Hit("idea", ref.ref, ref.idea.text, scope.id))
    if wanted is None:
        for todo in todos.read(content):
            if _has_all(words, todo.text):
                hits.append(Hit("todo", str(todo.number), todo.text, None, _todo_status(todo)))
    for p, entry in log_entries(content, [p for p in content.projects() if keep(p.id)]):
        if _has_all(words, entry.text):
            hits.append(Hit("log", stamp(entry), entry.text, p.id))
    return hits


def _todo_status(todo: todos.Todo) -> str:
    return "done" if todo.done else "todo"


def stamp(entry: LogEntry) -> str:
    return f"{entry.date.isoformat()} {entry.time:%H:%M}" if entry.time else entry.date.isoformat()


def log_entries(content: Content, projects: Iterable[Project]) -> list[tuple[Project, LogEntry]]:
    """The log lines of ``projects``, newest first."""
    entries = [(n, p, e) for p in projects for n, e in enumerate(content.log(p))]
    entries.sort(key=lambda npe: (npe[2].date, npe[2].time or dt.time.min, npe[0]), reverse=True)
    return [(p, e) for _, p, e in entries]
