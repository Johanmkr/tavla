"""``tv ui``: a full-screen view of the content repo, lazygit style.

Left, top to bottom: Status (what you are working on, alerts, todos),
Projects, Goals, and Tasks (with Ideas and Deliverables tabs). Right: the
detail of whatever is selected. Every change goes through the same core
functions as the CLI (so it is validated and committed the same way); the
app reloads whenever the repo's HEAD moves, whoever moved it.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from tavla import config
from tavla.cli.common import date_change, open_in_editor
from tavla.core import dates, git_sync, history, ideas, ops, queries, todos
from tavla.core import focus as work
from tavla.core.entities import Deliverable, Goal, Priority, Project, Task, TaskStatus
from tavla.core.errors import GitError, TavlaError, ValidationError
from tavla.core.ops import EditSession
from tavla.core.store import Content
from tavla.tui import model
from tavla.tui.model import ALL, Context, Row
from tavla.tui.screens import Confirm, Help, Prompt

POLL_SECONDS = 2.0
STATUS_EVERY = 30.0  # refresh the work timer and alerts this often
NARROW = 80  # below this many columns, panes stack and the detail opens on enter
MIN_SIZE = (40, 12)

TABS = ("tasks", "ideas", "deliverables")
TAB_LABELS = {"tasks": "Tasks", "ideas": "Ideas", "deliverables": "Deliv"}
NEXT_PRIORITY = {
    Priority.HIGH: Priority.MED,
    Priority.MED: Priority.LOW,
    Priority.LOW: Priority.HIGH,
}

HINTS = {
    "status": "space done  a add todo  D drop  enter go to task",
    "projects": "enter goals  a add  n log  e edit  ! priority",
    "goals": "enter tasks  space done  a add goal  n note  e edit  t due",
    "tasks": "space done  s start  w work  n note  a add  e edit  t due  D drop",
    "ideas": "a add  p promote  D drop  [ ] tabs",
    "deliverables": "a add  e edit  t deadline  D drop  [ ] tabs",
    "detail": "space tick  a add subtask  w work  n note  e edit  esc back",
}

# A write job gets a fresh Content and returns a message to show, plus
# optionally (pane id, row key) to select once the app has reloaded.
JobResult = str | tuple[str, tuple[str, str] | None] | None
Job = Callable[[Content], JobResult]


class Pane(OptionList):
    """A list of :class:`Row` s that keeps its selection across reloads."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "first", show=False),
        Binding("G", "last", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
    ]

    def __init__(self, title: str, *, id: str) -> None:
        super().__init__(id=id, classes="pane")
        self.title = title
        self.border_title = title
        self.rows: list[Row] = []
        self.filter = ""

    @property
    def current(self) -> Row | None:
        i = self.highlighted
        return self.rows[i] if i is not None and 0 <= i < len(self.rows) else None

    def show(self, rows: list[Row], keep: str | None = None, empty: str = "") -> None:
        """Replace the rows, keeping the selected key (or ``keep``) when it is still there."""
        keep = keep or (self.current.key if self.current else None)
        if self.filter:
            rows = [r for r in rows if r.disabled or r.matches(self.filter)]
        if not any(not r.disabled for r in rows) and empty:
            rows = [*rows, Row("empty", "empty", Text(empty, style="dim italic"), disabled=True)]
        with self.prevent(OptionList.OptionHighlighted):
            self.clear_options()
            self.add_options(
                [
                    Option(r.prompt, id=f"{n}:{r.key}", disabled=r.disabled)
                    for n, r in enumerate(rows)
                ]
            )
            self.rows = rows
            enabled = [n for n, r in enumerate(rows) if not r.disabled]
            wanted = next((n for n in enabled if rows[n].key == keep), None)
            self.highlighted = wanted if wanted is not None else (enabled[0] if enabled else None)
        title = self.title + (f" /{self.filter}" if self.filter else "")
        if self.id != "tasks":
            self.border_title = title

    def select_key(self, key: str) -> bool:
        for n, r in enumerate(self.rows):
            if r.key == key and not r.disabled:
                self.highlighted = n
                return True
        return False

    def on_focus(self) -> None:
        app = self.app
        if isinstance(app, TavlaApp):
            app.pane_focused(self)


class DetailPane(Pane):
    """The right-hand pane. Only subtask lines can be selected; with none,
    j/k scroll instead."""

    def _selectable(self) -> bool:
        return any(not r.disabled for r in self.rows)

    def action_cursor_down(self) -> None:
        super().action_cursor_down() if self._selectable() else self.scroll_down(animate=False)

    def action_cursor_up(self) -> None:
        super().action_cursor_up() if self._selectable() else self.scroll_up(animate=False)


class TavlaApp(App[None]):
    CSS = """
    Screen { background: ansi_default; }
    #main { height: 1fr; }
    #left { width: 38%; min-width: 30; max-width: 52; }
    .pane {
        height: 1fr; border: round ansi_bright_black; padding: 0;
        background: ansi_default; scrollbar-size-vertical: 1;
        border-title-color: ansi_default; border-subtitle-color: ansi_bright_black;
    }
    .pane:focus { border: round $accent; border-title-style: bold reverse; }
    .pane > .option-list--option-highlighted {
        background: ansi_default; color: ansi_default; text-style: underline;
    }
    .pane:focus > .option-list--option-highlighted { text-style: reverse bold; }
    .pane > .option-list--option-disabled { color: ansi_default; text-style: none; }
    .pane > .option-list--option-hover { background: ansi_default; }
    #status { height: auto; max-height: 9; }
    #tasks { height: 2fr; }
    #detail { width: 1fr; }
    #hints { height: 1; padding: 0 1; }
    #toosmall { display: none; content-align: center middle; height: 1fr; }

    .narrow #detail { display: none; }
    .narrow #left { width: 1fr; max-width: 100%; }
    .narrow #left > .pane { height: 3; }
    .narrow #left > .pane:focus { height: 1fr; }
    .detail-open #left { display: none; }
    .detail-open #detail { display: block; width: 1fr; }
    .tiny #main, .tiny #hints { display: none; }
    .tiny #toosmall { display: block; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit", show=False),
        Binding("ctrl+c", "quit", show=False, priority=True),
        Binding("question_mark", "help", show=False),
        Binding("1", "focus_pane('status')", show=False),
        Binding("2", "focus_pane('projects')", show=False),
        Binding("3", "focus_pane('goals')", show=False),
        Binding("4", "focus_pane('tasks')", show=False),
        Binding("0", "focus_pane('detail')", show=False),
        Binding("escape", "back", show=False),
        Binding("left_square_bracket", "tab(-1)", show=False),
        Binding("right_square_bracket", "tab(1)", show=False),
        Binding("space,x", "toggle_done", show=False),
        Binding("s", "start", show=False),
        Binding("w", "work", show=False),
        Binding("n", "note", show=False),
        Binding("a", "add", show=False),
        Binding("e", "edit", show=False),
        Binding("exclamation_mark", "priority", show=False),
        Binding("t", "due", show=False),
        Binding("p", "promote", show=False),
        Binding("D", "drop", show=False),
        Binding("u", "undo", show=False),
        Binding("r", "reload", show=False),
        Binding("slash", "filter", show=False),
        Binding("full_stop", "toggle_all", show=False),
    ]

    def __init__(self, root: Path) -> None:
        super().__init__(ansi_color=True)
        self.root = root.resolve()
        self.content = Content.open(root)
        self.context_pane = "status"  # which of status/projects/goals the Tasks pane follows
        self.detail_source = "tasks"  # whose selection the detail pane shows
        self.detail_item = ""
        self.tab = "tasks"
        self.show_all = False
        self.head: str | None = None
        self.loaded_at = time.monotonic()
        self.status_at = 0.0
        self.pending: dict[str, str] = {}
        self.write_lock = threading.Lock()

    # --- layout ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Pane("Status", id="status")
                yield Pane("Projects", id="projects")
                yield Pane("Goals", id="goals")
                yield Pane("Tasks", id="tasks")
            yield DetailPane("Detail", id="detail")
        yield Static(id="hints")
        yield Static(
            f"Terminal too small for tavla (need {MIN_SIZE[0]}×{MIN_SIZE[1]}).", id="toosmall"
        )

    def on_mount(self) -> None:
        self.theme = "ansi-dark"
        self.head = self.git_head()
        self.reload()
        self.pane("tasks").focus()
        self.set_layout(self.size.width, self.size.height)
        self.set_interval(POLL_SECONDS, self.poll)

    def on_resize(self, event: Resize) -> None:
        self.set_layout(event.size.width, event.size.height)
        self.call_after_refresh(self.refresh_detail)

    def set_layout(self, width: int, height: int) -> None:
        screen = self.screen
        narrow = width < NARROW
        screen.set_class(narrow, "narrow")
        screen.set_class(width < MIN_SIZE[0] or height < MIN_SIZE[1], "tiny")
        if not narrow:
            screen.remove_class("detail-open")
        for pane in self.query(Pane):
            pane.call_after_refresh(pane.scroll_to_highlight)

    def pane(self, pane_id: str) -> Pane:
        return self.query_one(f"#{pane_id}", Pane)

    @property
    def detail(self) -> DetailPane:
        return self.query_one("#detail", DetailPane)

    @property
    def focused_pane(self) -> Pane | None:
        return self.focused if isinstance(self.focused, Pane) else None

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
            self.refresh_status()
            if self.detail_source == "tasks":
                self.refresh_detail()
        self.update_hints()

    def reload(self) -> None:
        self.content.refresh()
        self.loaded_at = time.monotonic()
        try:
            self.refresh_status()
            self.pane("projects").show(
                model.project_rows(self.content, show_all=self.show_all),
                keep=self.pending.pop("projects", None),
                empty="No projects. Press a to add one.",
            )
            self.refresh_goals()
            self.refresh_tasks()
            self.refresh_detail()
        except TavlaError as e:
            self.notify(f"can't read the content repo: {e}", severity="error", timeout=10)
        self.update_hints()

    def refresh_status(self) -> None:
        self.status_at = time.monotonic()
        self.pane("status").show(
            model.status_rows(self.content), keep=self.pending.pop("status", None)
        )

    def selected_project(self) -> Project | None:
        row = self.pane("projects").current
        return row.ref if row and row.kind == "project" else None

    def refresh_goals(self) -> None:
        project = self.selected_project()
        self.pane("goals").show(
            model.goal_rows(
                self.content, project, show_all=self.show_all, today=dates.local_today()
            ),
            keep=self.pending.pop("goals", None),
            empty="No goals. Press a to add one." if project else "",
        )

    def context(self) -> Context:
        if self.context_pane == "status":
            return ALL
        project = self.selected_project()
        if project is None:
            return ALL
        if self.context_pane == "goals":
            row = self.pane("goals").current
            if row and row.kind == "goal":
                return Context("goal", project.id, row.ref.id)
            if row and row.kind == "loose":
                return Context("loose", project.id)
        return Context("project", project.id)

    def refresh_tasks(self) -> None:
        ctx = self.context()
        today = dates.local_today()
        pane = self.pane("tasks")
        if self.tab == "tasks":
            current = work.current(self.content)
            rows = model.task_rows(
                self.content,
                ctx,
                show_all=self.show_all,
                working=current.task_id if current else None,
                today=today,
            )
            empty = "Nothing ready. Press a to add a task." if ctx != ALL else "Nothing to do now."
        elif self.tab == "ideas":
            rows = model.idea_rows(self.content, ctx)
            empty = "No ideas here. Press a to add one."
        else:
            rows = model.deliverable_rows(self.content, ctx, today=today)
            empty = "No deliverables. Press a to add one."
        pane.show(rows, keep=self.pending.pop("tasks", None), empty=empty)
        strip = "│".join(
            f"[b]{TAB_LABELS[t]}[/b]" if t == self.tab else f"[dim]{TAB_LABELS[t]}[/dim]"
            for t in TABS
        )
        pane.border_title = strip + (f" /{pane.filter}" if pane.filter else "")
        if ctx.kind == "all":
            scope = "inbox" if self.tab == "ideas" else "next · all projects"
        else:
            scope = ctx.goal or (
                f"{ctx.project} {model.LOOSE}" if ctx.kind == "loose" else ctx.project or ""
            )
        pane.border_subtitle = scope

    def refresh_detail(self) -> None:
        source = self.pane(self.detail_source) if self.detail_source != "detail" else None
        row = source.current if source else None
        today = dates.local_today()
        width = max(self.detail.size.width - 3, 20)
        lines: list[model.Line] = []
        title = "Detail"
        if row is None:
            lines = []
        elif row.kind == "task":
            task = self._fresh_task(row.ref.id)
            lines = model.task_detail(self.content, task) if task else []
            title = task.id if task else title
        elif row.kind == "goal":
            lines = model.goal_detail(
                self.content, row.ref, width=width, today=today, open_only=not self.show_all
            )
            title = f"{row.ref.id} · flow"
        elif row.kind == "project":
            lines = model.project_detail(
                self.content, row.ref, width=width, today=today, open_only=not self.show_all
            )
            title = f"{row.ref.id} · flow"
        elif row.kind == "loose":
            lines = model.loose_detail(self.content, row.ref, today=today)
            title = model.LOOSE
        elif row.kind == "idea":
            lines, title = model.idea_detail(row.ref), "idea"
        elif row.kind == "deliverable":
            lines, title = model.deliverable_detail(row.ref, today=today), row.ref.id
        elif row.kind == "todo":
            lines, title = model.todo_detail(row.ref), "todo"
        elif row.kind in ("working", "summary"):
            lines, title = model.status_detail(self.content, today=today), "status"
        rows = [
            Row(
                line.key or f"line:{n}",
                "subtask" if line.subtask else "line",
                line.prompt,
                ref=line.subtask,
                disabled=line.subtask is None,
            )
            for n, line in enumerate(lines)
        ]
        item = row.key if row else ""
        detail = self.detail
        detail.title = title
        if item != self.detail_item:
            detail.highlighted = None
            detail.show(rows)
            detail.scroll_home(animate=False)
            self.detail_item = item
        else:
            detail.show(rows)
        detail.border_title = title

    def _fresh_task(self, task_id: str) -> Task | None:
        return next((t for t in self.content.tasks() if t.id == task_id), None)

    def update_hints(self) -> None:
        pane = self.focused_pane
        key = pane.id if pane else "tasks"
        if key == "tasks":
            key = self.tab
        age = int(time.monotonic() - self.loaded_at)
        fresh = "just now" if age < 5 else f"{age}s ago" if age < 60 else f"{age // 60}m ago"
        hints = HINTS.get(key or "", "")
        self.query_one("#hints", Static).update(
            model.two_columns(Text(hints, style="dim"), Text(f"? help  ↻ {fresh}", style="dim"))
        )

    # --- focus & navigation -----------------------------------------------------

    def pane_focused(self, pane: Pane) -> None:
        if pane.id in ("status", "projects", "goals") and pane.id != self.context_pane:
            self.context_pane = pane.id
            self.refresh_tasks()
        if pane.id != "detail":
            self.detail_source = pane.id or "tasks"
            self.refresh_detail()
        self.update_hints()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        pane_id = event.option_list.id
        if pane_id == "projects":
            self.refresh_goals()
            self.refresh_tasks()
        elif pane_id == "goals":
            self.refresh_tasks()
        if pane_id != "detail":
            self.refresh_detail()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        pane = event.option_list
        row = pane.current if isinstance(pane, Pane) else None
        if pane.id == "status":
            if row and row.kind == "working" and row.ref:
                self.jump_to_task(row.ref)
            else:
                self.pane("tasks").focus()
        elif pane.id == "projects":
            self.pane("goals").focus()
        elif pane.id == "goals":
            self.pane("tasks").focus()
        elif pane.id == "tasks":
            self.action_focus_pane("detail")

    def action_focus_pane(self, pane_id: str) -> None:
        if pane_id == "detail" and self.screen.has_class("narrow"):
            self.screen.add_class("detail-open")
        elif pane_id != "detail":
            self.screen.remove_class("detail-open")
        self.pane(pane_id).focus()

    def action_back(self) -> None:
        pane = self.focused_pane
        if pane is None:
            return
        if pane.filter:
            pane.filter = ""
            self.reload()
            return
        if pane.id == "detail":
            self.screen.remove_class("detail-open")
            self.pane(self.detail_source if self.detail_source != "detail" else "tasks").focus()
        elif pane.id == "tasks":
            self.pane(self.context_pane).focus()
        elif pane.id == "goals":
            self.pane("projects").focus()
        elif pane.id == "projects":
            self.pane("status").focus()

    def jump_to_task(self, task_id: str) -> None:
        task = self._fresh_task(task_id)
        if task is None:
            self.notify(f"no task {task_id}", severity="warning")
            return
        projects = self.pane("projects")
        if not projects.select_key(f"project:{task.project}"):
            self.show_all = True
            self.reload()
            projects.select_key(f"project:{task.project}")
        self.refresh_goals()
        goals = self.pane("goals")
        if not (task.goal and goals.select_key(f"goal:{task.goal}")):
            goals.select_key(f"loose:{task.project}")
        self.context_pane = "goals"
        self.tab = "tasks"
        self.pending["tasks"] = f"task:{task.id}"
        self.refresh_tasks()
        self.pane("tasks").focus()

    def action_tab(self, delta: int) -> None:
        self.tab = TABS[(TABS.index(self.tab) + delta) % len(TABS)]
        self.refresh_tasks()
        if self.detail_source == "tasks":
            self.refresh_detail()
        self.update_hints()

    def action_help(self) -> None:
        self.push_screen(Help())

    def action_reload(self) -> None:
        self.head = self.git_head()
        self.reload()

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.reload()
        self.notify(
            "Showing done and paused items" if self.show_all else "Hiding done items", timeout=2
        )

    def action_filter(self) -> None:
        pane = self.focused_pane
        if pane is None or pane.id == "detail":
            return

        def apply(value: str | None) -> None:
            if value is not None:
                pane.filter = value.strip()
                self.reload()

        self.push_screen(
            Prompt(f"Filter {pane.title}", pane.filter, "esc in the list clears it"), apply
        )

    # --- what an action applies to ----------------------------------------------

    def target(self) -> Row | None:
        """The row an action acts on: the focused pane's selection, or the
        item shown in the detail pane when that has focus."""
        pane = self.focused_pane
        if pane is None:
            return None
        if pane.id == "detail":
            source = self.detail_source
            return self.pane(source).current if source != "detail" else None
        return pane.current

    def selected_subtask(self) -> Any:
        pane = self.focused_pane
        if pane is not None and pane.id == "detail" and pane.current and pane.current.ref:
            return pane.current.ref
        return None

    def ask(
        self, question: str, then: Callable[[str], None], value: str = "", hint: str = ""
    ) -> None:
        def done(answer: str | None) -> None:
            if answer is not None and answer.strip():
                then(answer.strip())

        self.push_screen(Prompt(question, value, hint), done)

    def confirm(self, question: str, then: Callable[[], None]) -> None:
        self.push_screen(Confirm(question), lambda yes: then() if yes else None)

    def nothing(self, what: str) -> None:
        self.notify(what, severity="warning", timeout=3)

    # --- writes --------------------------------------------------------------------

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
            message, select = result if isinstance(result, tuple) else (result, None)
            if select:
                self.pending[select[0]] = select[1]
            self.head = self.git_head()
            self.reload()
            if message:
                self.notify(message, timeout=3)
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

    # --- actions -----------------------------------------------------------------

    def action_toggle_done(self) -> None:
        subtask = self.selected_subtask()
        row = self.target()
        if subtask is not None and row and row.kind == "task":
            task_id = row.ref.id

            def tick(c: Content) -> JobResult:
                task = c.task(task_id)
                fresh = model.subtask_by_number(task, subtask.number)
                if fresh is None or fresh.text != subtask.text:
                    raise ValidationError(f"{task.path} changed on disk; try again")
                ops.check_subtasks(c, task, [fresh], done=not fresh.done)
                return None

            self.write(tick)
            return
        if row is None:
            return
        if row.kind == "task":
            task_id = row.ref.id
            if row.ref.status == TaskStatus.DONE:
                self.write(lambda c: _reopen(c, c.task(task_id)))
            else:
                self.write(lambda c: _finish(c, c.task(task_id)))
        elif row.kind == "goal":
            goal_id = row.ref.id
            if row.ref.status == TaskStatus.DONE:
                self.write(lambda c: _reopen(c, c.goal(goal_id)))
            else:
                self.write(lambda c: ops.complete(c, c.goal(goal_id)) and f"Done: {goal_id}")
        elif row.kind == "todo":
            todo = row.ref

            def tick_todo(c: Content) -> JobResult:
                todos.set_done(c, [_fresh_todo(c, todo)])
                return f"Done: {todo.text}"

            self.write(tick_todo)
        else:
            self.nothing("Nothing to mark done here")

    def action_start(self) -> None:
        row = self.target()
        if row and row.kind in ("task", "goal"):
            kind, item_id = row.kind, row.ref.id

            def start(c: Content) -> JobResult:
                item = c.task(item_id) if kind == "task" else c.goal(item_id)
                return f"Started {item_id}" if ops.start(c, item) else f"{item_id} is already doing"

            self.write(start)
        else:
            self.nothing("Select a task or goal to start")

    def action_work(self) -> None:
        row = self.target()
        current = work.current(self.content)
        if current is not None and not (
            row and row.kind == "task" and row.ref.id != current.task_id
        ):

            def pause(c: Content) -> JobResult:
                focus, _, session = work.pause(c)
                return f"Paused {focus.task_id} after {work.format_duration(session.duration)}"

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
            return f"Working on {task_id}{note}"

        self.write(enter)

    def action_note(self) -> None:
        row = self.target()
        if row and row.kind in ("task", "goal"):
            kind, item_id = row.kind, row.ref.id

            def note(text: str) -> None:
                self.write(
                    lambda c: (
                        ops.add_update(
                            c, c.task(item_id) if kind == "task" else c.goal(item_id), text
                        ),
                        f"Noted on {item_id}",
                    )[1]
                )

            self.ask(f"Note on {item_id}", note)
        elif row and row.kind == "project":
            project_id = row.ref.id

            def log(text: str) -> None:
                self.write(
                    lambda c: (
                        ops.append_log(c, c.project(project_id), text),
                        f"Logged in {project_id}",
                    )[1]
                )

            self.ask(f"Log line for {project_id}", log)
        else:
            self.nothing("Select a task, goal or project to note on")

    def action_add(self) -> None:
        pane = self.focused_pane
        if pane is None:
            return
        if pane.id == "detail":
            row = self.target()
            if row is None or row.kind != "task":
                self.nothing("Subtasks are added to tasks")
                return
            task_id = row.ref.id
            self.ask(
                f"New subtask of {task_id}",
                lambda text: self.write(
                    lambda c: (ops.add_subtask(c, c.task(task_id), text), None)[1]
                ),
            )
        elif pane.id == "status":
            self.ask(
                "New todo",
                lambda text: self.write(lambda c: (todos.add(c, text), "Added to todo.md")[1]),
            )
        elif pane.id == "projects":

            def add_project(title: str) -> None:
                def job(c: Content) -> JobResult:
                    p = ops.add_project(c, title)
                    return f"Added project {p.id}", ("projects", f"project:{p.id}")

                self.write(job)

            self.ask("New project", add_project)
        elif pane.id == "goals":
            project = self.selected_project()
            if project is None:
                self.nothing("Select a project first")
                return
            project_id = project.id

            def add_goal(title: str) -> None:
                def job(c: Content) -> JobResult:
                    g = ops.add_goal(c, title, c.project(project_id))
                    return f"Added goal {g.id}", ("goals", f"goal:{g.id}")

                self.write(job)

            self.ask(f"New goal in {project_id}", add_goal)
        elif self.tab == "tasks":
            self.add_task()
        elif self.tab == "ideas":
            owner = model.idea_owner(self.content, self.context())
            scope = ideas.scope_of(self.content, owner)

            def add_idea(text: str) -> None:
                self.write(lambda c: (ideas.add(c, scope, text), f"Idea added to {scope.label}")[1])

            self.ask(
                f"New idea ({scope.label})", add_idea, hint="#tags work · enter ok · esc cancel"
            )
        else:
            project = self.selected_project() if self.context() != ALL else None
            if project is None:
                self.nothing("Select a project first (2)")
                return
            project_id = project.id

            def add_deliverable(title: str) -> None:
                def job(c: Content) -> JobResult:
                    d = ops.add_deliverable(c, title, c.project(project_id))
                    return f"Added deliverable {d.id}", ("tasks", f"deliverable:{d.id}")

                self.write(job)

            self.ask(f"New deliverable in {project_id}", add_deliverable)

    def add_task(self) -> None:
        ctx = self.context()
        if ctx.kind == "all":
            self.nothing("Select a project or goal first (2 or 3), then a")
            return
        where = ctx.goal or ctx.project

        def add(title: str) -> None:
            def job(c: Content) -> JobResult:
                goal = c.goal(ctx.goal) if ctx.goal else None
                task = ops.add_task(c, title, c.project(ctx.project or ""), goal=goal)
                return f"Added task {task.id}", ("tasks", f"task:{task.id}")

            self.write(job)

        self.ask(f"New task in {where}", add)

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
            elif row.kind == "project":
                item = content.project(row.ref.id)
                finish = lambda s: ops.finish_project_edit(content, item, s)
            elif row.kind == "deliverable":
                item = content.deliverable(row.ref.id)
                finish = lambda s: ops.finish_deliverable_edit(content, item, s)
            else:
                self.nothing("Ideas and todos are edited through their owner (e on it)")
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
                pane = self.focused_pane
                if pane is not None and pane.id != "detail":
                    self.pending[pane.id or ""] = f"{row.kind}:{result.id}"
        self.head = self.git_head()
        self.reload()

    def action_priority(self) -> None:
        row = self.target()
        if row is None or row.kind not in ("task", "goal", "project"):
            self.nothing("Select a task, goal or project")
            return
        kind, item_id = row.kind, row.ref.id
        new = NEXT_PRIORITY[row.ref.priority]

        def job(c: Content) -> JobResult:
            if kind == "project":
                ops.set_project_fields(c, c.project(item_id), {"priority": new.value})
            else:
                item = c.task(item_id) if kind == "task" else c.goal(item_id)
                ops.set_fields(c, item, {"priority": new.value})
            return f"{item_id}: priority {new.value}"

        self.write(job)

    def action_due(self) -> None:
        row = self.target()
        if row is None or row.kind not in ("task", "goal", "deliverable"):
            self.nothing("Select a task, goal or deliverable")
            return
        kind, item_id = row.kind, row.ref.id
        current = row.ref.deadline if kind == "deliverable" else row.ref.due
        if kind == "task" and "due" in row.ref.inherited:
            current = None

        def set_due(value: str) -> None:
            try:
                when = date_change(value)
            except TavlaError as e:
                self.show_error(e)
                return

            def job(c: Content) -> JobResult:
                if kind == "deliverable":
                    ops.set_deliverable_fields(c, c.deliverable(item_id), {"deadline": when})
                else:
                    item = c.task(item_id) if kind == "task" else c.goal(item_id)
                    ops.set_fields(c, item, {"due": when})
                return f"{item_id}: " + (f"due {when.isoformat()}" if when else "no due date")

            self.write(job)

        word = "Deadline" if kind == "deliverable" else "Due date"
        self.ask(
            f"{word} for {item_id}",
            set_due,
            value=current.isoformat() if current else "",
            hint="today, tomorrow, +3d, +2w, fri, 2026-11-01, 1.11.26 · none clears",
        )

    def action_promote(self) -> None:
        row = self.target()
        if row is None or row.kind != "idea":
            self.nothing("Select an idea (Ideas tab) to promote")
            return
        ref = row.ref
        ctx = self.context()

        def promote(target_id: str | None) -> None:
            def job(c: Content) -> JobResult:
                fresh = _fresh_idea(c, ref)
                if target_id is None:
                    project = c.project(ctx.project or "")
                    goal = c.goal(ctx.goal) if ctx.goal else None
                else:
                    target = queries.resolve_id(
                        target_id, [*c.projects(), *c.goals()], "project or goal"
                    )
                    goal = target if isinstance(target, Goal) else None
                    project = c.project(target.project) if isinstance(target, Goal) else target
                item = ideas.promote(c, fresh, project=project, goal=goal)
                return f"Promoted to task {item.id}"

            self.write(job)

        if ctx.kind == "all":
            self.ask("Promote to a task in which project or goal?", promote)
        else:
            promote(None)

    def action_drop(self) -> None:
        row = self.target()
        if row is None:
            return
        if row.kind in ("task", "goal", "deliverable"):
            kind, item_id = row.kind, row.ref.id
            content = Content.open(self.root)
            try:
                item = _item(content, kind, item_id)
                ops.check_droppable(content, item)
            except TavlaError as e:
                self.show_error(e)
                return
            self.confirm(
                f"Drop {kind} {item_id} ({item.title})?",
                lambda: self.write(
                    lambda c: (ops.drop(c, _item(c, kind, item_id)), f"Dropped {item_id}")[1]
                ),
            )
        elif row.kind == "idea":
            ref = row.ref
            self.confirm(
                f"Drop idea “{ref.idea.text}”?",
                lambda: self.write(
                    lambda c: (ideas.drop(c, _fresh_idea(c, ref)), "Idea dropped")[1]
                ),
            )
        elif row.kind == "todo":
            todo = row.ref
            self.confirm(
                f"Drop todo “{todo.text}”?",
                lambda: self.write(
                    lambda c: (todos.drop(c, [_fresh_todo(c, todo)]), "Todo dropped")[1]
                ),
            )
        else:
            self.nothing("Nothing to drop here")

    def action_undo(self) -> None:
        try:
            change = history.last_change(self.root)
        except TavlaError as e:
            self.show_error(e)
            return
        if change is None:
            self.nothing("Nothing to undo")
            return
        self.confirm(
            f"Undo “{change.subject}” ({change.when})?",
            lambda: self.write(
                lambda c: (history.undo(c.root, change), f"Undid: {change.subject}")[1]
            ),
        )


# --- job helpers (run in the worker thread, on a fresh Content) ----------------------


def _item(c: Content, kind: str, item_id: str) -> Task | Goal | Deliverable:
    if kind == "task":
        return c.task(item_id)
    if kind == "goal":
        return c.goal(item_id)
    return c.deliverable(item_id)


def _finish(c: Content, task: Task) -> JobResult:
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


def _reopen(c: Content, item: Task | Goal) -> JobResult:
    ops.set_status(c, item, TaskStatus.TODO, verb="reopen")
    return f"Reopened {item.id}"


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


def run(root: Path) -> None:
    TavlaApp(root).run()
