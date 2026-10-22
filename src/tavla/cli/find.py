"""``tavla find``: search everything."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    ContentDirOpt,
    JsonOpt,
    complete_project,
    emit_json,
    handles_errors,
    state,
)
from tavla.core import search

HEADINGS = {
    "project": "Projects",
    "goal": "Goals",
    "task": "Tasks",
    "deliverable": "Deliverables",
    "idea": "Ideas",
    "todo": "Todos",
    "log": "Log",
}
FINISHED = {"done", "archived", "accepted", "published"}


@handles_errors
def find(
    ctx: typer.Context,
    words: Annotated[
        list[str], typer.Argument(metavar="WORDS...", help="Every word must appear (any case).")
    ],
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Only this project (and its subprojects).",
            autocompletion=complete_project,
        ),
    ] = None,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Search projects, goals, tasks (with their notes), deliverables, ideas, todos and logs.

    Finished items are found too, and shown dim. A task or goal found by its
    text rather than its title shows the line that matched.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    project = content.project(project_id) if project_id else None
    hits = search.find(content, " ".join(words), project=project)
    if st.json:
        emit_json(hits)
        return
    if not hits:
        typer.echo("Nothing found.")
        return
    for kind in search.KINDS:
        group = [h for h in hits if h.kind == kind]
        if not group:
            continue
        typer.secho(f"{HEADINGS[kind]} ({len(group)})", bold=True)
        width = max(len(h.ref) for h in group)
        for h in group:
            status = f"[{h.status}]  " if h.status and kind != "todo" else ""
            where = f"  ({h.project})" if h.project and kind not in ("project", "idea") else ""
            line = f"  {h.ref:<{width}}  {status}{h.text}{where}"
            typer.secho(line, dim=h.status in FINISHED)
            if h.match:
                typer.secho(f"  {'':<{width}}  … {h.match}", dim=True)
