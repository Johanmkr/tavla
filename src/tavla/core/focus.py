"""Working on one task at a time: ``tv work``, ``tv pause`` and ``tv done``.

The task you are working on is recorded in ``focus.yaml`` at the root of the
content repo, which exists only while you are working on something::

    task: draft-methods
    since: 2026-10-12 09:30

When the stretch of work ends, it is written to the task's ``## Sessions``
section as ``- 2026-10-12 09:30-11:05 (1h35m)``: with the end date as well
when it ran past midnight, and an optional ``: note`` at the end.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from tavla.core import dates, git_sync, parsing
from tavla.core.entities import UPDATES_HEADING, Task, TaskStatus
from tavla.core.errors import NotFoundError, TavlaError, ValidationError
from tavla.core.store import Content

FOCUS_FILE = "focus.yaml"
SESSIONS_HEADING = "Sessions"

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
    """The task being worked on; an error explaining what to do if there's none."""
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
