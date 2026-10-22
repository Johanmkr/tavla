"""Working on one task at a time: ``tv work``, ``tv pause``, and the short
commands (``tick``, ``untick``, ``subtask``, ``note``) that act on that task;
``tv work -t`` and the hidden ``tv session`` for task terminals."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Annotated

import typer

from tavla import config
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
from tavla.core import colours, dates, focus, ops, terminal
from tavla.core.errors import TavlaError
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
    in_terminal: Annotated[
        bool,
        typer.Option(
            "--terminal", "-t", help="Open the task in a terminal of its own; closing it = done."
        ),
    ] = False,
    subtask_ref: Annotated[
        str | None,
        typer.Option(
            "--subtask", "-s", metavar="N|TEXT", help="With -t: for one subtask (ticked on close)."
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

    With -t the task opens in a new terminal instead, titled with the task
    and in its own colour (`tv task edit ID --colour NAME` changes it). The
    short commands act on that task inside it, and when the terminal closes
    the session is logged and the task marked done, or with -s the subtask
    ticked. `tv pause` in the terminal first, and closing it only logs the
    session. Any number of task terminals can be open at once.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    if subtask_ref is not None and not in_terminal:
        raise TavlaError("--subtask goes with --terminal (-t)")
    if in_terminal:
        if task_id is None:
            raise TavlaError("name the task to open: `tv work -t TASK`")
        task = content.task(task_id)
        sub = ops.resolve_subtask(task, subtask_ref) if subtask_ref is not None else None
        name = terminal.open_task(content, task, sub)
        what = f"'{sub.text}' of {task.id}" if sub else f"{task.id} ({task.title})"
        done = "ticks it" if sub else "marks it done"
        typer.echo(f"Opened {what} in {name}; closing the terminal {done}.")
        return
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
    terminals = focus.terminal_sessions(content)
    if current is None:
        if st.json:
            emit_json({"terminals": [_terminal_json(s) for s in terminals]} if terminals else None)
        elif terminals:
            print_terminals(terminals)
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
                "terminals": [_terminal_json(s) for s in terminals],
            }
        )
        return
    typer.echo(working_line(content))
    count = len(focus.sessions(current_task)) + 1
    sessions = f"{count} session{'s' * (count != 1)}"
    typer.echo(f"Total on this task: {focus.format_duration(total)} over {sessions}\n")
    print_subtasks(current_task)
    if terminals:
        typer.echo()
        print_terminals(terminals)


def _terminal_json(session: focus.TerminalSession) -> dict[str, object]:
    return {
        "task": session.task_id,
        "subtask": session.subtask,
        "since": session.since.isoformat(timespec="minutes"),
        "held": session.hold,
    }


def print_terminals(sessions: list[focus.TerminalSession]) -> None:
    typer.echo("Open task terminals:")
    for s in sessions:
        what = f"{s.task_id} › {s.subtask}" if s.subtask else s.task_id
        held = " (paused: won't finish)" if s.hold else ""
        typer.echo(f"  {what}, since {s.since:%H:%M}{held}")


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
    task's ## Sessions section. In a task terminal (`tv work -t`) it keeps
    the task from being marked done when the terminal closes.
    """
    content = state(ctx, content_dir=content_dir).content()
    held = focus.this_terminal()
    if held is not None:
        focus.hold_terminal(held)
        typer.echo(
            f"Closing this terminal will log the session on {held.task_id} but not finish it."
        )
        return
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


# --- the process inside a task terminal -------------------------------------------


def _osc(task_title: str, scheme: colours.Scheme) -> str:
    """Title and colours as escape codes, for terminals tavla can't set them
    for on the command line (and harmless in the others)."""
    codes = [
        f"2;{task_title}",
        f"10;{scheme.foreground}",
        f"11;{scheme.background}",
        f"12;{scheme.accent}",
    ]
    return "".join(f"\033]{c}\007" for c in codes)


def _detach_from_tty() -> None:
    """The window is gone: point stdio at /dev/null so nothing (git, a stray
    print) fails writing to a dead terminal."""
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)


def _take_tty_back() -> None:
    """After the shell exits, be the terminal's foreground process again so
    a prompt can be read."""
    try:
        old = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        os.tcsetpgrp(sys.stdin.fileno(), os.getpgrp())
        signal.signal(signal.SIGTTOU, old)
    except OSError:
        pass


def _log(message: str) -> None:
    try:
        config.cache_dir().mkdir(parents=True, exist_ok=True)
        with (config.cache_dir() / "sessions.log").open("a") as f:
            f.write(f"{dates.local_now():%Y-%m-%d %H:%M} {message}\n")
    except OSError:
        pass


def session(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(metavar="TASK")],
    subtask_number: Annotated[int | None, typer.Option("--subtask")] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Run your shell for a task terminal, and finish the task when it ends.

    Started by `tv work -t`; not meant to be run by hand.
    """
    content = state(ctx, content_dir=content_dir).content()
    task = content.task(task_id)
    sub = ops.resolve_subtask(task, str(subtask_number)) if subtask_number else None
    current = focus.start_terminal(content, task, sub.text if sub else None)
    sys.stdout.write(_osc(terminal.title(task, sub), colours.scheme(task.id, task.colour)))
    what = f"'{sub.text}' of {task.id}" if sub else task.id
    sys.stdout.write(
        f"Working on {what}. Closing this terminal marks it "
        f"{'ticked' if sub else 'done'}; `tv pause` first to only log the session.\n"
    )
    sys.stdout.flush()

    # Closing the window hangs up the terminal: the shell exits, and this
    # process must outlive it long enough to record the session. Handlers
    # (not SIG_IGN) so the shell still starts with the default ones.
    hung_up = False

    def on_hangup(signum: int, frame: object) -> None:
        nonlocal hung_up
        hung_up = True

    signal.signal(signal.SIGHUP, on_hangup)
    signal.signal(signal.SIGTERM, on_hangup)
    signal.signal(signal.SIGINT, lambda signum, frame: None)
    env = {
        **os.environ,
        focus.ENV_TASK: task.id,
        focus.ENV_SESSION: str(current.path),
        "DISABLE_AUTO_TITLE": "true",  # oh-my-zsh: keep the task as the title
    }
    shell = subprocess.Popen([os.environ.get("SHELL") or "/bin/sh"], env=env)
    grace = 5.0  # seconds the shell gets to exit after a hang-up
    while shell.poll() is None:
        if hung_up:
            grace -= 0.2
            if grace <= 0:
                break
        time.sleep(0.2)
    if hung_up:
        _detach_from_tty()
    try:
        message = focus.end_terminal(content, current)
    except Exception as e:  # noqa: BLE001 - the window may be gone; keep a trace
        _log(f"{task.id}: could not finish the session: {e}")
        if not hung_up:
            _take_tty_back()
            typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
            input("Press Enter to close.")
        raise typer.Exit(1) from None
    _log(f"{task.id}: {message}")
