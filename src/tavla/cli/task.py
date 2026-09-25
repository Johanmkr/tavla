"""``tavla task ...`` commands."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    JsonOpt,
    complete_project,
    complete_task,
    edit_until_valid,
    emit_json,
    fmt_date,
    handles_errors,
    state,
    table,
)
from tavla.core import ops
from tavla.core.dates import parse_date
from tavla.core.entities import Priority, Task, TaskStatus, to_dict

app = typer.Typer(help="Create, list and inspect tasks.", no_args_is_help=True)


@app.command()
@handles_errors
def add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="Task title.")],
    project_id: Annotated[
        str,
        typer.Option(
            "--project", "-p", help="Project to add the task to.", autocompletion=complete_project
        ),
    ],
    priority: Annotated[Priority, typer.Option("--priority", help="Task priority.")] = (
        Priority.MED
    ),
    due: Annotated[
        str | None,
        typer.Option("--due", help="YYYY-MM-DD, today, tomorrow, +3d, +2w or a weekday."),
    ] = None,
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags.")] = None,
    id_: Annotated[
        str | None, typer.Option("--id", help="Explicit id (default: derived from the title).")
    ] = None,
) -> None:
    """Create a new task in a project and commit it."""
    content = state(ctx).content()
    project = content.project(project_id)
    task = ops.add_task(
        content,
        title,
        project,
        id=id_,
        priority=priority,
        due=parse_date(due) if due else None,
        tags=ops.parse_tags(tags),
    )
    typer.echo(f"Added task {task.id} to {project.id}")


@app.command()
@handles_errors
def edit(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_task)],
) -> None:
    """Open the task's markdown file in $EDITOR, then validate and commit."""
    content = state(ctx).content()
    task = content.task(task_id)
    session = ops.EditSession(task.path)
    edited = edit_until_valid(session, lambda: ops.finish_task_edit(content, task, session))
    typer.echo("No changes." if edited is None else f"Saved task {edited.id}")


def _sort_key(task: Task) -> tuple:
    # Priority first, then soonest due date (undated last), then id.
    return (task.priority.rank, task.due is None, task.due, task.id)


def subtask_progress(task: Task) -> str:
    return f"{task.subtasks_done}/{task.subtasks_total}" if task.subtasks_total else "-"


@app.command("list")
@handles_errors
def list_(
    ctx: typer.Context,
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Only this project (and its subprojects).",
            autocompletion=complete_project,
        ),
    ] = None,
    status: Annotated[
        TaskStatus | None, typer.Option("--status", help="Only tasks with this status.")
    ] = None,
    all_: Annotated[bool, typer.Option("--all", "-a", help="Include done tasks.")] = False,
    json_out: JsonOpt = False,
) -> None:
    """List tasks, highest priority first. Done tasks are hidden unless asked for."""
    st = state(ctx, json_out=json_out)
    content = st.content()
    project = content.project(project_id) if project_id else None
    tasks = content.tasks(project)
    if status is not None:
        tasks = [t for t in tasks if t.status == status]
    elif not all_:
        tasks = [t for t in tasks if t.status != TaskStatus.DONE]
    tasks = sorted(tasks, key=_sort_key)

    if st.json:
        emit_json(to_dict(tasks, content.root, exclude=("meta", "body")))
        return
    if not tasks:
        typer.echo("No tasks.")
        return
    table(
        [
            [t.id, t.status, t.priority, fmt_date(t.due), subtask_progress(t), t.project, t.title]
            for t in tasks
        ],
        ["ID", "STATUS", "PRIORITY", "DUE", "SUBTASKS", "PROJECT", "TITLE"],
    )


@app.command()
@handles_errors
def show(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_task)],
    json_out: JsonOpt = False,
) -> None:
    """Show a task's metadata and its full markdown body."""
    st = state(ctx, json_out=json_out)
    content = st.content()
    task = content.task(task_id)

    if st.json:
        emit_json(task, content.root)
        return

    typer.secho(task.title, bold=True)
    fields = [
        ("id", task.id),
        ("project", task.project),
        ("status", task.status),
        ("priority", task.priority),
        ("tags", ", ".join(task.tags)),
        ("due", fmt_date(task.due) if task.due else None),
        ("subtasks", subtask_progress(task) if task.subtasks_total else None),
        ("created", fmt_date(task.created) if task.created else None),
        ("updated", fmt_date(task.updated) if task.updated else None),
        ("path", task.path.relative_to(content.root)),
    ]
    for name, value in fields:
        if value:
            typer.echo(f"  {name + ':':<10}{value}")
    typer.echo("")
    typer.echo(task.body.rstrip())
