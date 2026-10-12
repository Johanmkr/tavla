"""Working on one task at a time: ``tv work``, ``tv pause``, and the short
commands (``tick``, ``untick``, ``subtask``, ``note``) that act on that task."""

from __future__ import annotations

from typing import Annotated

import typer

from tavla.cli.common import (
    ContentDirOpt,
    JsonOpt,
    TextArg,
    complete_task,
    emit_json,
    handles_errors,
    state,
)
from tavla.cli.task import SubtaskRefs, print_subtasks, set_subtasks
from tavla.core import dates, focus, ops
from tavla.core.store import Content


def working_line(content: Content) -> str | None:
    """``Working on ID (Title) for 1h20m``, or None when not working on anything."""
    current = focus.current(content)
    if current is None:
        return None
    task = next((t for t in content.tasks() if t.id == current.task_id), None)
    title = f" ({task.title})" if task else " (no longer exists)"
    when = "%H:%M" if current.since.date() == dates.local_today() else "%Y-%m-%d %H:%M"
    since = f"since {current.since.strftime(when)}"
    return (
        f"Working on {current.task_id}{title}, {since} ({focus.format_duration(current.elapsed())})"
    )


@handles_errors
def work(
    ctx: typer.Context,
    task_id: Annotated[
        str | None,
        typer.Argument(
            metavar="[TASK]",
            help="Task to work on (none: show the current one).",
            autocompletion=complete_task,
        ),
    ] = None,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Start working on a task, or show the one you are working on.

    The task is marked doing, and until you `tv pause` or `tv done`, the
    short commands (tick, untick, subtask, note) act on it. Starting another
    task is refused until then. Each stretch of work is logged in the task's
    ## Sessions section.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    if task_id is not None:
        task = content.task(task_id)
        if focus.enter(content, task) is None:
            typer.echo(f"Already working on {task.id}.")
        else:
            typer.echo(
                f"Working on {task.id} ({task.title}). `tv pause` or `tv done` when you stop."
            )
            if task.is_waiting:
                typer.secho(
                    f"note: still waiting on {', '.join(task.waiting_on)}",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
        return

    current = focus.current(content)
    if current is None:
        if st.json:
            emit_json(None)
        else:
            typer.echo("Not working on anything. Pick a task with `tv work TASK` (see `tv next`).")
        return
    current_task = focus.focused_task(content)
    total = focus.total_time(current_task) + current.elapsed()
    if st.json:
        emit_json(
            {
                "task": current_task.id,
                "since": current.since.isoformat(timespec="minutes"),
                "minutes": int(current.elapsed().total_seconds()) // 60,
                "total_minutes": int(total.total_seconds()) // 60,
            }
        )
        return
    typer.echo(working_line(content))
    count = len(focus.sessions(current_task)) + 1
    sessions = f"{count} session{'s' * (count != 1)}"
    typer.echo(f"Total on this task: {focus.format_duration(total)} over {sessions}\n")
    print_subtasks(current_task)


@handles_errors
def pause(
    ctx: typer.Context,
    note: Annotated[
        list[str] | None,
        typer.Argument(metavar="[NOTE]...", help="What you got done (saved with the session)."),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Stop working on the current task for now (it stays doing).

    The session (start, end, duration and an optional note) is added to the
    task's ## Sessions section.
    """
    content = state(ctx, content_dir=content_dir).content()
    current, task, session = focus.pause(content, note=" ".join(note or []))
    took = focus.format_duration(session.duration)
    if task is None:
        typer.echo(f"Stopped working on {current.task_id} ({took}); it no longer exists.")
    else:
        typer.echo(f"Paused {task.id} after {took}. `tv work {task.id}` to pick it up again.")


@handles_errors
def tick(ctx: typer.Context, refs: SubtaskRefs, content_dir: ContentDirOpt = None) -> None:
    """Tick off subtasks of the task you are working on."""
    content = state(ctx, content_dir=content_dir).content()
    set_subtasks(content, focus.focused_task(content), refs, done=True)


@handles_errors
def untick(ctx: typer.Context, refs: SubtaskRefs, content_dir: ContentDirOpt = None) -> None:
    """Untick subtasks of the task you are working on."""
    content = state(ctx, content_dir=content_dir).content()
    set_subtasks(content, focus.focused_task(content), refs, done=False)


@handles_errors
def subtask(ctx: typer.Context, text: TextArg, content_dir: ContentDirOpt = None) -> None:
    """Add a subtask to the task you are working on."""
    content = state(ctx, content_dir=content_dir).content()
    print_subtasks(ops.add_subtask(content, focus.focused_task(content), " ".join(text)))


@handles_errors
def note(ctx: typer.Context, text: TextArg, content_dir: ContentDirOpt = None) -> None:
    """Add a timestamped line to the ## Updates of the task you are working on."""
    content = state(ctx, content_dir=content_dir).content()
    task = focus.focused_task(content)
    entry = ops.add_update(content, task, " ".join(text))
    typer.echo(f"Noted on {task.id}: {entry.text}")
