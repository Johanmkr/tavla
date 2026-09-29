from __future__ import annotations

import datetime as dt
import json

import pytest
from typer.testing import CliRunner

from tavla.cli.flow import arrange, plan_columns, split
from tavla.cli.main import app
from tavla.core import flow
from tavla.core.flow import CardState
from tavla.core.store import Content

runner = CliRunner()
TODAY = dt.date(2026, 9, 25)


def ids(board: flow.Board) -> list[list[str]]:
    return [[c.id for c in stage] for stage in board.stages]


# --- stages -------------------------------------------------------------------


def test_stages_chain_and_parallel():
    after = {"b": ["a"], "c": ["a"], "d": ["b", "c"]}
    assert flow.stages("abcd", after) == [["a"], ["b", "c"], ["d"]]


def test_stages_longest_path_wins():
    # d depends on a directly and via b -> c, so it goes after c.
    after = {"b": ["a"], "c": ["b"], "d": ["a", "c"]}
    assert flow.stages("abcd", after) == [["a"], ["b"], ["c"], ["d"]]


def test_stages_ignore_unknown_and_self():
    assert flow.stages(["a", "b"], {"a": ["zzz", "a"], "b": ["a"]}) == [["a"], ["b"]]


def test_stages_cycle_shares_a_stage():
    after = {"a": ["b"], "b": ["a"], "c": ["b"], "x": []}
    assert flow.stages(["a", "b", "c", "x"], after) == [["a", "b", "x"], ["c"]]


def test_stages_empty():
    assert flow.stages([], {}) == []


# --- boards -------------------------------------------------------------------


def write_task(
    root,
    id_,
    *,
    goal=None,
    depends_on=(),
    status="todo",
    subtasks=(),
    project="project-a",
    due=None,
):
    lines = ["---", f"id: {id_}", f"status: {status}"]
    if due:
        lines.append(f"due: {due}")
    if goal:
        lines.append(f"goal: {goal}")
    if depends_on:
        lines.append(f"depends_on: [{', '.join(depends_on)}]")
    lines += ["---", "", f"# {id_.replace('-', ' ').capitalize()}", "", "## Subtasks"]
    lines += [f"- [{'x' if done else ' '}] {text}" for text, done in subtasks]
    (root / "projects" / project / "tasks" / f"{id_}.md").write_text("\n".join(lines) + "\n")


@pytest.fixture
def content(content_copy):
    # write-methods waits on the advisor feedback (write-intro), making the
    # goals sequential.
    write_task(
        content_copy,
        "describe-sampler",
        goal="write-methods",
        depends_on=["get-feedback-from-advisor"],
        subtasks=[("Pseudocode", True), ("Complexity", False)],
    )
    return Content.open(content_copy)


def test_goal_board_stages(content):
    board = flow.goal_board(content, content.goal("write-intro"))
    assert ids(board) == [
        ["draft-related-work", "outline-structure"],
        ["get-feedback-from-advisor"],
    ]
    assert board.goal.id == "write-intro"
    draft = board.stages[0][0]
    assert draft.state == CardState.READY
    assert [(i.text, i.state) for i in draft.items] == [
        ("Collect MCMC papers", CardState.DONE),
        ("Write two paragraphs", CardState.READY),
    ]
    assert board.stages[1][0].state == CardState.WAITING


def test_goal_board_shows_outside_prerequisites(content):
    board = flow.goal_board(content, content.goal("write-methods"))
    assert ids(board) == [["get-feedback-from-advisor"], ["describe-sampler"]]
    outside = board.stages[0][0]
    assert outside.kind == "external"
    assert outside.project == "project-a"


def test_goal_board_open_only_hides_done(content):
    board = flow.goal_board(content, content.goal("write-intro"), open_only=True)
    assert ids(board) == [["draft-related-work"], ["get-feedback-from-advisor"]]
    assert [i.text for i in board.stages[0][0].items] == ["Write two paragraphs"]


def test_project_board_orders_goals_by_task_deps(content):
    board = flow.project_board(content, content.project("project-a"))
    stages = ids(board)
    assert stages[1] == ["write-methods"]
    assert "write-intro" in stages[0]
    methods = board.stages[1][0]
    assert methods.after == ["write-intro"]
    intro = next(c for c in board.stages[0] if c.id == "write-intro")
    # Tasks inside a goal card are listed in dependency order.
    assert [i.id for i in intro.items][-1] == "get-feedback-from-advisor"
    # Loose tasks get a card of their own; subproject goals are included.
    assert {"fix-plot-colors", "run-ablations"} <= {c.id for c in board.cards()}


def test_project_board_cycle_between_goals(content_copy):
    write_task(content_copy, "m1", goal="write-methods")
    write_task(content_copy, "i1", goal="write-intro", depends_on=["m1"])
    write_task(content_copy, "m2", goal="write-methods", depends_on=["i1"])
    content = Content.open(content_copy)
    board = flow.project_board(content, content.project("project-a"))
    stage = next(s for s in ids(board) if "write-intro" in s)
    assert "write-methods" in stage


def test_project_board_missing_dependency(content_copy):
    write_task(content_copy, "orphan", depends_on=["no-such-task"])
    content = Content.open(content_copy)
    board = flow.project_board(content, content.project("project-a"))
    missing = next(c for c in board.cards() if c.id == "no-such-task")
    assert (missing.kind, missing.state) == ("external", CardState.MISSING)
    assert ("no-such-task", "orphan") in board.edges()


def test_doing_is_its_own_state(content_copy):
    write_task(content_copy, "started", goal="write-methods", status="doing")
    content = Content.open(content_copy)
    board = flow.goal_board(content, content.goal("write-methods"))
    assert board.stages[0][0].state == CardState.DOING
    assert board.goal.state == CardState.DOING


def test_warnings_overdue_and_due_before_prerequisite(content_copy):
    write_task(content_copy, "late", goal="write-methods", due="2026-09-01")
    write_task(content_copy, "first", goal="write-methods", due="2026-10-20")
    write_task(content_copy, "second", goal="write-methods", due="2026-10-10", depends_on=["first"])
    content = Content.open(content_copy)
    board = flow.goal_board(content, content.goal("write-methods"), today=TODAY)
    cards = {c.id: c for c in board.cards()}
    assert cards["late"].warnings == ["overdue (due 2026-09-01)"]
    assert cards["second"].warnings == ["due before first (2026-10-20)"]
    assert cards["first"].warnings == []
    project = flow.project_board(content, content.project("project-a"), today=TODAY)
    methods = next(c for c in project.cards() if c.id == "write-methods")
    assert "late: overdue (due 2026-09-01)" in methods.warnings
    assert "second: due before first (2026-10-20)" in methods.warnings


def test_inherited_overdue_is_reported_once_on_the_goal(content):
    board = flow.project_board(content, content.project("project-a"), today=dt.date(2026, 12, 1))
    intro = next(c for c in board.cards() if c.id == "write-intro")
    assert intro.warnings[0] == "overdue (due 2026-10-01)"
    assert not any("draft-related-work: overdue" in w for w in intro.warnings)


def test_status_board_project(content):
    board = flow.status_board(content, content.project("project-a"))
    assert board.by == "status"
    assert [c.label for c in board.columns] == ["todo", "doing", "blocked", "done"]
    todo = [c.id for c in board.columns[0].cards]
    # Startable tasks first, in `next` order; waiting ones after.
    assert todo[:3] == ["draft-related-work", "wait-for-cluster-allocation", "fix-plot-colors"]
    feedback = next(c for c in board.cards() if c.id == "get-feedback-from-advisor")
    assert feedback.state == CardState.WAITING
    assert feedback.after == ["draft-related-work"]
    assert feedback.goal == "write-intro"


def test_status_board_goal_open_only(content):
    board = flow.status_board(content, content.goal("write-intro"), open_only=True)
    assert [c.label for c in board.columns] == ["todo", "doing", "blocked"]
    assert {c.id for c in board.cards()} == {"draft-related-work", "get-feedback-from-advisor"}
    assert all(c.goal is None for c in board.cards())  # same goal for all: not repeated


def test_arrange_links_prerequisite_rows(content):
    board = flow.goal_board(content, content.goal("write-intro"))
    columns, arrows = arrange(board.stages)
    assert columns[1][0].id == "get-feedback-from-advisor"
    assert arrows == {("draft-related-work", "get-feedback-from-advisor")}


def test_plan_columns_spreads_tall_columns_when_wide():
    assert plan_columns([5], 80) == ([2], 34)
    assert plan_columns([5], 130)[0] == [3]
    # Short columns aren't split, however wide the terminal.
    assert plan_columns([2, 1], 200) == ([1, 1], 34)
    # Too narrow for one column per stage: caller falls back to stacking.
    assert plan_columns([1, 1, 1, 1], 60) is None


def test_split_puts_cards_feeding_the_next_column_last():
    cards = [flow.Card(i, "task", i, CardState.READY) for i in "abcd"]
    parts = split(cards, 2, feeds_next={"a"})
    assert [[c.id for c in p] for p in parts] == [["b", "c"], ["d", "a"]]


def test_ready_lists_startable_tasks_in_next_order(content):
    board = flow.project_board(content, content.project("project-a"))
    assert [i.id for i in board.ready] == [
        "draft-related-work",
        "wait-for-cluster-allocation",
        "fix-plot-colors",
    ]
    goal = flow.goal_board(content, content.goal("write-intro"))
    assert [i.id for i in goal.ready] == ["draft-related-work"]


# --- CLI ----------------------------------------------------------------------


@pytest.fixture
def run(content, monkeypatch):
    monkeypatch.setattr("tavla.core.dates.local_today", lambda: TODAY)

    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(content.root), "flow", *args])

    return _run


def test_cli_goal_board(run):
    result = run("write-intro", "--width", "120")
    assert result.exit_code == 0, result.output
    assert "Goal: Write introduction section" in result.output
    assert "STAGE 2" in result.output and "GOAL" in result.output
    assert "──▶" in result.output
    assert "Collect MCMC papers" in result.output


def test_cli_project_board_arrow_between_goals(run):
    result = run("project-a", "--width", "120")
    assert result.exit_code == 0, result.output
    assert "STAGE 2" in result.output
    # write-methods sits in write-intro's row, so the edge is an arrow, not text.
    assert "──▶" in result.output
    assert "after:" not in result.output


def test_cli_narrow_stacks_stages(run):
    result = run("write-intro", "--width", "40")
    assert result.exit_code == 0, result.output
    assert "──▶" not in result.output
    assert "after: draft-related-work" in result.output


def test_cli_item_limit(run):
    result = run("write-intro", "--width", "120", "-n", "1")
    assert "… 1 more" in result.output


def test_cli_ready_footer(run):
    result = run("write-intro", "--width", "120")
    assert "Ready now: ● draft-related-work" in result.output


def test_cli_shows_warnings(run, content):
    write_task(content.root, "late", goal="write-intro", due="2026-09-01")
    result = run("write-intro", "--width", "120")
    assert "! overdue (due 2026-09-01)" in result.output


def test_cli_by_status(run):
    result = run("project-a", "--by", "status", "--width", "140")
    assert result.exit_code == 0, result.output
    assert "TODO (" in result.output and "DONE (" in result.output
    assert "──▶" not in result.output


def test_cli_mermaid(run):
    result = run("write-intro", "--format", "mermaid")
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith('---\ntitle: "Goal: Write introduction section"\n---\nflowchart LR')
    assert 'subgraph c0["Stage 1"]' in out
    assert '["● Draft related work<br/>due 2026-10-01<br/>1/2"]' in out
    assert "n0 --> n2" in out  # draft-related-work unblocks the advisor feedback
    assert "-.-> n3" in out  # into the goal
    assert "class n0 st_ready" in out


def test_cli_mermaid_escapes_labels(run, content):
    write_task(content.root, "quote", goal="write-intro")
    path = content.root / "projects/project-a/tasks/quote.md"
    path.write_text(path.read_text().replace("# Quote", '# Say "hi" <b>'))
    out = run("write-intro", "-f", "mermaid").output
    assert "Say #quot;hi#quot; #lt;b#gt;" in out


def test_cli_json(run):
    result = run("write-methods", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "goal"
    assert data["by"] == "stage"
    assert data["columns"][1]["cards"][0]["after"] == ["get-feedback-from-advisor"]


def test_cli_unknown_target(run):
    result = run("nope-nothing")
    assert result.exit_code == 2
    assert "no project or goal matching" in result.output
