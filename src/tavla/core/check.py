"""Consistency checks over the whole content repo (``tv check``).

Files edited outside tavla are never validated when saved, so this finds what
tavla would otherwise refuse: files that don't load, duplicate ids, broken
task links, and goals/tasks whose ``project:`` line disagrees with the
project folder they are in. That last kind can be fixed by moving the file,
or, when the line names no known project, by resetting the line.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from tavla.core import bootstrap, ops, parsing
from tavla.core.entities import (
    DELIVERABLES_DIR,
    GOALS_DIR,
    PROJECT_FILE,
    TASKS_DIR,
    Deliverable,
    Goal,
    Project,
    Source,
    Task,
)
from tavla.core.errors import TavlaError, ValidationError
from tavla.core.store import Content

T = TypeVar("T")


@dataclass
class Problem:
    path: Path
    message: str
    # How --fix resolves it: "move" the file to the project its project: line
    # names, or "reset" a line naming no known project to the file's project.
    fix: str | None = None

    @property
    def fixable(self) -> bool:
        return self.fix is not None


def find_problems(content: Content) -> list[Problem]:
    """Every problem found, goals before tasks. Unlike the store, a file that
    fails to load is reported and skipped rather than stopping everything."""
    content.refresh()
    try:
        projects = content.projects()
    except ValidationError as e:
        # Goals and tasks hang off projects, so there is nothing more to check.
        return [_load_problem(content.root, e)]

    problems: list[Problem] = []

    def load_all(paths: list[tuple[Path, str]], load: Callable[[Path, str], T]) -> list[T]:
        items = []
        for path, project_id in paths:
            try:
                items.append(load(path, project_id))
            except ValidationError as e:
                problems.append(_load_problem(path, e))
        return items

    def files(subdir: str, pattern: str) -> list[tuple[Path, str]]:
        return [(f, p.id) for p in projects for f in sorted((p.path / subdir).glob(pattern))]

    goals = load_all(files(GOALS_DIR, "*.md"), Goal.load)
    tasks = load_all(files(TASKS_DIR, "*.md"), Task.load)
    deliverables = load_all(files(DELIVERABLES_DIR, "*.y*ml"), Deliverable.load)
    library = sorted((content.root / bootstrap.LIBRARY_DIR).glob("*.md"))
    sources = load_all([(f, "") for f in library], lambda path, _: Source.load(path))

    ids: dict[str, list[Path]] = {}
    for e in [*projects, *goals, *tasks, *deliverables, *sources]:
        path = e.path / PROJECT_FILE if isinstance(e, Project) else e.path
        ids.setdefault(e.id, []).append(path)
    for id_, paths in ids.items():
        for path in paths[1:]:
            problems.append(Problem(path, f"id '{id_}' is already used by {paths[0]}"))

    project_ids = {p.id for p in projects}
    for item in [*goals, *tasks]:
        wanted = item.meta.get("project")
        if wanted is None or str(wanted) == item.project:
            continue
        if str(wanted) in project_ids:
            message = f"project: says {wanted}, but the file is in project {item.project}"
            problems.append(Problem(item.path, message, fix="move"))
        else:
            message = f"project: unknown project '{wanted}' (the file is in {item.project})"
            problems.append(Problem(item.path, message, fix="reset"))

    # Tasks of a goal that failed to load would all report it as unknown.
    loaded = {g.path for g in goals}
    broken_goals = {_raw_id(path) for path, _ in files(GOALS_DIR, "*.md") if path not in loaded}
    for task in tasks:
        if task.goal in broken_goals:
            continue
        error = ops.task_link_error(task, goals, tasks)
        if error:
            problems.append(Problem(task.path, error))
    return problems


def _raw_id(path: Path) -> str | None:
    """The ``id:`` of a file that doesn't load as an entity, if it can be read."""
    try:
        meta, _ = parsing.read_markdown(path)
    except ValidationError:
        return None
    return str(meta["id"]) if meta.get("id") else None


def _load_problem(path: Path, error: ValidationError) -> Problem:
    message = str(error).removeprefix(f"{path}: ")
    return Problem(path, message)


def fix(content: Content) -> tuple[list[str], list[Problem]]:
    """Fix every fixable problem, one commit each: move goals/tasks to the
    project their ``project:`` line names (a goal's tasks move with it), and
    reset lines naming no known project. Returns what was done, and the
    fixable problems that could not be fixed, with the reason."""
    done: list[str] = []
    failed: list[Problem] = []
    tried: set[Path] = set()
    while True:
        todo = [p for p in find_problems(content) if p.fixable and p.path not in tried]
        if not todo:
            return done, failed
        problem = todo[0]
        tried.add(problem.path)
        try:
            item = next(i for i in [*content.goals(), *content.tasks()] if i.path == problem.path)
            kind = ops.kind_of(item)
            if problem.fix == "move":
                item = ops.relocate(content, item)
                done.append(f"Moved {kind} {item.id} to project {item.project}")
            else:
                ops.reset_project_line(content, item)
                done.append(f"Set project: of {kind} {item.id} to {item.project}")
        except TavlaError as e:
            failed.append(Problem(problem.path, str(e).removeprefix(f"{problem.path}: ")))
