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

from tavla.core import bootstrap, dates, git_sync
from tavla.core.entities import (
    DELIVERABLES_DIR,
    GOALS_DIR,
    IDEAS_FILE,
    IDEAS_HEADING,
    LOG_FILE,
    PROJECT_FILE,
    SUBPROJECTS_DIR,
    TASKS_DIR,
    UPDATES_HEADING,
    Deliverable,
    DeliverableKind,
    DeliverableStatus,
    Goal,
    GoalStatus,
    LogEntry,
    Priority,
    Project,
    ProjectStatus,
    Subtask,
    Task,
    TaskStatus,
)
from tavla.core.errors import AmbiguousIdError, NotFoundError, ValidationError
from tavla.core.parsing import (
    SUBTASKS_HEADING,
    append_to_section,
    checkbox_items,
    ensure_section,
    read_markdown,
    remove_frontmatter_key,
    remove_yaml_key,
    set_checkbox,
    set_first_heading,
    set_frontmatter_key,
    set_yaml_key,
    yaml_inline,
)
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


def apply_list_spec(current: Iterable[str], spec: str, what: str = "tags") -> list[str]:
    """Apply a list-editing option value (``--tags``, ``--after``) to a list.

    ``"a,b"`` replaces the list; ``"+a,-b"`` adds ``a`` and removes ``b``.
    Mixing the two forms is an error.
    """
    items = parse_tags(spec)
    signed = [t[0] in "+-" for t in items]
    if not any(signed):
        return items
    if not all(signed):
        raise ValidationError(f"{what} '{spec}': use either a,b (replace) or +a,-b (adjust)")
    tags = list(current)
    for item in items:
        name = item[1:].strip()
        if item[0] == "+" and name not in tags:
            tags.append(name)
        elif item[0] == "-" and name in tags:
            tags.remove(name)
    return tags


def _yaml_lines(fields: dict[str, Any]) -> str:
    return "".join(f"{k}: {yaml_inline(v)}\n" for k, v in fields.items())


def clean_title(title: str) -> str:
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
    parent: Project | None = None,
    today: dt.date | None = None,
) -> Project:
    """Create a project, or a subproject of ``parent``."""
    git_sync.require_repo(content.root)
    title = clean_title(title)
    project_id = _new_id(content, title, id)
    directory = _projects_dir(content, parent) / project_id
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
                "created": today or dates.local_today(),
            }
        )
    )
    (directory / LOG_FILE).write_text("# Log\n\n")
    (directory / IDEAS_FILE).write_text("# Ideas\n\n")

    content.refresh()
    registry = sync_registry(content)
    where = f" under {parent.id}" if parent else ""
    git_sync.commit(content.root, f"project: add {project_id}{where}", [directory, registry])
    return content.project(project_id)


def _projects_dir(content: Content, parent: Project | None) -> Path:
    """Where the project directories under ``parent`` (or top-level ones) live."""
    if parent is None:
        return content.root / bootstrap.PROJECTS_DIR
    return parent.path / SUBPROJECTS_DIR


def move_project(content: Content, project: Project, parent: Project | None) -> Project | None:
    """Make ``project`` a subproject of ``parent``, or top-level with None.

    Its directory moves with everything in it, subprojects included; goals and
    tasks follow because their project is the directory they live in. Returns
    None if it is already there.
    """
    git_sync.require_repo(content.root)
    new_parent = parent.id if parent else None
    if new_parent == project.parent:
        return None
    if parent is not None and (
        parent.id == project.id or parent.id in {d.id for d in content.descendants(project)}
    ):
        raise ValidationError(f"can't move {project.id} under {parent.id}: that is inside it")
    directory = _projects_dir(content, parent) / project.path.name
    if directory.exists():
        raise ValidationError(f"directory already exists: {directory}")

    directory.parent.mkdir(parents=True, exist_ok=True)
    project.path.rename(directory)
    if project.parent is not None and not any(project.path.parent.iterdir()):
        project.path.parent.rmdir()  # the old parent's now-empty subprojects/
    content.refresh()
    registry = sync_registry(content)
    where = f"under {parent.id}" if parent else "to top level"
    git_sync.commit(
        content.root, f"project: move {project.id} {where}", [project.path, directory, registry]
    )
    return content.project(project.id)


# --- goals & tasks ------------------------------------------------------------

GOAL_BODY_TEMPLATE = "# {title}\n\n## Context\n\n## Ideas\n\n## Updates\n"
TASK_BODY_TEMPLATE = "# {title}\n\n## Instructions\n\n## Subtasks\n\n## Ideas\n\n## Updates\n"

Item = Goal | Task


def kind_of(item: Item) -> str:
    return "goal" if isinstance(item, Goal) else "task"


def _reload(item: Item) -> Item:
    """Re-read just this file (no goal inheritance or dependency state)."""
    return type(item).load(item.path, item.project)


def _fresh(content: Content, item: Item, path: Path | None = None) -> Item:
    """The item as the store sees it now (with inherited fields etc.), read
    from ``path`` if its file has moved."""
    content.refresh()
    items = content.goals() if isinstance(item, Goal) else content.tasks()
    return next(i for i in items if i.path == (path or item.path))


def _write_new(content: Content, path: Path, fields: dict[str, Any], body: str) -> None:
    if path.exists():
        raise ValidationError(f"file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{_yaml_lines(fields)}---\n\n{body}")


def add_goal(
    content: Content,
    title: str,
    project: Project,
    *,
    id: str | None = None,
    priority: Priority = Priority.MED,
    due: dt.date | None = None,
    tags: Iterable[str] = (),
    today: dt.date | None = None,
    extra_paths: Iterable[Path] = (),
) -> Goal:
    git_sync.require_repo(content.root)
    title = clean_title(title)
    goal_id = _new_id(content, title, id)
    path = project.path / GOALS_DIR / f"{goal_id}.md"
    today = today or dates.local_today()
    fields: dict[str, Any] = {
        "id": goal_id,
        "project": project.id,
        "status": GoalStatus.TODO.value,
        "priority": priority.value,
        "tags": parse_tags(tags),
        "created": today,
        "updated": today,
    }
    if due is not None:
        fields["due"] = due
    _write_new(content, path, fields, GOAL_BODY_TEMPLATE.format(title=title))
    content.refresh()
    git_sync.commit(content.root, f"goal: add {goal_id}", [path, *extra_paths])
    return content.goal(goal_id)


def add_task(
    content: Content,
    title: str,
    project: Project | None = None,
    *,
    goal: Goal | None = None,
    id: str | None = None,
    priority: Priority | None = None,
    due: dt.date | None = None,
    tags: Iterable[str] = (),
    depends_on: Iterable[str] = (),
    today: dt.date | None = None,
    extra_paths: Iterable[Path] = (),
) -> Task:
    """Create a task under ``goal`` (in the goal's project) or, without a goal,
    directly in ``project``. Without ``priority``, a goal's task inherits the
    goal's priority; a loose task gets ``med``."""
    git_sync.require_repo(content.root)
    if goal is not None:
        if project is not None and project.id != goal.project:
            raise ValidationError(f"goal '{goal.id}' belongs to project {goal.project}")
        project = content.project(goal.project)
    if project is None:
        raise ValidationError("a task needs a goal or a project")
    title = clean_title(title)
    task_id = _new_id(content, title, id)
    path = project.path / TASKS_DIR / f"{task_id}.md"
    if goal is None and priority is None:
        priority = Priority.MED
    today = today or dates.local_today()
    fields: dict[str, Any] = {"id": task_id, "project": project.id}
    if goal is not None:
        fields["goal"] = goal.id
    fields["status"] = TaskStatus.TODO.value
    if priority is not None:
        fields["priority"] = priority.value
    deps = list(depends_on)
    if deps:
        fields["depends_on"] = deps
    fields |= {"tags": parse_tags(tags), "created": today, "updated": today}
    if due is not None:
        fields["due"] = due
    _write_new(content, path, fields, TASK_BODY_TEMPLATE.format(title=title))
    try:
        _check_task_links(content, Task.load(path, project.id))
    except ValidationError:
        path.unlink()
        content.refresh()
        raise
    git_sync.commit(content.root, f"task: add {task_id}", [path, *extra_paths])
    return content.task(task_id)


def _find_cycle(start: str, deps: dict[str, list[str]]) -> list[str] | None:
    """A dependency path from ``start`` back to itself, if there is one."""
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    seen: set[str] = set()
    while stack:
        node, path = stack.pop()
        for nxt in deps.get(node, []):
            if nxt == start:
                return [*path, start]
            if nxt not in seen:
                seen.add(nxt)
                stack.append((nxt, [*path, nxt]))
    return None


def _check_task_links(content: Content, task: Task) -> None:
    """Validate a task's goal pointer and dependencies against what's on disk
    (the task's own file included): the goal must exist in the task's project,
    every dependency must be a known task, and there must be no cycle."""
    content.refresh()
    error = task_link_error(task, content.goals(), content.tasks())
    if error:
        raise ValidationError(f"{task.path}: {error}")


def task_link_error(task: Task, goals: Iterable[Goal], tasks: Iterable[Task]) -> str | None:
    """What is wrong with ``task``'s goal pointer or dependencies, if anything."""
    if task.goal:
        goal = next((g for g in goals if g.id == task.goal), None)
        if goal is None:
            return f"unknown goal '{task.goal}'"
        if goal.project != task.project:
            return f"goal '{goal.id}' is in project {goal.project}, not {task.project}"
    deps = {t.id: t.depends_on for t in tasks}
    for dep in task.depends_on:
        if dep not in deps:
            return f"depends_on: unknown task '{dep}'"
    cycle = _find_cycle(task.id, deps)
    if cycle:
        return f"dependency cycle: {' -> '.join(cycle)}"
    return None


def _links_changed(old: Item, new: Item) -> bool:
    if not isinstance(old, Task) or not isinstance(new, Task):
        return False
    return (old.id, old.goal, old.depends_on) != (new.id, new.goal, new.depends_on)


def _rename_references(content: Content, item: Item, old_id: str, new_id: str) -> list[Path]:
    """After a goal/task id change, update tasks that point at the old id
    (``goal:`` for goals, ``depends_on:`` for tasks). Returns changed files."""
    changed = []
    for task in content.tasks():
        if task.path == item.path:
            continue
        text = task.path.read_text()
        if isinstance(item, Goal) and task.goal == old_id:
            text = set_frontmatter_key(text, "goal", new_id)
        elif isinstance(item, Task) and old_id in task.depends_on:
            deps = [new_id if d == old_id else d for d in task.depends_on]
            text = set_frontmatter_key(text, "depends_on", deps)
        else:
            continue
        task.path.write_text(text)
        changed.append(task.path)
    return changed


def goal_to_task(
    content: Content, goal: Goal, *, under: Goal | None = None, today: dt.date | None = None
) -> Task:
    """Turn a goal into a task in the same project: loose, or under another
    goal ``under``. The file moves from ``goals/`` to ``tasks/`` with its
    frontmatter and notes intact (a ``## Subtasks`` section is added if
    missing). Refused while tasks still point at the goal.
    """
    git_sync.require_repo(content.root)
    children = content.goal_tasks(goal)
    if children:
        ids = ", ".join(t.id for t in children)
        raise ValidationError(
            f"goal '{goal.id}' still has tasks ({ids}); move or finish them first"
        )
    if under is not None and under.project != goal.project:
        raise ValidationError(
            f"goal '{under.id}' is in project {under.project}, not {goal.project}"
        )
    project = content.project(goal.project)
    path = project.path / TASKS_DIR / goal.path.name
    if path.exists():
        raise ValidationError(f"file already exists: {path}")

    original = text = goal.path.read_text()
    if under is not None:
        text = set_frontmatter_key(text, "goal", under.id)
    text = set_frontmatter_key(text, "updated", today or dates.local_today())
    text = ensure_section(text, SUBTASKS_HEADING, before=(IDEAS_HEADING, UPDATES_HEADING))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    goal.path.unlink()
    try:
        _check_task_links(content, Task.load(path, project.id))
    except ValidationError:
        path.unlink()
        goal.path.write_text(original)
        content.refresh()
        raise
    where = f" under {under.id}" if under else ""
    git_sync.commit(content.root, f"goal: to-task {goal.id}{where}", [goal.path, path])
    content.refresh()
    return content.task(goal.id)


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


def _normalize_dates(path: Path, entity: Any, keys: Iterable[str], *, frontmatter: bool) -> None:
    """Rewrite hand-typed day-first dates (``01.10.2026``) as ISO, in place.

    YAML already loads ISO dates as dates, so a string value that the entity
    parsed as a date is one the user typed in another format.
    """
    setter = set_frontmatter_key if frontmatter else set_yaml_key
    text = original = path.read_text()
    for key in keys:
        value = entity.meta.get(key)
        if isinstance(value, str) and value.strip():
            text = setter(text, key, getattr(entity, key))
    if text != original:
        path.write_text(text)


def _edit_message(kind: str, old_id: str, new_id: str) -> str:
    if old_id != new_id:
        return f"{kind}: rename {old_id} -> {new_id}"
    return f"{kind}: edit {new_id}"


def _finish_item_change(
    content: Content,
    item: Item,
    edited: Item,
    message: str,
    today: dt.date | None,
    *,
    bump: bool,
    relocating: bool = False,
) -> Item:
    """Shared tail of editor and field edits: link checks, id-rename
    propagation, ``updated`` bump, commit."""
    content.refresh()
    _check_unique(content, edited.id, item.path)
    target = _target_project(content, item, edited, relocating=relocating)
    if target is not None:
        edited.project = target.id
    if isinstance(edited, Task) and (target is not None or _links_changed(item, edited)):
        _check_task_links(content, edited)
    moves = _project_moves(content, item, target) if target is not None else []
    today = today or dates.local_today()
    if bump and edited.updated == item.updated and edited.updated != today:
        item.path.write_text(set_frontmatter_key(item.path.read_text(), "updated", today))
    paths = [item.path]
    if edited.id != item.id:
        paths += _rename_references(content, item, item.id, edited.id)
    for src, dst in moves:
        text = set_frontmatter_key(src.read_text(), "project", target.id)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text)
        src.unlink()
        paths += [src, dst]
    if target is not None:
        message += f" -> project {target.id}"
    git_sync.commit(content.root, message, paths)
    return _fresh(content, item, moves[0][1] if moves else None)


def relocate(content: Content, item: Item) -> Item:
    """Move ``item`` to the project its ``project:`` line names, as if that
    line had just been edited (a goal's tasks come along). Raises
    ValidationError, leaving everything in place, if the move isn't possible."""
    git_sync.require_repo(content.root)
    message = f"{kind_of(item)}: move {item.id}"
    return _finish_item_change(
        content, item, _reload(item), message, None, bump=False, relocating=True
    )


def reset_project_line(content: Content, item: Item) -> Item:
    """Set ``item``'s ``project:`` line back to the project whose folder it is in."""
    git_sync.require_repo(content.root)
    item.path.write_text(set_frontmatter_key(item.path.read_text(), "project", item.project))
    git_sync.commit(
        content.root, f"{kind_of(item)}: set project of {item.id} to {item.project}", [item.path]
    )
    return _fresh(content, item)


def _target_project(
    content: Content, item: Item, edited: Item, *, relocating: bool = False
) -> Project | None:
    """The project the edited file's ``project:`` field names, when the edit
    changed that line (or when ``relocating``) and it is not the project whose
    directory the file is in. An untouched stale line never blocks an edit."""
    wanted = edited.meta.get("project")
    if not relocating and wanted == item.meta.get("project"):
        return None
    if wanted is None or str(wanted) == item.project:
        return None
    project = next((p for p in content.projects() if p.id == str(wanted)), None)
    if project is None:
        raise ValidationError(f"{item.path}: project: unknown project '{wanted}'")
    return project


def _project_moves(content: Content, item: Item, project: Project) -> list[tuple[Path, Path]]:
    """(from, to) file moves that put ``item`` in ``project``, the item first.
    A goal takes its tasks along, since a task lives in its goal's project."""
    subdir = GOALS_DIR if isinstance(item, Goal) else TASKS_DIR
    moves = [(item.path, project.path / subdir / item.path.name)]
    if isinstance(item, Goal):
        moves += [
            (t.path, project.path / TASKS_DIR / t.path.name) for t in content.goal_tasks(item)
        ]
    for _, dst in moves:
        if dst.exists():
            raise ValidationError(f"can't move to project {project.id}: {dst} already exists")
    return moves


def finish_edit(
    content: Content, item: Item, session: EditSession, *, today: dt.date | None = None
) -> Item | None:
    """Validate and commit an edited goal or task file. Returns None if unchanged.

    Bumps ``updated`` to today unless the user changed it themselves. Raises
    ValidationError (without committing) if the file is no longer valid.
    """
    if not session.changed():
        return None
    git_sync.require_repo(content.root)
    edited = _reload(item)
    _normalize_dates(item.path, edited, ("created", "updated", "due"), frontmatter=True)
    return _finish_item_change(
        content, item, edited, _edit_message(kind_of(item), item.id, edited.id), today, bump=True
    )


def finish_project_edit(content: Content, project: Project, session: EditSession) -> Project | None:
    """Validate and commit an edited ``project.yaml``. Returns None if unchanged."""
    if not session.changed():
        return None
    git_sync.require_repo(content.root)
    edited = Project.load(project.path, project.parent)
    content.refresh()
    _check_unique(content, edited.id, project.path / PROJECT_FILE)
    _normalize_dates(project.path / PROJECT_FILE, edited, ("created",), frontmatter=False)

    registry = sync_registry(content)
    git_sync.commit(
        content.root,
        _edit_message("project", project.id, edited.id),
        [project.path / PROJECT_FILE, registry, *_retag_items(project, edited.id)],
    )
    content.refresh()
    return edited


# --- field edits (no editor) --------------------------------------------------
#
# ``changes`` maps a top-level key to its new value, or to None to remove it.
# Only the affected lines are rewritten, so comments and field order survive.


def _apply_changes(text: str, changes: dict[str, Any], *, frontmatter: bool) -> str:
    setter = set_frontmatter_key if frontmatter else set_yaml_key
    remover = remove_frontmatter_key if frontmatter else remove_yaml_key
    for key, value in changes.items():
        text = remover(text, key) if value is None else setter(text, key, value)
    return text


def set_fields(
    content: Content,
    item: Item,
    changes: dict[str, Any],
    *,
    title: str | None = None,
    today: dt.date | None = None,
) -> Item | None:
    """Set frontmatter fields (and optionally the ``# title`` heading) of a
    goal or task.

    Bumps ``updated`` unless it is among ``changes``. Returns None if nothing
    changed; raises ValidationError (leaving the file untouched) if the result
    would be invalid.
    """
    git_sync.require_repo(content.root)
    original = item.path.read_text()
    text = _apply_changes(original, changes, frontmatter=True)
    keys = list(changes)
    if title is not None:
        title = clean_title(title)
        retitled = set_first_heading(text, title)
        text = retitled if retitled is not None else set_frontmatter_key(text, "title", title)
        keys.append("title")
    if text == original:
        return None
    if "updated" not in changes:
        text = set_frontmatter_key(text, "updated", today or dates.local_today())
    item.path.write_text(text)
    try:
        edited = _reload(item)
        message = f"{kind_of(item)}: edit {item.id} ({', '.join(keys)})"
        return _finish_item_change(content, item, edited, message, today, bump=False)
    except ValidationError:
        item.path.write_text(original)
        content.refresh()
        raise


def set_project_fields(
    content: Content, project: Project, changes: dict[str, Any]
) -> Project | None:
    """Set top-level fields in ``project.yaml``. Returns None if nothing changed."""
    git_sync.require_repo(content.root)
    path = project.path / PROJECT_FILE
    original = path.read_text()
    text = _apply_changes(original, changes, frontmatter=False)
    if text == original:
        return None
    path.write_text(text)
    try:
        Project.load(project.path, project.parent)
    except ValidationError:
        path.write_text(original)
        raise
    content.refresh()
    registry = sync_registry(content)
    edited = Project.load(project.path, project.parent)
    git_sync.commit(
        content.root,
        f"project: edit {project.id} ({', '.join(changes)})",
        [path, registry, *_retag_items(project, edited.id)],
    )
    content.refresh()
    return edited


def _retag_items(project: Project, new_id: str) -> list[Path]:
    """After a project id change, point the ``project:`` lines of its own
    goals and tasks at ``new_id``. Returns changed files."""
    if new_id == project.id:
        return []
    changed = []
    for path in sorted(
        [*project.path.glob(f"{GOALS_DIR}/*.md"), *project.path.glob(f"{TASKS_DIR}/*.md")]
    ):
        text = path.read_text()
        meta, _ = read_markdown(path)
        if meta.get("project") == project.id:
            path.write_text(set_frontmatter_key(text, "project", new_id))
            changed.append(path)
    return changed


# --- append-only capture ------------------------------------------------------

COMMIT_SUMMARY_LEN = 50


def one_line(text: str, what: str) -> str:
    line = " ".join(text.split())
    if not line:
        raise ValidationError(f"{what} must not be empty")
    return line


def summary(text: str) -> str:
    return text if len(text) <= COMMIT_SUMMARY_LEN else text[: COMMIT_SUMMARY_LEN - 1] + "…"


def append_line(path: Path, line: str, header: str) -> None:
    """Append ``line`` to ``path``, creating it with ``header`` if missing."""
    existing = path.read_text() if path.exists() else header
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(f"{existing}{line}\n")


def append_log(
    content: Content, project: Project, text: str, *, now: dt.datetime | None = None
) -> LogEntry:
    """Append a timestamped ``- YYYY-MM-DD HH:MM: text`` line to the project's log.md."""
    git_sync.require_repo(content.root)
    line = one_line(text, "log text")
    now = now or dates.local_now()
    path = project.path / LOG_FILE
    append_line(path, f"- {now:%Y-%m-%d %H:%M}: {line}", "# Log\n\n")
    git_sync.commit(content.root, f"log: {project.id}: {summary(line)}", [path])
    return LogEntry(date=now.date(), time=now.time(), text=line)


# --- goal & task lifecycle ------------------------------------------------------


def set_status(
    content: Content,
    item: Item,
    status: TaskStatus,
    *,
    verb: str | None = None,
    today: dt.date | None = None,
) -> Item | None:
    """Change a goal's or task's status (and bump ``updated``), touching only
    those two frontmatter lines. Returns None if it already has that status."""
    if item.status == status:
        return None
    git_sync.require_repo(content.root)
    today = today or dates.local_today()
    text = set_frontmatter_key(item.path.read_text(), "status", status.value)
    item.path.write_text(set_frontmatter_key(text, "updated", today))
    git_sync.commit(content.root, f"{kind_of(item)}: {verb or status.value} {item.id}", [item.path])
    return _fresh(content, item)


def complete(content: Content, item: Item, *, today: dt.date | None = None) -> Item | None:
    return set_status(content, item, TaskStatus.DONE, verb="done", today=today)


def start(content: Content, item: Item, *, today: dt.date | None = None) -> Item | None:
    return set_status(content, item, TaskStatus.DOING, verb="start", today=today)


def drop(content: Content, item: Item | Deliverable) -> None:
    """Delete a goal, task or deliverable file (it stays in git history).

    Refused (see :func:`check_droppable`) while something points at it.
    """
    git_sync.require_repo(content.root)
    check_droppable(content, item)
    kind = "deliverable" if isinstance(item, Deliverable) else kind_of(item)
    item.path.unlink()
    content.refresh()
    git_sync.commit(content.root, f"{kind}: drop {item.id}", [item.path])


def check_droppable(content: Content, item: Item | Deliverable) -> None:
    """Raise ValidationError if tasks still point at ``item``: tasks under a
    goal, or tasks that depend on a task."""
    if isinstance(item, Goal):
        children = content.goal_tasks(item)
        if children:
            ids = ", ".join(t.id for t in children)
            raise ValidationError(
                f"goal '{item.id}' still has tasks ({ids}); move or drop them first"
            )
    elif isinstance(item, Task):
        dependents = [t.id for t in content.tasks() if item.id in t.depends_on]
        if dependents:
            raise ValidationError(
                f"tasks depend on '{item.id}' ({', '.join(dependents)}); "
                "remove the dependency first"
            )


# --- subtasks & updates -----------------------------------------------------------


def resolve_subtask(task: Task, ref: str) -> Subtask:
    """A subtask by number (``2``) or by a unique piece of its text."""
    ref = ref.strip()
    if ref.isdigit():
        n = int(ref)
        if not 1 <= n <= len(task.subtasks):
            raise NotFoundError(f"no subtask {n} in {task.id} (it has {len(task.subtasks)})")
        return task.subtasks[n - 1]
    matches = [s for s in task.subtasks if ref and ref.lower() in s.text.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFoundError(f"no subtask in {task.id} matching '{ref}'")
    raise AmbiguousIdError(ref, [f"{s.number}. {s.text}" for s in matches])


def check_subtasks(
    content: Content,
    task: Task,
    subtasks: Iterable[Subtask],
    *,
    done: bool = True,
    today: dt.date | None = None,
) -> Task | None:
    """Tick (or with ``done=False`` untick) subtasks of ``task``.

    Returns the updated task, or None if they were all already in that state.
    """
    git_sync.require_repo(content.root)
    changed = {s.number: s for s in subtasks if s.done != done}
    if not changed:
        return None
    text = task.path.read_text()
    items = checkbox_items(text)
    if len(items) != len(task.subtasks):
        raise ValidationError(f"{task.path} changed on disk; try again")
    for n in changed:
        text = set_checkbox(text, items[n - 1][0], done)
    task.path.write_text(set_frontmatter_key(text, "updated", today or dates.local_today()))
    verb = "check" if done else "uncheck"
    what = next(iter(changed.values())).text if len(changed) == 1 else f"{len(changed)} subtasks"
    git_sync.commit(content.root, f"task: {verb} {task.id}: {summary(what)}", [task.path])
    return _fresh(content, task)


def add_subtask(content: Content, task: Task, text: str, *, today: dt.date | None = None) -> Task:
    """Append an unchecked ``- [ ] text`` item to the task's ``## Subtasks``."""
    git_sync.require_repo(content.root)
    line = one_line(text, "subtask")
    body = task.path.read_text()
    body = ensure_section(body, SUBTASKS_HEADING, before=(IDEAS_HEADING, UPDATES_HEADING))
    body = append_to_section(body, SUBTASKS_HEADING, f"- [ ] {line}")
    task.path.write_text(set_frontmatter_key(body, "updated", today or dates.local_today()))
    git_sync.commit(content.root, f"task: subtask {task.id}: {summary(line)}", [task.path])
    return _fresh(content, task)


def add_update(
    content: Content, item: Item, text: str, *, now: dt.datetime | None = None
) -> LogEntry:
    """Append a timestamped ``- YYYY-MM-DD HH:MM: text`` line to the goal's or
    task's ``## Updates`` section (created at the end if missing)."""
    git_sync.require_repo(content.root)
    line = one_line(text, "update")
    now = now or dates.local_now()
    body = append_to_section(
        item.path.read_text(), UPDATES_HEADING, f"- {now:%Y-%m-%d %H:%M}: {line}"
    )
    item.path.write_text(set_frontmatter_key(body, "updated", now.date()))
    git_sync.commit(content.root, f"{kind_of(item)}: note {item.id}: {summary(line)}", [item.path])
    content.refresh()
    return LogEntry(date=now.date(), time=now.time(), text=line)


# --- deliverables -------------------------------------------------------------------


def add_deliverable(
    content: Content,
    title: str,
    project: Project,
    *,
    id: str | None = None,
    kind: DeliverableKind = DeliverableKind.PAPER,
    venue: str | None = None,
    deadline: dt.date | None = None,
    coauthors: Iterable[str] = (),
) -> Deliverable:
    git_sync.require_repo(content.root)
    title = clean_title(title)
    deliverable_id = _new_id(content, title, id)
    path = project.path / DELIVERABLES_DIR / f"{deliverable_id}.yaml"
    if path.exists():
        raise ValidationError(f"file already exists: {path}")
    fields: dict[str, Any] = {
        "id": deliverable_id,
        "title": title,
        "kind": kind.value,
        "status": DeliverableStatus.DRAFTING.value,
    }
    if venue:
        fields["venue"] = " ".join(venue.split())
    if deadline is not None:
        fields["deadline"] = deadline
    fields["coauthors"] = parse_tags(coauthors)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml_lines(fields))
    git_sync.commit(content.root, f"deliverable: add {deliverable_id}", [path])
    return content.deliverable(deliverable_id)


def set_deliverable_fields(
    content: Content, deliverable: Deliverable, changes: dict[str, Any]
) -> Deliverable | None:
    """Set top-level fields of a deliverable's YAML file. Returns None if nothing changed."""
    git_sync.require_repo(content.root)
    path = deliverable.path
    original = path.read_text()
    text = _apply_changes(original, changes, frontmatter=False)
    if text == original:
        return None
    path.write_text(text)
    try:
        edited = Deliverable.load(path, deliverable.project)
    except ValidationError:
        path.write_text(original)
        raise
    git_sync.commit(
        content.root, f"deliverable: edit {deliverable.id} ({', '.join(changes)})", [path]
    )
    return edited


def finish_deliverable_edit(
    content: Content, deliverable: Deliverable, session: EditSession
) -> Deliverable | None:
    """Validate and commit an edited deliverable file. Returns None if unchanged."""
    if not session.changed():
        return None
    git_sync.require_repo(content.root)
    edited = Deliverable.load(deliverable.path, deliverable.project)
    content.refresh()
    _check_unique(content, edited.id, deliverable.path)
    _normalize_dates(deliverable.path, edited, ("deadline",), frontmatter=False)
    git_sync.commit(
        content.root,
        _edit_message("deliverable", deliverable.id, edited.id),
        [deliverable.path],
    )
    return Deliverable.load(deliverable.path, deliverable.project)
