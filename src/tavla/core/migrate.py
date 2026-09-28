"""Upgrading a content repo to the current layout (``tavla migrate``).

v1 -> v2: what used to be a *task* (``tasks/<id>.md`` with a ``## Subtasks``
checklist) becomes a *goal* (``goals/<id>.md``), and each of its top-level
subtask checkboxes becomes its own task file pointing back at the goal (nested
checkboxes become that task's subtasks). Goal and task files get an ``## Ideas``
section. Everything happens in one commit, so ``git revert`` undoes it.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from tavla.core import bootstrap, dates, git_sync, parsing
from tavla.core.entities import GOALS_DIR, IDEAS_HEADING, TASKS_DIR, TaskStatus
from tavla.core.errors import TavlaError
from tavla.core.ops import TASK_BODY_TEMPLATE, slugify
from tavla.core.store import Content

_CHECKBOX_RE = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s+(.*\S)\s*$")


@dataclass
class NewTask:
    id: str
    title: str
    done: bool
    subtasks: list[str] = field(default_factory=list)  # raw checkbox lines, dedented


@dataclass
class GoalMove:
    old: Path
    new: Path
    goal_id: str
    project_id: str
    tasks: list[NewTask] = field(default_factory=list)


@dataclass
class MigrationPlan:
    root: Path
    from_version: int
    to_version: int
    moves: list[GoalMove] = field(default_factory=list)

    @property
    def needed(self) -> bool:
        return self.from_version < self.to_version


def plan(root: Path) -> MigrationPlan:
    """Work out what :func:`apply` would do, without touching anything."""
    if not bootstrap.is_initialized(root):
        raise TavlaError(f"no tavla content repo at {root} (run `tavla init`)")
    version = bootstrap.schema_version(root)
    result = MigrationPlan(root, version, bootstrap.SCHEMA_VERSION)
    if version >= bootstrap.SCHEMA_VERSION:
        return result

    content = Content(root)  # bypasses the version check in Content.open
    taken = set(content.all_ids())
    for project in content.projects():
        for old in sorted((project.path / TASKS_DIR).glob("*.md")):
            meta, _ = parsing.read_markdown(old)
            goal_id = str(meta.get("id") or old.stem)
            move = GoalMove(old, project.path / GOALS_DIR / old.name, goal_id, project.id)
            if move.new.exists():
                raise TavlaError(f"can't migrate {old}: {move.new} already exists")
            for title, done, children in _top_level_subtasks(old.read_text()):
                task_id = _unique(slugify(title) or "task", taken)
                move.tasks.append(NewTask(task_id, title, done, children))
            result.moves.append(move)
    return result


def apply(migration: MigrationPlan, *, today: dt.date | None = None) -> bool:
    """Carry out ``migration`` and commit it. Returns False if nothing was needed.

    Refuses to run on a repo with uncommitted changes, so the migration commit
    contains nothing else and can be reverted cleanly.
    """
    if not migration.needed:
        return False
    root = migration.root
    git_sync.require_repo(root)
    if not git_sync.is_clean(root):
        raise TavlaError(f"{root} has uncommitted changes; commit or stash them first")
    today = today or dates.local_today()

    for move in migration.moves:
        text = move.old.read_text()
        meta, _ = parsing.read_markdown(move.old)
        # New tasks carry the old file's dates, so staleness is unaffected.
        created = meta.get("created") or today
        updated = meta.get("updated") or created
        move.new.parent.mkdir(parents=True, exist_ok=True)
        move.new.write_text(_add_ideas_section(_strip_subtasks(text)))
        move.old.unlink()
        for task in move.tasks:
            _write_task(move.old.parent / f"{task.id}.md", task, move, created, updated)

    bootstrap.write_schema_version(root, migration.to_version)
    git_sync.commit(
        root, f"migrate: content layout v{migration.from_version} -> v{migration.to_version}"
    )
    return True


# --- helpers -------------------------------------------------------------------


def _unique(base: str, taken: set[str]) -> str:
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    taken.add(candidate)
    return candidate


def _subtask_span(lines: list[str], text: str) -> tuple[int, int] | None:
    return parsing.section_span(lines, parsing.SUBTASKS_HEADING, parsing.frontmatter_lines(text))


def _top_level_subtasks(text: str) -> list[tuple[str, bool, list[str]]]:
    """``(title, done, nested_checkbox_lines)`` for each top-level checkbox."""
    lines = text.splitlines()
    span = _subtask_span(lines, text)
    if span is None:
        return []
    items: list[tuple[str, bool, list[str]]] = []
    base_indent: int | None = None
    for line in lines[span[0] + 1 : span[1]]:
        m = _CHECKBOX_RE.match(line)
        if not m:
            continue
        indent = len(m.group(1).expandtabs())
        if base_indent is None or indent <= base_indent:
            base_indent = indent
            items.append((m.group(3), m.group(2) in "xX", []))
        elif items:
            depth = indent - base_indent
            nested = " " * max(depth - 2, 0) + f"- [{m.group(2)}] {m.group(3)}"
            items[-1][2].append(nested)
    return items


def _strip_subtasks(text: str) -> str:
    """Drop checkbox lines from ``## Subtasks``; drop the heading too if nothing
    else is left under it."""
    lines = text.splitlines(keepends=True)
    span = _subtask_span([ln.rstrip("\n") for ln in lines], text)
    if span is None:
        return text
    start, end = span
    rest = [ln for ln in lines[start + 1 : end] if not _CHECKBOX_RE.match(ln.rstrip("\n"))]
    if any(ln.strip() for ln in rest):
        return "".join([*lines[: start + 1], *rest, *lines[end:]])
    before = lines[:start]
    after = lines[end:]
    while before and not before[-1].strip() and after:
        before.pop()
    if after and before:
        before.append("\n")
    return "".join([*before, *after])


def _add_ideas_section(text: str) -> str:
    """Add an empty ``## Ideas`` section before ``## Updates`` (or at the end)."""
    lines = text.splitlines(keepends=True)
    start = parsing.frontmatter_lines(text)
    stripped = [ln.rstrip("\n") for ln in lines]
    if parsing.section_span(stripped, IDEAS_HEADING, start) is not None:
        return text
    updates = parsing.section_span(stripped, "Updates", start)
    if updates is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        return "".join([*lines, f"\n## {IDEAS_HEADING}\n"])
    at = updates[0]
    return "".join([*lines[:at], f"## {IDEAS_HEADING}\n\n", *lines[at:]])


def _write_task(
    path: Path, task: NewTask, move: GoalMove, created: object, updated: object
) -> None:
    fields = {
        "id": task.id,
        "project": move.project_id,
        "goal": move.goal_id,
        "status": (TaskStatus.DONE if task.done else TaskStatus.TODO).value,
        "tags": [],
        "created": created,
        "updated": updated,
    }
    body = TASK_BODY_TEMPLATE.format(title=task.title)
    if task.subtasks:
        body = body.replace(
            "## Subtasks\n", "## Subtasks\n" + "".join(f"{s}\n" for s in task.subtasks)
        )
    front = "".join(f"{k}: {parsing.yaml_inline(v)}\n" for k, v in fields.items())
    path.write_text(f"---\n{front}---\n\n{body}")
