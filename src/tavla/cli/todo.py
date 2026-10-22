"""``tavla todo ...``: a quick checklist outside any project."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from tavla.cli import inbox as inbox_cli
from tavla.cli.common import (
    ContentDirOpt,
    JsonOpt,
    complete_goal,
    complete_project,
    complete_task,
    emit_json,
    examples,
    handles_errors,
    state,
)
from tavla.core import inbox, todos


class _AddByDefault(TyperGroup):
    """``tv todo buy milk`` means ``tv todo add buy milk``: words that aren't a
    subcommand are a new todo."""

    # Untyped on purpose: newer typer bundles its own click, so the click
    # package may not be installed.
    def resolve_command(self, ctx: Any, args: list[str]) -> Any:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["add", *args]
        return super().resolve_command(ctx, args)


app = typer.Typer(
    cls=_AddByDefault,
    help="Quick todos outside any project: `tv todo TEXT` adds one, `tv todo` lists them.",
    invoke_without_command=True,
)

AllOpt = Annotated[bool, typer.Option("--all", "-a", help="Include finished todos.")]
RefsArg = Annotated[list[str], typer.Argument(metavar="N|TEXT...", help="Todo numbers or text.")]


def _print(items: list[todos.Todo]) -> None:
    for t in items:
        typer.echo(f"  {t.number:>2}. [{'x' if t.done else ' '}] {t.text}")


def _list(st: Any, all_: bool) -> None:
    items = todos.read(st.content())
    shown = items if all_ else [t for t in items if not t.done]
    if st.json:
        emit_json(
            [{"number": t.number, "text": t.text, "done": t.done, "tags": t.tags} for t in shown]
        )
        return
    if not shown:
        typer.echo("No open todos. Add one: tv todo TEXT")
    _print(shown)
    finished = len(items) - len([t for t in items if not t.done])
    if finished and not all_:
        typer.secho(
            f"… and {finished} done (--all shows them, `tv todo clear` removes them)", dim=True
        )


@app.callback()
@handles_errors
def main(
    ctx: typer.Context,
    all_: AllOpt = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    if ctx.invoked_subcommand is None:
        _list(state(ctx, json_out=json_out, content_dir=content_dir), all_)


@app.command(epilog=examples("tv todo add list the cables # text that is also a command name"))
@handles_errors
def add(
    ctx: typer.Context,
    text: Annotated[list[str], typer.Argument(help="The todo. Quotes optional; #words are tags.")],
    content_dir: ContentDirOpt = None,
) -> None:
    """Add a todo (same as `tv todo TEXT`)."""
    todo = todos.add(state(ctx, content_dir=content_dir).content(), " ".join(text))
    typer.echo(f"Added todo {todo.number}: {todo.text}")


@app.command("list")
@handles_errors
def list_(
    ctx: typer.Context,
    all_: AllOpt = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """List open todos, numbered (same as `tv todo`)."""
    _list(state(ctx, json_out=json_out, content_dir=content_dir), all_)


def _resolve(ctx: typer.Context, refs: list[str], content_dir: Any) -> tuple[Any, list[todos.Todo]]:
    content = state(ctx, content_dir=content_dir).content()
    return content, [todos.resolve(content, r) for r in refs]


@app.command(epilog=examples("tv todo done 2 5", "tv todo done milk"))
@handles_errors
def done(ctx: typer.Context, refs: RefsArg, content_dir: ContentDirOpt = None) -> None:
    """Tick off todos."""
    content, items = _resolve(ctx, refs, content_dir)
    changed = todos.set_done(content, items)
    if not changed:
        typer.echo("Already done.")
    _print([todos.read(content)[i.number - 1] for i in changed])


@app.command()
@handles_errors
def reopen(ctx: typer.Context, refs: RefsArg, content_dir: ContentDirOpt = None) -> None:
    """Untick todos."""
    content, items = _resolve(ctx, refs, content_dir)
    changed = todos.set_done(content, items, done=False)
    if not changed:
        typer.echo("Already open.")
    _print([todos.read(content)[i.number - 1] for i in changed])


@app.command()
@handles_errors
def drop(ctx: typer.Context, refs: RefsArg, content_dir: ContentDirOpt = None) -> None:
    """Delete todos (they stay in git history)."""
    content, items = _resolve(ctx, refs, content_dir)
    todos.drop(content, items)
    for t in items:
        typer.echo(f"Dropped: {t.text}")


@app.command()
@handles_errors
def clear(ctx: typer.Context, content_dir: ContentDirOpt = None) -> None:
    """Remove all finished todos."""
    removed = todos.clear(state(ctx, content_dir=content_dir).content())
    typer.echo(f"Removed {len(removed)} finished todo{'s' * (len(removed) != 1)}.")


@app.command(
    epilog=examples(
        "tv todo promote 3 -p thesis # a loose task in a project",
        "tv todo promote cables -g setup-env",
        "tv todo promote 4 -p thesis --as-goal",
        "tv todo promote 2 --as-project",
        "tv todo promote cables --subtask-of setup-cluster",
    )
)
@handles_errors
def promote(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(metavar="N|TEXT", help="Todo number or text.")],
    project: Annotated[
        str | None,
        typer.Option(
            "--project", "-p", help="Project for the task.", autocompletion=complete_project
        ),
    ] = None,
    goal: Annotated[
        str | None,
        typer.Option("--goal", "-g", help="Goal for the task.", autocompletion=complete_goal),
    ] = None,
    as_goal: Annotated[
        bool, typer.Option("--as-goal", help="Create a goal (needs -p) instead of a task.")
    ] = False,
    as_project: Annotated[
        bool,
        typer.Option("--as-project", help="Create a project (a subproject with -p) instead."),
    ] = False,
    subtask_of: Annotated[
        str | None,
        typer.Option(
            "--subtask-of", help="Add it as a subtask of this task.", autocompletion=complete_task
        ),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Turn a todo into a task (under -g, or loose in -p), a goal (--as-goal
    -p), a project (--as-project, under -p if given) or a subtask (--subtask-of).

    #tags in the todo become the new item's tags; the todo is removed.
    """
    content = state(ctx, content_dir=content_dir).content()
    item = inbox.Item("todo", todos.resolve(content, ref))
    message = inbox_cli.promote(
        content,
        item,
        project=project,
        goal=goal,
        as_goal=as_goal,
        as_project=as_project,
        subtask_of=subtask_of,
    )
    typer.echo(message)
