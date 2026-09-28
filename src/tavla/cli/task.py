"""``tavla task ...`` commands."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    DATE_HELP,
    TAGS_EDIT_HELP,
    ContentDirOpt,
    JsonOpt,
    complete_project,
    complete_task,
    date_change,
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
        typer.Option("--due", help=DATE_HELP),
    ] = None,
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags.")] = None,
    id_: Annotated[
        str | None, typer.Option("--id", help="Explicit id (default: derived from the title).")
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Create a new task in a project and commit it."""
    content = state(ctx, content_dir=content_dir).content()
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
    title: Annotated[str | None, typer.Option("--title", help="New title.")] = None,
    status: Annotated[TaskStatus | None, typer.Option("--status", help="New status.")] = None,
    priority: Annotated[Priority | None, typer.Option("--priority", help="New priority.")] = None,
    due: Annotated[str | None, typer.Option("--due", help=f"{DATE_HELP} 'none' clears it.")] = None,
    tags: Annotated[str | None, typer.Option("--tags", help=TAGS_EDIT_HELP)] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Change fields with the options given, or with none open the task in $EDITOR.

    Either way the result is validated and committed.
    """
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    changes: dict = {}
    if status is not None:
        changes["status"] = status.value
    if priority is not None:
        changes["priority"] = priority.value
    if due is not None:
        changes["due"] = date_change(due)
    if tags is not None:
        changes["tags"] = ops.apply_tags(task.tags, tags)
    if changes or title is not None:
        edited = ops.set_task_fields(content, task, changes, title=title)
        typer.echo("No changes." if edited is None else f"Saved task {edited.id}")
        return
    session = ops.EditSession(task.path)
    edited = edit_until_valid(session, lambda: ops.finish_task_edit(content, task, session))
    typer.echo("No changes." if edited is None else f"Saved task {edited.id}")


@app.command()
@handles_errors
def start(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_task)],
    content_dir: ContentDirOpt = None,
) -> None:
    """Mark a task as doing (from todo, blocked, or done)."""
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    if ops.start_task(content, task) is None:
        typer.echo(f"{task.id} is already in progress.")
        return
    typer.echo(f"Started: {task.id} ({task.title}) — was {task.status}")


@app.command()
@handles_errors
def done(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_task)],
    content_dir: ContentDirOpt = None,
) -> None:
    """Mark a task done (sets status and updated; the body is left untouched)."""
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    if ops.complete_task(content, task) is None:
        typer.echo(f"{task.id} is already done.")
        return
    typer.echo(f"Done: {task.id} ({task.title})")
    remaining = task.subtasks_total - task.subtasks_done
    if remaining:
        typer.secho(
            f"note: {remaining} of {task.subtasks_total} subtasks were still unchecked",
            fg=typer.colors.YELLOW,
            err=True,
        )


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
    content_dir: ContentDirOpt = None,
) -> None:
    """List tasks, highest priority first. Done tasks are hidden unless asked for."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
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
    content_dir: ContentDirOpt = None,
) -> None:
    """Show a task's metadata and its full markdown body."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
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
