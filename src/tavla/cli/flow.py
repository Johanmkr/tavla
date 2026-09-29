"""``tavla flow``: a project's goals or a goal's tasks as a dependency board."""

from __future__ import annotations

import itertools
import shutil
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
    CardState.READY: "●",
    CardState.WAITING: "○",
    CardState.BLOCKED: "✗",
    CardState.MISSING: "?",
}
STYLES = {
    CardState.DONE: "dim green",
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
OUTSIDE = "↗"


def resolve_target(content: Content, query: str) -> Project | Goal:
    """A project or goal id (prefix / title substring, like everywhere else)."""
    return resolve_id(query, [*content.projects(), *content.goals()], "project or goal")


# --- layout -------------------------------------------------------------------


def arrange(board: Board) -> tuple[list[dict[int, Card]], set[tuple[str, str]]]:
    """Give each card a row so a prerequisite and its dependent in the next
    stage share one where possible; those pairs get an arrow.

    Returns ``{row: card}`` per stage and the edges drawn as arrows. Every
    other edge is written as ``after:`` in the dependent's card.
    """
    columns: list[dict[int, Card]] = []
    for stage in board.stages:
        prev = {c.id: r for r, c in columns[-1].items()} if columns else {}
        rows: dict[int, Card] = {}
        pending = []
        for card in stage:
            wanted = [prev[a] for a in card.after if a in prev and prev[a] not in rows]
            if wanted:
                rows[min(wanted)] = card
            else:
                pending.append(card)
        free = (r for r in range(len(stage) + len(prev) + 1) if r not in rows)
        for card in pending:
            rows[next(free)] = card
        columns.append(rows)
    arrows = {
        (left[r].id, card.id)
        for left, right in itertools.pairwise(columns)
        for r, card in right.items()
        if r in left and left[r].id in card.after
    }
    return columns, arrows


def _line(text: str, style: str = "") -> Text:
    return Text(text, style=style, no_wrap=True, overflow="ellipsis")


def render_card(card: Card, width: int, drawn: set[tuple[str, str]], max_items: int) -> Panel:
    external = card.kind == "external"
    head = Text(no_wrap=True, overflow="ellipsis")
    head.append(f"{MARKERS[card.state]} ", style=STYLES[card.state])
    head.append(f"{OUTSIDE} " if external else "", style="dim")
    head.append(card.title, style="dim" if external else "bold")
    lines: list[RenderableType] = [head]

    meta = []
    if external and card.project:
        meta.append(card.project)
    if card.priority:
        meta.append(str(card.priority))
    if card.due:
        meta.append(f"due {card.due.isoformat()}")
    if card.total:
        meta.append(progress(card.done, card.total))
    if meta:
        lines.append(_line(" · ".join(meta), "dim"))

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
    if board.goal and board.goal.total:
        title.append(f"  ▸ {progress(board.goal.done, board.goal.total)} tasks done", style="dim")
    return title


def _legend() -> Text:
    legend = Text(style="dim")
    names = {CardState.WAITING: "waiting on others"}
    for state_, marker in MARKERS.items():
        legend.append(f"{marker} ", style=STYLES[state_])
        legend.append(f"{names.get(state_, state_.value)}   ")
    legend.append(f"{OUTSIDE} outside this board")
    return legend


def render(board: Board, width: int, max_items: int) -> RenderableType:
    """The board as stage columns, or stacked stages if too narrow."""
    n = len(board.stages) + (board.goal is not None)
    card_w = min(MAX_CARD, (width - GAP * (n - 1)) // max(n, 1))
    if card_w < MIN_CARD:
        return _render_stacked(board, min(width, 60), max_items)

    columns, drawn = arrange(board)
    grid = Table.grid(padding=0)
    for i in range(len(columns)):
        if i:
            grid.add_column(width=GAP, justify="center")
        grid.add_column(width=card_w)
    if board.goal:
        grid.add_column(width=GAP, justify="center")
        grid.add_column(width=card_w)

    headers: list[RenderableType] = []
    for i in range(len(columns)):
        if i:
            headers.append("")
        headers.append(Text(f"STAGE {i + 1}", style="bold dim"))
    if board.goal:
        headers += ["", Text("GOAL", style="bold dim")]
    grid.add_row(*headers)

    n_rows = max((max(c) + 1 for c in columns if c), default=0)
    for r in range(max(n_rows, 1 if board.goal else 0)):
        cells: list[RenderableType] = []
        for i, col in enumerate(columns):
            if i:
                left, right = columns[i - 1].get(r), col.get(r)
                linked = left and right and (left.id, right.id) in drawn
                cells.append(Text(f"\n{ARROW}") if linked else "")
            card = col.get(r)
            cells.append(render_card(card, card_w, drawn, max_items) if card else "")
        if board.goal:
            if r == 0:
                cells += [Text(f"\n{INTO_GOAL}"), render_card(board.goal, card_w, drawn, 0)]
            else:
                cells += ["", ""]
        grid.add_row(*cells)
    return Group(_header(board), Text(), grid, _legend())


def _render_stacked(board: Board, width: int, max_items: int) -> RenderableType:
    parts: list[RenderableType] = [_header(board)]
    for i, stage in enumerate(board.stages):
        parts.append(Text(f"\nSTAGE {i + 1}", style="bold dim"))
        parts += [render_card(c, width, set(), max_items) for c in stage]
    if board.goal:
        parts.append(Text("\nGOAL", style="bold dim"))
        parts.append(render_card(board.goal, width, set(), 0))
    parts.append(_legend())
    return Group(*parts)


# --- command ------------------------------------------------------------------


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
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Dependency board: what can happen in parallel and what has to wait.

    Items are grouped into stages: everything in a stage only depends on
    earlier stages. For a project the cards are its goals (ordered by task
    dependencies across goals) with their tasks; for a goal the cards are its
    tasks with their subtasks. An arrow links a card to one it unblocks;
    other dependencies are listed as "after:" in the card.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    item = resolve_target(content, target)
    if isinstance(item, Goal):
        board = flow.goal_board(content, item, open_only=open_only)
    else:
        board = flow.project_board(content, item, open_only=open_only)

    if st.json:
        emit_json(board)
        return
    if not board.stages and board.goal is None:
        typer.echo(f"No goals or tasks in {board.id}.")
        return
    width = width or shutil.get_terminal_size().columns
    Console(width=width, highlight=False).print(render(board, width, items))
