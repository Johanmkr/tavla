"""What the TUI shows, as plain data: the rows of each pane and the lines of
the detail pane, built from a :class:`Content`. No Textual here, so it can be
tested (and reused) without a terminal.

A :class:`Row` carries a stable ``key`` (``task:run-baseline``) that the app
uses to keep the selection across reloads, the ``ref`` it acts on, and a
rich renderable to draw.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from rich.console import RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from tavla.cli.flow import MARKERS, STYLES
from tavla.core import dates, flow, focus, ideas, queries, todos
from tavla.core.entities import (
    Deliverable,
    Goal,
    Project,
    ProjectStatus,
    Subtask,
    Task,
    TaskStatus,
)
from tavla.core.flow import Board, CardState
from tavla.core.store import Content

LOOSE = "(loose)"

PROJECT_MARKS = {
    ProjectStatus.ACTIVE: "",
    ProjectStatus.PAUSED: "⏸",
    ProjectStatus.DONE: "✓",
    ProjectStatus.ARCHIVED: "▪",
}


@dataclass
class Row:
    key: str
    kind: str  # working | summary | todo | project | goal | loose | task | idea | deliverable
    prompt: RenderableType
    ref: Any = None
    disabled: bool = False
    search: str = ""  # what `/` filters on

    def matches(self, query: str) -> bool:
        return query.lower() in self.search.lower()


@dataclass(frozen=True)
class Context:
    """What the Tasks pane lists: everything (``all``, the `next` ranking),
    one ``project``, one ``goal``, or a project's ``loose`` tasks."""

    kind: str
    project: str | None = None
    goal: str | None = None


ALL = Context("all")


# --- small formatting helpers -------------------------------------------------------


def marker(state: CardState) -> Text:
    return Text(MARKERS[state], style=STYLES[state])


def task_state(task: Task) -> CardState:
    return flow._task_state(task)


def goal_state(goal: Goal, tasks: list[Task]) -> CardState:
    return flow._goal_state(goal, tasks)


def short_due(due: dt.date | None, today: dt.date) -> Text:
    """``today``, ``in 3d``, ``8d late``: coloured when close or overdue."""
    if due is None:
        return Text("")
    days = (due - today).days
    if days < 0:
        return Text(f"{-days}d late", style="bold red")
    if days == 0:
        return Text("today", style="bold yellow")
    style = "yellow" if days <= 3 else "dim"
    if days < 60:
        return Text(f"in {days}d", style=style)
    return Text(due.strftime("%b %Y" if due.year != today.year else "%d %b"), style=style)


def long_due(due: dt.date | None, today: dt.date) -> str:
    if due is None:
        return "no due date"
    days = (due - today).days
    rel = "today" if days == 0 else f"in {days}d" if days > 0 else f"{-days}d overdue"
    return f"due {due.isoformat()} ({rel})"


def two_columns(left: Text, right: Text | str = "") -> RenderableType:
    """A row that fills the pane: ``left`` truncated with … and ``right`` kept."""
    grid = Table.grid(expand=True, padding=(0, 0))
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(no_wrap=True, justify="right")
    right = Text(right) if isinstance(right, str) else right
    if right.plain:
        right = Text(" ") + right
    grid.add_row(left, right)
    return grid


def heading(text: str) -> Text:
    return Text(text, style="bold")


def dim(text: str) -> Text:
    return Text(text, style="dim")


# --- panes --------------------------------------------------------------------------


def status_rows(content: Content, now: dt.datetime | None = None) -> list[Row]:
    """The Status pane: what you are working on, what needs attention, open todos."""
    now = now or dates.local_now()
    rows: list[Row] = []
    current = focus.current(content)
    if current is None:
        rows.append(Row("working", "working", Text("○ not working  (w to start)", style="dim")))
    else:
        left = Text.assemble(("▶ ", "bold cyan"), (current.task_id, "bold"))
        took = Text(focus.format_duration(current.elapsed(now)), style="cyan")
        rows.append(Row("working", "working", two_columns(left, took), ref=current.task_id))
    report = queries.status(content, today=now.date())
    overdue = sum(1 for t in report.due_tasks if t.due and t.due < now.date())
    parts = []
    if overdue:
        parts.append((f"! {overdue} overdue", "bold red"))
    if report.blocked:
        parts.append((f"✗ {len(report.blocked)} blocked", "red"))
    if report.inbox:
        parts.append((f"{report.inbox} inbox", "dim"))
    summary = Text(" · ").join(Text(t, style=s) for t, s in parts) if parts else dim("✓ all clear")
    rows.append(
        Row("summary", "summary", two_columns(summary), disabled=True, search=summary.plain)
    )
    for todo in todos.open_todos(content):
        rows.append(
            Row(
                f"todo:{todo.number}",
                "todo",
                Text.assemble(("☐ ", "dim"), todo.text),
                ref=todo,
                search=todo.text,
            )
        )
    return rows


def _project_depth(content: Content, project: Project) -> int:
    depth, parent = 0, project.parent
    by_id = {p.id: p for p in content.projects()}
    while parent is not None and parent in by_id:
        depth, parent = depth + 1, by_id[parent].parent
    return depth


def project_rows(content: Content, *, show_all: bool = False) -> list[Row]:
    active = {p.id for p in queries.active_projects(content)}
    rows = []
    for p in content.projects():
        if not show_all and p.id not in active:
            continue
        open_count = sum(
            1 for t in content.tasks(p, recursive=False) if t.status != TaskStatus.DONE
        )
        mark = PROJECT_MARKS[p.status]
        left = Text("  " * _project_depth(content, p))
        left.append(p.id, style="dim" if p.id not in active else "")
        if mark:
            left.append(f" {mark}", style="dim")
        rows.append(
            Row(
                f"project:{p.id}",
                "project",
                two_columns(left, dim(str(open_count)) if open_count else ""),
                ref=p,
                search=f"{p.id} {p.title}",
            )
        )
    return rows


def loose_tasks(content: Content, project: Project) -> list[Task]:
    goal_ids = {g.id for g in content.goals()}
    return [t for t in content.tasks(project, recursive=False) if t.goal not in goal_ids]


def goal_rows(
    content: Content, project: Project | None, *, show_all: bool = False, today: dt.date
) -> list[Row]:
    if project is None:
        return []
    rows = []
    for g in sorted(content.goals(project, recursive=False), key=flow._sort_key):
        if not show_all and g.status == TaskStatus.DONE:
            continue
        state = goal_state(g, content.goal_tasks(g))
        left = Text.assemble(marker(state), " ", (g.id, "dim" if state == CardState.DONE else ""))
        right = Text.assemble(short_due(g.due, today), " " if g.due else "", dim(_progress(g)))
        rows.append(
            Row(f"goal:{g.id}", "goal", two_columns(left, right), ref=g, search=f"{g.id} {g.title}")
        )
    loose = loose_tasks(content, project)
    open_loose = [t for t in loose if t.status != TaskStatus.DONE]
    if open_loose or (show_all and loose):
        rows.append(
            Row(
                f"loose:{project.id}",
                "loose",
                two_columns(dim(LOOSE), dim(str(len(open_loose)))),
                ref=project,
                search=LOOSE,
            )
        )
    return rows


def _progress(goal: Goal) -> str:
    return f"{goal.tasks_done}/{goal.tasks_total}" if goal.tasks_total else "-"


def context_tasks(content: Content, ctx: Context, *, show_all: bool = False) -> list[Task]:
    """The tasks the Tasks pane lists for ``ctx``, in display order."""
    if ctx.kind == "all":
        return queries.next_tasks(content)
    projects = {p.id: p for p in content.projects()}
    project = projects.get(ctx.project or "")
    if project is None:
        return []
    if ctx.kind == "goal":
        goal = next((g for g in content.goals() if g.id == ctx.goal), None)
        tasks = flow._order(content.goal_tasks(goal)) if goal else []
    elif ctx.kind == "loose":
        tasks = loose_tasks(content, project)
    else:
        tasks = content.tasks(project, recursive=False)
    ranked = {t.id: n for n, t in enumerate(queries.next_tasks(content, project=project))}
    if ctx.kind != "goal":
        # Ready work first (in `next` order), then what waits, then what's done.
        tasks = sorted(
            tasks,
            key=lambda t: (
                t.status == TaskStatus.DONE,
                t.id not in ranked,
                ranked.get(t.id, 0),
                *flow._sort_key(t),
            ),
        )
    else:
        tasks = sorted(tasks, key=lambda t: t.status == TaskStatus.DONE)
    if not show_all:
        tasks = [t for t in tasks if t.status != TaskStatus.DONE]
    return tasks


def task_rows(
    content: Content,
    ctx: Context,
    *,
    show_all: bool = False,
    working: str | None = None,
    today: dt.date,
) -> list[Row]:
    rows = []
    for t in context_tasks(content, ctx, show_all=show_all):
        state = task_state(t)
        style = "dim" if state == CardState.DONE else "bold" if t.id == working else ""
        left = Text.assemble(marker(state), " ", (t.id, style))
        right = Text()
        if t.status != TaskStatus.DONE:
            right.append_text(short_due(t.due, today))
        if t.subtasks_total:
            right.append(f" {t.subtasks_done}/{t.subtasks_total}", style="dim")
        if ctx.kind == "all":
            right.append(f" {t.project}", style="dim")
        rows.append(
            Row(
                f"task:{t.id}",
                "task",
                two_columns(left, right),
                ref=t,
                search=f"{t.id} {t.title} {' '.join(t.tags)}",
            )
        )
    return rows


def idea_owner(content: Content, ctx: Context) -> Project | Goal | None:
    """Whose ideas the Ideas tab shows: the inbox (None), a project or a goal."""
    if ctx.kind == "all":
        return None
    if ctx.kind == "goal":
        goal = next((g for g in content.goals() if g.id == ctx.goal), None)
        if goal is not None:
            return goal
    return next((p for p in content.projects() if p.id == ctx.project), None)


def idea_rows(content: Content, ctx: Context) -> list[Row]:
    scope = ideas.scope_of(content, idea_owner(content, ctx))
    return [
        Row(
            f"idea:{scope.label}:{r.number}",
            "idea",
            two_columns(Text.assemble(("· ", "dim"), r.idea.text)),
            ref=r,
            search=r.idea.text,
        )
        for r in ideas.read(scope)
    ]


def deliverable_rows(content: Content, ctx: Context, *, today: dt.date) -> list[Row]:
    if ctx.kind == "all":
        active = queries.active_projects(content)
        items = [d for p in active for d in content.deliverables(p)]
    else:
        project = next((p for p in content.projects() if p.id == ctx.project), None)
        items = content.deliverables(project) if project else []
    items.sort(key=lambda d: (d.deadline or dt.date.max, d.id))
    rows = []
    for d in items:
        right = Text.assemble(dim(d.status.value), " ", short_due(d.deadline, today))
        rows.append(
            Row(
                f"deliverable:{d.id}",
                "deliverable",
                two_columns(Text(d.id), right),
                ref=d,
                search=f"{d.id} {d.title}",
            )
        )
    return rows


# --- detail pane --------------------------------------------------------------------


@dataclass
class Line:
    """A line of the detail pane; lines with a ``subtask`` can be selected."""

    prompt: RenderableType
    subtask: Subtask | None = None
    key: str = ""


def _lines(*texts: RenderableType) -> list[Line]:
    return [Line(t) for t in texts]


def _body_sections(body: str, skip: Iterable[str]) -> list[Line]:
    """The free-text sections of a goal/task file (Instructions, Context,
    Ideas, Updates, ...), headings bold; empty sections are left out."""
    skipped = {s.lower() for s in skip}
    out: list[Line] = []
    heading_text: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        lines = [b for b in buffer if b.strip() and not b.strip().startswith("<!--")]
        if heading_text is not None and heading_text.lower() not in skipped and lines:
            out.append(Line(Text("")))
            out.append(Line(heading(heading_text)))
            out.extend(Line(Padding(Text(b.rstrip()), (0, 0, 0, 2))) for b in lines)

    for raw in body.splitlines():
        if raw.startswith("## "):
            flush()
            heading_text, buffer = raw[3:].strip(), []
        elif raw.startswith("# ") and heading_text is None:
            continue
        else:
            buffer.append(raw)
    flush()
    return out


def _people_line(people: list) -> list[Line]:
    if not people:
        return []
    return _lines(Text.assemble(dim("people  "), ", ".join(str(p) for p in people)))


def task_detail(content: Content, task: Task, *, now: dt.datetime | None = None) -> list[Line]:
    now = now or dates.local_now()
    today = now.date()
    state = task_state(task)
    lines = _lines(
        Text.assemble(marker(state), " ", (task.title, "bold")),
        dim(f"{task.id} · {task.project}" + (f" · goal {task.goal}" if task.goal else "")),
    )
    facts = Text()
    facts.append(task.priority.value, style="bold" if task.priority.value == "high" else "")
    if "priority" in task.inherited:
        facts.append(" (goal)", style="dim")
    facts.append(f" · {task.status.value} · ")
    overdue = task.due is not None and task.due < today and task.status != TaskStatus.DONE
    facts.append(long_due(task.due, today), style="bold red" if overdue else "")
    if "due" in task.inherited:
        facts.append(" (goal)", style="dim")
    lines.append(Line(facts))

    status_by_id = {t.id: t for t in content.tasks()}
    if task.depends_on:
        after = Text("after   ", style="dim")
        for n, d in enumerate(task.depends_on):
            dep = status_by_id.get(d)
            st = task_state(dep) if dep else CardState.MISSING
            after.append_text(Text.assemble(", " if n else "", marker(st), " ", d))
        lines.append(Line(after))
    blocks = [t.id for t in content.tasks() if task.id in t.depends_on]
    if blocks:
        lines.append(Line(Text.assemble(dim("blocks  "), ", ".join(blocks))))
    lines += _people_line(task.everyone)
    if task.tags:
        lines.append(Line(Text.assemble(dim("tags    "), " ".join(f"#{t}" for t in task.tags))))

    if task.subtasks:
        lines.append(Line(Text("")))
        lines.append(Line(heading(f"Subtasks {task.subtasks_done}/{task.subtasks_total}")))
        for s in task.subtasks:
            mark = marker(CardState.DONE if s.done else CardState.READY)
            text = Text.assemble("  ", mark, " ", (s.text, "dim" if s.done else ""))
            lines.append(Line(text, subtask=s, key=f"sub:{s.number}"))

    sessions = focus.sessions(task)
    current = focus.current(content)
    working = current is not None and current.task_id == task.id
    if sessions or working:
        total = focus.total_time(task) + (
            current.elapsed(now) if working and current else dt.timedelta(0)
        )
        lines.append(Line(Text("")))
        lines.append(Line(heading(f"Sessions · total {focus.format_duration(total)}")))
        for s in sessions[-3:]:
            lines.append(Line(dim("  " + focus.session_line(s).lstrip("- "))))
        if working and current:
            took = focus.format_duration(current.elapsed(now))
            lines.append(
                Line(Text(f"  ▶ working since {current.since:%H:%M} ({took})", style="bold cyan"))
            )
    lines += _body_sections(task.body, skip=("subtasks", "sessions"))
    return lines


def goal_detail(
    content: Content, goal: Goal, *, width: int, today: dt.date, open_only: bool = False
) -> list[Line]:
    state = goal_state(goal, content.goal_tasks(goal))
    lines = _lines(
        Text.assemble(marker(state), " ", (goal.title, "bold")),
        dim(f"{goal.id} · {goal.project} · {_progress(goal)} tasks"),
        Text(f"{goal.priority.value} · {goal.status.value} · {long_due(goal.due, today)}"),
    )
    lines += _people_line(goal.people)
    lines.append(Line(Text("")))
    lines += flow_lines(flow.goal_board(content, goal, open_only=open_only, today=today), width)
    lines += _body_sections(goal.body, skip=())
    return lines


def project_detail(
    content: Content, project: Project, *, width: int, today: dt.date, open_only: bool = False
) -> list[Line]:
    lines = _lines(
        Text(project.title, style="bold"),
        dim(f"{project.id} · {project.status.value} · {project.priority.value}"),
        Text(""),
    )
    lines += flow_lines(
        flow.project_board(content, project, open_only=open_only, today=today), width
    )
    return lines


def loose_detail(content: Content, project: Project, *, today: dt.date) -> list[Line]:
    tasks = loose_tasks(content, project)
    lines = _lines(heading(f"Tasks without a goal in {project.id}"), Text(""))
    for t in tasks:
        due = short_due(t.due, today) if t.status != TaskStatus.DONE else Text("")
        lines.append(Line(two_columns(Text.assemble(marker(task_state(t)), " ", t.title), due)))
    return lines


def idea_detail(ref: ideas.IdeaRef) -> list[Line]:
    lines = _lines(Text(ref.idea.text, style="bold"), dim(f"idea {ref.ref}"))
    if ref.idea.tags:
        lines.append(Line(Text.assemble(dim("tags  "), " ".join(f"#{t}" for t in ref.idea.tags))))
    lines += _lines(Text(""), dim("p promote to a task · D drop"))
    return lines


def deliverable_detail(d: Deliverable, *, today: dt.date) -> list[Line]:
    lines = _lines(
        Text(d.title, style="bold"),
        dim(f"{d.id} · {d.project} · {d.kind.value}"),
        Text(f"{d.status.value} · " + long_due(d.deadline, today).replace("due", "deadline")),
    )
    if d.venue:
        lines.append(Line(Text.assemble(dim("venue      "), d.venue)))
    if d.coauthors:
        lines.append(Line(Text.assemble(dim("coauthors  "), ", ".join(d.coauthors))))
    return lines


def status_detail(content: Content, *, today: dt.date) -> list[Line]:
    """Like ``tv status``: what needs attention across active projects."""
    report = queries.status(content, today=today)
    lines = _lines(
        heading(f"Status · {today:%A %d %B}"),
        dim(
            f"{report.active_projects} active projects · {report.open_tasks} open tasks "
            f"({report.doing_tasks} doing)"
        ),
    )

    def section(title: str, rows: list[RenderableType]) -> None:
        if rows:
            lines.append(Line(Text("")))
            lines.append(Line(heading(f"{title} ({len(rows)})")))
            lines.extend(Line(r) for r in rows)

    section(
        "Due soon",
        [
            two_columns(
                Text.assemble("  ", marker(task_state(t)), " ", t.id), short_due(t.due, today)
            )
            for t in report.due_tasks
        ],
    )
    section(
        "Blocked",
        [Text.assemble("  ", marker(CardState.BLOCKED), " ", t.id) for t in report.blocked],
    )
    section(
        "Waiting on others",
        [
            Text.assemble(
                "  ",
                marker(CardState.WAITING),
                " ",
                t.id,
                dim(f"  after {', '.join(t.waiting_on)}"),
            )
            for t in report.waiting
        ],
    )
    section(
        "Deadlines",
        [two_columns(Text(f"  {d.id}"), short_due(d.deadline, today)) for d in report.deadlines],
    )
    section(
        "Goals ready to close",
        [Text.assemble("  ", marker(CardState.DONE), " ", g.id) for g in report.goals_ready],
    )
    section(
        "Stale projects",
        [
            two_columns(
                Text(f"  {s.project.id}"),
                dim(f"{s.days_idle}d idle" if s.days_idle is not None else "no activity"),
            )
            for s in report.stale
        ],
    )
    if report.inbox:
        lines += _lines(Text(""), dim(f"{report.inbox} ideas in the inbox (Ideas tab)"))
    return lines


def todo_detail(todo: todos.Todo) -> list[Line]:
    return _lines(
        Text(todo.text, style="bold"),
        dim(f"todo {todo.number} · todo.md"),
        Text(""),
        dim("space done · D drop · a add"),
    )


# --- compact flow board ---------------------------------------------------------------

MIN_COLUMN = 18
COLUMN_GAP = 2


def _card_lines(card: flow.Card, width: int) -> list[Text]:
    head = Text.assemble(marker(card.state), " ", (card.id, "bold" if card.kind == "goal" else ""))
    if card.kind == "external":
        head.append(" ↗", style="dim")
    elif card.total:
        head.append(f" {card.done}/{card.total}", style="dim")
    out = [head]
    for item in card.items:
        out.append(Text.assemble("  ", marker(item.state), " ", (item.id or item.text, "dim")))
    if card.after and card.kind != "external":
        out.append(Text("  after " + ", ".join(card.after), style="dim italic"))
    for w in card.warnings:
        out.append(Text(f"  ! {w}", style="red"))
    for line in out:
        line.truncate(width, overflow="ellipsis")
    return out


def flow_lines(board: Board, width: int) -> list[Line]:
    """The board's stages as side-by-side columns of one-line cards (each
    followed by its items), or stacked stage by stage when too narrow."""
    columns = [c for c in board.columns if c.cards]
    lines: list[Line] = []
    if not columns:
        return _lines(dim("Nothing planned yet."))
    n = len(columns)
    col_width = (width - COLUMN_GAP * (n - 1)) // n if n else width
    if col_width >= MIN_COLUMN:
        cells = []
        for col in columns:
            cell = [Text(col.label, style="bold underline")]
            for card in col.cards:
                cell += _card_lines(card, col_width)
            cells.append(cell)
        for i in range(max(len(c) for c in cells)):
            row = Text()
            for j, cell in enumerate(cells):
                part = cell[i].copy() if i < len(cell) else Text("")
                if j < n - 1:
                    part.pad_right(col_width - part.cell_len + COLUMN_GAP)
                row.append_text(part)
            lines.append(Line(row))
    else:
        for col in columns:
            lines.append(Line(Text(col.label, style="bold underline")))
            for card in col.cards:
                lines += [Line(t) for t in _card_lines(card, width)]
    if board.ready:
        ready = Text("Ready now ", style="bold")
        for item in board.ready[:6]:
            ready.append_text(Text.assemble(" ", marker(item.state), " ", item.id or ""))
        lines += [Line(Text("")), Line(ready)]
    return lines


def subtask_by_number(task: Task, number: int) -> Subtask | None:
    return next((s for s in task.subtasks if s.number == number), None)
