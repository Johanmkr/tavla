"""Modal screens: a one-line prompt, a picker, a yes/no confirmation, inbox
triage, a read-only list, the full-screen flow board, and the key help."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, ClassVar

from rich.segment import Segment
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from tavla.core import inbox
from tavla.core.store import Content
from tavla.tui.model import Line

MODAL_CSS = """
ModalScreen { align: center middle; background: transparent; }
#dialog {
    width: 70%; max-width: 80; min-width: 36; height: auto;
    border: round $accent; padding: 0 1; background: $background;
}
#dialog Input { border: none; height: 1; padding: 0; background: $background; }
#dialog .hint { color: $text-muted; }
#dialog OptionList {
    border: none; background: $background; height: auto; max-height: 70vh;
    scrollbar-size-vertical: 1;
}
#choices { text-wrap: nowrap; text-overflow: ellipsis; }
#dialog OptionList > .option-list--option-highlighted {
    background: $background; color: $foreground; text-style: reverse bold;
}
#dialog OptionList > .option-list--option-hover { background: $background; }
#dialog BarList > .bar-list--bar { color: $accent; background: $background; text-style: bold; }
"""


class BarList(OptionList):
    """An option list whose selected row also has a bar in a one-cell left
    gutter, so the row you are on stands out more than reverse video alone
    (the accent colour where the list has focus, dim elsewhere: see the CSS)."""

    COMPONENT_CLASSES: ClassVar[set[str]] = {"bar-list--bar"}
    BAR = "▌"

    def _get_left_gutter_width(self) -> int:
        return len(self.BAR)

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        try:
            index, _ = self._lines[self.scroll_offset.y + y]
        except IndexError:
            return strip  # below the last row: already full width
        if index == self.highlighted and not self.options[index].disabled:
            gutter = Segment(self.BAR, self.get_component_rich_style("bar-list--bar"))
        else:
            gutter = Segment(" ")
        return Strip([gutter, *strip], strip.cell_length + 1)


class Prompt(ModalScreen[str | None]):
    """Ask for one line of text. Enter submits, Esc cancels (returns None)."""

    DEFAULT_CSS = MODAL_CSS
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, question: str, value: str = "", hint: str = "") -> None:
        super().__init__()
        self.question, self.value, self.hint = question, value, hint

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(self.question, style="bold"))
            yield Input(value=self.value)
            yield Label(self.hint or "enter ok · esc cancel", classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Picker(ModalScreen[str | None]):
    """Choose one of ``options`` — ``(key, label)`` pairs, or ``(key, label,
    also)`` where ``also`` is more text the filter matches (a subproject's
    parent) — or Esc for None. Typing filters the list."""

    DEFAULT_CSS = MODAL_CSS
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("down,ctrl+n", "cursor_down", show=False, priority=True),
        Binding("up,ctrl+p", "cursor_up", show=False, priority=True),
        Binding("pagedown", "page_down", show=False, priority=True),
        Binding("pageup", "page_up", show=False, priority=True),
    ]

    def __init__(self, question: str, options: Sequence[tuple[str, ...]]) -> None:
        super().__init__()
        self.question, self.options = question, list(options)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(self.question, style="bold"))
            yield Input(placeholder="type to filter", id="filter")
            yield BarList(id="choices")
            yield Label("↑ ↓ move · enter choose · esc clear / cancel", classes="hint")

    def on_mount(self) -> None:
        self.choices.can_focus = False  # typing always goes to the filter
        self.refill("")
        self.query_one("#filter", Input).focus()

    @property
    def choices(self) -> BarList:
        return self.query_one("#choices", BarList)

    def matching(self, text: str) -> list[tuple[str, str]]:
        """The options with every word of ``text`` in their key, label or
        extra text, ignoring case."""
        words = text.lower().split()
        return [
            (option[0], option[1])
            for option in self.options
            if all(w in " ".join(option).lower() for w in words)
        ]

    def refill(self, text: str) -> None:
        choices = self.choices
        shown = self.matching(text)
        choices.clear_options()
        if shown:
            choices.add_options([Option(label, id=key) for key, label in shown])
            choices.highlighted = 0
        else:
            choices.add_option(Option(Text("nothing matches", style="dim italic"), disabled=True))

    def on_input_changed(self, event: Input.Changed) -> None:
        self.refill(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        option = self.choices.highlighted_option
        if option is not None and not option.disabled:
            self.dismiss(str(option.id))

    def action_cursor_down(self) -> None:
        self.choices.action_cursor_down()

    def action_cursor_up(self) -> None:
        self.choices.action_cursor_up()

    def action_page_down(self) -> None:
        self.choices.action_page_down()

    def action_page_up(self) -> None:
        self.choices.action_page_up()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    def action_cancel(self) -> None:
        """Esc clears the filter first, then closes."""
        typed = self.query_one("#filter", Input)
        if typed.value:
            typed.value = ""
        else:
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


class Triage(ModalScreen[None]):
    """Empty the inbox one item at a time, one kind per pass: chores, then
    ideas, then (when asked) the ideas filed under projects. Each key decides
    the item on the card; the app does the asking and the writing
    (``decide``) and calls :meth:`load` when the change has landed."""

    DEFAULT_CSS = MODAL_CSS
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q", "close", show=False),
        Binding("t", "decide('task')", show=False),
        Binding("g", "decide('goal')", show=False),
        Binding("P", "decide('project')", show=False),
        Binding("s", "decide('subtask')", show=False),
        Binding("l", "decide('later')", show=False),
        Binding("x", "decide('finish')", show=False),
        Binding("D", "decide('drop')", show=False),
        Binding("n,j,down", "skip(1)", show=False),
        Binding("b,k,up", "skip(-1)", show=False),
        Binding("enter", "next_pass", show=False),
        Binding("u", "undo", show=False),
        Binding("c", "switch('todo')", show=False),
        Binding("i", "switch('idea')", show=False),
        Binding("f", "switch('filed')", show=False),
    ]
    KEYS = (
        "t task   g goal   P project   s subtask\n"
        "l later: file under a project or goal\n"
        "x done already   D drop   n skip   b back   u undo   esc close"
    )
    FILED_KEYS = (
        "t task   g goal   P project   s subtask\n"
        "l move to another project or goal\n"
        "x done already   D drop   n keep   b back   u undo   esc close"
    )

    def __init__(
        self,
        root: Path,
        kind: str,
        decide: Callable[[Triage, str, inbox.Item], None],
    ) -> None:
        super().__init__()
        self.root, self.kind, self.decide = root, kind, decide
        self.index = 0
        self.busy = False  # a decision is being written: keys wait
        self.items: list[inbox.Item] = []
        self.counts: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(id="card")

    def on_mount(self) -> None:
        self.load()

    @property
    def current(self) -> inbox.Item | None:
        return self.items[self.index] if 0 <= self.index < len(self.items) else None

    def load(self) -> None:
        """Re-read the items (a decision landed, or the pass changed); the
        cursor stays at its position, which is now the next item."""
        content = Content.open(self.root)
        self.items = inbox.items(content, self.kind)
        self.counts = inbox.counts(content)
        self.index = min(self.index, max(len(self.items) - 1, 0))
        self.busy = False
        self.query_one("#card", Static).update(self.card())

    def next_kind(self) -> str | None:
        """The pass to offer when this one is through."""
        later = inbox.KINDS[inbox.KINDS.index(self.kind) + 1 :]
        return next((k for k in later if self.counts.get(k)), None)

    def passes(self) -> Text:
        """``c chores 2 · i ideas 3 · f filed 6``: the passes and their keys,
        this one in bold."""
        out = Text()
        for n, (key, kind) in enumerate((("c", "todo"), ("i", "idea"), ("f", "filed"))):
            if n:
                out.append(" · ", style="dim")
            label = f"{key} {inbox.NAMES[kind].split()[0]} {self.counts.get(kind, 0)}"
            out.append(label, style="bold reverse" if kind == self.kind else "dim")
        return out

    def card(self) -> Text:
        text = self.passes()
        text.append("\n\n")
        text.append_text(self.body())
        return text

    def body(self) -> Text:
        name = inbox.NAMES[self.kind].capitalize()
        item = self.current
        if item is None:
            text = Text.assemble((f"{name}: nothing left ✓", "bold green"), "\n\n")
            following = self.next_kind()
            if following is not None:
                n = self.counts[following]
                text.append(f"enter: go through the {inbox.NAMES[following]} ({n})\n")
            text.append("esc close", style="dim")
            return text
        text = Text.assemble(
            (f"{name} · {self.index + 1} of {len(self.items)}", "bold"),
            "\n\n",
            (item.text, "bold"),
            "\n",
            (f"from {item.where}", "dim"),
            "\n\n",
            (self.FILED_KEYS if self.kind == "filed" else self.KEYS, "dim"),
        )
        return text

    def action_decide(self, action: str) -> None:
        item = self.current
        if item is None or self.busy:
            return
        self.decide(self, action, item)

    def action_skip(self, step: int) -> None:
        if self.items and not self.busy:
            self.index = (self.index + step) % len(self.items)
            self.query_one("#card", Static).update(self.card())

    def action_switch(self, kind: str) -> None:
        if kind != self.kind and not self.busy:
            self.kind, self.index = kind, 0
            self.load()

    def action_next_pass(self) -> None:
        following = self.next_kind() if self.current is None else None
        if following is not None:
            self.kind, self.index = following, 0
            self.load()

    def action_undo(self) -> None:
        if not self.busy:
            self.app.run_action("undo")

    def action_close(self) -> None:
        self.dismiss(None)


class ListScreen(ModalScreen[None]):
    """A read-only, scrollable list of lines (people, warnings, notes)."""

    DEFAULT_CSS = (
        MODAL_CSS
        + """
    #list { width: 80; max-width: 95%; height: 80%; border: round $accent;
            background: $background; padding: 0 1; }
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,enter", "close", show=False),
        Binding("j,down", "scroll(1)", show=False),
        Binding("k,up", "scroll(-1)", show=False),
        Binding("ctrl+d", "scroll(10)", show=False),
        Binding("ctrl+u", "scroll(-10)", show=False),
    ]

    def __init__(self, title: str, lines: list[Any]) -> None:
        super().__init__()
        self.title, self.lines = title, lines

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="list") as scroll:
            scroll.border_title = f"{self.title} · esc to close"
            yield Static(Table.grid() if not self.lines else _stack(self.lines))

    def action_scroll(self, lines: int) -> None:
        self.query_one("#list", VerticalScroll).scroll_relative(y=lines, animate=False)

    def action_close(self) -> None:
        self.dismiss(None)


def _stack(lines: list[Any]) -> Any:
    from rich.console import Group

    return Group(*lines)


class FlowScreen(ModalScreen[str | None]):
    """The flow board, full screen: stages, or the same cards by status.

    ``f`` toggles between the two; ``enter`` on a card returns its id so the
    app can jump into the hierarchy at that item."""

    DEFAULT_CSS = (
        MODAL_CSS
        + """
    #board { width: 100%; height: 100%; border: none; background: $background;
             padding: 0 1; }
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q", "close", show=False),
        Binding("f", "toggle", show=False),
        Binding("enter", "select", show=False),
        Binding("j,down", "scroll(1)", show=False),
        Binding("k,up", "scroll(-1)", show=False),
        Binding("ctrl+d", "scroll(10)", show=False),
        Binding("ctrl+u", "scroll(-10)", show=False),
        Binding("ctrl+f", "scroll(20)", show=False),
        Binding("ctrl+b", "scroll(-20)", show=False),
        Binding("g", "home", show=False),
        Binding("G", "end", show=False),
    ]

    def __init__(
        self,
        title: str,
        build: dict[str, Callable[[int], list[Line]]],
        *,
        view: str = "stage",
    ) -> None:
        super().__init__()
        self.title, self.build, self.view = title, build, view
        self.lines: list[Line] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="board") as scroll:
            scroll.border_title = self._legend()
            yield Static(id="cards")

    def _legend(self) -> str:
        return f"{self.title} · f {'by status' if self.view == 'stage' else 'by stage'} · esc close"

    def on_mount(self) -> None:
        self.render_board()

    def render_board(self) -> None:
        width = max(self.size.width - 6, 40)
        self.lines = self.build[self.view](width)
        self.query_one("#cards", Static).update(_stack([line.prompt for line in self.lines]))
        self.query_one("#board", VerticalScroll).border_title = self._legend()
        self.query_one("#board", VerticalScroll).scroll_home(animate=False)

    def action_toggle(self) -> None:
        self.view = "status" if self.view == "stage" else "stage"
        self.render_board()

    def action_select(self) -> None:
        """Return the card at the top of the viewport, so `enter` is predictable."""
        scroll = self.query_one("#board", VerticalScroll)
        top = scroll.scroll_offset.y
        card = next((line.card for line in self.lines[top:] if line.card), None)
        self.dismiss(card)

    def action_scroll(self, lines: int) -> None:
        self.query_one("#board", VerticalScroll).scroll_relative(y=lines, animate=False)

    def action_home(self) -> None:
        self.query_one("#board", VerticalScroll).scroll_home(animate=False)

    def action_end(self) -> None:
        self.query_one("#board", VerticalScroll).scroll_end(animate=False)

    def action_close(self) -> None:
        self.dismiss(None)


HELP = [
    (
        "Moving around (vim motions)",
        [
            ("h l  ← →", "one column left / right"),
            ("j k  ↑ ↓", "one row down / up"),
            ("g  G", "first / last row"),
            ("ctrl-d  ctrl-u", "half page down / up"),
            ("ctrl-f  ctrl-b", "full page down / up"),
            ("H  M  L", "viewport top / middle / end"),
            ("enter", "into the next column (a task opens its preview)"),
            ("esc", "one column back · clear the filter · leave the preview"),
            ("tab  shift-tab", "next / previous scope"),
            ("1 2 3 4", "project · next · inbox · agenda"),
        ],
    ),
    (
        "Changing things",
        [
            ("space", "done (an idea: done already, so it is removed; a deliverable: its status)"),
            ("x", "reopen"),
            ("s", "start (mark doing)"),
            ("w", "work on this task; again to pause"),
            ("W", "open in a terminal of its own (a subtask in the preview); closing = done"),
            ("o  O", "add here  /  one level up (project, goal, task, idea)"),
            ("n", "note (## Updates; a log line on a project)"),
            ("c  C", "capture an idea into the inbox / a chore into todo.md, from anywhere"),
            ("R", "rename: a new title, the id stays"),
            ("y", "copy the id (an idea's scope:N, a todo's number) for the CLI"),
            ("e", "open in $EDITOR: validated and committed on return"),
            ("t", "due date / deadline (today, +3d, fri, 2026-11-01, none)"),
            ("!", "cycle priority high → med → low"),
            ("m", "move to another project or goal"),
            ("p", "promote an idea or chore to a task (inbox)"),
            ("T", "triage: go through chores, then ideas, one at a time"),
            ("D", "drop (asks first; refused while other tasks depend on it)"),
            ("u", "undo the last change (asks, and names it)"),
            ("J  K", "move the row down / up (writes `order:`)"),
            ("a  A", "add / remove an `after` dependency (picked from the list)"),
            ("@a  @d  @m  @l", "people: add · remove · mail · list"),
        ],
    ),
    (
        "What the symbols mean",
        [
            ("●", "ready: can be started now"),
            ("▶", "doing (in the header: the task you are working on)"),
            ("○", "waiting on tasks that aren't done (`after`)"),
            ("✗", "blocked (status)"),
            ("✓", "done"),
            ("[ ]  [x]", "subtask open / ticked"),
            ("◆", "deliverable"),
            ("☾", "project with no activity for a while (stale)"),
            ("⏸  ▪", "project paused / archived"),
            ("▣", "open task terminals (`W`)"),
            ("·", "idea"),
        ],
    ),
    (
        "Seeing",
        [
            ("v", "mark a row; j/k extend, space and friends then act on all marks"),
            ("V", "mark the whole column · with nothing marked: show done and paused"),
            ("/", "filter every column at once (esc clears)"),
            ("i", "next item behind the header's alerts: overdue, blocked, stale"),
            ("f", "flow board, full screen (f again: by status, enter: jump to a card)"),
            ("P", "pick the project (every picker filters as you type)"),
            ("r", "reload now (it also reloads when the repo changes)"),
            ("ctrl-p", "command palette (themes, …)"),
            ("?  q  ctrl-c", "this help · quit"),
        ],
    ),
    (
        "Deliberate departures from vim",
        [
            ("space", "done — not the leader key"),
            ("w", "work on the task — vim: next word"),
            ("n", "note — vim: next match"),
            ("x", "reopen — vim: delete a character"),
            ("c", "capture — vim: change"),
            ("g", "top of the row list — vim says gg, but Textual has no key chords"),
            ("P", "pick the project — vim: paste before the cursor"),
        ],
    ),
    (
        "How changes are recorded",
        [
            ("", "Each marked row is its own commit, so `u` takes bulk changes"),
            ("", "back one item at a time; everything else is one commit."),
            ("", "Only `D`, `u`, and a verb over more than three marked rows ask."),
        ],
    ),
]


def _split_hint(hint: str) -> tuple[str, str, str]:
    """``J K order`` -> ``("J K", " ", "order")``: the keys are the leading
    words that aren't plain lowercase words (``space`` and ``esc`` count as keys)."""
    words = hint.split()
    n = 0
    while n < len(words) - 1 and (
        len(words[n]) == 1 or words[n] in ("space", "esc", "enter", "tab") or not words[n].isalpha()
    ):
        n += 1
    n = max(n, 1)
    return " ".join(words[:n]), " ", " ".join(words[n:])


class Help(ModalScreen[None]):
    DEFAULT_CSS = (
        MODAL_CSS
        + """
    #help { width: 84; max-width: 95%; height: 90%; border: round $accent;
            background: $background; padding: 0 1; }
    """
    )
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,question_mark,enter", "close", show=False),
        Binding("j,down", "scroll(1)", show=False),
        Binding("k,up", "scroll(-1)", show=False),
        Binding("ctrl+d", "page(0.5)", show=False),
        Binding("ctrl+u", "page(-0.5)", show=False),
        Binding("ctrl+f,pagedown,space", "page(1)", show=False),
        Binding("ctrl+b,pageup", "page(-1)", show=False),
        Binding("g,home", "edge(False)", show=False),
        Binding("G,end", "edge(True)", show=False),
    ]

    def __init__(self, here: str = "") -> None:
        super().__init__()
        self.here = here  # the hint line where `?` was pressed

    def compose(self) -> ComposeResult:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True, style="bold")
        grid.add_column()
        if self.here:
            grid.add_row(Text("Where you are", style="bold underline"), "")
            for hint in self.here.split("  "):
                if hint.strip():
                    keys, _, what = _split_hint(hint.strip())
                    grid.add_row(keys, what)
            grid.add_row("", "")
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

    def action_page(self, pages: float) -> None:
        scroll = self.query_one("#help", VerticalScroll)
        scroll.scroll_relative(y=int(scroll.size.height * pages), animate=False)

    def action_edge(self, end: bool) -> None:
        scroll = self.query_one("#help", VerticalScroll)
        scroll.scroll_end(animate=False) if end else scroll.scroll_home(animate=False)

    def action_close(self) -> None:
        self.dismiss(None)
