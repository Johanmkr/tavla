"""Low-friction capture: ``tavla capture`` and ``tavla log`` (which also reads the log)."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    ContentDirOpt,
    GlobalOpt,
    JsonOpt,
    complete_project,
    emit_json,
    handles_errors,
    scoped_project,
    state,
)
from tavla.core import ideas, ops, search
from tavla.core.entities import ProjectStatus, to_dict


@handles_errors
def capture(
    ctx: typer.Context,
    text: Annotated[
        list[str], typer.Argument(help="What to capture. Quotes optional: words are joined.")
    ],
    content_dir: ContentDirOpt = None,
) -> None:
    """Append a thought or idea to the inbox for later triage (see `idea`; todos: `todo`)."""
    content = state(ctx, content_dir=content_dir).content()
    line = ideas.add(content, ideas.scope_of(content, None), " ".join(text))
    typer.echo(f"Captured: {line}")


@handles_errors
def log(
    ctx: typer.Context,
    project_id: Annotated[
        str | None,
        typer.Argument(
            metavar="[PROJECT]",
            help="Default: the project of the folder you are in, else all projects.",
            autocompletion=complete_project,
        ),
    ] = None,
    text: Annotated[
        list[str] | None,
        typer.Argument(metavar="[TEXT]...", help="Log entry. Quotes optional."),
    ] = None,
    last: Annotated[
        int, typer.Option("--last", "-n", min=0, help="Show this many entries (0 = all).")
    ] = 10,
    global_: GlobalOpt = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Append a timestamped progress note to a project's log.md, or show the log.

    With TEXT, the note is added. Without it, the newest entries are shown:
    of PROJECT, of the project whose folder you are in, or of every project
    that isn't archived.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    if project_id and text:
        project = content.project(project_id)
        entry = ops.append_log(content, project, " ".join(text))
        typer.echo(f"Logged to {project.id}: {entry.text}")
        return
    project = scoped_project(st, content, project_id, global_)
    projects = (
        [project]
        if project is not None
        else [p for p in content.projects() if p.status != ProjectStatus.ARCHIVED]
    )
    entries = search.log_entries(content, projects)
    if last:
        entries = entries[:last]
    if st.json:
        emit_json([{"project": p.id, **to_dict(e)} for p, e in entries])
        return
    if not entries:
        typer.echo(f"No log entries{f' in {project.id}' if project else ''}.")
        return
    for p, entry in entries:
        stamp = search.stamp(entry)
        where = "" if project is not None else f"  {p.id}"
        typer.echo(f"{stamp:<16}{where}  {entry.text}")
