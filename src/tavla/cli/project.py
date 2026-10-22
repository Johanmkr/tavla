"""``tavla project ...`` commands."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from tavla.cli.common import (
    TAGS_EDIT_HELP,
    ContentDirOpt,
    JsonOpt,
    YesOpt,
    complete_project,
    edit_until_valid,
    emit_json,
    examples,
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


@app.command(
    epilog=examples(
        'tv project add "PhD thesis" --id thesis --tags phd',
        'tv project add "Chapter 2" -p thesis  # a subproject',
    )
)
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


ProjectArg = Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_project)]


def _set_status(
    ctx: typer.Context,
    project_id: str,
    status: ProjectStatus,
    verb: str,
    shown: str,
    content_dir: Path | None,
) -> None:
    content = state(ctx, content_dir=content_dir).content()
    project = content.project(project_id)
    if ops.set_project_status(content, project, status, verb=verb) is None:
        typer.echo(f"{project.id} is already {status}.")
        return
    typer.echo(f"{shown}: {project.id} ({project.title}) — was {project.status}")


@app.command()
@handles_errors
def pause(ctx: typer.Context, project_id: ProjectArg, content_dir: ContentDirOpt = None) -> None:
    """Put a project on hold: its tasks leave `tv next`, and it is never called stale."""
    _set_status(ctx, project_id, ProjectStatus.PAUSED, "pause", "Paused", content_dir)


@app.command()
@handles_errors
def resume(ctx: typer.Context, project_id: ProjectArg, content_dir: ContentDirOpt = None) -> None:
    """Make a paused, done or archived project active again."""
    _set_status(ctx, project_id, ProjectStatus.ACTIVE, "resume", "Resumed", content_dir)


@app.command()
@handles_errors
def done(ctx: typer.Context, project_id: ProjectArg, content_dir: ContentDirOpt = None) -> None:
    """Mark a project done: it leaves `tv next` and `tv status`. Its goals and tasks are left as they are."""
    _set_status(ctx, project_id, ProjectStatus.DONE, "done", "Done", content_dir)


@app.command()
@handles_errors
def archive(ctx: typer.Context, project_id: ProjectArg, content_dir: ContentDirOpt = None) -> None:
    """Archive a project: like done, and also hidden from `tv project list` unless -a."""
    _set_status(ctx, project_id, ProjectStatus.ARCHIVED, "archive", "Archived", content_dir)


@app.command(
    epilog=examples(
        "tv project drop scratch",
        "tv project drop old-course --force  # with its goals, tasks and notes",
    )
)
@handles_errors
def drop(
    ctx: typer.Context,
    project_id: ProjectArg,
    force: Annotated[
        bool,
        typer.Option("--force", help="Also drop the goals, tasks and deliverables in it."),
    ] = False,
    yes: YesOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Delete a project folder (it stays in git history; `tv undo` brings it back).

    Refused while it has subprojects, while tasks elsewhere depend on its
    tasks, and, without --force, while it has goals, tasks or deliverables.
    `tv project archive` hides a project without deleting it.
    """
    st = state(ctx, content_dir=content_dir, yes=yes)
    content = st.content()
    project = content.project(project_id)
    ops.check_project_droppable(content, project, force=force)
    if not st.yes and not typer.confirm(f"Drop project {project.id} ({project.title})?"):
        raise typer.Abort()
    ops.drop_project(content, project, force=force)
    typer.echo(f"Dropped project {project.id}")


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
        ("repo_path", ", ".join(project.repo_paths)),
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


FolderArg = Annotated[
    Path | None,
    typer.Argument(metavar="[FOLDER]", help="The folder (default: the current one)."),
]


@app.command(
    epilog=examples(
        "cd ~/code/thesis && tv project link thesis",
        "tv project link thesis ~/papers/thesis-draft # a second folder",
    )
)
@handles_errors
def link(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_project)],
    folder: FolderArg = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Link a folder (e.g. the project's code) to the project.

    Inside a linked folder or below it, `tv next` and `tv task list` show just
    this project (-G shows everything). Saved in repo_path:, with your home
    directory written as ~.
    """
    content = state(ctx, content_dir=content_dir).content()
    project = content.project(project_id)
    folder = folder or Path.cwd()
    if ops.link_folder(content, project, folder) is None:
        typer.echo(f"{ops.stored_folder(folder)} is already linked to {project.id}.")
        return
    typer.echo(f"Linked {ops.stored_folder(folder)} to project {project.id}")


@app.command()
@handles_errors
def unlink(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_project)],
    folder: Annotated[
        Path | None,
        typer.Argument(metavar="[FOLDER]", help="The folder to unlink (default: all of them)."),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Remove a linked folder from the project (all of them if none is given)."""
    content = state(ctx, content_dir=content_dir).content()
    project = content.project(project_id)
    removed = ops.unlink_folder(content, project, folder)
    if not removed:
        typer.echo(f"{project.id} has no linked folders.")
    for entry in removed:
        typer.echo(f"Unlinked {entry} from project {project.id}")
