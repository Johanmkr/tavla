"""``tavla deliverable ...`` commands."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    DATE_HELP,
    ContentDirOpt,
    JsonOpt,
    YesOpt,
    complete_deliverable,
    complete_project,
    date_change,
    drop_item,
    edit_until_valid,
    emit_json,
    examples,
    fmt_date,
    handles_errors,
    is_clear,
    state,
    table,
)
from tavla.core import ops
from tavla.core.dates import parse_date
from tavla.core.entities import Deliverable, DeliverableKind, DeliverableStatus
from tavla.core.queries import FINISHED_DELIVERABLE_STATUSES

app = typer.Typer(
    help="Deliverables: papers, slides, datasets and code releases, with venue and deadline.",
    no_args_is_help=True,
)

DeliverableArg = Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_deliverable)]
COAUTHORS_EDIT_HELP = "Replace coauthors (a,b) or adjust them (+a,-b)."


@app.command(
    epilog=examples(
        'tv deliverable add "Adaptive sampling paper" -p thesis --venue "NeurIPS 2027" '
        "--deadline 15.05.2027",
        'tv deliverable add "Group meeting talk" -p thesis --kind slides --deadline fri',
    )
)
@handles_errors
def add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="Deliverable title.")],
    project_id: Annotated[
        str,
        typer.Option(
            "--project", "-p", help="Project it belongs to.", autocompletion=complete_project
        ),
    ],
    kind: Annotated[DeliverableKind, typer.Option("--kind", help="What it is.")] = (
        DeliverableKind.PAPER
    ),
    venue: Annotated[str | None, typer.Option("--venue", help="Journal, conference, …")] = None,
    deadline: Annotated[str | None, typer.Option("--deadline", help=DATE_HELP)] = None,
    coauthors: Annotated[
        str | None, typer.Option("--coauthors", help="Comma-separated names.")
    ] = None,
    id_: Annotated[
        str | None, typer.Option("--id", help="Explicit id (default: derived from the title).")
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Create a deliverable (status: drafting) in a project and commit it."""
    content = state(ctx, content_dir=content_dir).content()
    project = content.project(project_id)
    deliverable = ops.add_deliverable(
        content,
        title,
        project,
        id=id_,
        kind=kind,
        venue=venue,
        deadline=parse_date(deadline) if deadline else None,
        coauthors=ops.parse_tags(coauthors),
    )
    typer.echo(f"Added deliverable {deliverable.id} to {project.id}")


@app.command(
    epilog=examples(
        "tv deliverable edit adaptive --status submitted",
        "tv deliverable edit adaptive --deadline none --coauthors +advisor",
        "tv deliverable edit adaptive # no options: open in $EDITOR",
    )
)
@handles_errors
def edit(
    ctx: typer.Context,
    deliverable_id: DeliverableArg,
    title: Annotated[str | None, typer.Option("--title", help="New title.")] = None,
    status: Annotated[
        DeliverableStatus | None, typer.Option("--status", help="New status.")
    ] = None,
    kind: Annotated[DeliverableKind | None, typer.Option("--kind", help="New kind.")] = None,
    venue: Annotated[
        str | None, typer.Option("--venue", help="New venue; 'none' clears it.")
    ] = None,
    deadline: Annotated[
        str | None, typer.Option("--deadline", help=f"{DATE_HELP} 'none' clears it.")
    ] = None,
    coauthors: Annotated[str | None, typer.Option("--coauthors", help=COAUTHORS_EDIT_HELP)] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Change fields with the options given, or with none open the file in $EDITOR.

    Either way the result is validated and committed.
    """
    content = state(ctx, content_dir=content_dir).content()
    deliverable = content.deliverable(deliverable_id)
    changes: dict = {}
    if title is not None:
        changes["title"] = ops.clean_title(title)
    if status is not None:
        changes["status"] = status.value
    if kind is not None:
        changes["kind"] = kind.value
    if venue is not None:
        changes["venue"] = None if is_clear(venue) else " ".join(venue.split())
    if deadline is not None:
        changes["deadline"] = date_change(deadline)
    if coauthors is not None:
        changes["coauthors"] = ops.apply_list_spec(deliverable.coauthors, coauthors, "coauthors")
    if changes:
        edited = ops.set_deliverable_fields(content, deliverable, changes)
    else:
        session = ops.EditSession(deliverable.path)
        edited = edit_until_valid(
            session, lambda: ops.finish_deliverable_edit(content, deliverable, session)
        )
    typer.echo("No changes." if edited is None else f"Saved deliverable {edited.id}")


def _sort_key(d: Deliverable) -> tuple:
    # Soonest deadline first (undated last), then id.
    return (d.deadline is None, d.deadline, d.id)


@app.command(
    "list",
    epilog=examples("tv deliverable list -p thesis", "tv deliverable list --status submitted"),
)
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
        DeliverableStatus | None, typer.Option("--status", help="Only this status.")
    ] = None,
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Include accepted and published ones.")
    ] = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """List deliverables, soonest deadline first. Accepted and published ones are
    hidden unless asked for."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    if project_id:
        project = content.project(project_id)
        scope = {project.id} | {p.id for p in content.descendants(project)}
        deliverables = [d for d in content.deliverables() if d.project in scope]
    else:
        deliverables = content.deliverables()
    if status is not None:
        deliverables = [d for d in deliverables if d.status == status]
    elif not all_:
        deliverables = [d for d in deliverables if d.status not in FINISHED_DELIVERABLE_STATUSES]
    deliverables = sorted(deliverables, key=_sort_key)

    if st.json:
        emit_json(deliverables, content.root)
        return
    if not deliverables:
        typer.echo("No deliverables.")
        return
    table(
        [
            [d.id, d.kind, d.status, fmt_date(d.deadline), d.venue or "-", d.project, d.title]
            for d in deliverables
        ],
        ["ID", "KIND", "STATUS", "DEADLINE", "VENUE", "PROJECT", "TITLE"],
    )


@app.command()
@handles_errors
def show(
    ctx: typer.Context,
    deliverable_id: DeliverableArg,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Show a deliverable's fields."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    d = content.deliverable(deliverable_id)
    if st.json:
        emit_json(d, content.root)
        return
    typer.secho(d.title, bold=True)
    fields = [
        ("id", d.id),
        ("project", d.project),
        ("kind", d.kind),
        ("status", d.status),
        ("venue", d.venue),
        ("deadline", fmt_date(d.deadline) if d.deadline else None),
        ("coauthors", ", ".join(d.coauthors)),
        ("path", d.path.relative_to(content.root)),
    ]
    for name, value in fields:
        if value:
            typer.echo(f"  {name + ':':<11}{value}")


@app.command()
@handles_errors
def drop(
    ctx: typer.Context,
    deliverable_id: DeliverableArg,
    yes: YesOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Delete a deliverable (it stays in git history; `tv undo` brings it back)."""
    st = state(ctx, content_dir=content_dir, yes=yes)
    content = st.content()
    drop_item(st, content, "deliverable", content.deliverable(deliverable_id))
