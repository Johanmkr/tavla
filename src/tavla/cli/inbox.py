"""``tavla inbox``: everything waiting to be sorted, and ``tavla inbox
review`` to go through it one item at a time (the TUI's `T`)."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from tavla.cli.common import ContentDirOpt, JsonOpt, emit_json, examples, handles_errors, state
from tavla.core import ideas, inbox, ops
from tavla.core.errors import NotFoundError, TavlaError
from tavla.core.store import Content

app = typer.Typer(
    help="Chores and ideas waiting to be sorted: `tv inbox` lists them, "
    "`tv inbox review` goes through them one at a time.",
    invoke_without_command=True,
)

FiledOpt = Annotated[
    bool, typer.Option("--filed", "-f", help="Ideas filed under projects, goals and tasks.")
]


def _list(st: Any, filed: bool) -> None:
    content = st.content()
    kinds = ["filed"] if filed else ["todo", "idea"]
    groups = {kind: inbox.items(content, kind) for kind in kinds}
    if st.json:
        emit_json(
            [
                {"kind": kind, "ref": _ref(i), "text": i.text, "where": i.where, "tags": i.tags}
                for kind, items in groups.items()
                for i in items
            ]
        )
        return
    width = max((len(_ref(i)) for items in groups.values() for i in items), default=1)
    for kind, items in groups.items():
        typer.secho(f"{inbox.NAMES[kind].capitalize()} ({len(items)})", bold=True)
        for i in items:
            where = f"  ({i.where})" if kind == "filed" else ""
            typer.echo(f"  {_ref(i):>{width}}  {i.text}{where}")
    if not filed:
        left = len(inbox.items(content, "filed"))
        if any(groups.values()):
            typer.secho("Go through them one at a time: tv inbox review", dim=True)
        else:
            typer.echo("The inbox is empty.")
        if left:
            typer.secho(f"{left} filed ideas: tv inbox --filed", dim=True)


def _ref(item: inbox.Item) -> str:
    """How to name the item in `tv todo …` / `tv idea …`."""
    if item.kind == "todo":
        return str(item.source.number)
    return item.source.ref if item.kind == "filed" else str(item.source.number)


@app.callback()
@handles_errors
def main(
    ctx: typer.Context,
    filed: FiledOpt = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    if ctx.invoked_subcommand is None:
        _list(state(ctx, json_out=json_out, content_dir=content_dir), filed)


# --- review ----------------------------------------------------------------------

KEYS = "t task · g goal · P project · s subtask · l later · x done · D drop · n skip · q quit"
WHERE = {
    "task": "In which goal or project? (? lists them)",
    "goal": "In which project? (? lists them)",
    "project": "Under which project? (enter: a top-level one, ? lists them)",
    "subtask": "Subtask of which task? (? lists them)",
    "later": "File under which project or goal? (? lists them)",
}


def _candidates(content: Content, action: str) -> list[str]:
    """What `?` lists for ``action``'s question: ids first, then titles."""
    projects = [f"{p.id}  {p.title}" for p in content.projects()]
    goals = [f"{g.id}  {g.project} › {g.title}" for g in content.goals() if g.status != "done"]
    if action == "subtask":
        return [f"{t.id}  {t.project} › {t.title}" for t in content.tasks() if t.status != "done"]
    if action in ("task", "later"):
        return goals + projects
    return projects


ACTIONS = {
    "t": "task",
    "g": "goal",
    "P": "project",
    "s": "subtask",
    "l": "later",
    "x": "finish",
    "D": "drop",
}


def decide(content: Content, item: inbox.Item, action: str, where: str, title: str) -> str:
    """Carry out one review decision; returns what happened."""
    if action == "finish":
        inbox.finish(content, item)
        return f"Done: {item.text}"
    if action == "drop":
        inbox.drop(content, item)
        return f"Dropped: {item.text} (tv undo brings it back)"
    if action == "later":
        scope = ideas.resolve_scope(content, where)
        inbox.file_under(content, item, scope)
        return f"Filed under {scope.label}"
    if action == "task":
        try:
            goal = content.goal(where)
        except NotFoundError:
            task = inbox.to_task(content, item, title, project=content.project(where))
            return f"Task {task.id} in {task.project}"
        task = inbox.to_task(content, item, title, goal=goal)
        return f"Task {task.id} in {goal.id}"
    if action == "goal":
        made = inbox.to_goal(content, item, title, content.project(where))
        return f"Goal {made.id} in {made.project}"
    if action == "project":
        parent = content.project(where) if where else None
        project = inbox.to_project(content, item, title, parent)
        return f"Project {project.id}" + (f" under {parent.id}" if parent else "")
    task = inbox.to_subtask(content, item, title, content.task(where))
    return f"Subtask of {task.id}"


def _pass(st: Any, kind: str) -> bool:
    """Go through one kind; False when the user quit."""
    index = 0
    while True:
        content = st.content()
        items = inbox.items(content, kind)
        if index >= len(items):
            typer.secho(f"{inbox.NAMES[kind].capitalize()}: nothing left ✓", fg="green")
            return True
        item = items[index]
        typer.echo("")
        typer.secho(f"{inbox.NAMES[kind].capitalize()} · {index + 1} of {len(items)}", bold=True)
        typer.secho(f"  {item.text}", bold=True)
        typer.secho(f"  from {item.where}", dim=True)
        typer.secho(f"  {KEYS}", dim=True)
        key = typer.prompt("  key", default="n", show_default=False).strip()
        if key == "q":
            return False
        if key not in ACTIONS:
            index += 1  # n, or any other key, skips
            continue
        action = ACTIONS[key]
        where = title = ""
        if action in WHERE:
            where = typer.prompt(f"  {WHERE[action]}", default="", show_default=False).strip()
            while where == "?":
                for line in _candidates(content, action):
                    typer.echo(f"    {line}")
                where = typer.prompt(f"  {WHERE[action]}", default="", show_default=False).strip()
            if not where and action != "project":
                continue  # nothing chosen: ask about the same item again
        if action in ("task", "goal", "project", "subtask"):
            title = typer.prompt("  Title", default=item.title).strip()
        try:
            message = decide(content, item, action, where, title)
        except TavlaError as e:
            typer.secho(f"  {e}", fg="red")
            continue
        typer.secho(f"  {message}", fg="cyan")


@app.command(
    epilog=examples(
        "tv inbox review # chores, then ideas",
        "tv inbox review --ideas",
        "tv inbox review --filed # ideas filed under projects and goals",
    )
)
@handles_errors
def review(
    ctx: typer.Context,
    chores: Annotated[bool, typer.Option("--chores", "-c", help="Only the chores.")] = False,
    ideas_: Annotated[bool, typer.Option("--ideas", "-i", help="Only the ideas.")] = False,
    filed: FiledOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Go through the inbox one item at a time: chores first, then ideas.

    One key per item: t task, g goal, P project, s subtask, l file under a
    project or goal for later, x done already, D drop, n skip, q quit. Each
    decision is one commit.
    """
    st = state(ctx, content_dir=content_dir)
    chosen = [k for k, on in (("todo", chores), ("idea", ideas_), ("filed", filed)) if on]
    for kind in chosen or ["todo", "idea"]:
        if not _pass(st, kind):
            return
    left = len(inbox.items(st.content(), "filed"))
    if not chosen and left:
        typer.secho(f"{left} filed ideas wait too: tv inbox review --filed", dim=True)


def promote(
    content: Content,
    item: inbox.Item,
    *,
    project: str | None,
    goal: str | None,
    as_goal: bool,
    as_project: bool,
    subtask_of: str | None,
) -> str:
    """The shared end of `tv idea promote` and `tv todo promote`."""
    if subtask_of:
        task = inbox.to_subtask(content, item, item.title, content.task(subtask_of))
        return f"Promoted to a subtask of {task.id}: {item.title}"
    if as_project:
        made = inbox.to_project(
            content, item, item.title, content.project(project) if project else None
        )
        return f"Promoted to project {made.id}: {made.title}"
    if goal is None and project is None:
        raise typer.BadParameter("give a goal (-g) or a project (-p)")
    if as_goal:
        if project is None:
            raise typer.BadParameter("--as-goal needs a project (-p)")
        made_goal = inbox.to_goal(content, item, item.title, content.project(project))
        return f"Promoted to goal {made_goal.id}: {made_goal.title}"
    task = inbox.to_task(
        content,
        item,
        item.title,
        project=content.project(project) if project else None,
        goal=content.goal(goal) if goal else None,
    )
    return f"Promoted to {ops.kind_of(task)} {task.id}: {task.title}"
