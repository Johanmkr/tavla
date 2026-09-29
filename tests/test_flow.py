from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tavla.cli.flow import arrange
from tavla.cli.main import app
from tavla.core import flow
from tavla.core.flow import CardState
from tavla.core.store import Content

runner = CliRunner()


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
    root, id_, *, goal=None, depends_on=(), status="todo", subtasks=(), project="project-a"
):
    lines = ["---", f"id: {id_}", f"status: {status}"]
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


def test_arrange_links_prerequisite_rows(content):
    board = flow.goal_board(content, content.goal("write-intro"))
    columns, arrows = arrange(board)
    assert columns[1][0].id == "get-feedback-from-advisor"
    assert arrows == {("draft-related-work", "get-feedback-from-advisor")}


# --- CLI ----------------------------------------------------------------------


@pytest.fixture
def run(content):
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


def test_cli_json(run):
    result = run("write-methods", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "goal"
    assert data["stages"][1][0]["after"] == ["get-feedback-from-advisor"]


def test_cli_unknown_target(run):
    result = run("nope-nothing")
    assert result.exit_code == 2
    assert "no project or goal matching" in result.output
