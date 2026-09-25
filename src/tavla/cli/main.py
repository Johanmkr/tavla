"""Entry point for the ``tavla`` CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tavla import __version__, config
from tavla.cli import capture, overview, project, task
from tavla.cli.common import State, handles_errors, state
from tavla.core import bootstrap

app = typer.Typer(
    name="tavla",
    help="Research operations: projects, tasks, deliverables and reading, in plain text + git.",
    no_args_is_help=True,
)
app.command("capture")(capture.capture)
app.command("log")(capture.log)
app.command("next")(overview.next_)
app.command("status")(overview.status)
app.add_typer(project.app, name="project")
app.add_typer(task.app, name="task")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tavla {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    content_dir: Annotated[
        Path | None,
        typer.Option("--content-dir", help="Override content dir for this invocation."),
    ] = None,
    json_out: Annotated[
        bool, typer.Option("--json", help="Machine-readable output on read commands.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompts.")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Verbose output.")] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    ctx.obj = State(content_dir, json_out, yes, verbose)


@app.command()
@handles_errors
def init(
    ctx: typer.Context,
    content_dir: Annotated[
        Path | None,
        typer.Option("--content-dir", help="Where to create the content repo."),
    ] = None,
) -> None:
    """Bootstrap a content dir, git-init it, and write a default config."""
    st = state(ctx)
    if content_dir is not None:
        st.content_dir_flag = content_dir
    result = bootstrap.init_content_dir(st.content_dir)
    typer.echo(f"Initialized tavla content repo at {result.content_dir}")
    if result.config_written:
        typer.echo(f"Wrote config to {result.config_written}")
    elif st.verbose:
        typer.echo(f"Existing config left untouched: {config.config_path()}")
