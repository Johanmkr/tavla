"""``tavla flow``: a project's goals or a goal's tasks as a dependency board."""

from __future__ import annotations

import itertools
import math
import shutil
from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tavla.cli.common import (
    ContentDirOpt,
    JsonOpt,
    complete_project_or_goal,
    emit_json,
    handles_errors,
    progress,
    state,
)
from tavla.core import flow
from tavla.core.entities import Goal, Project
from tavla.core.flow import Board, Card, CardState
from tavla.core.queries import resolve_id
from tavla.core.store import Content

MARKERS = {
    CardState.DONE: "✓",
    CardState.DOING: "▶",
    CardState.READY: "●",
    CardState.WAITING: "○",
    CardState.BLOCKED: "✗",
    CardState.MISSING: "?",
}
STYLES = {
    CardState.DONE: "dim green",
    CardState.DOING: "bold cyan",
    CardState.READY: "bold green",
    CardState.WAITING: "yellow",
    CardState.BLOCKED: "red",
    CardState.MISSING: "red",
}
ARROW = "──▶"
INTO_GOAL = "══▶"
GAP = len(ARROW) + 2  # arrow column incl. padding
MIN_CARD = 20
MAX_CARD = 34
SPREAD_CARD = 28  # don't split a tall column if cards would get narrower than this
SPREAD_FROM = 3  # only split columns at least this many cards tall
OUTSIDE = "↗"


def resolve_target(content: Content, query: str) -> Project | Goal:
    """A project or goal id (prefix / title substring, like everywhere else)."""
    return resolve_id(query, [*content.projects(), *content.goals()], "project or goal")


# --- layout -------------------------------------------------------------------


def plan_columns(sizes: list[int], width: int, fixed: int = 0) -> tuple[list[int], int] | None:
    """How many side-by-side sub-columns each column of cards gets, and the
    card width; ``fixed`` more single columns follow (the goal). Tall columns
    are split while there is room. None if even one column each won't fit."""
    n = len(sizes) + fixed
    if (width - GAP * (n - 1)) // max(n, 1) < MIN_CARD:
        return None
    splits = [1] * len(sizes)

    def height(i: int) -> int:
        return math.ceil(sizes[i] / splits[i])

    while sizes:
        total = sum(splits) + fixed + 1
        if (width - GAP * (total - 1)) // total < SPREAD_CARD:
            break
        tallest = max(range(len(sizes)), key=height)
        if height(tallest) < SPREAD_FROM:
            break
        splits[tallest] += 1
    total = sum(splits) + fixed
    return splits, min(MAX_CARD, (width - GAP * (total - 1)) // total)


def split(cards: list[Card], parts: int, feeds_next: set[str]) -> list[list[Card]]:
    """Spread one column's cards over ``parts`` sub-columns. Cards that the
    next column depends on go last, next to it, so they can get arrows."""
    ordered = [c for c in cards if c.id not in feeds_next] + [
        c for c in cards if c.id in feeds_next
    ]
    size = math.ceil(len(cards) / parts) if cards else 0
    return [ordered[i * size : (i + 1) * size] for i in range(parts)] if size else [[]]


def arrange(columns: list[list[Card]]) -> tuple[list[dict[int, Card]], set[tuple[str, str]]]:
    """Give each card a row so a prerequisite and its dependent in the next
    column share one where possible; those pairs get an arrow.

    Returns ``{row: card}`` per column and the edges drawn as arrows. Every
    other edge is written as ``after:`` in the dependent's card.
    """
    placed: list[dict[int, Card]] = []
    for cards in columns:
        prev = {c.id: r for r, c in placed[-1].items()} if placed else {}
        rows: dict[int, Card] = {}
        pending = []
        for card in cards:
            wanted = [prev[a] for a in card.after if a in prev and prev[a] not in rows]
            if wanted:
                rows[min(wanted)] = card
            else:
                pending.append(card)
        free = (r for r in range(len(cards) + len(prev) + 1) if r not in rows)
        for card in pending:
            rows[next(free)] = card
        placed.append(rows)
    arrows = {
        (left[r].id, card.id)
        for left, right in itertools.pairwise(placed)
        for r, card in right.items()
        if r in left and left[r].id in card.after
    }
    return placed, arrows


def _line(text: str, style: str = "") -> Text:
    return Text(text, style=style, no_wrap=True, overflow="ellipsis")


def render_card(card: Card, width: int, drawn: set[tuple[str, str]], max_items: int) -> Panel:
    external = card.kind == "external"
    head = Text()  # wraps: the title matters most
    head.append(f"{MARKERS[card.state]} ", style=STYLES[card.state])
    head.append(f"{OUTSIDE} " if external else "", style="dim")
    head.append(card.title, style="dim" if external else "bold")
    lines: list[RenderableType] = [head]

    meta = []
    if external and card.project:
        meta.append(card.project)
    if card.goal:
        meta.append(f"→ {card.goal}")
    if card.priority:
        meta.append(str(card.priority))
    if card.due:
        meta.append(f"due {card.due.isoformat()}")
    if card.total:
        meta.append(progress(card.done, card.total))
    if meta:
        lines.append(Text(" · ".join(meta), style="dim"))  # wraps: dates matter

    shown = card.items if not max_items else card.items[:max_items]
    for item in shown:
        if card.kind == "goal":
            marker, style = MARKERS[item.state], STYLES[item.state]
        else:  # subtasks: plain checkboxes
            done = item.state == CardState.DONE
            marker, style = ("✓", "dim green") if done else ("☐", "")
        row = Text(no_wrap=True, overflow="ellipsis")
        row.append(f"  {marker} ", style=style)
        row.append(item.text, style="dim" if item.state == CardState.DONE else "")
        lines.append(row)
    if len(shown) < len(card.items):
        lines.append(_line(f"  … {len(card.items) - len(shown)} more", "dim"))

    lines += [Text(f"! {w}", style="bold red") for w in card.warnings]  # wraps
    after = [a for a in card.after if (a, card.id) not in drawn]
    if after:
        lines.append(_line(f"after: {', '.join(after)}", "yellow"))

    return Panel(
        Group(*lines),
        title=Text(card.id, style="dim" if external else "bold"),
        title_align="left",
        border_style="dim" if external or card.state == CardState.DONE else STYLES[card.state],
        width=width,
        padding=(0, 1),
    )


def _header(board: Board) -> Text:
    title = Text()
    title.append(f"{board.kind.capitalize()}: ", style="bold")
    title.append(board.title, style="bold")
    title.append(f"  ({board.id})", style="dim")
    if board.by == "status":
        title.append("  by status", style="dim")
    if board.goal and board.goal.total:
        title.append(f"  ▸ {progress(board.goal.done, board.goal.total)} tasks done", style="dim")
    return title


def _legend() -> Text:
    legend = Text(style="dim")
    for state_, marker in MARKERS.items():
        legend.append(f"{marker} ", style=STYLES[state_])
        legend.append(f"{state_.value}   ")
    legend.append(f"{OUTSIDE} elsewhere   ")
    legend.append("! date problem", style="red")
    return legend


def _ready(board: Board) -> Text | None:
    if not board.ready:
        return None
    line = Text()
    line.append("Ready now: ", style="bold")
    for i, item in enumerate(board.ready):
        line.append("  " if i else "")
        line.append(f"{MARKERS[item.state]} ", style=STYLES[item.state])
        line.append(item.id or item.text)
    return line


def _footer(board: Board) -> list[RenderableType]:
    ready = _ready(board)
    return [*([ready] if ready else []), _legend()]


def _label(board: Board, col: flow.Column) -> str:
    if board.by == "stage":
        return col.label.upper()
    return f"{col.label.upper()} ({len(col.cards)})"


def render(board: Board, width: int, max_items: int) -> RenderableType:
    """The board as columns (stages or statuses), or stacked if too narrow.
    Only stage boards get arrows; their columns are ordered by dependency."""
    plan = plan_columns([len(s) for s in board.stages], width, fixed=board.goal is not None)
    if plan is None:
        return _render_stacked(board, min(width, 60), max_items)
    splits, card_w = plan

    columns: list[list[Card]] = []
    headers: list[str] = []
    by_stage = board.by == "stage"
    for i, (col, parts) in enumerate(zip(board.columns, splits, strict=True)):
        following = board.stages[i + 1] if by_stage and i + 1 < len(board.stages) else []
        feeds_next = {a for c in following for a in c.after}
        for sub in split(col.cards, parts, feeds_next):
            columns.append(sub)
            headers.append(_label(board, col))
    placed, drawn = arrange(columns)
    if not by_stage:
        drawn = set()

    grid = Table.grid(padding=0)
    for i in range(len(placed) + (board.goal is not None)):
        if i:
            grid.add_column(width=GAP, justify="center")
        grid.add_column(width=card_w)
    head_cells: list[RenderableType] = []
    for i, h in enumerate([*headers, *(["GOAL"] if board.goal else [])]):
        head_cells += [""] if i else []
        head_cells.append(Text(h, style="bold dim"))
    grid.add_row(*head_cells)

    n_rows = max((max(c) + 1 for c in placed if c), default=0)
    # The goal sits beside the first card of the last stage, which feeds it.
    goal_row = min(placed[-1]) if placed and placed[-1] else 0
    for r in range(max(n_rows, 1 if board.goal else 0)):
        cells: list[RenderableType] = []
        for i, col in enumerate(placed):
            if i:
                left, right = placed[i - 1].get(r), col.get(r)
                linked = left and right and (left.id, right.id) in drawn
                cells.append(Text(f"\n{ARROW}") if linked else "")
            card = col.get(r)
            cells.append(render_card(card, card_w, drawn, max_items) if card else "")
        if board.goal:
            if r == goal_row:
                arrow = Text(f"\n{INTO_GOAL}") if placed and r in placed[-1] else ""
                cells += [arrow, render_card(board.goal, card_w, drawn, 0)]
            else:
                cells += ["", ""]
        grid.add_row(*cells)
    return Group(_header(board), Text(), grid, *_footer(board))


def _render_stacked(board: Board, width: int, max_items: int) -> RenderableType:
    parts: list[RenderableType] = [_header(board)]
    for col in board.columns:
        parts.append(Text(f"\n{_label(board, col)}", style="bold dim"))
        parts += [render_card(c, width, set(), max_items) for c in col.cards]
    if board.goal:
        parts.append(Text("\nGOAL", style="bold dim"))
        parts.append(render_card(board.goal, width, set(), 0))
    parts += _footer(board)
    return Group(*parts)


# --- mermaid ------------------------------------------------------------------

# Stroke colours only, so the diagram reads on light and dark backgrounds.
MERMAID_CLASSES = {
    CardState.DONE: "stroke:#2e7d32,color:#888",
    CardState.DOING: "stroke:#0288d1,stroke-width:3px",
    CardState.READY: "stroke:#43a047,stroke-width:3px",
    CardState.WAITING: "stroke:#f9a825",
    CardState.BLOCKED: "stroke:#e53935,stroke-width:3px",
    CardState.MISSING: "stroke:#e53935,stroke-dasharray:4",
}


def _mermaid_text(text: str) -> str:
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def to_mermaid(board: Board) -> str:
    """The board as a Mermaid flowchart: columns as subgraphs, every
    dependency an edge (dotted into the goal of a goal board)."""
    names: dict[str, str] = {}

    def node(card: Card) -> str:
        name = names.setdefault(card.id, f"n{len(names)}")
        label = f"{MARKERS[card.state]} {card.title}"
        details = [f"due {card.due.isoformat()}"] if card.due else []
        if card.total:
            details.append(progress(card.done, card.total))
        if card.warnings:
            details.append("⚠ " + "; ".join(card.warnings))
        if card.kind == "external":
            details.append(f"{OUTSIDE} {card.project or 'missing'}")
        text = "<br/>".join(_mermaid_text(x) for x in [label, *details])
        return f'{name}["{text}"]'

    title = f"{board.kind.capitalize()}: {board.title}"
    quoted = title.replace("\\", "").replace('"', "'")
    lines = ["---", f'title: "{quoted}"', "---", "flowchart LR"]
    for n, col in enumerate(board.columns):
        label = col.label if board.by == "stage" else col.label.capitalize()
        lines.append(f'  subgraph c{n}["{label}"]')
        lines.append("    direction TB")
        lines += [f"    {node(c)}" for c in col.cards]
        lines.append("  end")
    if board.goal:
        lines.append(f"  {node(board.goal)}")
    for a, b in board.edges():
        if a in names and b in names:
            lines.append(f"  {names[a]} --> {names[b]}")
    if board.goal:
        feeding = {a for a, _ in board.edges()}
        for c in board.cards():
            if c.id not in feeding and c.kind != "external":
                lines.append(f"  {names[c.id]} -.-> {names[board.goal.id]}")
    cards = [*board.cards(), *([board.goal] if board.goal else [])]
    for state_, style in MERMAID_CLASSES.items():
        members = [names[c.id] for c in cards if c.state == state_]
        if members:
            lines.append(f"  classDef st_{state_.value} {style}")
            lines.append(f"  class {','.join(members)} st_{state_.value}")
    return "\n".join(lines)


# --- command ------------------------------------------------------------------


class By(StrEnum):
    STAGE = "stage"
    STATUS = "status"


class Format(StrEnum):
    TEXT = "text"
    MERMAID = "mermaid"


@handles_errors
def flow_(
    ctx: typer.Context,
    target: Annotated[
        str,
        typer.Argument(
            metavar="PROJECT|GOAL",
            help="A project (its goals) or a goal (its tasks).",
            autocompletion=complete_project_or_goal,
        ),
    ],
    open_only: Annotated[
        bool, typer.Option("--open", "-o", help="Hide finished goals, tasks and subtasks.")
    ] = False,
    items: Annotated[
        int, typer.Option("--items", "-n", min=0, help="Max lines per card (0 = all).")
    ] = 6,
    width: Annotated[
        int | None,
        typer.Option("--width", "-w", min=20, help="Board width (default: terminal width)."),
    ] = None,
    by: Annotated[
        By,
        typer.Option("--by", help="Columns: dependency stages, or task status (a kanban board)."),
    ] = By.STAGE,
    fmt: Annotated[
        Format,
        typer.Option("--format", "-f", help="text (the board), or mermaid (a flowchart)."),
    ] = Format.TEXT,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Dependency board: what can happen in parallel and what has to wait.

    Items are grouped into stages: everything in a stage only depends on
    earlier stages. For a project the cards are its goals (ordered by task
    dependencies across goals) with their tasks; for a goal the cards are its
    tasks with their subtasks. An arrow links a card to one it unblocks;
    other dependencies are listed as "after:" in the card.

    With --by status, the tasks go in todo / doing / blocked / done columns
    instead (a kanban board); "after:" then lists unfinished prerequisites.
    --format mermaid prints the board as a Mermaid flowchart, for notes,
    GitHub issues or anything else that renders Mermaid.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    item = resolve_target(content, target)
    if by == By.STATUS:
        board = flow.status_board(content, item, open_only=open_only)
    elif isinstance(item, Goal):
        board = flow.goal_board(content, item, open_only=open_only)
    else:
        board = flow.project_board(content, item, open_only=open_only)

    if st.json:
        emit_json(board)
        return
    if fmt == Format.MERMAID:
        typer.echo(to_mermaid(board))
        return
    if not board.cards() and board.goal is None:
        typer.echo(f"No goals or tasks in {board.id}.")
        return
    width = width or shutil.get_terminal_size().columns
    Console(width=width, highlight=False).print(render(board, width, items))
