"""``tavla goal ...`` commands."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    DATE_HELP,
    TAGS_EDIT_HELP,
    ContentDirOpt,
    JsonOpt,
    complete_goal,
    complete_project,
    edit_until_valid,
    emit_json,
    fmt_date,
    handles_errors,
    item_changes,
    progress,
    state,
    table,
)
from tavla.core import ops
from tavla.core.dates import parse_date
from tavla.core.entities import Goal, GoalStatus, Priority, TaskStatus, to_dict

app = typer.Typer(help="Goals: the outcomes a project works towards.", no_args_is_help=True)

GoalArg = Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_goal)]


@app.command()
@handles_errors
def add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="Goal title.")],
    project_id: Annotated[
        str,
        typer.Option(
            "--project", "-p", help="Project to add the goal to.", autocompletion=complete_project
        ),
    ],
    priority: Annotated[Priority, typer.Option("--priority", help="Goal priority.")] = (
        Priority.MED
    ),
    due: Annotated[str | None, typer.Option("--due", help=DATE_HELP)] = None,
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags.")] = None,
    id_: Annotated[
        str | None, typer.Option("--id", help="Explicit id (default: derived from the title).")
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Create a new goal in a project and commit it."""
    content = state(ctx, content_dir=content_dir).content()
    project = content.project(project_id)
    goal = ops.add_goal(
        content,
        title,
        project,
        id=id_,
        priority=priority,
        due=parse_date(due) if due else None,
        tags=ops.parse_tags(tags),
    )
    typer.echo(f"Added goal {goal.id} to {project.id}")


@app.command()
@handles_errors
def edit(
    ctx: typer.Context,
    goal_id: GoalArg,
    title: Annotated[str | None, typer.Option("--title", help="New title.")] = None,
    status: Annotated[GoalStatus | None, typer.Option("--status", help="New status.")] = None,
    priority: Annotated[Priority | None, typer.Option("--priority", help="New priority.")] = None,
    due: Annotated[str | None, typer.Option("--due", help=f"{DATE_HELP} 'none' clears it.")] = None,
    tags: Annotated[str | None, typer.Option("--tags", help=TAGS_EDIT_HELP)] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Change fields with the options given, or with none open the goal in $EDITOR.

    Either way the result is validated and committed.
    """
    content = state(ctx, content_dir=content_dir).content()
    goal = content.goal(goal_id)
    changes = item_changes(goal, status=status, priority=priority, due=due, tags=tags)
    if changes or title is not None:
        edited = ops.set_fields(content, goal, changes, title=title)
    else:
        session = ops.EditSession(goal.path)
        edited = edit_until_valid(session, lambda: ops.finish_edit(content, goal, session))
    typer.echo("No changes." if edited is None else f"Saved goal {edited.id}")


@app.command()
@handles_errors
def start(ctx: typer.Context, goal_id: GoalArg, content_dir: ContentDirOpt = None) -> None:
    """Mark a goal as doing (from todo, blocked, or done)."""
    content = state(ctx, content_dir=content_dir).content()
    goal = content.goal(goal_id)
    if ops.start(content, goal) is None:
        typer.echo(f"{goal.id} is already in progress.")
        return
    typer.echo(f"Started: {goal.id} ({goal.title}) — was {goal.status}")


@app.command()
@handles_errors
def done(ctx: typer.Context, goal_id: GoalArg, content_dir: ContentDirOpt = None) -> None:
    """Mark a goal done. Its tasks are left as they are."""
    content = state(ctx, content_dir=content_dir).content()
    goal = content.goal(goal_id)
    if ops.complete(content, goal) is None:
        typer.echo(f"{goal.id} is already done.")
        return
    typer.echo(f"Done: {goal.id} ({goal.title})")
    remaining = goal.tasks_total - goal.tasks_done
    if remaining:
        typer.secho(
            f"note: {remaining} of {goal.tasks_total} tasks are not done",
            fg=typer.colors.YELLOW,
            err=True,
        )


def _sort_key(goal: Goal) -> tuple:
    return (goal.priority.rank, goal.due is None, goal.due, goal.id)


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
        GoalStatus | None, typer.Option("--status", help="Only goals with this status.")
    ] = None,
    all_: Annotated[bool, typer.Option("--all", "-a", help="Include done goals.")] = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """List goals, highest priority first. Done goals are hidden unless asked for."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    project = content.project(project_id) if project_id else None
    goals = content.goals(project)
    if status is not None:
        goals = [g for g in goals if g.status == status]
    elif not all_:
        goals = [g for g in goals if g.status != GoalStatus.DONE]
    goals = sorted(goals, key=_sort_key)

    if st.json:
        emit_json(to_dict(goals, content.root, exclude=("meta", "body")))
        return
    if not goals:
        typer.echo("No goals.")
        return
    table(
        [
            [
                g.id,
                g.status,
                g.priority,
                fmt_date(g.due),
                progress(g.tasks_done, g.tasks_total),
                g.project,
                g.title,
            ]
            for g in goals
        ],
        ["ID", "STATUS", "PRIORITY", "DUE", "TASKS", "PROJECT", "TITLE"],
    )


@app.command()
@handles_errors
def show(
    ctx: typer.Context,
    goal_id: GoalArg,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Show a goal's metadata, its tasks, and its markdown body."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    goal = content.goal(goal_id)
    tasks = content.goal_tasks(goal)

    if st.json:
        data = to_dict(goal, content.root)
        data["tasks"] = to_dict(tasks, content.root, exclude=("meta", "body"))
        emit_json(data)
        return

    typer.secho(goal.title, bold=True)
    fields = [
        ("id", goal.id),
        ("project", goal.project),
        ("status", goal.status),
        ("priority", goal.priority),
        ("tags", ", ".join(goal.tags)),
        ("due", fmt_date(goal.due) if goal.due else None),
        ("tasks", progress(goal.tasks_done, goal.tasks_total) if goal.tasks_total else None),
        ("created", fmt_date(goal.created) if goal.created else None),
        ("updated", fmt_date(goal.updated) if goal.updated else None),
        ("path", goal.path.relative_to(content.root)),
    ]
    for name, value in fields:
        if value:
            typer.echo(f"  {name + ':':<10}{value}")

    if tasks:
        typer.secho("\nTasks", bold=True)
        for t in tasks:
            mark = "x" if t.status == TaskStatus.DONE else " "
            waiting = f"  (after {', '.join(t.waiting_on)})" if t.is_waiting else ""
            typer.echo(f"  [{mark}] {t.id}  [{t.status}]  {t.title}{waiting}")
    typer.echo("")
    typer.echo(goal.body.rstrip())
