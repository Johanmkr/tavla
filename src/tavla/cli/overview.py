"""Cross-project views: ``tavla next`` and ``tavla status``."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

import typer

from tavla.cli.common import (
    JsonOpt,
    complete_project,
    emit_json,
    handles_errors,
    state,
    table,
)
from tavla.cli.task import subtask_progress
from tavla.core import dates, queries
from tavla.core.entities import Priority, to_dict


def relative(date: dt.date | None, today: dt.date) -> str:
    """``2026-10-01 (in 6d)`` / ``(today)`` / ``(3d overdue)``."""
    if date is None:
        return "-"
    days = (date - today).days
    if days == 0:
        rel = "today"
    elif days > 0:
        rel = f"in {days}d"
    else:
        rel = f"{-days}d overdue"
    return f"{date.isoformat()} ({rel})"


def plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _heading(text: str, count: int) -> None:
    typer.secho(f"\n{text} ({count})", bold=True)


@handles_errors
def next_(
    ctx: typer.Context,
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Only this project and its subprojects (even if not active).",
            autocompletion=complete_project,
        ),
    ] = None,
    priority: Annotated[
        Priority | None,
        typer.Option("--priority", help="Only tasks at or above this priority."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", min=0, help="Max tasks (0 = all).")] = 10,
    json_out: JsonOpt = False,
) -> None:
    """What to work on next: open tasks across active projects, most important first."""
    st = state(ctx, json_out=json_out)
    content = st.content()
    project = content.project(project_id) if project_id else None
    tasks = queries.next_tasks(content, project=project, min_priority=priority)
    shown = tasks[:limit] if limit else tasks

    if st.json:
        emit_json(to_dict(shown, content.root, exclude=("meta", "body")))
        return
    if not shown:
        typer.echo("Nothing to do.")
        return
    today = dates.local_today()
    table(
        [
            [
                t.id,
                t.priority,
                t.status,
                relative(t.due, today),
                subtask_progress(t),
                t.project,
                t.title,
            ]
            for t in shown
        ],
        ["ID", "PRIORITY", "STATUS", "DUE", "SUBTASKS", "PROJECT", "TITLE"],
    )
    if len(shown) < len(tasks):
        typer.secho(f"… and {len(tasks) - len(shown)} more (use -n 0 for all)", dim=True)


@handles_errors
def status(
    ctx: typer.Context,
    stale_days: Annotated[
        int,
        typer.Option("--stale-days", min=1, help="Flag active projects idle this many days."),
    ] = queries.DEFAULT_STALE_DAYS,
    deadline_days: Annotated[
        int,
        typer.Option("--deadline-days", min=0, help="Show deliverable deadlines this far ahead."),
    ] = queries.DEFAULT_DEADLINE_DAYS,
    json_out: JsonOpt = False,
) -> None:
    """Health check: stale projects, blocked tasks, and what's coming due."""
    st = state(ctx, json_out=json_out)
    content = st.content()
    report = queries.status(content, stale_days=stale_days, deadline_days=deadline_days)

    if st.json:
        emit_json(to_dict(report, content.root, exclude=("meta", "body")))
        return

    today = report.today
    typer.secho(f"tavla status — {today.isoformat()}", bold=True)
    typer.echo(
        f"{plural(report.active_projects, 'active project')} · "
        f"{plural(report.open_tasks, 'open task')} ({report.doing_tasks} doing) · "
        f"{len(report.blocked)} blocked"
    )

    _heading(f"Stale projects (idle {stale_days}+ days)", len(report.stale))
    for s in report.stale:
        idle = f"{s.last_activity} ({s.days_idle}d ago)" if s.last_activity else "no activity"
        typer.echo(f"  {s.project.id}  last activity {idle}")

    _heading("Blocked tasks", len(report.blocked))
    for t in report.blocked:
        since = f"since {t.updated}" if t.updated else ""
        typer.echo(f"  {t.id}  [{t.project}]  {t.title}  {since}".rstrip())

    _heading(f"Tasks due within {queries.DEFAULT_TASK_DUE_DAYS} days", len(report.due_tasks))
    for t in report.due_tasks:
        typer.echo(f"  {t.id}  {relative(t.due, today)}  [{t.project}]  {t.title}")

    _heading(f"Deliverable deadlines within {deadline_days} days", len(report.deadlines))
    for d in report.deadlines:
        typer.echo(f"  {d.id}  {relative(d.deadline, today)}  [{d.project}]  {d.status}  {d.title}")
