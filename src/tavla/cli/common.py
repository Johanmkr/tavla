"""Shared CLI plumbing: global state, error handling, output, completion."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, ParamSpec, TypeVar

import typer

from tavla import config
from tavla.core.entities import to_dict
from tavla.core.errors import TavlaError
from tavla.core.queries import complete_ids
from tavla.core.store import Content


@dataclass
class State:
    content_dir_flag: Path | None = None
    json: bool = False
    yes: bool = False
    verbose: bool = False

    @property
    def content_dir(self) -> Path:
        return config.resolve_content_dir(self.content_dir_flag)

    def content(self) -> Content:
        return Content.open(self.content_dir)


def state(ctx: typer.Context, *, json_out: bool = False) -> State:
    """Global state; a per-command ``--json`` flag is folded into it."""
    st = ctx.find_object(State) or ctx.ensure_object(State)
    st.json = st.json or json_out
    return st


JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]


P = ParamSpec("P")
R = TypeVar("R")


def handles_errors(fn: Callable[P, R]) -> Callable[P, R]:
    """Turn TavlaError into a red message and the error's exit code."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except TavlaError as e:
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(e.exit_code) from e

    return wrapper


# --- output -----------------------------------------------------------------


def emit_json(data: Any, root: Path | None = None) -> None:
    typer.echo(json.dumps(to_dict(data, root), indent=2, ensure_ascii=False))


def table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> None:
    """Print left-aligned columns; the last column is never padded."""
    if not rows:
        return
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers) - 1)]

    def fmt(row: Sequence[str]) -> str:
        cells = [str(c).ljust(w) for c, w in zip(row, widths, strict=False)]
        return "  ".join([*cells, str(row[-1])]).rstrip()

    typer.secho(fmt(headers), bold=True)
    for row in rows:
        typer.echo(fmt(row))


def fmt_date(value: Any) -> str:
    return value.isoformat() if value else "-"


# --- shell completion -------------------------------------------------------


def _content_for_completion(ctx: typer.Context) -> Content:
    flag = None
    c: typer.Context | None = ctx
    while c is not None:
        flag = flag or c.params.get("content_dir")
        c = c.parent
    return Content.open(config.resolve_content_dir(flag))


def complete_project(ctx: typer.Context, incomplete: str) -> list[str]:
    try:
        return complete_ids(incomplete, _content_for_completion(ctx).projects())
    except (TavlaError, OSError):
        return []


def complete_task(ctx: typer.Context, incomplete: str) -> list[str]:
    try:
        return complete_ids(incomplete, _content_for_completion(ctx).tasks())
    except (TavlaError, OSError):
        return []
