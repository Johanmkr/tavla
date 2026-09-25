"""``tavla project ...`` commands."""

from __future__ import annotations

from collections import Counter
from typing import Annotated

import typer

from tavla.cli.common import (
    JsonOpt,
    complete_project,
    emit_json,
    fmt_date,
    handles_errors,
    state,
    table,
)
from tavla.core.entities import ProjectStatus, TaskStatus, to_dict

app = typer.Typer(help="Create, list and inspect projects.", no_args_is_help=True)

RECENT_LOG_ENTRIES = 5


@app.command("list")
@handles_errors
def list_(
    ctx: typer.Context,
    status: Annotated[
        ProjectStatus | None, typer.Option("--status", help="Only projects with this status.")
    ] = None,
    all_: Annotated[bool, typer.Option("--all", "-a", help="Include archived projects.")] = False,
    json_out: JsonOpt = False,
) -> None:
    """List projects (subprojects indented under their parent)."""
    st = state(ctx, json_out=json_out)
    content = st.content()
    projects = content.projects()
    if status is not None:
        projects = [p for p in projects if p.status == status]
    elif not all_:
        projects = [p for p in projects if p.status != ProjectStatus.ARCHIVED]

    if st.json:
        emit_json(projects, content.root)
        return
    if not projects:
        typer.echo("No projects.")
        return
    depth = {}
    for p in content.projects():
        depth[p.id] = depth[p.parent] + 1 if p.parent in depth else 0
    table(
        [
            ["  " * depth[p.id] + p.id, p.status, p.priority, str(len(content.tasks(p))), p.title]
            for p in projects
        ],
        ["ID", "STATUS", "PRIORITY", "TASKS", "TITLE"],
    )


@app.command()
@handles_errors
def show(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_project)],
    json_out: JsonOpt = False,
) -> None:
    """Show a project's metadata, subprojects, tasks, deliverables and recent log."""
    st = state(ctx, json_out=json_out)
    content = st.content()
    project = content.project(project_id)
    tasks = content.tasks(project)
    children = content.children(project)
    deliverables = content.deliverables(project)
    log = content.log(project)

    if st.json:
        data = to_dict(project, content.root)
        data["subprojects"] = [c.id for c in children]
        data["tasks"] = to_dict(tasks, content.root, exclude=("meta", "body"))
        data["deliverables"] = to_dict(deliverables, content.root)
        data["log"] = to_dict(log)
        emit_json(data)
        return

    typer.secho(f"{project.title}", bold=True)
    fields = [
        ("id", project.id),
        ("parent", project.parent),
        ("status", project.status),
        ("priority", project.priority),
        ("tags", ", ".join(project.tags)),
        ("related", ", ".join(project.related)),
        ("repo_path", project.repo_path),
        ("created", fmt_date(project.created)),
        ("path", project.path.relative_to(content.root)),
    ]
    for name, value in fields:
        if value:
            typer.echo(f"  {name + ':':<11}{value}")

    if children:
        typer.secho("\nSubprojects", bold=True)
        for c in children:
            typer.echo(f"  {c.id}  [{c.status}]  {c.title}")

    typer.secho("\nTasks", bold=True)
    counts = Counter(t.status for t in tasks)
    typer.echo("  " + "  ".join(f"{s}: {counts.get(s, 0)}" for s in TaskStatus))

    if deliverables:
        typer.secho("\nDeliverables", bold=True)
        for d in deliverables:
            typer.echo(f"  {d.id}  [{d.status}]  due {fmt_date(d.deadline)}  {d.title}")

    if log:
        typer.secho("\nRecent log", bold=True)
        for entry in log[-RECENT_LOG_ENTRIES:]:
            typer.echo(f"  {entry.date.isoformat()}  {entry.text}")
