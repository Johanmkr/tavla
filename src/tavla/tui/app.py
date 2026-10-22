"""``tv ui``: a drill-down view of the content repo, in columns.

``PROJECT | GOAL | TASK | preview``: pick a project, pick a goal, pick a task,
read it on the right. The header says where you are, what you are working on
and what needs attention; the hint line says what the keys do here. Four
scopes — a project (`1`), `next` (`2`), the inbox (`3`) and the agenda (`4`) —
decide what the left column holds.

Every change goes through the same core functions as the CLI (validated, one
commit, so `tv undo` works), and the view reloads whenever the repo's HEAD
moves, whoever moved it.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.events import Key, Resize
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from tavla import config
from tavla.cli.common import date_change, open_in_editor
from tavla.core import (
    dates,
    flow,
    git_sync,
    history,
    ideas,
    ops,
    people,
    queries,
    terminal,
    todos,
)
from tavla.core import focus as work
from tavla.core.entities import (
    Deliverable,
    Goal,
    Priority,
    Project,
    Task,
    TaskStatus,
)
from tavla.core.errors import GitError, TavlaError, ValidationError
from tavla.core.ops import EditSession
from tavla.core.store import Content
from tavla.tui import model
from tavla.tui.model import Context, Row
from tavla.tui.screens import Confirm, FlowScreen, Help, ListScreen, Picker, Prompt

POLL_SECONDS = 2.0
STATUS_EVERY = 30.0  # refresh the work timer and alerts this often
MIN_SIZE = (40, 12)
# From this many columns up every column fits; below it the leftmost one is
# dropped and the breadcrumb says what went (decision 8).
WIDE = 100
LIST_MIN = 20  # narrowest a navigation column may get
PREVIEW_MIN = 34

SCOPES = ("project", "next", "inbox", "agenda")
SCOPE_KEYS = {"1": "project", "2": "next", "3": "inbox", "4": "agenda"}

NEXT_PRIORITY = {
    Priority.HIGH: Priority.MED,
    Priority.MED: Priority.LOW,
    Priority.LOW: Priority.HIGH,
}

# The hint line: what the keys do where the cursor is.
HINTS = {
    ("project", "list"): "enter tasks  o goal  O project  space done  s start  P project",
    ("project", "mid"): "space done  s start  w work  W terminal  a after  J K order  m move",
    ("project", "preview"): "space tick  o subtask  e edit  w work  W terminal  n note  esc back",
    ("next", "list"): "space done  s start  w work  W terminal  enter open  e edit  t due",
    ("next", "preview"): "space tick  o subtask  e edit  W terminal  n note  esc back",
    ("inbox", "list"): "space done  p promote  o add  O project  D drop  e edit file",
    ("inbox", "preview"): "space tick  o subtask  D drop  esc back",
    ("agenda", "list"): "enter go to item  space done  w work  o todo  / filter",
    ("agenda", "preview"): "space tick  o subtask  e edit  esc back",
}
COMMON_HINT = "  v mark  J K order  @ people  f board  / filter  ? help"
MARK_HINT = "j k extend marks  space done all  V mark column  esc leave  "


@dataclass
class Outcome:
    """What a write job reports back to the UI thread."""

    message: str = ""
    select: tuple[str, str] | None = None  # (column, row key) to select afterwards
    at: tuple[str, int] | None = None  # (column, row index) to select afterwards


JobResult = Outcome | None
Job = Callable[[Content], JobResult]


class Column(OptionList):
    """One column: a list of :class:`Row` s that keeps its selection by key
    across reloads."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j,down", "cursor_down", show=False),
        Binding("k,up", "cursor_up", show=False),
        Binding("G", "last", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("ctrl+f", "page_down", show=False),
        Binding("ctrl+b", "page_up", show=False),
        Binding("H", "view_top", show=False),
        Binding("M", "view_middle", show=False),
        Binding("L", "view_bottom", show=False),
    ]

    def __init__(self, title: str, *, id: str) -> None:
        super().__init__(id=id, classes="column")
        self.title = title
        self.border_title = title
        self.rows: list[Row] = []
        self.wanted: str | None = None  # a key asked for before the row existed

    @property
    def current(self) -> Row | None:
        i = self.highlighted
        return self.rows[i] if i is not None and 0 <= i < len(self.rows) else None

    @property
    def index(self) -> int | None:
        return self.highlighted

    def enabled(self) -> list[Row]:
        return [r for r in self.rows if not r.disabled]

    def show(
        self,
        rows: list[Row],
        keep: str | None = None,
        marked: set[str] | None = None,
        empty: str = "",
    ) -> None:
        """Replace the rows, keeping the selected key (or ``keep``) when it is
        still there."""
        keep = keep or self.wanted or (self.current.key if self.current else None)
        marked = marked or set()
        if not any(not r.disabled for r in rows) and empty:
            rows = [*rows, Row("empty", "empty", Text(empty, style="dim italic"), disabled=True)]
        with self.prevent(OptionList.OptionHighlighted):
            self.clear_options()
            self.add_options(
                [
                    Option(
                        model.mark_prompt(r.prompt) if r.key in marked else r.prompt,
                        id=f"{n}:{r.key}",
                        disabled=r.disabled,
                    )
                    for n, r in enumerate(rows)
                ]
            )
            self.rows = rows
            enabled = [n for n, r in enumerate(rows) if not r.disabled]
            wanted = next((n for n in enabled if rows[n].key == keep), None)
            if wanted is not None:
                self.wanted = None  # found: nothing left to wait for
            self.highlighted = wanted if wanted is not None else self.first_row(enabled)

    def first_row(self, enabled: list[int]) -> int | None:
        """The row to land on when no row was selected before."""
        return enabled[0] if enabled else None

    def select_key(self, key: str) -> bool:
        """Select ``key``, or remember it until a reload brings the row in
        (the preview is rebuilt a message pass after the write lands)."""
        for n, r in enumerate(self.rows):
            if r.key == key and not r.disabled:
                self.highlighted = n
                self.wanted = None
                return True
        self.wanted = key
        return False

    def select_at(self, index: int) -> None:
        """Select the row that took ``index``'s place, clamped to the end."""
        enabled = [n for n, r in enumerate(self.rows) if not r.disabled]
        if not enabled:
            return
        self.highlighted = min(enabled, key=lambda n: abs(n - index))

    def set_title(self, title: str) -> None:
        if title != self.border_title:
            self.border_title = title

    # vim motions that work on the viewport rather than the highlight
    def _at_view(self, where: float) -> None:
        lines = self._lines
        if not lines:
            return
        region = self.scrollable_content_region
        y = min(max(int(region.y + region.height * where), 0), len(lines) - 1)
        self.select_at(lines[y][0])

    def action_view_top(self) -> None:
        self._at_view(0.0)

    def action_view_middle(self) -> None:
        self._at_view(0.5)

    def action_view_bottom(self) -> None:
        self._at_view(0.99)

    def on_focus(self) -> None:
        app = self.app
        if isinstance(app, TavlaApp):
            app.column_focused(self)


class PreviewColumn(Column):
    """The rightmost column: the item's detail. Only subtask lines can be
    selected; with none, j/k scroll the text instead."""

    def _selectable(self) -> bool:
        return any(not r.disabled for r in self.rows)

    def first_row(self, enabled: list[int]) -> int | None:
        """The first open subtask, so `space` never unticks finished work by
        accident; the first line when they are all ticked."""
        open_ = (n for n in enabled if not getattr(self.rows[n].ref, "done", False))
        return next(open_, enabled[0] if enabled else None)

    def action_cursor_down(self) -> None:
        super().action_cursor_down() if self._selectable() else self.scroll_down(animate=False)

    def action_cursor_up(self) -> None:
        super().action_cursor_up() if self._selectable() else self.scroll_up(animate=False)


class TavlaApp(App[None]):
    CSS = """
    Screen { background: ansi_default; }
    #main { height: 1fr; }
    .column {
        height: 1fr; border: round ansi_bright_black; padding: 0;
        background: ansi_default; scrollbar-size-vertical: 1;
        border-title-color: ansi_default; border-subtitle-color: ansi_bright_black;
    }
    .column:focus { border: round $accent; border-title-style: bold reverse; }
    .column > .option-list--option-highlighted {
        background: ansi_default; color: ansi_default; text-style: underline;
    }
    .column:focus > .option-list--option-highlighted { text-style: reverse bold; }
    .column > .option-list--option-disabled { color: ansi_default; text-style: none; }
    .column > .option-list--option-hover { background: ansi_default; }
    #header, #hints { height: 1; padding: 0 1; }
    #toosmall { display: none; content-align: center middle; height: 1fr; }

    .tiny #main, .tiny #header, .tiny #hints { display: none; }
    .tiny #toosmall { display: block; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", show=False),
        Binding("ctrl+c", "quit", show=False, priority=True),
        Binding("question_mark", "help", show=False),
        Binding("1", "scope('project')", show=False),
        Binding("2", "scope('next')", show=False),
        Binding("3", "scope('inbox')", show=False),
        Binding("4", "scope('agenda')", show=False),
        Binding("tab", "next_scope(1)", show=False, priority=True),
        Binding("shift+tab", "next_scope(-1)", show=False, priority=True),
        # Not priority: escape must reach an open modal (Prompt, Confirm, an
        # open board) before it moves the cursor back a column.
        Binding("escape", "back", show=False),
        Binding("h,left", "go_left", show=False),
        Binding("l,right", "go_right", show=False),
        Binding("space", "toggle_done", show=False),
        Binding("x", "reopen", show=False),
        Binding("s", "start", show=False),
        Binding("w", "work", show=False),
        Binding("W", "terminal", show=False),
        Binding("n", "note", show=False),
        Binding("o", "add_here", show=False),
        Binding("O", "add_above", show=False),
        Binding("e", "edit", show=False),
        Binding("exclamation_mark", "priority", show=False),
        Binding("t", "due", show=False),
        Binding("m", "move", show=False),
        Binding("D", "drop", show=False),
        Binding("u", "undo", show=False),
        Binding("v", "mark", show=False),
        Binding("V", "visual", show=False),
        Binding("J", "reorder(1)", show=False),
        Binding("K", "reorder(-1)", show=False),
        Binding("a", "dep_edge(True)", show=False),
        Binding("A", "dep_edge(False)", show=False),
        Binding("at", "people", show=False),
        Binding("P", "pick_project", show=False),
        Binding("f", "flow", show=False),
        Binding("slash", "filter", show=False),
        Binding("r", "reload", show=False),
    ]

    def __init__(self, root: Path) -> None:
        super().__init__(ansi_color=True)
        self.root = root.resolve()
        self.content = Content.open(root)
        self.scope = "project"
        self.project_id: str | None = None
        self.list_source = "list"  # whose selection the preview follows
        self.preview_key = ""  # what the preview is showing now
        self.show_all = False
        self.filter = ""
        self.marked: set[str] = set()
        self.visual = False
        self.pending_key: str | None = None  # `g` (before gg) and `@` (before @a)
        self.head: str | None = None
        self.loaded_at = time.monotonic()
        self.status_at = 0.0
        self.pending: dict[str, str] = {}
        self.pending_at: dict[str, int] = {}
        self.write_lock = threading.Lock()

    # --- layout ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield Column("Goals", id="list")
            yield Column("Tasks", id="mid")
            yield PreviewColumn("Preview", id="preview")
        yield Static(id="header")
        yield Static(
            f"Terminal too small for tavla (need {MIN_SIZE[0]}×{MIN_SIZE[1]}).", id="toosmall"
        )
        yield Static(id="hints")

    def on_mount(self) -> None:
        self.theme = "ansi-dark"
        self.head = self.git_head()
        self.start_project()
        self.reload()
        self.set_layout(self.size.width, self.size.height)
        self.ensure_focus()
        self.set_interval(POLL_SECONDS, self.poll)

    def on_resize(self, event: Resize) -> None:
        self.set_layout(event.size.width, event.size.height)
        self.call_after_refresh(self.render_preview)

    def start_project(self) -> None:
        """Decision 11: the linked folder, the project being worked on, the
        last one used here, then the first active project."""
        current = queries.current_project(self.content, Path.cwd())
        self.project_id = self._pick_project_id(current, self._read_last_project())

    def _read_last_project(self) -> str | None:
        try:
            return (config.cache_dir() / "ui-last-project").read_text().strip() or None
        except OSError:
            return None

    def _write_last_project(self, project_id: str) -> None:
        try:
            path = config.cache_dir() / "ui-last-project"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(project_id + "\n")
        except OSError:
            pass  # a cache write must never break the app

    def _pick_project_id(self, *candidates: Project | str | None) -> str | None:
        known = {p.id for p in self.content.projects()}
        for candidate in candidates:
            wanted = candidate.id if isinstance(candidate, Project) else candidate
            if wanted in known:
                return wanted
        active = queries.active_projects(self.content)
        if active:
            return active[0].id
        projects = self.content.projects()
        return projects[0].id if projects else None

    @property
    def project(self) -> Project | None:
        if self.project_id is None:
            return None
        return next((p for p in self.content.projects() if p.id == self.project_id), None)

    def column_names(self) -> list[str]:
        """The columns this scope has, left to right."""
        return ["list", "mid", "preview"] if self.scope == "project" else ["list", "preview"]

    def hidden_columns(self) -> list[str]:
        """The columns that don't fit at this width: the breadcrumb names them."""
        names = self.column_names()
        if len(names) < 3 or self.size.width >= WIDE:
            return []
        return names[:1]

    def visible_columns(self) -> list[str]:
        dropped = self.hidden_columns()
        return [n for n in self.column_names() if n not in dropped]

    def layout(self, width: int) -> dict[str, int]:
        """Column widths. The preview keeps ``max(34, width//3)``; the list
        columns share the rest, ``width: 1fr``-style."""
        names = self.visible_columns()
        lists = [n for n in names if n != "preview"]
        if not names:
            return {}
        room = max(width - 2, MIN_SIZE[0])
        if not lists:
            return {"preview": room}
        preview = max(PREVIEW_MIN, room // 3) if "preview" in names else 0
        preview = min(preview, max(room - LIST_MIN * len(lists), LIST_MIN))
        rest = room - preview
        widths = {n: rest // len(lists) for n in lists}
        if lists:
            widths[lists[-1]] += rest - sum(widths.values())
        if preview:
            widths["preview"] = preview
        return widths

    def set_layout(self, width: int, height: int) -> None:
        self.screen.set_class(width < MIN_SIZE[0] or height < MIN_SIZE[1], "tiny")
        if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
            return
        widths = self.layout(width)
        for name in ("list", "mid", "preview"):
            column = self.column(name)
            visible = name in widths
            column.display = visible
            if visible:
                column.styles.width = widths[name]
        self.ensure_focus()
        self.render_header()
        self.update_hints()

    def ensure_focus(self) -> None:
        focused = self.focused
        if isinstance(focused, Column) and focused.display:
            return
        for name in self.visible_columns():
            self.column(name).focus()
            return

    def column(self, name: str) -> Column:
        return self.query_one(f"#{name}", Column)

    def preview(self) -> PreviewColumn:
        return self.query_one("#preview", PreviewColumn)

    @property
    def focused_column(self) -> Column | None:
        return self.focused if isinstance(self.focused, Column) else None

    # --- loading -----------------------------------------------------------------

    def git_head(self) -> str | None:
        try:
            return git_sync.run(self.root, "rev-parse", "HEAD").stdout.strip()
        except (GitError, OSError):
            return None

    def poll(self) -> None:
        head = self.git_head()
        if head != self.head:
            self.head = head
            self.reload()
        elif time.monotonic() - self.status_at > STATUS_EVERY:
            self.status_at = time.monotonic()
            self.render_header()
            self.render_preview()
        else:
            self.render_header()

    def reload(self) -> None:
        self.content.refresh()
        self.loaded_at = time.monotonic()
        try:
            self.render_list()
            self.render_mid()
            self.render_preview()
        except TavlaError as e:
            self.notify(f"can't read the content repo: {e}", severity="error", timeout=10)
        self.render_header()
        self.update_hints()

    def render_list(self) -> None:
        """Column 1: the scope's own items."""
        today = dates.local_today()
        current = work.current(self.content)
        empty = ""
        if self.scope == "project":
            project = self.project
            if project is None:
                self.column("list").show(
                    [
                        Row(
                            "empty",
                            "empty",
                            Text("No projects yet", style="dim italic"),
                            disabled=True,
                        )
                    ]
                )
                self.column("list").set_title("Goals")
                return
            rows = model.goal_column_rows(
                self.content, project, show_all=self.show_all, today=today
            )
            title, empty = f"Goals · {project.id}", "No goals. o to add one."
        elif self.scope == "next":
            rows = model.next_column_rows(
                self.content,
                show_all=self.show_all,
                today=today,
                working=current.task_id if current else None,
            )
            title, empty = "Next", "Nothing ready now."
        elif self.scope == "inbox":
            rows = model.inbox_rows(self.content, today=today)
            title = "Inbox"
        else:
            rows = model.agenda_rows(self.content, today=today)
            title = "Agenda"
        for row in rows:
            row.column = "list"
        if self.filter:
            rows = self.filter_list(rows, today=today)
        self._show("list", rows, empty=empty)
        self.column("list").set_title(title + (f" /{self.filter}" if self.filter else ""))

    def filter_list(self, rows: list[Row], *, today: Any) -> list[Row]:
        """`/` keeps a heading, a matching row, and any row whose children
        match — so a task you searched for still shows where it lives. A dim
        marker counts what the filter hid."""
        out: list[Row] = []
        for row in rows:
            if (
                row.disabled
                or row.matches(self.filter)
                or self.has_matching_child(row, today=today)
            ):
                out.append(row)
        shown = len([r for r in out if not r.disabled])
        hidden = len([r for r in rows if not r.disabled]) - shown
        if hidden and shown:
            # Nothing shown at all is the "empty" message's job, not a marker's.
            out.append(model.hidden_row("list", hidden))
        return out

    def has_matching_child(self, row: Row, *, today: Any) -> bool:
        """Does anything one level under ``row`` match the filter?"""
        if self.scope != "project":
            return False
        if row.kind == "goal":
            rows = model.task_rows(
                self.content, Context("goal", row.ref.project, row.ref.id), today=today
            )
        elif row.kind == "loose":
            rows = model.task_rows(self.content, Context("loose", row.ref.id), today=today)
        else:
            return False
        return any(r.matches(self.filter) for r in rows)

    def selected_goal(self) -> Goal | None:
        row = self.column("list").current
        if row is not None and row.kind == "goal" and isinstance(row.ref, Goal):
            return row.ref
        return None

    def render_mid(self) -> None:
        """Column 2: what the goal column's selection contains."""
        if self.scope != "project":
            return
        row = self.column("list").current
        today = dates.local_today()
        current = work.current(self.content)
        working = current.task_id if current else None
        rows: list[Row] = []
        title, empty = "Tasks", ""
        if row is not None and row.kind == "goal":
            rows = model.task_rows(
                self.content,
                Context("goal", row.ref.project, row.ref.id),
                show_all=self.show_all,
                working=working,
                today=today,
            )
            title, empty = f"Tasks · {row.ref.id}", "No tasks yet. o to add one."
        elif row is not None and row.kind == "deliverables":
            rows = model.deliverable_rows(self.content, Context("project", row.ref.id), today=today)
            title, empty = "Deliverables", "No deliverables. o to add one."
        elif row is not None and row.kind == "loose":
            rows = model.task_rows(
                self.content,
                Context("loose", row.ref.id),
                show_all=self.show_all,
                working=working,
                today=today,
            )
            title, empty = model.LOOSE, "No tasks without a goal."
        for item in rows:
            item.column = "mid"
        if self.filter:
            rows = [r for r in rows if r.matches(self.filter)]
        self._show("mid", rows, empty=empty)
        self.column("mid").set_title(title + (f" /{self.filter}" if self.filter else ""))

    def render_preview(self) -> None:
        """The rightmost column: the detail of the row the cursor is on."""
        row = self.source_row()
        today = dates.local_today()
        width = max(self.preview().size.width - 3, 20)
        lines: list[model.Line] = []
        title = "Preview"
        if row is not None:
            title, lines = self.detail_lines(row, width=width, today=today)
        rows = [
            Row(
                line.key or f"line:{n}",
                "subtask" if line.subtask else "line",
                line.prompt,
                ref=line.subtask,
                disabled=line.subtask is None,
                column="preview",
            )
            for n, line in enumerate(lines)
        ]
        item = row.key if row is not None else ""
        same = item == self.preview_key
        preview = self.preview()
        wanted = preview.wanted
        preview.show(rows)
        preview.set_title(title)
        if not same:
            if wanted is not None:
                # Someone asked for a specific line (a subtask after a reorder):
                # keep it rather than resetting to the top.
                preview.select_key(wanted)
            else:
                preview.highlighted = None
            preview.scroll_home(animate=False)
            self.preview_key = item

    def source_row(self) -> Row | None:
        """The row the preview follows: the navigation column that has focus."""
        source = self.list_source
        if source == "preview" or not self.column(source).display:
            source = "mid" if self.column("mid").display else "list"
        return self.column(source).current

    def detail_lines(self, row: Row, *, width: int, today: Any) -> tuple[str, list[model.Line]]:
        """``(title, lines)`` for whatever the row is."""
        if row.kind == "task":
            task = self._fresh_task(row.ref.id)
            return (task.id if task else "task"), (
                model.task_detail(self.content, task) if task else []
            )
        if row.kind == "goal":
            return f"{row.ref.id} · flow", model.goal_detail(
                self.content, row.ref, width=width, today=today, open_only=not self.show_all
            )
        if row.kind == "project":
            project = self.project or row.ref
            return f"{project.id} · flow", model.project_detail(
                self.content, project, width=width, today=today, open_only=not self.show_all
            )
        if row.kind == "loose":
            project = self.project or row.ref
            return model.LOOSE, model.loose_detail(self.content, project, today=today)
        if row.kind == "deliverables":
            project = self.project or row.ref
            return "deliverables", model.deliverables_detail(self.content, project, today=today)
        if row.kind == "deliverable":
            return row.ref.id, model.deliverable_detail(row.ref, today=today)
        if row.kind == "idea":
            return "idea", model.idea_detail(row.ref)
        if row.kind == "todo":
            return "todo", model.todo_detail(row.ref)
        return "Preview", []

    def _fresh_task(self, task_id: str) -> Task | None:
        return next((t for t in self.content.tasks() if t.id == task_id), None)

    def _show(self, column_id: str, rows: list[Row], empty: str = "") -> None:
        column = self.column(column_id)
        keep = self.pending.pop(column_id, None)
        column.show(rows, keep=keep, marked=self.marked, empty=empty)
        index = self.pending_at.pop(column_id, None)
        if index is not None and keep is None:
            column.select_at(index)

    # --- header & hints ----------------------------------------------------------

    def render_header(self) -> None:
        parts = self.breadcrumb()
        left = Text()
        for n, part in enumerate(parts):
            if n:
                left.append(" › ", style="dim")
            left.append(part, style="bold" if n == len(parts) - 1 else "dim")
        left.append(f" ·[{self.scope}]", style="dim")
        if self.filter:
            left.append(f"  /{self.filter}", style="bold yellow")
        if self.marked:
            left.append(f"  marked {len(self.marked)}", style="bold")

        right = Text()
        current = work.current(self.content)
        if current is not None:
            right.append("▶ ", style="bold cyan")
            right.append(current.task_id, style="bold")
            right.append(f" {work.format_duration(current.elapsed())}", style="cyan")
        else:
            right.append("○ w to start", style="dim")
        terminals = work.terminal_sessions(self.content)
        if terminals:
            many = len(terminals) > 1
            right.append(
                f"  ▣ {len(terminals)} terminals" if many else f"  ▣ {terminals[0].task_id}"
            )
        report = self._status_report()
        if report is not None:
            overdue = sum(1 for t in report.due_tasks if t.due and t.due < report.today)
            alerts = []
            if overdue:
                alerts.append((f"!{overdue} overdue", "bold red"))
            if report.blocked:
                alerts.append((f"✗{len(report.blocked)} blocked", "red"))
            if report.inbox:
                alerts.append((f"{report.inbox} ideas", "dim"))
            if report.todos:
                alerts.append((f"{report.todos} todos", "dim"))
            if report.stale:
                alerts.append((f"{len(report.stale)} stale", "dim"))
            if alerts:
                right.append("  ")
                right.append_text(Text(" · ").join(Text(t, style=s) for t, s in alerts))
        age = int(time.monotonic() - self.loaded_at)
        fresh = "just now" if age < 5 else f"{age}s" if age < 60 else f"{age // 60}m"
        right.append(f"  ↻ {fresh}", style="dim")
        self.query_one("#header", Static).update(model.two_columns(left, right))

    def _status_report(self) -> Any:
        try:
            return queries.status(self.content)
        except TavlaError:
            return None

    def breadcrumb(self) -> list[str]:
        """Where you are: the dropped ancestors first, so nothing is invisible."""
        parts: list[str] = []
        row = self.column("list").current
        if self.scope != "project":
            parts.append(self.scope)
            if row is not None and not row.disabled and row.ref is not None:
                parts.append(getattr(row.ref, "id", None) or row.key.split(":", 1)[-1])
            return parts
        project = self.project
        parts.append(project.id if project is not None else "no project")
        goal = self.selected_goal()
        if goal is not None and ("list" in self.hidden_columns() or self.list_source != "list"):
            parts.append(goal.id)
        mid = self.column("mid").current if self.column("mid").display else None
        if (
            mid is not None
            and mid.kind in ("task", "deliverable", "loose")
            and ("mid" in self.hidden_columns() or self.list_source == "preview")
        ):
            parts.append(getattr(mid.ref, "id", mid.key.split(":", 1)[-1]))
        return parts

    def update_hints(self) -> None:
        column = self.focused_column
        name = column.id if column is not None and column.id else "list"
        if name == "preview" and self.list_source != "preview":
            name = self.list_source
        if name == "mid" and self.scope != "project":
            name = "list"
        hints = HINTS.get((self.scope, name or "list"), "")
        if self.pending_key == "at":
            hints = "@a add  @d remove  @m mail  @l list  esc cancel"
        elif self.marked or self.visual:
            hints = MARK_HINT + hints
        self.query_one("#hints", Static).update(
            model.two_columns(Text(hints, style="dim"), Text(COMMON_HINT, style="dim"))
        )

    # --- focus & navigation ------------------------------------------------------

    def column_focused(self, column: Column) -> None:
        if column.id and column.id != "preview":
            self.list_source = column.id
        # The preview follows whichever navigation column has focus.
        self.render_preview()
        self.render_header()
        self.update_hints()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        column = event.option_list
        if not isinstance(column, Column):
            return
        if column.id == "list" and self.scope == "project":
            self.render_mid()
        if column.id != "preview":
            self.render_preview()
        self.render_header()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        column = event.option_list
        if not isinstance(column, Column):
            return
        if column.id == "preview":
            return
        if column.id == "list" and self.scope == "project":
            self.action_go_right()  # into the tasks of this goal
        else:
            self.action_go_right()

    def action_go_left(self) -> None:
        column = self.focused_column
        if column is None or not column.id:
            return
        if column.id == "preview":
            source = self.list_source if self.column(self.list_source).display else "mid"
            self.column(source).focus()
            return
        order = self.visible_columns()
        if column.id in order and order.index(column.id) > 0:
            self.column(order[order.index(column.id) - 1]).focus()
        elif "list" in self.hidden_columns():
            self.notify("the goal column is hidden at this width (widen or r)", timeout=3)

    def action_go_right(self) -> None:
        column = self.focused_column
        if column is None or not column.id:
            return
        order = self.visible_columns()
        if column.id in order and order.index(column.id) < len(order) - 1:
            self.column(order[order.index(column.id) + 1]).focus()
        elif column.id != "preview" and self.preview().display:
            self.preview().focus()

    def action_back(self) -> None:
        if self.pending_key is not None:
            self.pending_key = None
            self.update_hints()
            return
        if self.filter:
            self.filter = ""
            self.reload()
            return
        if self.marked or self.visual:
            self.clear_marks()
            return
        if self.focused_column is not None and self.focused_column.id == "preview":
            self.action_go_left()
            return
        self.action_go_left()

    def action_scope(self, scope: str) -> None:
        if scope == self.scope:
            return
        self.scope = scope
        self.list_source = "list"
        self.marked.clear()
        self.visual = False
        self.set_layout(self.size.width, self.size.height)
        self.reload()
        if self.column("list").display:
            self.column("list").focus()

    def action_next_scope(self, delta: int) -> None:
        self.action_scope(SCOPES[(SCOPES.index(self.scope) + delta) % len(SCOPES)])

    # --- what a verb acts on -----------------------------------------------------

    def target(self) -> Row | None:
        """The row a verb acts on: the focused column's selection, or — when
        the preview has focus — the row the preview is showing."""
        column = self.focused_column
        if column is None:
            return None
        if column.id == "preview":
            return self.source_row()
        return column.current

    def target_column(self) -> Column | None:
        column = self.focused_column
        if column is None:
            return None
        if column.id == "preview":
            source = self.list_source if self.column(self.list_source).display else "mid"
            return self.column(source) if self.column(source).display else self.column("list")
        return column

    def rows_under_cursor(self) -> list[Row]:
        """The rows a verb applies to: the marks, or the row under the cursor."""
        if self.marked:
            return self.marked_rows()
        row = self.target()
        return [row] if row is not None and not row.disabled else []

    def marked_rows(self) -> list[Row]:
        found: list[Row] = []
        for column_id in self.visible_columns():
            for row in self.column(column_id).rows:
                if row.key in self.marked and not row.disabled:
                    found.append(row)
        return found

    def selected_subtask(self) -> Any:
        column = self.focused_column
        if column is not None and column.id == "preview" and column.current is not None:
            return column.current.ref
        return None

    def position(self, column_id: str) -> tuple[str, int] | None:
        index = self.column(column_id).index
        return (column_id, index) if index is not None else None

    # --- multi-select ------------------------------------------------------------

    def action_mark(self) -> None:
        row = self.target()
        if row is None or row.disabled:
            return
        if row.key in self.marked:
            self.marked.discard(row.key)
            if not self.marked:
                self.visual = False
        else:
            self.marked.add(row.key)
            self.visual = True
        self.render_marks()

    def action_visual(self) -> None:
        """`V`: with marks, mark the whole column; with none, show done items."""
        if self.marked or self.visual:
            column = self.target_column()
            if column is not None and column.id != "preview":
                self.marked |= {r.key for r in column.enabled()}
            self.visual = True
            self.render_marks()
            return
        self.show_all = not self.show_all
        self.reload()
        self.notify(
            "Showing done and paused items" if self.show_all else "Hiding done items", timeout=2
        )

    def render_marks(self) -> None:
        for column_id in self.visible_columns():
            column = self.column(column_id)
            if column_id == "preview":
                continue
            column.show(
                column.rows, keep=column.current.key if column.current else None, marked=self.marked
            )
        self.render_header()
        self.update_hints()

    def clear_marks(self) -> None:
        self.marked.clear()
        self.visual = False
        self.reload()

    def extend_marks(self) -> None:
        row = self.target()
        if row is not None and not row.disabled:
            self.marked.add(row.key)
            self.render_marks()

    # --- writes ------------------------------------------------------------------

    def write(self, job: Job) -> None:
        """Run ``job`` off the UI thread (git commits take a moment), one at a time."""

        def run() -> JobResult:
            with self.write_lock:
                return job(Content.open(self.root))

        self.run_worker(run, thread=True, group="write", exit_on_error=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group != "write":
            return
        if worker.state == WorkerState.SUCCESS:
            result = worker.result
            message = ""
            if isinstance(result, Outcome):
                if result.select:
                    self.pending[result.select[0]] = result.select[1]
                if result.at:
                    self.pending_at[result.at[0]] = result.at[1]
                message = result.message
            self.head = self.git_head()
            self.reload()
            if message:
                self.notify(message, timeout=4)
        elif worker.state == WorkerState.ERROR:
            self.show_error(worker.error)
            self.reload()

    def show_error(self, error: BaseException | None) -> None:
        if isinstance(error, TavlaError):
            self.notify(str(error), severity="error", timeout=8)
            return
        log = config.cache_dir() / "tui.log"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                f.write(f"--- {dates.local_now():%Y-%m-%d %H:%M}\n")
                f.write("".join(traceback.format_exception(error)) if error else "unknown\n")
        except OSError:
            pass
        self.notify(f"unexpected error: {error!r} (details in {log})", severity="error", timeout=10)

    def nothing(self, what: str) -> None:
        self.notify(what, severity="warning", timeout=3)

    def ask(
        self, question: str, then: Callable[[str], None], value: str = "", hint: str = ""
    ) -> None:
        def done(answer: str | None) -> None:
            if answer is not None and answer.strip():
                then(answer.strip())

        self.push_screen(Prompt(question, value, hint), done)

    def pick(
        self, question: str, options: list[tuple[str, str]], then: Callable[[str], None]
    ) -> None:
        if not options:
            self.nothing("Nothing to choose from")
            return

        def done(choice: str | None) -> None:
            if choice is not None:
                then(choice)

        self.push_screen(Picker(question, options), done)

    def confirm(self, question: str, then: Callable[[], None]) -> None:
        self.push_screen(Confirm(question), lambda yes: then() if yes else None)

    def confirm_bulk(self, what: str, rows: list[Row], then: Callable[[], None]) -> None:
        """Decision 20: only a verb over more than three marked rows asks."""
        if len(rows) > 3:
            self.confirm(f"{what} {len(rows)} items?", then)
        else:
            then()

    # --- verbs -------------------------------------------------------------------

    def action_toggle_done(self) -> None:
        subtask = self.selected_subtask()
        row = self.target()
        if subtask is not None and row is not None and row.kind == "task":
            task_id = row.ref.id

            def tick(c: Content) -> JobResult:
                task = c.task(task_id)
                fresh = model.subtask_by_number(task, subtask.number)
                if fresh is None or fresh.text != subtask.text:
                    raise ValidationError(f"{task.path} changed on disk; try again")
                ops.check_subtasks(c, task, [fresh], done=not fresh.done)
                return Outcome(f"{'Unticked' if fresh.done else 'Ticked'} {fresh.text}")

            self.write(tick)
            return
        rows = [r for r in self.rows_under_cursor() if r.kind in ("task", "goal", "todo")]
        if not rows:
            self.nothing("Nothing to mark done here")
            return
        column = self.target_column()
        position = self.position(column.id) if column is not None and column.id else None
        if len(rows) == 1:
            self._toggle_one(rows[0], position)
            return

        def bulk() -> None:
            def job(c: Content) -> JobResult:
                done: list[str] = []
                for row in rows:
                    done += _complete(c, row)
                return Outcome(
                    f"Done {len(done)}: {', '.join(done)}" if done else "Nothing changed",
                    at=position,
                )

            self.clear_marks()
            self.write(job)

        self.confirm_bulk("Mark done on", rows, bulk)

    def _toggle_one(self, row: Row, position: tuple[str, int] | None) -> None:
        def job(c: Content) -> JobResult:
            if row.kind == "todo":
                todo = _fresh_todo(c, row.ref)
                todos.set_done(c, [todo])
                return Outcome(f"Done: {todo.text}", at=position)
            if row.kind == "goal":
                goal = c.goal(row.ref.id)
                if ops.complete(c, goal) is None:
                    return Outcome(f"{goal.id} is already done", select=("list", row.key))
                return Outcome(f"Done: {goal.id}", at=position)
            task = c.task(row.ref.id)
            if task.status == TaskStatus.DONE:
                ops.set_status(c, task, TaskStatus.TODO, verb="reopen")
                return Outcome(f"Reopened {task.id}", select=("list", row.key))
            return Outcome(_finish(c, task), at=position)

        self.write(job)

    def action_reopen(self) -> None:
        rows = [r for r in self.rows_under_cursor() if r.kind in ("task", "goal")]
        if not rows:
            self.nothing("Select a task or goal to reopen")
            return
        if len(rows) > 3:
            self.confirm(
                f"Reopen {len(rows)} items?",
                lambda: self._reopen_rows(rows),
            )
            return
        self._reopen_rows(rows)

    def _reopen_rows(self, rows: list[Row]) -> None:
        def job(c: Content) -> JobResult:
            reopened = []
            for row in rows:
                item = c.task(row.ref.id) if row.kind == "task" else c.goal(row.ref.id)
                if ops.set_status(c, item, TaskStatus.TODO, verb="reopen") is not None:
                    reopened.append(item.id)
            if not reopened:
                return Outcome("Already open")
            return Outcome(f"Reopened {', '.join(reopened)}")

        self.clear_marks()
        self.write(job)

    def action_start(self) -> None:
        rows = [r for r in self.rows_under_cursor() if r.kind in ("task", "goal")]
        if not rows:
            self.nothing("Select a task or goal to start")
            return

        def job(c: Content) -> JobResult:
            started = []
            for row in rows:
                item = c.task(row.ref.id) if row.kind == "task" else c.goal(row.ref.id)
                if ops.start(c, item) is not None:
                    started.append(item.id)
            if not started:
                return Outcome("Already started")
            return Outcome(f"Started {', '.join(started)}")

        self.clear_marks()
        self.write(job)

    def action_work(self) -> None:
        row = self.target()
        current = work.current(self.content)
        if current is not None and not (
            row and row.kind == "task" and row.ref.id != current.task_id
        ):

            def pause(c: Content) -> JobResult:
                focus, _, session = work.pause(c)
                return Outcome(
                    f"Paused {focus.task_id} after {work.format_duration(session.duration)}"
                )

            self.write(pause)
            return
        if row is None or row.kind != "task":
            self.nothing("Select a task to work on")
            return
        task_id = row.ref.id

        def enter(c: Content) -> JobResult:
            task = c.task(task_id)
            work.enter(c, task)
            note = f" (still waiting on {', '.join(task.waiting_on)})" if task.waiting_on else ""
            return Outcome(f"Working on {task_id}{note}", select=("list", f"task:{task_id}"))

        self.write(enter)

    def action_terminal(self) -> None:
        """`W`: open the task (or, in the preview, the subtask) in a terminal
        of its own; closing it marks the task done or ticks the subtask."""
        row = self.target()
        if row is None or row.kind != "task":
            self.nothing("Select a task to open in a terminal")
            return
        task_id, subtask = row.ref.id, self.selected_subtask()

        def job(c: Content) -> JobResult:
            task = c.task(task_id)
            fresh = None
            if subtask is not None:
                fresh = model.subtask_by_number(task, subtask.number)
                if fresh is None or fresh.text != subtask.text:
                    raise ValidationError(f"{task.path} changed on disk; try again")
            name = terminal.open_task(c, task, fresh)
            done = "ticks it" if fresh else "marks it done"
            return Outcome(f"Opened {task_id} in {name}; closing it {done}")

        self.write(job)

    def action_note(self) -> None:
        row = self.target()
        if row is None:
            return
        if row.kind in ("task", "goal"):
            item_id, kind = row.ref.id, row.kind

            def note(text: str) -> None:
                def job(c: Content) -> JobResult:
                    item = c.task(item_id) if kind == "task" else c.goal(item_id)
                    ops.add_update(c, item, text)
                    return Outcome(f"Noted on {item_id}")

                self.write(job)

            self.ask(f"Note on {item_id}", note)
        elif row.kind == "project":
            project_id = row.ref.id

            def log(text: str) -> None:
                def job(c: Content) -> JobResult:
                    ops.append_log(c, c.project(project_id), text)
                    return Outcome(f"Logged in {project_id}")

                self.write(job)

            self.ask(f"Log line for {project_id}", log)
        else:
            self.nothing("Notes go on a task, goal or project")

    def action_add_here(self) -> None:
        """`o`: a new item at the level the cursor is on. In the preview that is
        a subtask of the task; in a task column, a task; in the next scope, a
        goal, task or todo, by row."""
        row = self.target()
        focused = self.focused_column
        if row is None:
            self._add_project()
            return
        if focused is not None and focused.id == "preview" and row.kind == "task":
            self._add_subtask(row.ref.id)  # in the preview, `o` adds a subtask
            return
        if self.scope == "agenda":
            self._add_todo()
            return
        if self.scope == "inbox":
            if row.kind == "idea":
                self._add_idea(row.ref.scope, row.ref.scope.label)
            else:
                self._add_todo()
            return
        if row.kind in ("task", "goal", "loose", "deliverables"):
            self._add_task(row)
        elif row.kind == "project":
            self._add_goal(row.ref.id)
        elif row.kind == "deliverable":
            self._add_deliverable(row.ref.project)
        elif row.kind == "idea":
            self._add_idea(row.ref.scope, row.ref.scope.label)
        elif row.kind == "todo":
            self._add_todo()
        else:
            self.nothing("Nothing to add at this level")

    def action_add_above(self) -> None:
        """`O`: a new item one level up from the cursor — from a subtask a
        task, from a task a goal, from a goal (or an idea) a project."""
        row = self.target()
        column = self.target_column()
        column_id = column.id if column is not None and column.id else "list"
        if column_id == "preview" and row is not None and row.kind == "task":
            self._add_task(row)  # above a subtask sits its task
            return
        if self.scope == "project" and column_id == "mid":
            project = self.project
            if project is None:
                self.nothing("Pick a project first (P)")
                return
            self._add_goal(project.id)
            return
        self._add_project()

    def _add_project(self) -> None:
        def add(title: str) -> None:
            def job(c: Content) -> JobResult:
                p = ops.add_project(c, title)
                self.pending_at.pop("list", None)
                return Outcome(f"Added project {p.id}", select=("list", f"project:{p.id}"))

            self.write(job)

        self.ask("New project", add)

    def _add_goal(self, project_id: str) -> None:
        def add(title: str) -> None:
            def job(c: Content) -> JobResult:
                g = ops.add_goal(c, title, c.project(project_id))
                return Outcome(f"Added goal {g.id}", select=("list", f"goal:{g.id}"))

            self.write(job)

        self.ask(f"New goal in {project_id}", add)

    def _add_subtask(self, task_id: str) -> None:
        def add(text: str) -> None:
            def job(c: Content) -> JobResult:
                ops.add_subtask(c, c.task(task_id), text)
                return Outcome(f"Subtask added to {task_id}", select=("preview", ""))

            self.write(job)

        self.ask(f"New subtask of {task_id}", add)

    def _add_deliverable(self, project_id: str) -> None:
        def add(title: str) -> None:
            def job(c: Content) -> JobResult:
                d = ops.add_deliverable(c, title, c.project(project_id))
                return Outcome(f"Added deliverable {d.id}", select=("mid", f"deliverable:{d.id}"))

            self.write(job)

        self.ask(f"New deliverable in {project_id}", add)

    def _add_task(self, row: Row | None) -> None:
        """A task under the cursor's goal, or loose in its project."""
        project_id: str | None = None
        goal_id: str | None = None
        if row is not None and row.kind == "goal":
            goal_id, project_id = row.ref.id, row.ref.project
        elif row is not None and row.kind in ("task", "loose"):
            project_id, goal_id = row.ref.project, row.ref.goal
        elif row is not None and row.kind == "deliverables":
            project_id = row.ref.id
        if project_id is None:
            project = self.project
            project_id = project.id if project is not None else None
        if project_id is None:
            self.nothing("Pick a project first (P)")
            return
        where = goal_id or project_id
        column_id = "mid" if self.column("mid").display else "list"

        def add(title: str) -> None:
            def job(c: Content) -> JobResult:
                goal = c.goal(goal_id) if goal_id else None
                task = ops.add_task(c, title, c.project(project_id), goal=goal)
                return Outcome(f"Added task {task.id}", select=(column_id, f"task:{task.id}"))

            self.write(job)

        self.ask(f"New task in {where}", add)

    def _add_idea(self, scope: Any, label: str) -> None:
        def add(text: str) -> None:
            def job(c: Content) -> JobResult:
                where = scope if scope is not None else ideas.scope_of(c, None)
                ideas.add(c, where, text)
                return Outcome(f"Idea added to {label}")

            self.write(job)

        self.ask(f"New idea ({label})", add, hint="#tags work · enter ok · esc cancel")

    def _add_todo(self) -> None:
        def add(text: str) -> None:
            def job(c: Content) -> JobResult:
                todos.add(c, text)
                return Outcome("Added to todo.md")

            self.write(job)

        self.ask("New todo", add)

    def action_edit(self) -> None:
        row = self.target()
        if row is None:
            return
        content = Content.open(self.root)
        try:
            if row.kind == "task":
                item: Any = content.task(row.ref.id)
                finish: Callable[[EditSession], Any] = lambda s: ops.finish_edit(content, item, s)
            elif row.kind == "goal":
                item = content.goal(row.ref.id)
                finish = lambda s: ops.finish_edit(content, item, s)
            elif row.kind == "project" or row.kind == "loose":
                project = self.project
                if project is None:
                    self.nothing("No project to edit")
                    return
                item = project
                finish = lambda s: ops.finish_project_edit(content, item, s)
            elif row.kind == "deliverable":
                item = content.deliverable(row.ref.id)
                finish = lambda s: ops.finish_deliverable_edit(content, item, s)
            elif row.kind == "idea":
                self._edit_file(row.ref.scope.path, "the idea's file")
                return
            elif row.kind == "todo":
                self._edit_file(todos.todo_path(self.content), "todo.md")
                return
            else:
                self.nothing("Nothing to edit here")
                return
        except TavlaError as e:
            self.show_error(e)
            return
        path = item.path / "project.yaml" if isinstance(item, Project) else item.path
        session = EditSession(path)
        try:
            with self.suspend():
                open_in_editor(path)
        except SuspendNotSupported:
            self.nothing("Can't open an editor from here")
            return
        except TavlaError as e:
            session.restore()
            self.show_error(e)
            return
        try:
            with self.write_lock:
                result = finish(session)
        except ValidationError as e:
            session.restore()
            self.notify(f"Edit discarded (file restored): {e}", severity="error", timeout=10)
        else:
            self.notify(f"Saved {item.id}" if result is not None else "No changes", timeout=3)
            if result is not None and result.id != item.id:
                column = self.target_column()
                if column is not None and column.id:
                    self.pending[column.id] = f"{row.kind}:{result.id}"
        self.head = self.git_head()
        self.reload()

    def _edit_file(self, path: Path, what: str) -> None:
        """Ideas and todos live inside a shared file, so `e` opens that."""
        if not path.is_file():
            self.nothing(f"{path.name} does not exist yet")
            return
        try:
            with self.suspend():
                open_in_editor(path)
        except SuspendNotSupported:
            self.nothing("Can't open an editor from here")
            return
        except TavlaError as e:
            self.show_error(e)
            return
        self.notify(f"Edited {what}; changes are yours to commit", timeout=3)
        self.head = self.git_head()
        self.reload()

    def action_priority(self) -> None:
        rows = [r for r in self.rows_under_cursor() if r.kind in ("task", "goal", "loose")]
        if not rows:
            self.nothing("Select a task or goal")
            return

        def job(c: Content) -> JobResult:
            out = []
            for row in rows:
                item = c.task(row.ref.id) if row.kind in ("task", "loose") else c.goal(row.ref.id)
                new = NEXT_PRIORITY[item.priority]
                ops.set_fields(c, item, {"priority": new.value})
                out.append(f"{item.id} {new.value}")
            return Outcome(", ".join(out))

        self.clear_marks()
        self.write(job)

    def action_due(self) -> None:
        rows = [r for r in self.rows_under_cursor() if r.kind in ("task", "goal", "deliverable")]
        if not rows:
            self.nothing("Select a task, goal or deliverable")
            return
        row = rows[0]
        current = row.ref.deadline if row.kind == "deliverable" else row.ref.due
        if row.kind == "task" and "due" in row.ref.inherited:
            current = None

        def set_due(value: str) -> None:
            try:
                when = date_change(value)
            except TavlaError as e:
                self.show_error(e)
                return
            stamp = when.isoformat() if when else "no date"

            def job(c: Content) -> JobResult:
                if row.kind == "deliverable":
                    ops.set_deliverable_fields(c, c.deliverable(row.ref.id), {"deadline": when})
                else:
                    item = c.task(row.ref.id) if row.kind == "task" else c.goal(row.ref.id)
                    ops.set_fields(c, item, {"due": when})
                return Outcome(f"{row.ref.id}: {stamp}")

            self.write(job)

        word = "Deadline" if row.kind == "deliverable" else "Due date"
        self.ask(
            f"{word} for {row.ref.id}",
            set_due,
            value=current.isoformat() if current else "",
            hint="today, tomorrow, +3d, +2w, fri, 2026-11-01, 1.11.26 · none clears",
        )

    def action_move(self) -> None:
        row = self.target()
        if row is None or row.kind not in ("task", "goal"):
            self.nothing("Select a task or goal to move")
            return
        options = self.move_options(row)
        if not options:
            self.nothing("Nowhere to move it to")
            return

        def move(choice: str) -> None:
            project_id, goal_id = choice.split("|", 1)

            def job(c: Content) -> JobResult:
                item = c.task(row.ref.id) if row.kind == "task" else c.goal(row.ref.id)
                goal = c.goal(goal_id) if goal_id else None
                moved = ops.move_item(c, item, c.project(project_id), goal=goal)
                if moved is None:
                    return Outcome(f"{item.id} is already there")
                where = f"{goal_id} in {project_id}" if goal_id else project_id
                return Outcome(f"Moved {moved.id} to {where}")

            self.write(job)

        self.pick(f"Move {row.ref.id} to", options, move)

    def move_options(self, row: Row) -> list[tuple[str, str]]:
        """The reachable homes for ``row`` — so a refused move can't be picked."""
        item = row.ref
        projects = self.content.projects()
        if row.kind == "goal":
            return [(f"{p.id}|", f"project {p.id}") for p in projects if p.id != item.project]
        if item.goal is None:
            # loose: a goal in this project, no goal at all, or another project
            options = [
                (f"{item.project}|{g.id}", f"goal {g.id}")
                for g in self.content.goals()
                if g.project == item.project
            ]
            options.append((f"{item.project}|", "— no goal —"))
            options += [
                (f"{p.id}|", f"→ project {p.id} (no goal)")
                for p in projects
                if p.id != item.project
            ]
            return options
        options = [(f"{item.project}|", "— no goal — (run it in the project)")]
        options += [
            (f"{item.project}|{g.id}", f"goal {g.id}")
            for g in self.content.goals()
            if g.project == item.project and g.id != item.goal
        ]
        return options

    def action_promote(self) -> None:
        row = self.target()
        if row is None or row.kind != "idea":
            self.nothing("Promote works on an idea (scope 3)")
            return
        ref = row.ref
        options = [(f"{p.id}|", f"project {p.id}") for p in self.content.projects()]
        options += [(f"{g.project}|{g.id}", f"goal {g.id}") for g in self.content.goals()]

        def promote(choice: str) -> None:
            project_id, goal_id = choice.split("|", 1)

            def job(c: Content) -> JobResult:
                fresh = _fresh_idea(c, ref)
                goal = c.goal(goal_id) if goal_id else None
                item = ideas.promote(c, fresh, project=c.project(project_id), goal=goal)
                return Outcome(f"Promoted to task {item.id}", select=("list", f"task:{item.id}"))

            self.write(job)

        self.pick("Promote to a task in", options, promote)

    def action_drop(self) -> None:
        rows = [r for r in self.rows_under_cursor() if r.kind in ("task", "goal", "todo")]
        if not rows:
            self.nothing("Nothing to drop here")
            return
        content = Content.open(self.root)
        for row in rows:
            if row.kind == "todo":
                continue
            try:
                ops.check_droppable(content, _item(content, row.kind, row.ref.id))
            except TavlaError as e:
                self.show_error(e)  # refused: no question, no commit
                return
        column = self.target_column()
        position = self.position(column.id) if column is not None and column.id else None

        def drop() -> None:
            def job(c: Content) -> JobResult:
                names = []
                for row in rows:
                    if row.kind == "todo":
                        todos.drop(c, [_fresh_todo(c, row.ref)])
                        names.append(row.ref.text)
                    else:
                        ops.drop(c, _item(c, row.kind, row.ref.id))
                        names.append(row.ref.id)
                return Outcome(f"Dropped {', '.join(names)}", at=position)

            self.clear_marks()
            self.write(job)

        what = (
            f"Drop {rows[0].ref.id}?"
            if len(rows) == 1 and hasattr(rows[0].ref, "id")
            else f"Drop {rows[0].ref.text}?"
            if len(rows) == 1
            else f"Drop {len(rows)} items?"
        )
        self.confirm(what, drop)

    def action_undo(self) -> None:
        try:
            change = history.last_change(self.root)
        except TavlaError as e:
            self.show_error(e)
            return
        if change is None:
            self.nothing("Nothing to undo")
            return

        def job(c: Content) -> JobResult:
            history.undo(c.root, change)
            return Outcome(f"Undid: {change.subject}")

        self.confirm(f"Undo “{change.subject}” ({change.when})?", lambda: self.write(job))

    def action_dep_edge(self, add: bool) -> None:
        row = self.target()
        if row is None or row.kind not in ("task", "loose"):
            self.nothing("Dependencies go between tasks")
            return
        task = row.ref
        if add:
            options = [
                (t.id, f"{t.id}  ({t.status}{'*' if t.is_waiting else ''})")
                for t in self.dependency_pool(task)
                if t.id not in task.depends_on
            ]

            def add_edge(after_id: str) -> None:
                def job(c: Content) -> JobResult:
                    edited = ops.add_dep(c, c.task(task.id), c.task(after_id))
                    if edited is None:
                        return Outcome(f"{task.id} already waits on {after_id}")
                    return Outcome(
                        f"{task.id} now waits on {after_id}",
                        select=("mid", f"task:{task.id}"),
                    )

                self.write(job)

            self.pick(f"{task.id} waits on", options, add_edge)
            return
        if not task.depends_on:
            self.nothing(f"{task.id} has no dependencies")

            return

        def remove_edge(after_id: str) -> None:
            def job(c: Content) -> JobResult:
                edited = ops.remove_dep(c, c.task(task.id), c.task(after_id))
                if edited is None:
                    return Outcome(f"{task.id} did not wait on {after_id}")
                return Outcome(f"{task.id} no longer waits on {after_id}")

            self.write(job)

        self.pick(
            f"Remove which dependency of {task.id}",
            [(d, d) for d in task.depends_on],
            remove_edge,
        )

    def dependency_pool(self, task: Task) -> list[Task]:
        """The tasks an `after` edge can point at: its own board, minus itself."""
        if task.goal:
            pool = self.content.goal_tasks(self.content.goal(task.goal))
        else:
            project = next((p for p in self.content.projects() if p.id == task.project), None)
            pool = self.content.tasks(project) if project is not None else []
        return [t for t in pool if t.id != task.id]

    # --- reorder -----------------------------------------------------------------

    def action_reorder(self, delta: int) -> None:
        """Decision 19: tasks within a goal or a project, subtasks within a task."""
        focused = self.focused_column
        if focused is not None and focused.id == "preview":
            subtask = self.selected_subtask()
            row = self.target()
            if subtask is not None and row is not None and row.kind == "task":
                self._reorder_subtasks(row.ref.id, subtask.number, delta)
            return
        column = self.target_column()
        if column is not None and column.id == "mid":
            self._reorder_tasks(column, delta)

    def _reorder_subtasks(self, task_id: str, number: int, delta: int) -> None:
        def job(c: Content) -> JobResult:
            task = c.task(task_id)
            numbers = list(range(1, len(task.subtasks) + 1))
            at, to = number - 1, number - 1 + delta
            if not 0 <= to < len(numbers):
                return Outcome("Already at the end")
            numbers[at], numbers[to] = numbers[to], numbers[at]
            ops.reorder_subtasks(c, task, numbers)
            return Outcome(
                f"{task_id}: subtask {number} → {to + 1}", select=("preview", f"sub:{to + 1}")
            )

        self.write(job)

    def _reorder_tasks(self, column: Column, delta: int) -> None:
        current = column.current
        if current is None or current.kind not in ("task", "loose"):
            return
        tasks = [r for r in column.enabled() if r.kind in ("task", "loose")]
        position = next((n for n, r in enumerate(tasks) if r.key == current.key), None)
        if position is None:
            return
        to = position + delta
        if not 0 <= to < len(tasks):
            return
        order = [r.ref.id for r in tasks]
        order[position], order[to] = order[to], order[position]
        column_id = column.id or "mid"

        def job(c: Content) -> JobResult:
            fresh = [c.task(t) for t in order]
            if not ops.reorder(c, fresh):
                return Outcome("Nothing to reorder")
            where = fresh[0].goal or fresh[0].project
            # The row that moved stays under the cursor, wherever it landed.
            return Outcome(f"Reordered {where}", select=(column_id, current.key))

        self.write(job)

    # --- search, board, projects, help -------------------------------------------

    def action_filter(self) -> None:
        def apply(value: str | None) -> None:
            if value is not None:
                self.filter = value.strip()
                self.reload()

        self.push_screen(
            Prompt("Filter every column", self.filter, "esc clears it · enter applies"), apply
        )

    def action_flow(self) -> None:
        target = self._board_target()
        if target is None:
            self.nothing("Nothing to draw a board for")
            return
        kind, ident = target
        today = dates.local_today()

        def builder(view: str) -> Callable[[int], list[model.Line]]:
            def build(width: int) -> list[model.Line]:
                board = _board(self.content, kind, ident, view=view, today=today)
                return model.flow_lines(board, width)

            return build

        title = f"{kind} {ident}"
        self.push_screen(
            FlowScreen(title, {"stage": builder("stage"), "status": builder("status")}),
            self._jump_to,
        )

    def _board_target(self) -> tuple[str, str] | None:
        """What `f` draws: the selected goal, else the selected thing's goal or
        project, else the current project."""
        row = self.target()
        if row is not None and row.kind == "goal":
            return "goal", row.ref.id
        goal = self.selected_goal()
        if self.scope == "project" and goal is not None and "list" not in self.hidden_columns():
            return "goal", goal.id
        if row is not None and row.kind in ("task", "loose"):
            if row.ref.goal:
                return "goal", row.ref.goal
            return "project", row.ref.project
        if row is not None and row.kind in ("deliverable", "deliverables"):
            project = self.project
            return ("project", project.id) if project is not None else None
        project = self.project
        return ("project", project.id) if project is not None else None

    def _jump_to(self, card: str | None) -> None:
        if card is not None:
            self.jump_to(card)

    def jump_to(self, item_id: str) -> None:
        """Put the cursor on ``item_id`` in scope 1, from wherever it lives."""
        content = Content.open(self.root)
        task = next((t for t in content.tasks() if t.id == item_id), None)
        goal = next((g for g in content.goals() if g.id == item_id), None)
        project = None
        if task is not None:
            project = next((p for p in content.projects() if p.id == task.project), None)
        elif goal is not None:
            project = next((p for p in content.projects() if p.id == goal.project), None)
        else:
            project = next((p for p in content.projects() if p.id == item_id), None)
        if project is None:
            self.notify(f"no item {item_id}", severity="warning")
            return
        self.scope = "project"
        self.project_id = project.id
        self.filter = ""
        self.marked.clear()
        self.visual = False
        if task is not None and task.status == TaskStatus.DONE:
            self.show_all = True  # otherwise the row we are aiming at is hidden
        if goal is not None:
            self.pending["list"] = f"goal:{goal.id}"
        if task is not None:
            self.pending["list"] = f"goal:{task.goal}" if task.goal else f"loose:{project.id}"
            self.pending["mid"] = f"task:{task.id}"
        self.set_layout(self.size.width, self.size.height)
        self.reload()
        if task is not None and self.column("mid").display:
            self.column("mid").focus()
        else:
            self.column("list").focus()

    def action_pick_project(self) -> None:
        projects = self.content.projects()
        if not projects:
            self.nothing("No projects yet")
            return
        options = [
            (
                p.id,
                f"{p.id}  ({p.title})"
                + (f" {model.PROJECT_MARKS[p.status]}" if model.PROJECT_MARKS[p.status] else ""),
            )
            for p in projects
        ]

        def pick(project_id: str) -> None:
            self.project_id = project_id
            self._write_last_project(project_id)
            if self.scope != "project":
                self.scope = "project"
            self.reload()
            self.column("list").focus()

        self.pick("Project", options, pick)

    def action_help(self) -> None:
        self.push_screen(Help())

    def action_reload(self) -> None:
        self.head = self.git_head()
        self.reload()

    # --- people (`@`) -------------------------------------------------------------

    def action_people(self) -> None:
        row = self.target()
        if row is None or row.kind not in ("task", "goal"):
            self.nothing("People live on tasks and goals")
            return
        self.pending_key = "at"
        self.update_hints()
        self.notify("@a add · @d remove · @m mail · @l list", timeout=3)

    def _people_item(self) -> tuple[str, str] | None:
        row = self.target()
        if row is None or row.kind not in ("task", "goal"):
            return None
        return row.ref.id, row.kind

    def _people_new(self, item_id: str, kind: str) -> None:
        def spec(person: str) -> None:
            def job(c: Content) -> JobResult:
                item = c.task(item_id) if kind == "task" else c.goal(item_id)
                person_obj = people.resolve(c, person)
                if any(p.key == person_obj.key for p in item.people):
                    return Outcome(f"{person_obj} is already on {item_id}")
                ops.set_fields(c, item, {"people": people.to_yaml([*item.people, person_obj])})
                return Outcome(f"{item_id}: + {person_obj}")

            self.write(job)

        self.ask(
            f"Add someone to {item_id}",
            spec,
            hint='"Name <email>", an address, or a name',
        )

    def _people_add(self) -> None:
        picked = self._people_item()
        if picked is None:
            return
        item_id, kind = picked
        content = self.content
        item = content.task(item_id) if kind == "task" else content.goal(item_id)
        options = [(str(p), str(p)) for p in people.known(content) if p not in item.people]
        options.append(("__new__", "+ someone new…"))

        def chosen(choice: str) -> None:
            if choice == "__new__":
                self._people_new(item_id, kind)
                return
            self._people_new_spec(item_id, kind, choice)

        self.pick(f"Add someone to {item_id}", options, chosen)

    def _people_new_spec(self, item_id: str, kind: str, spec: str) -> None:
        def job(c: Content) -> JobResult:
            item = c.task(item_id) if kind == "task" else c.goal(item_id)
            person = people.resolve(c, spec)
            if any(p.key == person.key for p in item.people):
                return Outcome(f"{person} is already on {item_id}")
            ops.set_fields(c, item, {"people": people.to_yaml([*item.people, person])})
            return Outcome(f"{item_id}: + {person}")

        self.write(job)

    def _people_remove(self) -> None:
        picked = self._people_item()
        if picked is None:
            return
        item_id, kind = picked
        content = self.content
        item = content.task(item_id) if kind == "task" else content.goal(item_id)
        if not item.people:
            why = (
                f" (they come from goal {item.goal})"
                if isinstance(item, Task) and item.goal_people
                else ""
            )
            self.nothing(f"No one listed on {item_id}{why}")
            return

        def remove(spec: str) -> None:
            def job(c: Content) -> JobResult:
                fresh = c.task(item_id) if kind == "task" else c.goal(item_id)
                kept = people.apply_specs(c, fresh, [f"-{spec}"])
                edited = ops.set_fields(c, fresh, {"people": people.to_yaml(kept)})
                return Outcome(f"{item_id}: − {spec}" if edited is not None else "No changes")

            self.write(job)

        self.pick(f"Remove someone from {item_id}", [(str(p), str(p)) for p in item.people], remove)

    def _people_mail(self) -> None:
        picked = self._people_item()
        if picked is None:
            return
        item_id, kind = picked
        content = self.content
        item = content.task(item_id) if kind == "task" else content.goal(item_id)
        involved = item.everyone if isinstance(item, Task) else item.people
        with_address = [p for p in involved if p.email]
        if not with_address:
            self.nothing(f"No addresses on {item_id} (use @a)")
            return
        try:
            url = people.mailto(with_address, item.title)
        except ValidationError as e:
            self.show_error(e)
            return
        try:
            with self.suspend():
                opened = people.open_mailto(url)
        except SuspendNotSupported:
            self.nothing("Can't open a mail program from here")
            return
        if opened:
            self.notify(f"Opening a new email to {len(with_address)} people", timeout=3)
        else:
            self.notify(f"No mail program handled {url}", severity="warning", timeout=8)

    def _people_list(self) -> None:
        picked = self._people_item()
        if picked is None:
            return
        item_id, kind = picked
        content = self.content
        item = content.task(item_id) if kind == "task" else content.goal(item_id)
        lines: list[Any] = []
        if isinstance(item, Task):
            own = {p.key for p in item.people}
            lines += [
                Text(f"{p}{'' if p.key in own else '  (from the goal)'}") for p in item.everyone
            ]
        else:
            lines += [Text(str(p)) for p in item.people]
        if not lines:
            lines = [Text(f"No one listed on {item_id}. @a adds someone.", style="dim")]
        lines += [
            Text(""),
            Text(f"everyone listed in the repo ({len(people.known(content))})", style="bold"),
        ]
        lines += [
            Text(f"  {p}" + (f"  <{p.email}>" if p.email else "")) for p in people.known(content)
        ]
        self.push_screen(ListScreen(f"People · {item_id}", lines))

    # --- pending keys -------------------------------------------------------------

    def on_key(self, event: Key) -> None:
        """Keys that need a first key of their own: `gg`, `@a`, and visual
        mode's `j`/`k`.

        Textual has no multi-key bindings, so this reads a pending first key
        and marks the event handled with ``prevent_default()`` — the one thing
        that also stops the focused widget's binding from acting on the same
        press.
        """
        key = event.key
        if self.pending_key is not None:
            pending, self.pending_key = self.pending_key, None
            event.prevent_default()
            event.stop()
            if pending == "at":
                if key == "a":
                    self._people_add()
                elif key == "d":
                    self._people_remove()
                elif key == "m":
                    self._people_mail()
                elif key == "l":
                    self._people_list()
                else:
                    self.nothing("@a add · @d remove · @m mail · @l list")
            elif key == "g":  # `gg`: vim's first row
                column = self.focused_column
                if column is not None:
                    column.action_first()
            self.update_hints()
            return
        if key == "g":
            self.pending_key = "g"
            event.prevent_default()
            self.set_timer(3.0, self._clear_pending)
            self.update_hints()
            return
        if self.visual and key in ("j", "down", "k", "up"):
            column = self.focused_column
            if column is not None and column.id != "preview":
                event.prevent_default()
                event.stop()
                if key in ("j", "down"):
                    column.action_cursor_down()
                else:
                    column.action_cursor_up()
                self.extend_marks()
            return
        if key == "p":
            row = self.target()
            if row is not None and row.kind == "idea":
                event.prevent_default()
                self.action_promote()
            # Any other row: `p` falls through to Textual (nothing to paste on).

    def _clear_pending(self) -> None:
        if self.pending_key == "g":
            self.pending_key = None
            self.update_hints()


# --- module helpers -----------------------------------------------------------


def _item(c: Content, kind: str, item_id: str) -> Task | Goal | Deliverable:
    if kind == "task":
        return c.task(item_id)
    if kind == "goal":
        return c.goal(item_id)
    return c.deliverable(item_id)


def _complete(c: Content, row: Row) -> list[str]:
    """Mark one row done inside an existing write job."""
    if row.kind == "todo":
        todos.set_done(c, [_fresh_todo(c, row.ref)])
        return [row.ref.text]
    if row.kind == "goal":
        goal = c.goal(row.ref.id)
        return [goal.id] if ops.complete(c, goal) is not None else []
    if row.kind == "task":
        task = c.task(row.ref.id)
        if task.status == TaskStatus.DONE:
            return []
        work.finish(c, task)
        return [task.id]
    return []


def _finish(c: Content, task: Task) -> str:
    unblocked = [
        t.id for t in c.tasks() if t.waiting_on == [task.id] and t.status != TaskStatus.DONE
    ]
    done, session = work.finish(c, task)
    if done is None:
        return f"{task.id} is already done"
    message = f"Done: {task.id}"
    if session is not None:
        message += f" ({work.format_duration(session.duration)} this session)"
    if unblocked:
        message += f"; now ready: {', '.join(unblocked)}"
    return message


def _fresh_todo(c: Content, todo: todos.Todo) -> todos.Todo:
    for t in todos.read(c):
        if t.number == todo.number and t.text == todo.text:
            return t
    raise ValidationError("todo.md changed on disk; try again")


def _fresh_idea(c: Content, ref: ideas.IdeaRef) -> ideas.IdeaRef:
    for r in ideas.read(ref.scope):
        if r.number == ref.number and r.idea.text == ref.idea.text:
            return r
    raise ValidationError(f"the ideas in {ref.scope.label} changed on disk; try again")


def _board(content: Content, kind: str, ident: str, *, view: str, today: Any) -> flow.Board:
    target: Project | Goal
    if kind == "goal":
        target = content.goal(ident)
    else:
        target = content.project(ident)
    if view == "status":
        return flow.status_board(content, target, today=today)
    if isinstance(target, Goal):
        return flow.goal_board(content, target, today=today)
    return flow.project_board(content, target, today=today)


def run(root: Path) -> None:
    TavlaApp(root).run()
