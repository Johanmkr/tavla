"""Id resolution and the cross-project aggregation queries (``next``, ``status``)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, TypeVar

from tavla.core import dates
from tavla.core.entities import (
    Deliverable,
    DeliverableStatus,
    Priority,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)
from tavla.core.errors import AmbiguousIdError, NotFoundError

if TYPE_CHECKING:
    from tavla.core.store import Content


class HasId(Protocol):
    id: str


T = TypeVar("T", bound=HasId)


def resolve_id(query: str, items: Iterable[T], kind: str = "item") -> T:
    """Resolve ``query`` to exactly one item by exact id, else unique prefix.

    Raises NotFoundError if nothing matches and AmbiguousIdError (listing the
    candidates) if several do — never guesses.
    """
    items = list(items)
    exact = [i for i in items if i.id == query]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        # Duplicate ids on disk (e.g. a hand-edited file). Show where they are.
        raise AmbiguousIdError(query, [f"{i.id} ({getattr(i, 'path', '?')})" for i in exact])
    matches = [i for i in items if i.id.startswith(query)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFoundError(f"no {kind} matching '{query}'")
    raise AmbiguousIdError(query, sorted(i.id for i in matches))


def complete_ids(prefix: str, items: Iterable[HasId]) -> list[str]:
    return sorted({i.id for i in items if i.id.startswith(prefix)})


# --- shared helpers -----------------------------------------------------------

OPEN_TASK_STATUSES = (TaskStatus.TODO, TaskStatus.DOING)
FINISHED_DELIVERABLE_STATUSES = (DeliverableStatus.ACCEPTED, DeliverableStatus.PUBLISHED)


def active_projects(content: Content) -> list[Project]:
    """Projects that are active *and* whose ancestors are all active — a
    subproject of a paused project is effectively paused too."""
    by_id = {p.id: p for p in content.projects()}
    active: list[Project] = []
    for project in content.projects():
        p: Project | None = project
        while p is not None and p.status == ProjectStatus.ACTIVE:
            p = by_id.get(p.parent) if p.parent else None
            if p is None:
                active.append(project)
    return active


def last_activity(content: Content, project: Project) -> dt.date | None:
    """Most recent date of any log entry or task created/updated in the project
    or its subprojects (falls back to the project's ``created`` date)."""
    candidates: list[dt.date] = []
    for p in [project, *content.descendants(project)]:
        candidates += [e.date for e in content.log(p)]
    for t in content.tasks(project):
        candidates += [d for d in (t.updated, t.created) if d]
    if not candidates and project.created:
        candidates.append(project.created)
    return max(candidates, default=None)


# --- next ---------------------------------------------------------------------


def next_tasks(
    content: Content,
    *,
    project: Project | None = None,
    min_priority: Priority | None = None,
) -> list[Task]:
    """Open tasks, most important first.

    Without ``project``: tasks from effectively active projects. With
    ``project``: that project and its subprojects, whatever their status (you
    asked for it explicitly). ``min_priority`` keeps tasks at or above it.

    Order: task priority, doing before todo, soonest due (undated last),
    project priority, id.
    """
    if project is not None:
        tasks = content.tasks(project)
    else:
        active = {p.id for p in active_projects(content)}
        tasks = [t for t in content.tasks() if t.project in active]
    tasks = [t for t in tasks if t.status in OPEN_TASK_STATUSES]
    if min_priority is not None:
        tasks = [t for t in tasks if t.priority.rank <= min_priority.rank]

    project_rank = {p.id: p.priority.rank for p in content.projects()}
    return sorted(
        tasks,
        key=lambda t: (
            t.priority.rank,
            t.status != TaskStatus.DOING,
            t.due is None,
            t.due or dt.date.max,
            project_rank.get(t.project, Priority.LOW.rank),
            t.id,
        ),
    )


# --- status -------------------------------------------------------------------

DEFAULT_STALE_DAYS = 14
DEFAULT_TASK_DUE_DAYS = 7
DEFAULT_DEADLINE_DAYS = 30


@dataclass
class StaleProject:
    project: Project
    last_activity: dt.date | None
    days_idle: int | None


@dataclass
class StatusReport:
    today: dt.date
    active_projects: int
    open_tasks: int
    doing_tasks: int
    stale: list[StaleProject] = field(default_factory=list)
    blocked: list[Task] = field(default_factory=list)
    due_tasks: list[Task] = field(default_factory=list)
    deadlines: list[Deliverable] = field(default_factory=list)


def status(
    content: Content,
    *,
    today: dt.date | None = None,
    stale_days: int = DEFAULT_STALE_DAYS,
    task_due_days: int = DEFAULT_TASK_DUE_DAYS,
    deadline_days: int = DEFAULT_DEADLINE_DAYS,
) -> StatusReport:
    """Cross-project health check, limited to effectively active projects.

    - stale: no activity for ``stale_days`` or more (or no dated activity at all)
    - blocked: every blocked task
    - due_tasks: open or blocked tasks due within ``task_due_days`` (incl. overdue)
    - deadlines: unfinished deliverables due within ``deadline_days`` (incl. overdue)
    """
    today = today or dates.local_today()
    active = active_projects(content)
    active_ids = {p.id for p in active}
    tasks = [t for t in content.tasks() if t.project in active_ids]

    stale = []
    for project in active:
        last = last_activity(content, project)
        idle = (today - last).days if last else None
        if idle is None or idle >= stale_days:
            stale.append(StaleProject(project, last, idle))
    stale.sort(key=lambda s: (s.days_idle is not None, -(s.days_idle or 0), s.project.id))

    task_horizon = today + dt.timedelta(days=task_due_days)
    due_tasks = sorted(
        (t for t in tasks if t.status != TaskStatus.DONE and t.due and t.due <= task_horizon),
        key=lambda t: (t.due, t.priority.rank, t.id),
    )

    deadline_horizon = today + dt.timedelta(days=deadline_days)
    deadlines = sorted(
        (
            d
            for p in active
            for d in content.deliverables(p)
            if d.deadline
            and d.deadline <= deadline_horizon
            and d.status not in FINISHED_DELIVERABLE_STATUSES
        ),
        key=lambda d: (d.deadline, d.id),
    )

    return StatusReport(
        today=today,
        active_projects=len(active),
        open_tasks=sum(t.status in OPEN_TASK_STATUSES for t in tasks),
        doing_tasks=sum(t.status == TaskStatus.DOING for t in tasks),
        stale=stale,
        blocked=sorted(
            (t for t in tasks if t.status == TaskStatus.BLOCKED),
            key=lambda t: (t.priority.rank, t.id),
        ),
        due_tasks=due_tasks,
        deadlines=deadlines,
    )
