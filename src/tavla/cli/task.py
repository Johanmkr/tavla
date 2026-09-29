"""``tavla task ...`` commands."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    DATE_HELP,
    TAGS_EDIT_HELP,
    ContentDirOpt,
    JsonOpt,
    TextArg,
    YesOpt,
    complete_goal,
    complete_project,
    complete_task,
    drop_item,
    edit_until_valid,
    emit_json,
    examples,
    fmt_date,
    handles_errors,
    is_clear,
    item_changes,
    progress,
    state,
    table,
    warn_misplaced,
)
from tavla.core import ops
from tavla.core.dates import parse_date
from tavla.core.entities import Priority, Task, TaskStatus, to_dict
from tavla.core.store import Content

app = typer.Typer(
    help="Tasks: units of work, optionally under a goal, with subtasks.", no_args_is_help=True
)

TaskArg = Annotated[str, typer.Argument(metavar="ID", autocompletion=complete_task)]
AFTER_HELP = "Tasks this one depends on (comma-separated ids or prefixes)."


def _dep_ids(content: Content, spec: str) -> list[str]:
    """Resolve comma-separated task ids/prefixes to full ids."""
    return [content.task(q).id for q in ops.parse_tags(spec)]


def _after_change(content: Content, task: Task, spec: str) -> list[str] | None:
    """``--after`` on an edit: replace (a,b), adjust (+a,-b) or clear (none)."""
    if is_clear(spec):
        return None
    items = ops.parse_tags(spec)
    if items and all(i[0] in "+-" for i in items):
        parts = []
        for item in items:
            sign, query = item[0], item[1:].strip()
            if sign == "-":
                # Match against the current deps, so a dangling id can be removed.
                current = [d for d in task.depends_on if d.startswith(query)]
                parts.append(f"-{current[0] if len(current) == 1 else query}")
            else:
                parts.append(f"+{content.task(query).id}")
        resolved = ",".join(parts)
    else:
        resolved = ",".join(_dep_ids(content, spec))
    deps = ops.apply_list_spec(task.depends_on, resolved, "--after")
    return deps or None


@app.command(
    epilog=examples(
        'tv task add "Write intro" -g intro --due fri',
        'tv task add "Fix plots" -p thesis --after write-intro --priority high',
    )
)
@handles_errors
def add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="Task title.")],
    goal_id: Annotated[
        str | None,
        typer.Option(
            "--goal", "-g", help="Goal the task belongs to.", autocompletion=complete_goal
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Project for a task without a goal.",
            autocompletion=complete_project,
        ),
    ] = None,
    priority: Annotated[
        Priority | None,
        typer.Option("--priority", help="Task priority (default: the goal's, or med)."),
    ] = None,
    due: Annotated[str | None, typer.Option("--due", help=DATE_HELP)] = None,
    after: Annotated[str | None, typer.Option("--after", help=AFTER_HELP)] = None,
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags.")] = None,
    id_: Annotated[
        str | None, typer.Option("--id", help="Explicit id (default: derived from the title).")
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Create a new task under a goal (-g), or directly in a project (-p), and commit it."""
    content = state(ctx, content_dir=content_dir).content()
    if goal_id is None and project_id is None:
        raise typer.BadParameter("give a goal (-g) or a project (-p)")
    goal = content.goal(goal_id) if goal_id else None
    project = content.project(project_id) if project_id else None
    task = ops.add_task(
        content,
        title,
        project,
        goal=goal,
        id=id_,
        priority=priority,
        due=parse_date(due) if due else None,
        tags=ops.parse_tags(tags),
        depends_on=_dep_ids(content, after) if after else (),
    )
    where = f"goal {task.goal}" if task.goal else f"project {task.project}"
    typer.echo(f"Added task {task.id} to {where}")


def _priority(value: str) -> Priority:
    try:
        return Priority(value.strip().lower())
    except ValueError:
        allowed = ", ".join(p.value for p in Priority)
        raise typer.BadParameter(f"'{value}' is not one of {allowed}, none") from None


@app.command(
    epilog=examples(
        "tv task edit fix-plots --status blocked",
        "tv task edit fix-plots --due none --tags +urgent,-later",
        "tv task edit fix-plots --after +write-intro",
        "tv task edit fix-plots # no options: open in $EDITOR",
    )
)
@handles_errors
def edit(
    ctx: typer.Context,
    task_id: TaskArg,
    title: Annotated[str | None, typer.Option("--title", help="New title.")] = None,
    status: Annotated[TaskStatus | None, typer.Option("--status", help="New status.")] = None,
    priority: Annotated[
        str | None,
        typer.Option("--priority", help="high, med or low; 'none' inherits the goal's."),
    ] = None,
    due: Annotated[str | None, typer.Option("--due", help=f"{DATE_HELP} 'none' clears it.")] = None,
    goal_id: Annotated[
        str | None,
        typer.Option(
            "--goal", "-g", help="Move to this goal; 'none' detaches.", autocompletion=complete_goal
        ),
    ] = None,
    after: Annotated[
        str | None,
        typer.Option("--after", help="Dependencies: a,b replaces, +a,-b adjusts, 'none' clears."),
    ] = None,
    tags: Annotated[str | None, typer.Option("--tags", help=TAGS_EDIT_HELP)] = None,
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Move to this project (with -g, or a loose task).",
            autocompletion=complete_project,
        ),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Change fields with the options given, or with none open the task in $EDITOR.

    Either way the result is validated and committed. Changing `project:` moves
    the task to that project; its goal, if any, must be there too.
    """
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    changes = item_changes(task, status=status, due=due, tags=tags)
    if priority is not None:
        changes["priority"] = None if is_clear(priority) else _priority(priority).value
    if goal_id is not None:
        changes["goal"] = None if is_clear(goal_id) else content.goal(goal_id).id
    if after is not None:
        changes["depends_on"] = _after_change(content, task, after)
    if project_id is not None:
        changes["project"] = content.project(project_id).id
    if changes or title is not None:
        edited = ops.set_fields(content, task, changes, title=title)
    else:
        session = ops.EditSession(task.path)
        edited = edit_until_valid(session, lambda: ops.finish_edit(content, task, session))
    typer.echo("No changes." if edited is None else f"Saved task {edited.id}")


@app.command()
@handles_errors
def start(ctx: typer.Context, task_id: TaskArg, content_dir: ContentDirOpt = None) -> None:
    """Mark a task as doing (from todo, blocked, or done)."""
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    if ops.start(content, task) is None:
        typer.echo(f"{task.id} is already in progress.")
        return
    typer.echo(f"Started: {task.id} ({task.title}) — was {task.status}")
    if task.is_waiting:
        typer.secho(
            f"note: still waiting on {', '.join(task.waiting_on)}",
            fg=typer.colors.YELLOW,
            err=True,
        )


@app.command()
@handles_errors
def done(ctx: typer.Context, task_id: TaskArg, content_dir: ContentDirOpt = None) -> None:
    """Mark a task done (sets status and updated; the body is left untouched)."""
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    # Tasks waiting on nothing but this one: they become available now.
    unblocked = [
        t.id for t in content.tasks() if t.waiting_on == [task.id] and t.status != TaskStatus.DONE
    ]
    if ops.complete(content, task) is None:
        typer.echo(f"{task.id} is already done.")
        return
    typer.echo(f"Done: {task.id} ({task.title})")
    remaining = task.subtasks_total - task.subtasks_done
    if remaining:
        typer.secho(
            f"note: {remaining} of {task.subtasks_total} subtasks were still unchecked",
            fg=typer.colors.YELLOW,
            err=True,
        )
    if unblocked:
        typer.echo(f"Now unblocked: {', '.join(unblocked)}")


SubtaskRefs = Annotated[
    list[str], typer.Argument(metavar="N|TEXT...", help="Subtask numbers, or text to match.")
]


def print_subtasks(task: Task) -> None:
    typer.secho(f"{task.title} ({task.id})", bold=True)
    if not task.subtasks:
        typer.echo(f"  No subtasks. Add one: tv task subtask {task.id} TEXT")
    for s in task.subtasks:
        typer.echo(f"  {s.number:>2}. [{'x' if s.done else ' '}] {s.text}")


def _set_subtasks(content: Content, task: Task, refs: list[str], *, done: bool) -> None:
    subtasks = [ops.resolve_subtask(task, ref) for ref in refs]
    edited = ops.check_subtasks(content, task, subtasks, done=done)
    if edited is None:
        typer.echo(f"Already {'checked' if done else 'unchecked'}.")
        return
    print_subtasks(edited)
    if done and edited.subtasks_done == edited.subtasks_total and edited.status != TaskStatus.DONE:
        typer.secho(
            f"All subtasks done; close the task with: tv task done {edited.id}",
            fg=typer.colors.GREEN,
        )


@app.command(
    epilog=examples(
        "tv task check draft-r # list the subtasks, numbered",
        "tv task check draft-r 2 3",
        'tv task check draft-r "two paragraphs" # by text',
    )
)
@handles_errors
def check(
    ctx: typer.Context,
    task_id: TaskArg,
    refs: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="[N|TEXT]...", help="Subtask numbers, or text to match (none: list them)."
        ),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Tick off subtasks. With none given, list them numbered."""
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    if not refs:
        print_subtasks(task)
        return
    _set_subtasks(content, task, refs, done=True)


@app.command()
@handles_errors
def uncheck(
    ctx: typer.Context, task_id: TaskArg, refs: SubtaskRefs, content_dir: ContentDirOpt = None
) -> None:
    """Untick subtasks."""
    content = state(ctx, content_dir=content_dir).content()
    _set_subtasks(content, content.task(task_id), refs, done=False)


@app.command(epilog=examples("tv task subtask draft-r Write the conclusion"))
@handles_errors
def subtask(
    ctx: typer.Context, task_id: TaskArg, text: TextArg, content_dir: ContentDirOpt = None
) -> None:
    """Add a subtask (an unchecked item at the end of ## Subtasks)."""
    content = state(ctx, content_dir=content_dir).content()
    edited = ops.add_subtask(content, content.task(task_id), " ".join(text))
    print_subtasks(edited)


@app.command(epilog=examples('tv task note draft-r "Found two more MCMC papers"'))
@handles_errors
def note(
    ctx: typer.Context, task_id: TaskArg, text: TextArg, content_dir: ContentDirOpt = None
) -> None:
    """Add a timestamped line to the task's ## Updates section."""
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    entry = ops.add_update(content, task, " ".join(text))
    typer.echo(f"Noted on {task.id}: {entry.text}")


@app.command()
@handles_errors
def drop(
    ctx: typer.Context,
    task_id: TaskArg,
    yes: YesOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Delete a task (it stays in git history; `tv undo` brings it back).

    Refused while other tasks depend on it.
    """
    st = state(ctx, content_dir=content_dir, yes=yes)
    content = st.content()
    drop_item(st, content, "task", content.task(task_id))


def _sort_key(task: Task) -> tuple:
    # Priority first, then soonest due date (undated last), then id.
    return (task.priority.rank, task.due is None, task.due, task.id)


def subtask_progress(task: Task) -> str:
    return progress(task.subtasks_done, task.subtasks_total)


def status_label(task: Task) -> str:
    """Status, marked when the task is waiting on unfinished dependencies."""
    return f"{task.status}*" if task.is_waiting and task.status != TaskStatus.DONE else task.status


@app.command(
    "list",
    epilog=examples(
        "tv task list -p thesis",
        "tv task list -g intro --all",
        "tv task list --status blocked --json",
    ),
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
    goal_id: Annotated[
        str | None,
        typer.Option("--goal", "-g", help="Only this goal's tasks.", autocompletion=complete_goal),
    ] = None,
    status: Annotated[
        TaskStatus | None, typer.Option("--status", help="Only tasks with this status.")
    ] = None,
    all_: Annotated[bool, typer.Option("--all", "-a", help="Include done tasks.")] = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """List tasks, highest priority first. Done tasks are hidden unless asked for.

    A * after the status means the task is waiting on unfinished dependencies.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    project = content.project(project_id) if project_id else None
    tasks = content.tasks(project)
    if goal_id is not None:
        goal = content.goal(goal_id)
        tasks = [t for t in tasks if t.goal == goal.id]
    if status is not None:
        tasks = [t for t in tasks if t.status == status]
    elif not all_:
        tasks = [t for t in tasks if t.status != TaskStatus.DONE]
    tasks = sorted(tasks, key=_sort_key)
    warn_misplaced(tasks)

    if st.json:
        emit_json(to_dict(tasks, content.root, exclude=("meta", "body")))
        return
    if not tasks:
        typer.echo("No tasks.")
        return
    table(
        [
            [
                t.id,
                status_label(t),
                t.priority,
                fmt_date(t.due),
                subtask_progress(t),
                t.goal or "-",
                t.project,
                t.title,
            ]
            for t in tasks
        ],
        ["ID", "STATUS", "PRIORITY", "DUE", "SUBTASKS", "GOAL", "PROJECT", "TITLE"],
    )


@app.command()
@handles_errors
def show(
    ctx: typer.Context,
    task_id: TaskArg,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Show a task's metadata and its full markdown body."""
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    task = content.task(task_id)
    warn_misplaced([task])

    if st.json:
        emit_json(task, content.root)
        return

    def inherited(name: str, value: str) -> str:
        return f"{value} (from goal)" if name in task.inherited else value

    typer.secho(task.title, bold=True)
    statuses = {t.id: t.status for t in content.tasks()}
    deps = ", ".join(f"{d} [{statuses.get(d, 'missing')}]" for d in task.depends_on)
    fields = [
        ("id", task.id),
        ("project", task.project),
        ("goal", task.goal),
        ("status", task.status),
        ("priority", inherited("priority", task.priority)),
        ("after", deps),
        ("tags", ", ".join(task.tags)),
        ("due", inherited("due", fmt_date(task.due)) if task.due else None),
        ("subtasks", subtask_progress(task) if task.subtasks_total else None),
        ("created", fmt_date(task.created) if task.created else None),
        ("updated", fmt_date(task.updated) if task.updated else None),
        ("path", task.path.relative_to(content.root)),
    ]
    for name, value in fields:
        if value:
            typer.echo(f"  {name + ':':<10}{value}")
    typer.echo("")
    typer.echo(task.body.rstrip())
