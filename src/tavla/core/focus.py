"""Working on one task at a time: ``tv work``, ``tv pause`` and ``tv done``.

The task you are working on is recorded in ``focus.yaml`` at the root of the
content repo, which exists only while you are working on something::

    task: draft-methods
    since: 2026-10-12 09:30

When the stretch of work ends, it is written to the task's ``## Sessions``
section as ``- 2026-10-12 09:30-11:05 (1h35m)``: with the end date as well
when it ran past midnight, and an optional ``: note`` at the end.

A task can also be worked on in a terminal of its own (``tv work -t``). Those
sessions don't use ``focus.yaml``, so several can be open at once: each one
is a small file in the cache dir, kept by the ``tv session`` process that runs
the terminal's shell, and when the terminal closes the session is logged and
the task marked done (or the subtask ticked). ``tv pause`` inside the
terminal keeps it from finishing.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from pathlib import Path

from tavla import config
from tavla.core import dates, git_sync, parsing
from tavla.core.entities import UPDATES_HEADING, Task, TaskStatus
from tavla.core.errors import NotFoundError, TavlaError, ValidationError
from tavla.core.store import Content

FOCUS_FILE = "focus.yaml"
SESSIONS_HEADING = "Sessions"
# Set in the shell of a task terminal: the task, and its session file.
ENV_TASK = "TAVLA_TASK"
ENV_SESSION = "TAVLA_SESSION"

_HEADER = "# The task you are working on — managed by tavla (`tv work`, `tv pause`).\n"


@dataclass
class Focus:
    task_id: str
    since: dt.datetime
    path: Path

    def elapsed(self, now: dt.datetime | None = None) -> dt.timedelta:
        return max((now or dates.local_now()) - self.since, dt.timedelta(0))


@dataclass
class Session:
    start: dt.datetime
    end: dt.datetime
    note: str = ""

    @property
    def duration(self) -> dt.timedelta:
        return max(self.end - self.start, dt.timedelta(0))


def focus_path(content: Content) -> Path:
    return content.root / FOCUS_FILE


def current(content: Content) -> Focus | None:
    """The task being worked on, or None. A hand-broken file is an error."""
    path = focus_path(content)
    if not path.is_file():
        return None
    data = parsing.read_yaml(path) or {}
    if not isinstance(data, dict) or not data.get("task"):
        raise ValidationError(f"{path}: expected 'task: ID' (`tv pause` clears it)")
    try:
        since = dt.datetime.fromisoformat(str(data.get("since")))
    except ValueError:
        raise ValidationError(
            f"{path}: invalid since '{data.get('since')}' (expected YYYY-MM-DD HH:MM)"
        ) from None
    return Focus(str(data["task"]), since.replace(tzinfo=None), path)


def focused_task(content: Content) -> Task:
    """The task being worked on (in a task terminal, that terminal's task);
    an error explaining what to do if there's none."""
    if os.environ.get(ENV_TASK):
        return content.task(os.environ[ENV_TASK])
    focus = current(content)
    if focus is None:
        raise TavlaError("you aren't working on a task; pick one with `tv work TASK`")
    task = next((t for t in content.tasks() if t.id == focus.task_id), None)
    if task is None:
        raise NotFoundError(
            f"you were working on '{focus.task_id}', which no longer exists; `tv pause` clears it"
        )
    return task


def format_duration(span: dt.timedelta) -> str:
    """``1h35m``, ``45m``, ``0m``."""
    minutes = int(span.total_seconds()) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


_SESSION_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{1,2}:\d{2})\s*[-–]\s*(?:(\d{4}-\d{2}-\d{2}) )?(\d{1,2}:\d{2})"
    r"(?:\s*\([^)]*\))?\s*(?::\s*(.*))?$"
)


def session_line(session: Session) -> str:
    start, end = session.start, session.end
    until = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%Y-%m-%d %H:%M}"
    line = f"- {start:%Y-%m-%d %H:%M}-{until} ({format_duration(session.duration)})"
    return f"{line}: {session.note}" if session.note else line


def sessions(task: Task) -> list[Session]:
    """The task's recorded work sessions; lines that don't parse are skipped."""
    out = []
    for _, text in parsing.section_bullets(task.body, SESSIONS_HEADING, skip_frontmatter=False):
        m = _SESSION_RE.match(text)
        if not m:
            continue
        try:
            start = dt.datetime.fromisoformat(f"{m[1]} {m[2].zfill(5)}")
            end = dt.datetime.fromisoformat(f"{m[3] or m[1]} {m[4].zfill(5)}")
        except ValueError:
            continue
        out.append(Session(start, end, (m[5] or "").strip()))
    return out


def total_time(task: Task) -> dt.timedelta:
    return sum((s.duration for s in sessions(task)), dt.timedelta(0))


# --- writes ----------------------------------------------------------------------


def _write_focus(path: Path, task_id: str, since: dt.datetime) -> None:
    path.write_text(f"{_HEADER}task: {task_id}\nsince: {since:%Y-%m-%d %H:%M}\n")


def _record_session(task: Task, focus: Focus, now: dt.datetime, note: str | None) -> Session:
    """Append the session to the task file (and bump ``updated``); no commit."""
    session = Session(focus.since, max(now, focus.since), " ".join((note or "").split()))
    text = task.path.read_text()
    text = parsing.ensure_section(text, SESSIONS_HEADING, before=(UPDATES_HEADING,))
    text = parsing.append_to_section(text, SESSIONS_HEADING, session_line(session))
    task.path.write_text(parsing.set_frontmatter_key(text, "updated", now.date()))
    return session


def enter(content: Content, task: Task, *, now: dt.datetime | None = None) -> Focus | None:
    """Start working on ``task``: record it in ``focus.yaml`` and mark it
    doing. Refused while you are working on another task. Returns None if
    you are already working on this one."""
    git_sync.require_repo(content.root)
    focus = current(content)
    if focus is not None:
        if focus.task_id == task.id:
            return None
        raise ValidationError(
            f"you are working on '{focus.task_id}' (since {focus.since:%H:%M}); "
            "`tv pause` or `tv done` first"
        )
    now = now or dates.local_now()
    path = focus_path(content)
    _write_focus(path, task.id, now)
    paths = [path]
    if task.status != TaskStatus.DOING:
        text = parsing.set_frontmatter_key(task.path.read_text(), "status", TaskStatus.DOING.value)
        task.path.write_text(parsing.set_frontmatter_key(text, "updated", now.date()))
        paths.append(task.path)
    git_sync.commit(content.root, f"focus: work on {task.id}", paths)
    content.refresh()
    return current(content)


def pause(
    content: Content, *, note: str | None = None, now: dt.datetime | None = None
) -> tuple[Focus, Task | None, Session]:
    """Stop working on the current task: its session goes in the task file,
    ``focus.yaml`` is removed, and the task stays doing. If the task no
    longer exists, the focus is cleared and the session is not recorded
    (the returned task is None)."""
    git_sync.require_repo(content.root)
    focus = current(content)
    if focus is None:
        raise TavlaError("you aren't working on a task")
    now = now or dates.local_now()
    task = next((t for t in content.tasks() if t.id == focus.task_id), None)
    if task is None:
        session = Session(focus.since, max(now, focus.since))
        paths = [focus.path]
    else:
        session = _record_session(task, focus, now, note)
        paths = [focus.path, task.path]
    focus.path.unlink()
    git_sync.commit(
        content.root,
        f"focus: pause {focus.task_id} ({format_duration(session.duration)})",
        paths,
    )
    content.refresh()
    return focus, task, session


def finish(
    content: Content, task: Task, *, note: str | None = None, now: dt.datetime | None = None
) -> tuple[Task | None, Session | None]:
    """Mark ``task`` done; if you are working on it, also end and record the
    session, all in one commit. Returns the updated task (None if it was
    already done and not being worked on) and the session, if one ended."""
    git_sync.require_repo(content.root)
    focus = current(content)
    working = focus is not None and focus.task_id == task.id
    if task.status == TaskStatus.DONE and not working:
        return None, None
    now = now or dates.local_now()
    session = _record_session(task, focus, now, note) if working and focus else None
    text = parsing.set_frontmatter_key(task.path.read_text(), "status", TaskStatus.DONE.value)
    task.path.write_text(parsing.set_frontmatter_key(text, "updated", now.date()))
    paths = [task.path]
    if working and focus:
        focus.path.unlink()
        paths.append(focus.path)
    git_sync.commit(content.root, f"task: done {task.id}", paths)
    content.refresh()
    return content.task(task.id), session


def rename(content: Content, old_id: str, new_id: str) -> list[Path]:
    """Point ``focus.yaml`` at a renamed task. Returns the changed file, if any."""
    focus = current(content)
    if focus is None or focus.task_id != old_id:
        return []
    _write_focus(focus.path, new_id, focus.since)
    return [focus.path]


# --- task terminals --------------------------------------------------------------


@dataclass
class TerminalSession:
    task_id: str
    since: dt.datetime
    root: Path  # the content repo
    path: Path  # this session's file
    subtask: str | None = None  # text of the subtask the terminal is for
    hold: bool = False  # `tv pause` inside: log the session but don't finish
    pid: int = 0


def sessions_dir() -> Path:
    return config.cache_dir() / "sessions"


def _write_terminal(session: TerminalSession) -> None:
    data = {
        "task": session.task_id,
        "since": f"{session.since:%Y-%m-%d %H:%M}",
        "root": str(session.root),
        "pid": session.pid,
    }
    if session.subtask is not None:
        data["subtask"] = session.subtask
    if session.hold:
        data["hold"] = True
    parsing.write_yaml(session.path, data)


def read_terminal(path: Path) -> TerminalSession | None:
    """The session in ``path``, or None if it is gone or unreadable."""
    try:
        data = parsing.read_yaml(path)
        return TerminalSession(
            task_id=str(data["task"]),
            since=dt.datetime.fromisoformat(str(data["since"])),
            root=Path(data["root"]),
            path=path,
            subtask=None if data.get("subtask") is None else str(data["subtask"]),
            hold=bool(data.get("hold")),
            pid=int(data.get("pid") or 0),
        )
    except (OSError, TypeError, KeyError, ValueError, TavlaError):
        return None


def start_terminal(
    content: Content,
    task: Task,
    subtask: str | None = None,
    *,
    pid: int | None = None,
    now: dt.datetime | None = None,
) -> TerminalSession:
    """Record that a terminal for ``task`` (or one of its subtasks) is open."""
    pid = pid or os.getpid()
    sessions_dir().mkdir(parents=True, exist_ok=True)
    session = TerminalSession(
        task.id,
        (now or dates.local_now()).replace(second=0, microsecond=0),
        content.root.resolve(),
        sessions_dir() / f"{pid}.yaml",
        subtask,
        pid=pid,
    )
    _write_terminal(session)
    return session


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminal_sessions(content: Content) -> list[TerminalSession]:
    """Task terminals open on this content repo, oldest first. Files left by
    terminals that died without cleaning up are removed."""
    out = []
    root = content.root.resolve()
    for path in sorted(sessions_dir().glob("*.yaml")) if sessions_dir().is_dir() else []:
        session = read_terminal(path)
        if session is None or not _alive(session.pid):
            path.unlink(missing_ok=True)
        elif session.root == root:
            out.append(session)
    return sorted(out, key=lambda s: s.since)


def this_terminal() -> TerminalSession | None:
    """The session of the task terminal this process runs in, if any."""
    path = os.environ.get(ENV_SESSION)
    return read_terminal(Path(path)) if path else None


def hold_terminal(session: TerminalSession) -> None:
    """``tv pause`` inside a task terminal: closing it only logs the session."""
    session.hold = True
    _write_terminal(session)


def end_terminal(
    content: Content, session: TerminalSession, *, now: dt.datetime | None = None
) -> str:
    """The terminal closed: log the session in the task file and, unless it
    was held, mark the task done (or tick the subtask), in one commit.
    Returns what happened, in a few words."""
    session = read_terminal(session.path) or session  # `tv pause` may have held it
    session.path.unlink(missing_ok=True)
    content.refresh()
    task = next((t for t in content.tasks() if t.id == session.task_id), None)
    if task is None:
        return f"{session.task_id} no longer exists; nothing recorded"
    git_sync.require_repo(content.root)
    now = now or dates.local_now()
    focus = Focus(task.id, session.since, session.path)
    took = format_duration(_record_session(task, focus, now, None).duration)
    text = task.path.read_text()
    if session.hold:
        done, message = None, f"logged {took} on {task.id}"
    elif session.subtask is not None:
        item = next(
            (i for i, d, t in parsing.checkbox_items(text) if t == session.subtask and not d), None
        )
        done = None if item is None else parsing.set_checkbox(text, item, True)
        message = f"ticked '{session.subtask}' after {took}" if done else f"logged {took}"
    elif task.status != TaskStatus.DONE:
        done = parsing.set_frontmatter_key(text, "status", TaskStatus.DONE.value)
        message = f"done {task.id} after {took}"
    else:
        done, message = None, f"logged {took} on {task.id} (already done)"
    if done is not None:
        task.path.write_text(done)
    git_sync.commit(content.root, f"session: {message}", [task.path])
    content.refresh()
    return message
