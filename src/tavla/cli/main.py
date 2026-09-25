"""Entry point for the ``tavla`` CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from tavla import __version__, config
from tavla.core import bootstrap
from tavla.core.errors import TavlaError

app = typer.Typer(
    name="tavla",
    help="Research operations: projects, tasks, deliverables and reading, in plain text + git.",
    no_args_is_help=True,
)


@dataclass
class State:
    content_dir_flag: Path | None = None
    json: bool = False
    yes: bool = False
    verbose: bool = False

    @property
    def content_dir(self) -> Path:
        return config.resolve_content_dir(self.content_dir_flag)


def _state(ctx: typer.Context) -> State:
    return ctx.ensure_object(State)


def _fail(err: TavlaError) -> typer.Exit:
    typer.secho(f"error: {err}", fg=typer.colors.RED, err=True)
    return typer.Exit(err.exit_code)


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
def init(
    ctx: typer.Context,
    content_dir: Annotated[
        Path | None,
        typer.Option("--content-dir", help="Where to create the content repo."),
    ] = None,
) -> None:
    """Bootstrap a content dir, git-init it, and write a default config."""
    state = _state(ctx)
    if content_dir is not None:
        state.content_dir_flag = content_dir
    try:
        result = bootstrap.init_content_dir(state.content_dir)
    except TavlaError as e:
        raise _fail(e) from e
    typer.echo(f"Initialized tavla content repo at {result.content_dir}")
    if result.config_written:
        typer.echo(f"Wrote config to {result.config_written}")
    elif state.verbose:
        typer.echo(f"Existing config left untouched: {config.config_path()}")
