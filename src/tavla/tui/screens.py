"""Modal screens: a one-line prompt, a yes/no confirmation and the key help."""

from __future__ import annotations

from typing import ClassVar

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

MODAL_CSS = """
ModalScreen { align: center middle; background: transparent; }
#dialog {
    width: 70%; max-width: 80; min-width: 36; height: auto;
    border: round $accent; padding: 0 1; background: $background;
}
#dialog Input { border: none; height: 1; padding: 0; background: $background; }
#dialog .hint { color: $text-muted; }
"""


class Prompt(ModalScreen[str | None]):
    """Ask for one line of text. Enter submits, Esc cancels (returns None)."""

    DEFAULT_CSS = MODAL_CSS
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, question: str, value: str = "", hint: str = "") -> None:
        super().__init__()
        self.question, self.value, self.hint = question, value, hint

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(self.question, style="bold"))
            yield Input(value=self.value, select_on_focus=True)
            yield Label(self.hint or "enter ok · esc cancel", classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Confirm(ModalScreen[bool]):
    """A yes/no question; anything but ``y`` means no."""

    DEFAULT_CSS = MODAL_CSS
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "answer(True)", show=False),
        Binding("n,escape,enter,q", "answer(False)", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(self.question, style="bold"))
            yield Label("y yes · n / esc no", classes="hint")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


HELP = [
    (
        "Moving around",
        [
            ("j k  ↑ ↓", "move in a list"),
            ("g G", "top / bottom"),
            ("tab  shift-tab", "next / previous pane"),
            ("1 2 3 4  0", "status, projects, goals, tasks / detail"),
            ("enter", "go into the next pane (or the task you are working on)"),
            ("esc", "back out one pane, or clear a filter"),
            ("[ ]", "Tasks pane: switch Tasks / Ideas / Deliverables"),
            ("/", "filter the focused list"),
            (".", "show done tasks and goals, paused projects"),
        ],
    ),
    (
        "Changing things",
        [
            ("space  x", "toggle done (a todo, a subtask in the detail pane)"),
            ("s", "start (mark doing)"),
            ("w", "work on this task / pause the current session"),
            ("n", "add a note (Updates; a log line on a project)"),
            ("a", "add: task, goal, project, idea, todo, subtask (by pane)"),
            ("e", "open in $EDITOR"),
            ("!", "cycle priority high → med → low"),
            ("t", "set due date (today, +3d, fri, 2026-11-01, none)"),
            ("p", "promote an idea to a task"),
            ("D", "drop (asks first)"),
            ("u", "undo the last change (asks first)"),
        ],
    ),
    (
        "App",
        [
            ("r", "reload now (it also reloads when the repo changes)"),
            ("ctrl-p", "command palette (themes, ...)"),
            ("?", "this help"),
            ("q  ctrl-c", "quit"),
        ],
    ),
]


class Help(ModalScreen[None]):
    DEFAULT_CSS = (
        MODAL_CSS
        + """
    #help { width: 76; max-width: 95%; height: 90%; border: round $accent;
            background: $background; padding: 0 1; }
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,question_mark,enter", "close", show=False),
        Binding("j,down", "scroll(1)", show=False),
        Binding("k,up", "scroll(-1)", show=False),
    ]

    def compose(self) -> ComposeResult:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True, style="bold")
        grid.add_column()
        for title, rows in HELP:
            grid.add_row(Text(title, style="bold underline"), "")
            for keys, what in rows:
                grid.add_row(keys, what)
            grid.add_row("", "")
        with VerticalScroll(id="help") as scroll:
            scroll.border_title = "keys · esc to close"
            yield Static(grid)

    def action_scroll(self, lines: int) -> None:
        self.query_one("#help", VerticalScroll).scroll_relative(y=lines, animate=False)

    def action_close(self) -> None:
        self.dismiss(None)
