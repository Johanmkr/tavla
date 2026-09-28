"""``tavla idea ...`` commands: capture, list and triage loose ideas."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    ContentDirOpt,
    JsonOpt,
    complete_goal,
    complete_project,
    complete_task,
    emit_json,
    handles_errors,
    print_ideas,
    state,
)
from tavla.core import ideas, ops
from tavla.core.store import Content

app = typer.Typer(
    help=(
        "Loose ideas, owned by the inbox, a project, a goal or a task. "
        "Refer to one as [SCOPE:]N or [SCOPE:]TEXT, e.g. 3, parx:2, intro:tempering "
        "(SCOPE defaults to the inbox)."
    ),
    no_args_is_help=True,
)

ProjectOpt = Annotated[
    str | None,
    typer.Option("--project", "-p", help="A project's ideas.", autocompletion=complete_project),
]
GoalOpt = Annotated[
    str | None, typer.Option("--goal", "-g", help="A goal's ideas.", autocompletion=complete_goal)
]
TaskOpt = Annotated[
    str | None, typer.Option("--task", "-t", help="A task's ideas.", autocompletion=complete_task)
]
RefArg = Annotated[str, typer.Argument(metavar="REF", help="[SCOPE:]N or [SCOPE:]TEXT.")]


def _scope(
    content: Content, project: str | None, goal: str | None, task: str | None
) -> ideas.Scope | None:
    """The scope picked by -p/-g/-t (at most one), or None if none was given."""
    given = [(k, v) for k, v in (("p", project), ("g", goal), ("t", task)) if v]
    if len(given) > 1:
        raise typer.BadParameter("give at most one of -p, -g, -t")
    if project:
        return ideas.scope_of(content, content.project(project))
    if goal:
        return ideas.scope_of(content, content.goal(goal))
    if task:
        return ideas.scope_of(content, content.task(task))
    return None


@app.command()
@handles_errors
def add(
    ctx: typer.Context,
    text: Annotated[list[str], typer.Argument(help="The idea. Quotes optional; #words are tags.")],
    project: ProjectOpt = None,
    goal: GoalOpt = None,
    task: TaskOpt = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Add an idea to a project, goal or task (default: the inbox)."""
    content = state(ctx, content_dir=content_dir).content()
    scope = _scope(content, project, goal, task) or ideas.scope_of(content, None)
    line = ideas.add(content, scope, " ".join(text))
    typer.echo(f"Added to {scope.label}: {line}")


@app.command("list")
@handles_errors
def list_(
    ctx: typer.Context,
    project: ProjectOpt = None,
    goal: GoalOpt = None,
    task: TaskOpt = None,
    tag: Annotated[
        str | None, typer.Option("--tag", help="Only ideas with this #tag (searches everywhere).")
    ] = None,
    all_: Annotated[bool, typer.Option("--all", "-a", help="Ideas from every scope.")] = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """List ideas: the inbox by default, one scope with -p/-g/-t, or --all."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    scope = _scope(content, project, goal, task)
    if scope is not None:
        scopes = [scope]
    elif all_ or tag:
        scopes = ideas.all_scopes(content)
    else:
        scopes = [ideas.scope_of(content, None)]
    wanted = tag.lstrip("#") if tag else None
    groups = []
    for sc in scopes:
        refs = ideas.read(sc)
        if wanted:
            refs = [r for r in refs if wanted in r.idea.tags]
        if refs:
            groups.append((sc, refs))

    if st.json:
        emit_json(
            [
                {"ref": r.ref, "scope": sc.kind, "text": r.idea.text, "tags": r.idea.tags}
                for sc, refs in groups
                for r in refs
            ]
        )
        return
    if not groups:
        typer.echo("No ideas.")
        return
    single = len(scopes) == 1
    for i, (sc, refs) in enumerate(groups):
        heading = None if single else f"{sc.label} ({sc.kind})" if sc.id else sc.label
        if heading and i:
            typer.echo("")
        if heading:
            typer.secho(heading, bold=True)
        print_ideas(refs, heading=None)


@app.command()
@handles_errors
def move(
    ctx: typer.Context,
    ref: RefArg,
    project: ProjectOpt = None,
    goal: GoalOpt = None,
    task: TaskOpt = None,
    inbox: Annotated[bool, typer.Option("--inbox", help="Move back to the inbox.")] = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Move an idea to a project (-p), goal (-g), task (-t) or back to the inbox."""
    content = state(ctx, content_dir=content_dir).content()
    target = _scope(content, project, goal, task)
    if (target is None) == (not inbox):
        raise typer.BadParameter("give exactly one target: -p, -g, -t or --inbox")
    target = target or ideas.scope_of(content, None)
    idea = ideas.resolve(content, ref)
    ideas.move(content, idea, target)
    typer.echo(f"Moved to {target.label}: {idea.idea.text}")


@app.command()
@handles_errors
def promote(
    ctx: typer.Context,
    ref: RefArg,
    project: ProjectOpt = None,
    goal: GoalOpt = None,
    as_goal: Annotated[
        bool, typer.Option("--as-goal", help="Create a goal (needs -p) instead of a task.")
    ] = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Turn an idea into a task (under -g, or loose in -p) or a goal (--as-goal -p).

    #tags in the idea become the new item's tags; the idea is removed.
    """
    content = state(ctx, content_dir=content_dir).content()
    if goal is None and project is None:
        raise typer.BadParameter("give a goal (-g) or a project (-p)")
    idea = ideas.resolve(content, ref)
    item = ideas.promote(
        content,
        idea,
        project=content.project(project) if project else None,
        goal=content.goal(goal) if goal else None,
        as_goal=as_goal,
    )
    typer.echo(f"Promoted to {ops.kind_of(item)} {item.id}: {item.title}")


@app.command()
@handles_errors
def drop(ctx: typer.Context, ref: RefArg, content_dir: ContentDirOpt = None) -> None:
    """Delete an idea (it stays in git history)."""
    content = state(ctx, content_dir=content_dir).content()
    idea = ideas.resolve(content, ref)
    ideas.drop(content, idea)
    typer.echo(f"Dropped from {idea.scope.label}: {idea.idea.text}")
