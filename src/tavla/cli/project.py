"""``tavla project ...`` commands."""

from __future__ import annotations

from collections import Counter
from typing import Annotated

import typer

from tavla.cli.common import (
    TAGS_EDIT_HELP,
    ContentDirOpt,
    JsonOpt,
    complete_project,
    edit_until_valid,
    emit_json,
    fmt_date,
    handles_errors,
    is_clear,
    print_ideas,
    progress,
    state,
    table,
)
from tavla.core import ideas, ops
from tavla.core.entities import PROJECT_FILE, Priority, ProjectStatus, TaskStatus, to_dict

app = typer.Typer(help="Create, list and inspect projects.", no_args_is_help=True)

RECENT_LOG_ENTRIES = 5


@app.command()
@handles_errors
def add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project title.")],
    priority: Annotated[Priority, typer.Option("--priority", help="Project priority.")] = (
        Priority.MED
    ),
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags.")] = None,
    id_: Annotated[
        str | None, typer.Option("--id", help="Explicit id (default: derived from the name).")
    ] = None,
    parent_id: Annotated[
        str | None,
        typer.Option(
            "--parent",
            "-p",
            help="Create it as a subproject of this project.",
            autocompletion=complete_project,
        ),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Create a new project (or, with -p, a subproject) and commit it."""
    content = state(ctx, content_dir=content_dir).content()
    parent = content.project(parent_id) if parent_id else None
    project = ops.add_project(
        content, name, id=id_, priority=priority, tags=ops.parse_tags(tags), parent=parent
    )
    where = f" under {parent.id}" if parent else ""
    typer.echo(f"Added project {project.id}{where}")


@app.command()
@handles_errors
def edit(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_project)],
    title: Annotated[str | None, typer.Option("--title", help="New title.")] = None,
    status: Annotated[ProjectStatus | None, typer.Option("--status", help="New status.")] = None,
    priority: Annotated[Priority | None, typer.Option("--priority", help="New priority.")] = None,
    tags: Annotated[str | None, typer.Option("--tags", help=TAGS_EDIT_HELP)] = None,
    parent_id: Annotated[
        str | None,
        typer.Option(
            "--parent",
            "-p",
            help="Move under this project; 'none' makes it top-level.",
            autocompletion=complete_project,
        ),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Change fields with the options given, or with none open project.yaml in $EDITOR.

    Either way the result is validated and committed.
    """
    content = state(ctx, content_dir=content_dir).content()
    project = content.project(project_id)
    moved = None
    if parent_id is not None:
        parent = None if is_clear(parent_id) else content.project(parent_id)
        moved = ops.move_project(content, project, parent)
        if moved is not None:
            project = moved
            where = f"under {moved.parent}" if moved.parent else "to top level"
            typer.echo(f"Moved project {moved.id} {where}")
    changes: dict = {}
    if title is not None:
        changes["title"] = ops.clean_title(title)
    if status is not None:
        changes["status"] = status.value
    if priority is not None:
        changes["priority"] = priority.value
    if tags is not None:
        changes["tags"] = ops.apply_list_spec(project.tags, tags)
    if changes:
        edited = ops.set_project_fields(content, project, changes)
        if edited is not None:
            typer.echo(f"Saved project {edited.id}")
        elif moved is None:
            typer.echo("No changes.")
        return
    if parent_id is not None:
        if moved is None:
            typer.echo("No changes.")
        return
    session = ops.EditSession(project.path / PROJECT_FILE)
    edited = edit_until_valid(session, lambda: ops.finish_project_edit(content, project, session))
    typer.echo("No changes." if edited is None else f"Saved project {edited.id}")


@app.command("list")
@handles_errors
def list_(
    ctx: typer.Context,
    status: Annotated[
        ProjectStatus | None, typer.Option("--status", help="Only projects with this status.")
    ] = None,
    all_: Annotated[bool, typer.Option("--all", "-a", help="Include archived projects.")] = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """List projects (subprojects indented under their parent)."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
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
            [
                "  " * depth[p.id] + p.id,
                p.status,
                p.priority,
                str(len(content.goals(p))),
                str(len(content.tasks(p))),
                p.title,
            ]
            for p in projects
        ],
        ["ID", "STATUS", "PRIORITY", "GOALS", "TASKS", "TITLE"],
    )


@app.command()
@handles_errors
def show(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_project)],
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Show a project's metadata, subprojects, goals, tasks, deliverables, ideas and recent log."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    project = content.project(project_id)
    goals = content.goals(project)
    tasks = content.tasks(project)
    idea_refs = ideas.read(ideas.scope_of(content, project))
    children = content.children(project)
    deliverables = content.deliverables(project)
    log = content.log(project)

    if st.json:
        data = to_dict(project, content.root)
        data["subprojects"] = [c.id for c in children]
        data["goals"] = to_dict(goals, content.root, exclude=("meta", "body"))
        data["tasks"] = to_dict(tasks, content.root, exclude=("meta", "body"))
        data["ideas"] = [r.idea.text for r in idea_refs]
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

    if goals:
        typer.secho("\nGoals", bold=True)
        for g in goals:
            done = progress(g.tasks_done, g.tasks_total)
            typer.echo(f"  {g.id}  [{g.status}]  {done} tasks  {g.title}")

    typer.secho("\nTasks", bold=True)
    counts = Counter(t.status for t in tasks)
    typer.echo("  " + "  ".join(f"{s}: {counts.get(s, 0)}" for s in TaskStatus))
    loose = [t for t in tasks if not t.goal and t.status != TaskStatus.DONE]
    for t in loose:
        typer.echo(f"  {t.id}  [{t.status}]  {t.title}  (no goal)")

    if deliverables:
        typer.secho("\nDeliverables", bold=True)
        for d in deliverables:
            typer.echo(f"  {d.id}  [{d.status}]  due {fmt_date(d.deadline)}  {d.title}")

    print_ideas(idea_refs)

    if log:
        typer.secho("\nRecent log", bold=True)
        for entry in log[-RECENT_LOG_ENTRIES:]:
            typer.echo(f"  {entry.date.isoformat()}  {entry.text}")
