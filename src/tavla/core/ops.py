"""Mutating operations on the content repo.

Every operation here validates first, then writes, then auto-commits via
:mod:`tavla.core.git_sync` — so any interface calling into it gets the same
guarantees. Operations take ``today`` so tests can pin the date.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from tavla.core import bootstrap, git_sync
from tavla.core.dates import local_today
from tavla.core.entities import (
    IDEAS_FILE,
    LOG_FILE,
    PROJECT_FILE,
    TASKS_DIR,
    Priority,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)
from tavla.core.errors import ValidationError
from tavla.core.parsing import set_frontmatter_key, yaml_inline
from tavla.core.store import Content

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_SLUG_LEN = 40

# Letters NFKD can't decompose to ASCII.
_TRANSLITERATE = str.maketrans(
    {"æ": "ae", "ø": "o", "œ": "oe", "ß": "ss", "đ": "d", "ł": "l", "þ": "th", "ð": "d"}
)


# --- ids --------------------------------------------------------------------


def slugify(text: str) -> str:
    slug = unicodedata.normalize("NFKD", text.lower().translate(_TRANSLITERATE))
    slug = re.sub(r"[^a-z0-9]+", "-", slug.encode("ascii", "ignore").decode()).strip("-")
    if len(slug) > MAX_SLUG_LEN:
        cut = slug[:MAX_SLUG_LEN]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else cut
    return slug


def validate_id(id_: str) -> None:
    if not ID_RE.match(id_):
        raise ValidationError(
            f"invalid id '{id_}' (letters, digits, '.', '_' and '-' only; "
            "must start with a letter or digit)"
        )


def _new_id(content: Content, title: str, explicit: str | None) -> str:
    taken = content.all_ids()
    if explicit:
        validate_id(explicit)
        if explicit in taken:
            raise ValidationError(f"id '{explicit}' is already used by {taken[explicit][0]}")
        return explicit
    base = slugify(title)
    if not base:
        raise ValidationError(f"can't derive an id from '{title}'; pass one with --id")
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _check_unique(content: Content, id_: str, own_path: Path) -> None:
    others = [p for p in content.all_ids().get(id_, []) if p != own_path]
    if others:
        raise ValidationError(f"id '{id_}' is already used by {others[0]}")


def parse_tags(value: str | Iterable[str] | None) -> list[str]:
    """``"a, b,a"`` -> ``["a", "b"]`` (order kept, blanks and duplicates dropped)."""
    if value is None:
        return []
    parts = value.split(",") if isinstance(value, str) else value
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))


def _yaml_lines(fields: dict[str, Any]) -> str:
    return "".join(f"{k}: {yaml_inline(v)}\n" for k, v in fields.items())


def _clean_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise ValidationError("title must not be empty")
    return title


# --- registry ---------------------------------------------------------------


def sync_registry(content: Content) -> Path:
    """Rewrite ``registry.yaml`` from the top-level projects on disk."""
    entries = [
        {
            "id": p.id,
            "path": p.path.relative_to(content.root).as_posix(),
            "status": p.status.value,
        }
        for p in content.projects()
        if p.parent is None
    ]
    body = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True) if entries else "[]\n"
    path = content.root / bootstrap.REGISTRY_FILE
    text = bootstrap.REGISTRY_HEADER + body
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path


# --- projects ---------------------------------------------------------------


def add_project(
    content: Content,
    title: str,
    *,
    id: str | None = None,
    priority: Priority = Priority.MED,
    tags: Iterable[str] = (),
    today: dt.date | None = None,
) -> Project:
    git_sync.require_repo(content.root)
    title = _clean_title(title)
    project_id = _new_id(content, title, id)
    directory = content.root / bootstrap.PROJECTS_DIR / project_id
    if directory.exists():
        raise ValidationError(f"directory already exists: {directory}")

    directory.mkdir(parents=True)
    (directory / PROJECT_FILE).write_text(
        _yaml_lines(
            {
                "id": project_id,
                "title": title,
                "status": ProjectStatus.ACTIVE.value,
                "priority": priority.value,
                "tags": parse_tags(tags),
                "related": [],
                "created": today or local_today(),
            }
        )
    )
    (directory / LOG_FILE).write_text("# Log\n\n")
    (directory / IDEAS_FILE).write_text("# Ideas\n\n")

    content.refresh()
    registry = sync_registry(content)
    git_sync.commit(content.root, f"project: add {project_id}", [directory, registry])
    return content.project(project_id)


# --- tasks ------------------------------------------------------------------

TASK_BODY_TEMPLATE = "# {title}\n\n## Context\n\n## Subtasks\n\n## Updates\n"


def add_task(
    content: Content,
    title: str,
    project: Project,
    *,
    id: str | None = None,
    priority: Priority = Priority.MED,
    due: dt.date | None = None,
    tags: Iterable[str] = (),
    today: dt.date | None = None,
) -> Task:
    git_sync.require_repo(content.root)
    title = _clean_title(title)
    task_id = _new_id(content, title, id)
    path = project.path / TASKS_DIR / f"{task_id}.md"
    if path.exists():
        raise ValidationError(f"file already exists: {path}")

    today = today or local_today()
    fields: dict[str, Any] = {
        "id": task_id,
        "project": project.id,
        "status": TaskStatus.TODO.value,
        "priority": priority.value,
        "tags": parse_tags(tags),
        "created": today,
        "updated": today,
    }
    if due is not None:
        fields["due"] = due
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{_yaml_lines(fields)}---\n\n{TASK_BODY_TEMPLATE.format(title=title)}")

    content.refresh()
    git_sync.commit(content.root, f"task: add {task_id}", [path])
    return content.task(task_id)


# --- editing ----------------------------------------------------------------


class EditSession:
    """Snapshot of a file before an external edit, so it can be validated,
    committed, or rolled back."""

    def __init__(self, path: Path):
        self.path = path
        self.original = path.read_text()

    def changed(self) -> bool:
        return self.path.read_text() != self.original

    def restore(self) -> None:
        self.path.write_text(self.original)


def _edit_message(kind: str, old_id: str, new_id: str) -> str:
    if old_id != new_id:
        return f"{kind}: rename {old_id} -> {new_id}"
    return f"{kind}: edit {new_id}"


def finish_task_edit(
    content: Content, task: Task, session: EditSession, *, today: dt.date | None = None
) -> Task | None:
    """Validate and commit an edited task file. Returns None if unchanged.

    Bumps ``updated`` to today unless the user changed it themselves. Raises
    ValidationError (without committing) if the file is no longer valid.
    """
    if not session.changed():
        return None
    git_sync.require_repo(content.root)
    edited = Task.load(task.path, task.project)
    content.refresh()
    _check_unique(content, edited.id, task.path)

    today = today or local_today()
    if edited.updated == task.updated and edited.updated != today:
        task.path.write_text(set_frontmatter_key(task.path.read_text(), "updated", today))

    git_sync.commit(content.root, _edit_message("task", task.id, edited.id), [task.path])
    content.refresh()
    return Task.load(task.path, task.project)


def finish_project_edit(content: Content, project: Project, session: EditSession) -> Project | None:
    """Validate and commit an edited ``project.yaml``. Returns None if unchanged."""
    if not session.changed():
        return None
    git_sync.require_repo(content.root)
    edited = Project.load(project.path, project.parent)
    content.refresh()
    _check_unique(content, edited.id, project.path / PROJECT_FILE)

    registry = sync_registry(content)
    git_sync.commit(
        content.root,
        _edit_message("project", project.id, edited.id),
        [project.path / PROJECT_FILE, registry],
    )
    content.refresh()
    return edited
