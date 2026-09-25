"""Low-friction capture: ``tavla capture`` and ``tavla log``."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import complete_project, handles_errors, state
from tavla.core import ops


@handles_errors
def capture(
    ctx: typer.Context,
    text: Annotated[
        list[str], typer.Argument(help="What to capture. Quotes optional: words are joined.")
    ],
) -> None:
    """Append a thought, idea or todo to the inbox for later triage."""
    line = ops.capture(state(ctx).content(), " ".join(text))
    typer.echo(f"Captured: {line}")


@handles_errors
def log(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(metavar="PROJECT", autocompletion=complete_project)],
    text: Annotated[list[str], typer.Argument(help="Log entry. Quotes optional.")],
) -> None:
    """Append a timestamped progress note to a project's log.md."""
    content = state(ctx).content()
    project = content.project(project_id)
    entry = ops.append_log(content, project, " ".join(text))
    typer.echo(f"Logged to {project.id}: {entry.text}")
