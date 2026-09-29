"""Boards for ``tavla flow``: items laid out in stages (or by status).

A stage holds everything whose prerequisites all sit in earlier stages, so
items in the same stage can be worked on in parallel. The board is plain data
(also the ``--json`` output); drawing it is up to the interface.

Two scopes:

* a **project**: one card per goal, listing its tasks. Goals are ordered by
  the task dependencies that cross between them. Tasks without a goal get a
  card of their own.
* a **goal**: one card per task, listing its subtasks.

Prerequisites outside the scope show up as ``external`` cards so the first
stage never hides what it is waiting for.

A status board (``--by status``) puts the same task cards in todo / doing /
blocked / done columns instead: a kanban view.

Cards carry ``warnings`` for plans that can't work as written: overdue work,
and tasks due before one of their prerequisites.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from tavla.core import dates, queries
from tavla.core.entities import Goal, Priority, Project, Task, TaskStatus

if TYPE_CHECKING:
    from tavla.core.store import Content


class CardState(StrEnum):
    DONE = "done"
    DOING = "doing"  # in progress
    READY = "ready"  # can be started now
    WAITING = "waiting"  # unfinished prerequisites
    BLOCKED = "blocked"  # status: blocked
    MISSING = "missing"  # a dependency on an id that doesn't exist


@dataclass
class Item:
    """A line inside a card: a subtask (goal board) or a task (project board)."""

    text: str
    state: CardState
    id: str | None = None


@dataclass
class Card:
    id: str
    kind: str  # "goal", "task" or "external"
    title: str
    state: CardState
    project: str | None = None
    goal: str | None = None  # status boards: the task's goal
    priority: Priority | None = None
    due: dt.date | None = None
    done: int = 0
    total: int = 0
    after: list[str] = field(default_factory=list)  # prerequisite card ids
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Column:
    label: str  # "Stage 1", or a status
    cards: list[Card]


@dataclass
class Board:
    kind: str  # "project" or "goal"
    id: str
    title: str
    columns: list[Column]
    by: str = "stage"  # or "status"
    goal: Card | None = None  # the goal a goal board flows into
    ready: list[Item] = field(default_factory=list)  # tasks to start now, `next` order

    @property
    def stages(self) -> list[list[Card]]:
        return [c.cards for c in self.columns]

    def cards(self) -> list[Card]:
        return [c for col in self.columns for c in col.cards]

    def edges(self) -> list[tuple[str, str]]:
        """``(prerequisite, dependent)`` pairs between cards on the board."""
        return [(a, c.id) for c in self.cards() for a in c.after]


# --- layering -----------------------------------------------------------------


def stages(nodes: Iterable[str], after: Mapping[str, Iterable[str]]) -> list[list[str]]:
    """Group ``nodes`` into stages: each node goes one stage past its latest
    prerequisite (``after[node]``; ids outside ``nodes`` are ignored).

    Nodes on a cycle share a stage. Within a stage, nodes keep their input order.
    """
    nodes = list(nodes)
    known = set(nodes)
    preds = {n: [p for p in after.get(n, ()) if p in known and p != n] for n in nodes}
    comp = _components(nodes, preds)
    level: dict[int, int] = {}

    def depth(c: int, members: dict[int, list[str]]) -> int:
        if c not in level:
            level[c] = 0  # guards recursion; components form a DAG
            level[c] = max(
                (depth(comp[p], members) + 1 for n in members[c] for p in preds[n] if comp[p] != c),
                default=0,
            )
        return level[c]

    members: dict[int, list[str]] = {}
    for n in nodes:
        members.setdefault(comp[n], []).append(n)
    out: list[list[str]] = []
    for n in nodes:
        d = depth(comp[n], members)
        while len(out) <= d:
            out.append([])
        out[d].append(n)
    return out


def _components(nodes: list[str], preds: Mapping[str, list[str]]) -> dict[str, int]:
    """Strongly connected components (Tarjan), as node -> component number."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    comp: dict[str, int] = {}
    count = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        on_stack.add(v)
        for w in preds[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            n = count[0]
            count[0] += 1
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp[w] = n
                if w == v:
                    break

    for v in nodes:
        if v not in index:
            visit(v)
    return comp


# --- boards -------------------------------------------------------------------


def _task_state(task: Task) -> CardState:
    if task.status == TaskStatus.DONE:
        return CardState.DONE
    if task.status == TaskStatus.BLOCKED:
        return CardState.BLOCKED
    if task.status == TaskStatus.DOING:
        return CardState.DOING  # started, even if a prerequisite isn't done
    return CardState.WAITING if task.waiting_on else CardState.READY


def _goal_state(goal: Goal, tasks: list[Task]) -> CardState:
    if goal.status == TaskStatus.DONE:
        return CardState.DONE
    if goal.status == TaskStatus.BLOCKED:
        return CardState.BLOCKED
    states = {_task_state(t) for t in tasks if t.status != TaskStatus.DONE}
    if goal.status == TaskStatus.DOING or CardState.DOING in states:
        return CardState.DOING
    if not states or CardState.READY in states:
        return CardState.READY
    return CardState.WAITING


def _overdue(item: Goal | Task, today: dt.date) -> bool:
    return item.status != TaskStatus.DONE and item.due is not None and item.due < today


def _task_warnings(task: Task, all_tasks: Mapping[str, Task], today: dt.date) -> list[str]:
    """Overdue, and due before an unfinished prerequisite is (so it can't
    be finished on time without that one being early)."""
    if task.status == TaskStatus.DONE:
        return []
    out = [f"overdue (due {task.due.isoformat()})"] if _overdue(task, today) else []
    for d in task.depends_on:
        dep = all_tasks.get(d)
        if (
            task.due is not None
            and dep is not None
            and dep.status != TaskStatus.DONE
            and dep.due is not None
            and dep.due > task.due
        ):
            out.append(f"due before {dep.id} ({dep.due.isoformat()})")
    return out


def _goal_warnings(
    goal: Goal, tasks: list[Task], all_tasks: Mapping[str, Task], today: dt.date
) -> list[str]:
    """The goal's own lateness, plus its tasks' warnings (except being
    overdue only because the goal is)."""
    out = [f"overdue (due {goal.due.isoformat()})"] if _overdue(goal, today) else []
    for t in tasks:
        for w in _task_warnings(t, all_tasks, today):
            if not (w.startswith("overdue") and "due" in t.inherited):
                out.append(f"{t.id}: {w}")
    return out


def _order(tasks: list[Task]) -> list[Task]:
    """Tasks in dependency order (stage by stage), for listing inside a card."""
    by_id = {t.id: t for t in tasks}
    layers = stages(by_id, {t.id: t.depends_on for t in tasks})
    return [by_id[i] for layer in layers for i in layer]


def _task_card(
    task: Task, after: list[str], open_only: bool, all_tasks: Mapping[str, Task], today: dt.date
) -> Card:
    subtasks = [s for s in task.subtasks if not (open_only and s.done)]
    return Card(
        id=task.id,
        kind="task",
        title=task.title,
        state=_task_state(task),
        project=task.project,
        priority=task.priority,
        due=task.due,
        done=task.subtasks_done,
        total=task.subtasks_total,
        after=after,
        items=[Item(s.text, CardState.DONE if s.done else CardState.READY) for s in subtasks],
        warnings=_task_warnings(task, all_tasks, today),
    )


def _external_cards(
    ids: Iterable[str], all_tasks: Mapping[str, Task], all_goals: Mapping[str, Goal]
) -> list[Card]:
    """Placeholder cards for prerequisites outside the board's scope."""
    cards = []
    for i in dict.fromkeys(ids):
        item = all_goals.get(i) or all_tasks.get(i)
        if item is None:
            cards.append(Card(id=i, kind="external", title="(missing)", state=CardState.MISSING))
            continue
        state = (
            _task_state(item)
            if isinstance(item, Task)
            else _goal_state(item, [t for t in all_tasks.values() if t.goal == item.id])
        )
        cards.append(
            Card(id=i, kind="external", title=item.title, state=state, project=item.project)
        )
    return cards


def _layout(cards: list[Card]) -> list[Column]:
    by_id = {c.id: c for c in cards}
    layers = stages(by_id, {c.id: c.after for c in cards})
    return [Column(f"Stage {n}", [by_id[i] for i in layer]) for n, layer in enumerate(layers, 1)]


def _sort_key(item: Goal | Task) -> tuple:
    return (item.priority.rank, item.due or dt.date.max, item.id)


def goal_board(
    content: Content, goal: Goal, *, open_only: bool = False, today: dt.date | None = None
) -> Board:
    """Tasks of ``goal`` in stages, each listing its subtasks."""
    today = today or dates.local_today()
    all_tasks = {t.id: t for t in content.tasks()}
    tasks = sorted(content.goal_tasks(goal), key=_sort_key)
    if open_only:
        tasks = [t for t in tasks if t.status != TaskStatus.DONE]
    ids = {t.id for t in tasks}
    outside = [
        d
        for t in tasks
        for d in t.depends_on
        if d not in ids and not (open_only and _is_done(all_tasks.get(d)))
    ]
    cards = _external_cards(outside, all_tasks, {})
    cards += [
        _task_card(
            t,
            [d for d in t.depends_on if not (open_only and _is_done(all_tasks.get(d)))],
            open_only,
            all_tasks,
            today,
        )
        for t in tasks
    ]
    goal_card = Card(
        id=goal.id,
        kind="goal",
        title=goal.title,
        state=_goal_state(goal, content.goal_tasks(goal)),
        project=goal.project,
        priority=goal.priority,
        due=goal.due,
        done=goal.tasks_done,
        total=goal.tasks_total,
        warnings=[f"overdue (due {goal.due.isoformat()})"] if _overdue(goal, today) else [],
    )
    ready = [
        t
        for t in queries.next_tasks(content, project=content.project(goal.project))
        if t.goal == goal.id
    ]
    return Board(
        "goal", goal.id, goal.title, _layout(cards), goal=goal_card, ready=_ready_items(ready)
    )


def project_board(
    content: Content, project: Project, *, open_only: bool = False, today: dt.date | None = None
) -> Board:
    """Goals of ``project`` (and its subprojects) in stages, each listing its
    tasks; goal order comes from task dependencies that cross goals."""
    today = today or dates.local_today()
    all_tasks = {t.id: t for t in content.tasks()}
    all_goals = {g.id: g for g in content.goals()}
    goals = sorted(content.goals(project), key=_sort_key)
    tasks = content.tasks(project)
    if open_only:
        goals = [g for g in goals if g.status != TaskStatus.DONE]
        tasks = [t for t in tasks if t.status != TaskStatus.DONE]
    goal_ids = {g.id for g in goals}
    loose = sorted((t for t in tasks if t.goal not in goal_ids), key=_sort_key)
    loose_ids = {t.id for t in loose}

    def node(task_id: str) -> str | None:
        """The card a task belongs to: its goal's, its own, or None (hidden)."""
        t = all_tasks.get(task_id)
        if t is None:
            return task_id  # missing: an external card
        if open_only and t.status == TaskStatus.DONE:
            return None
        if t.goal in goal_ids:
            return t.goal
        if t.id in loose_ids:
            return t.id
        # Outside the board: show its goal (or itself if it has none).
        return t.goal if t.goal in all_goals else t.id

    def prereqs(own: Iterable[Task], self_id: str) -> list[str]:
        out = (node(d) for t in own for d in t.depends_on)
        return list(dict.fromkeys(n for n in out if n is not None and n != self_id))

    cards: list[Card] = []
    for g in goals:
        own = _order([t for t in tasks if t.goal == g.id])
        cards.append(
            Card(
                id=g.id,
                kind="goal",
                title=g.title,
                state=_goal_state(g, content.goal_tasks(g)),
                project=g.project,
                priority=g.priority,
                due=g.due,
                done=g.tasks_done,
                total=g.tasks_total,
                after=prereqs(own, g.id),
                items=[Item(t.title, _task_state(t), t.id) for t in own],
                warnings=_goal_warnings(g, own, all_tasks, today),
            )
        )
    cards += [_task_card(t, prereqs([t], t.id), open_only, all_tasks, today) for t in loose]
    on_board = {c.id for c in cards}
    outside = [a for c in cards for a in c.after if a not in on_board]
    cards = _external_cards(outside, all_tasks, all_goals) + cards
    ready = queries.next_tasks(content, project=project)
    return Board("project", project.id, project.title, _layout(cards), ready=_ready_items(ready))


def _ready_items(tasks: list[Task]) -> list[Item]:
    return [Item(t.title, _task_state(t), t.id) for t in tasks]


def _is_done(task: Task | None) -> bool:
    return task is not None and task.status == TaskStatus.DONE


STATUS_COLUMNS = (TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED, TaskStatus.DONE)


def status_board(
    content: Content,
    target: Project | Goal,
    *,
    open_only: bool = False,
    today: dt.date | None = None,
) -> Board:
    """Tasks of a project (and its subprojects) or a goal in one column per
    status, most important first. ``after`` lists only unfinished
    prerequisites, since that is what keeps a todo task waiting."""
    today = today or dates.local_today()
    all_tasks = {t.id: t for t in content.tasks()}
    if isinstance(target, Goal):
        project = content.project(target.project)
        tasks = content.goal_tasks(target)
    else:
        project = target
        tasks = content.tasks(target)
    order = {t.id: n for n, t in enumerate(queries.next_tasks(content, project=project))}
    tasks = sorted(tasks, key=lambda t: (order.get(t.id, len(order)), *_sort_key(t)))
    columns = []
    for status in STATUS_COLUMNS:
        if open_only and status == TaskStatus.DONE:
            continue
        cards = []
        for t in tasks:
            if t.status == status:
                card = _task_card(t, list(t.waiting_on), open_only, all_tasks, today)
                if isinstance(target, Project):
                    card.goal = t.goal
                cards.append(card)
        columns.append(Column(status.value, cards))
    in_scope = {t.id for t in tasks}
    ready = [all_tasks[i] for i in order if i in in_scope]
    return Board(
        "goal" if isinstance(target, Goal) else "project",
        target.id,
        target.title,
        columns,
        by="status",
        ready=_ready_items(ready),
    )
