"""Read access to a content directory.

The filesystem is the source of truth: projects, tasks etc. are discovered by
scanning at query time (no index). A :class:`Content` instance caches what it
has scanned; call :meth:`Content.refresh` after files change.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tavla.core import bootstrap, parsing
from tavla.core.entities import (
    DELIVERABLES_DIR,
    GOALS_DIR,
    IDEAS_FILE,
    LOG_FILE,
    PROJECT_FILE,
    REFERENCES_FILE,
    SUBPROJECTS_DIR,
    TASKS_DIR,
    Deliverable,
    Goal,
    Idea,
    LogEntry,
    Project,
    Reference,
    Source,
    Task,
    TaskStatus,
    parse_ideas,
    parse_log,
    parse_references,
)
from tavla.core.errors import TavlaError
from tavla.core.queries import resolve_id


class Content:
    def __init__(self, root: Path):
        self.root = root
        self._projects: list[Project] | None = None
        self._goals: list[Goal] | None = None
        self._tasks: list[Task] | None = None

    @classmethod
    def open(cls, root: Path) -> Content:
        """Open an initialized content repo whose layout this tavla understands."""
        if not bootstrap.is_initialized(root):
            raise TavlaError(f"no tavla content repo at {root} (run `tavla init`)")
        version = bootstrap.schema_version(root)
        if version < bootstrap.SCHEMA_VERSION:
            raise TavlaError(
                f"content at {root} uses layout v{version}; this tavla needs "
                f"v{bootstrap.SCHEMA_VERSION}. Run `tavla migrate` (try --dry-run first)."
            )
        if version > bootstrap.SCHEMA_VERSION:
            raise TavlaError(
                f"content at {root} uses layout v{version}, newer than this tavla "
                f"supports (v{bootstrap.SCHEMA_VERSION}); update tavla"
            )
        return cls(root)

    def refresh(self) -> None:
        self._projects = None
        self._goals = None
        self._tasks = None

    def all_ids(self) -> dict[str, list[Path]]:
        """Every entity id in the tree (projects, tasks, deliverables, sources)
        mapped to the file(s) defining it. Ids must be globally unique."""
        ids: dict[str, list[Path]] = {}
        entities = [
            *self.projects(),
            *self.goals(),
            *self.tasks(),
            *self.deliverables(),
            *self.sources(),
        ]
        for e in entities:
            path = e.path / PROJECT_FILE if isinstance(e, Project) else e.path
            ids.setdefault(e.id, []).append(path)
        return ids

    # --- projects -----------------------------------------------------------

    def projects(self) -> list[Project]:
        """All projects, depth-first, each parent before its subprojects."""
        if self._projects is None:
            self._projects = list(self._walk(self.root / bootstrap.PROJECTS_DIR, None))
        return self._projects

    def _walk(self, directory: Path, parent: str | None) -> Iterator[Project]:
        if not directory.is_dir():
            return
        for child in sorted(directory.iterdir()):
            if not (child / PROJECT_FILE).is_file():
                continue
            project = Project.load(child, parent)
            yield project
            yield from self._walk(child / SUBPROJECTS_DIR, project.id)

    def project(self, query: str) -> Project:
        return resolve_id(query, self.projects(), "project")

    def children(self, project: Project) -> list[Project]:
        return [p for p in self.projects() if p.parent == project.id]

    def descendants(self, project: Project) -> list[Project]:
        out = []
        for child in self.children(project):
            out.append(child)
            out.extend(self.descendants(child))
        return out

    def _scope(self, project: Project | None, recursive: bool) -> set[str] | None:
        if project is None:
            return None
        wanted = {project.id}
        if recursive:
            wanted |= {p.id for p in self.descendants(project)}
        return wanted

    # --- goals --------------------------------------------------------------

    def goals(self, project: Project | None = None, *, recursive: bool = True) -> list[Goal]:
        """All goals, or those of ``project`` (and its subprojects if recursive).

        Each goal's ``tasks_done``/``tasks_total`` count the tasks pointing at it.
        """
        if self._goals is None:
            self._load()
        assert self._goals is not None
        wanted = self._scope(project, recursive)
        return self._goals if wanted is None else [g for g in self._goals if g.project in wanted]

    def goal(self, query: str) -> Goal:
        return resolve_id(query, self.goals(), "goal")

    def goal_tasks(self, goal: Goal) -> list[Task]:
        return [t for t in self.tasks() if t.goal == goal.id]

    # --- tasks --------------------------------------------------------------

    def tasks(self, project: Project | None = None, *, recursive: bool = True) -> list[Task]:
        """All tasks, or those of ``project`` (and its subprojects if recursive)."""
        if self._tasks is None:
            self._load()
        assert self._tasks is not None
        wanted = self._scope(project, recursive)
        return self._tasks if wanted is None else [t for t in self._tasks if t.project in wanted]

    def task(self, query: str) -> Task:
        return resolve_id(query, self.tasks(), "task")

    def _load(self) -> None:
        """Load goals and tasks together, then link them: goal progress,
        inherited task priority/due, and unfinished dependencies."""
        projects = self.projects()
        goals = [
            Goal.load(path, p.id)
            for p in projects
            for path in sorted((p.path / GOALS_DIR).glob("*.md"))
        ]
        tasks = [
            Task.load(path, p.id)
            for p in projects
            for path in sorted((p.path / TASKS_DIR).glob("*.md"))
        ]
        goals_by_id = {g.id: g for g in goals}
        status_by_id = {t.id: t.status for t in tasks}
        for task in tasks:
            goal = goals_by_id.get(task.goal) if task.goal else None
            if goal is not None:
                goal.tasks_total += 1
                goal.tasks_done += task.status == TaskStatus.DONE
                if "priority" not in task.meta:
                    task.priority = goal.priority
                    task.inherited.append("priority")
                if task.due is None and goal.due is not None:
                    task.due = goal.due
                    task.inherited.append("due")
            # A dependency on an unknown id counts as unfinished, so a typo is
            # noticed rather than silently ignored.
            task.waiting_on = [d for d in task.depends_on if status_by_id.get(d) != TaskStatus.DONE]
        self._goals, self._tasks = goals, tasks

    # --- other per-project files ---------------------------------------------

    def deliverables(self, project: Project | None = None) -> list[Deliverable]:
        projects = [project] if project else self.projects()
        return [
            Deliverable.load(path, p.id)
            for p in projects
            for path in sorted((p.path / DELIVERABLES_DIR).glob("*.y*ml"))
        ]

    def deliverable(self, query: str) -> Deliverable:
        return resolve_id(query, self.deliverables(), "deliverable")

    def log(self, project: Project) -> list[LogEntry]:
        path = project.path / LOG_FILE
        return parse_log(path.read_text()) if path.is_file() else []

    def ideas(self, project: Project) -> list[Idea]:
        path = project.path / IDEAS_FILE
        return parse_ideas(path.read_text()) if path.is_file() else []

    def references(self, project: Project) -> list[Reference]:
        path = project.path / REFERENCES_FILE
        return parse_references(parsing.read_yaml(path), path) if path.is_file() else []

    # --- global files -------------------------------------------------------

    def inbox(self) -> list[Idea]:
        path = self.root / bootstrap.INBOX_FILE
        return parse_ideas(path.read_text()) if path.is_file() else []

    def sources(self) -> list[Source]:
        return [
            Source.load(path) for path in sorted((self.root / bootstrap.LIBRARY_DIR).glob("*.md"))
        ]
