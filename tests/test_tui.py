"""The TUI (`tv ui`): the pure row/detail model, and the app driven headless."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app as cli
from tavla.core import demo, focus, ops, todos
from tavla.core.entities import TaskStatus
from tavla.core.store import Content
from tavla.tui import model
from tavla.tui.app import TavlaApp
from tavla.tui.model import ALL, Context

runner = CliRunner()


@pytest.fixture
def demo_repo(tmp_path) -> Path:
    dest = tmp_path / "demo"
    demo.create(dest)
    return dest


def keys(rows: list[model.Row]) -> list[str]:
    return [r.key for r in rows]


def plain(lines: list[model.Line]) -> str:
    out = []
    for line in lines:
        prompt = line.prompt
        out.append(prompt.plain if hasattr(prompt, "plain") else str(prompt))
    return "\n".join(out)


# --- model ---------------------------------------------------------------------------


def test_status_rows_show_work_alerts_and_todos(demo_repo):
    content = Content.open(demo_repo)
    todos.add(content, "buy milk")
    rows = model.status_rows(content)
    assert keys(rows)[:2] == ["working", "summary"]
    assert rows[0].ref is None  # not working on anything
    assert "overdue" in rows[1].search
    assert rows[-1].kind == "todo" and rows[-1].ref.text == "buy milk"

    focus.enter(content, content.task("draft-methods"))
    assert model.status_rows(content)[0].ref == "draft-methods"


def test_project_rows_hide_inactive_unless_show_all(demo_repo):
    content = Content.open(demo_repo)
    shown = keys(model.project_rows(content))
    everything = keys(model.project_rows(content, show_all=True))
    assert "project:thesis" in shown
    assert set(shown) <= set(everything)
    assert len(everything) == len(content.projects())


def test_task_rows_follow_the_context(demo_repo):
    content = Content.open(demo_repo)
    today = demo.ANCHOR
    everywhere = keys(model.task_rows(content, ALL, today=today))
    # The `next` ranking: only tasks that can be started now.
    assert everywhere == [f"task:{t.id}" for t in model.queries.next_tasks(content)]

    goal = keys(model.task_rows(content, Context("goal", "thesis", "experiments"), today=today))
    assert "task:run-adaptive" in goal  # waiting tasks are listed in their goal
    assert "task:set-up-pipeline" not in goal  # done: hidden by default
    with_done = model.task_rows(
        content, Context("goal", "thesis", "experiments"), show_all=True, today=today
    )
    assert keys(with_done)[-1] == "task:set-up-pipeline"  # done last

    loose = keys(model.task_rows(content, Context("loose", "thesis"), today=today))
    assert loose and all(content.task(k[5:]).goal is None for k in loose)


def test_goal_rows_add_a_loose_row(demo_repo):
    content = Content.open(demo_repo)
    rows = model.goal_rows(content, content.project("thesis"), today=demo.ANCHOR)
    assert keys(rows)[-1] == "loose:thesis"
    assert "goal:lit-review" not in keys(rows)  # done
    assert model.goal_rows(content, None, today=demo.ANCHOR) == []


def test_task_detail_lists_subtasks_as_selectable_lines(demo_repo):
    content = Content.open(demo_repo)
    lines = model.task_detail(content, content.task("run-baseline"))
    subtasks = [line for line in lines if line.subtask]
    assert [s.subtask.text for s in subtasks][:2] == ["Toy model", "Logistic regression"]
    text = plain(lines)
    assert "Run the NUTS baseline" in text
    assert "blocks" in text and "run-adaptive" in text


def test_flow_lines_side_by_side_or_stacked(demo_repo):
    content = Content.open(demo_repo)
    board = model.flow.project_board(content, content.project("thesis"))
    wide = plain(model.flow_lines(board, 120))
    assert "Stage 1" in wide and "Stage 2" in wide.splitlines()[0]
    narrow = plain(model.flow_lines(board, 30))
    assert narrow.splitlines()[0].strip() == "Stage 1"
    assert all(len(line) <= 30 for line in narrow.splitlines() if "Ready" not in line)


# --- app ------------------------------------------------------------------------------


def drive(root: Path, *steps: str | tuple, size=(110, 32)):
    """Run the app headless, pressing keys (``type:text`` types text); returns the app."""

    async def run() -> TavlaApp:
        app = TavlaApp(root)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            for step in steps:
                if callable(step):
                    step(app)
                elif step.startswith("type:"):
                    await pilot.press(*step[5:])
                else:
                    await pilot.press(step)
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
        return app

    return asyncio.run(run())


def last_commit(git, repo: Path) -> str:
    return git(repo, "log", "-1", "--format=%s").strip()


def test_starts_on_the_next_list(demo_repo):
    seen = {}
    drive(
        demo_repo,
        lambda app: seen.update(
            focused=app.focused.id, top=app.pane("tasks").current.key, ctx=app.context()
        ),
    )
    first = model.queries.next_tasks(Content.open(demo_repo))[0]
    assert seen == {"focused": "tasks", "top": f"task:{first.id}", "ctx": ALL}


def test_projects_pane_scopes_the_tasks(demo_repo):
    seen = {}

    def look(app):
        seen["ctx"] = app.context()
        seen["detail"] = app.detail.border_title

    drive(demo_repo, "2", lambda app: app.pane("projects").select_key("project:thesis"), look)
    assert seen["ctx"] == Context("project", "thesis")
    assert seen["detail"] == "thesis · flow"


def test_space_marks_the_task_done_and_commits(demo_repo, git):
    content = Content.open(demo_repo)
    first = model.queries.next_tasks(content)[0]
    drive(demo_repo, "space")
    assert Content.open(demo_repo).task(first.id).status == TaskStatus.DONE
    assert last_commit(git, demo_repo) == f"task: done {first.id}"


def test_work_note_and_pause(demo_repo, git):
    def pick(app):
        app.pane("tasks").select_key("task:draft-methods")

    drive(demo_repo, pick, "w", "n", "type:outline done", "enter", "w")
    content = Content.open(demo_repo)
    assert focus.current(content) is None
    task = content.task("draft-methods")
    assert len(focus.sessions(task)) == 1
    assert "outline done" in task.body
    assert last_commit(git, demo_repo).startswith("focus: pause draft-methods")


def test_add_goal_then_task_in_it(demo_repo):
    def thesis(app):
        app.pane("projects").select_key("project:thesis")

    drive(
        demo_repo,
        "2",
        thesis,
        "3",
        "a",
        "type:Polish figures",
        "enter",
        "4",
        "a",
        "type:Pick a colour map",
        "enter",
    )
    content = Content.open(demo_repo)
    task = content.task("pick-a-colour-map")
    assert (task.goal, task.project) == ("polish-figures", "thesis")


def test_drop_asks_and_refuses_with_dependents(demo_repo, git):
    def pick(task_id):
        return lambda app: app.pane("tasks").select_key(f"task:{task_id}")

    before = last_commit(git, demo_repo)
    drive(demo_repo, pick("run-baseline"), "D")  # others depend on it: refused, no question
    assert last_commit(git, demo_repo) == before
    drive(demo_repo, pick("book-supervisor-meeting"), "D", "n")
    assert last_commit(git, demo_repo) == before
    drive(demo_repo, pick("book-supervisor-meeting"), "D", "y")
    assert last_commit(git, demo_repo) == "task: drop book-supervisor-meeting"
    drive(demo_repo, "u", "y")
    assert last_commit(git, demo_repo) == "undo: task: drop book-supervisor-meeting"
    assert Content.open(demo_repo).task("book-supervisor-meeting")


def test_tick_subtask_from_the_detail_pane(demo_repo):
    def pick(app):
        app.pane("tasks").select_key("task:run-baseline")

    drive(demo_repo, pick, "0", "j", "j", "space")
    task = Content.open(demo_repo).task("run-baseline")
    assert [s.done for s in task.subtasks][:3] == [True, True, True]


def test_due_prompt_replaces_the_old_date(demo_repo):
    def pick(app):
        app.pane("tasks").select_key("task:draft-methods")

    drive(demo_repo, pick, "t", "type:2030-01-31", "enter")
    assert str(Content.open(demo_repo).task("draft-methods").due) == "2030-01-31"


def test_reloads_when_something_else_commits(demo_repo):
    seen = {}

    def outside(app):
        content = Content.open(demo_repo)
        ops.complete(content, content.task(app.pane("tasks").current.ref.id))
        seen["before"] = app.pane("tasks").current.key
        app.poll()
        seen["after"] = app.pane("tasks").current.key

    drive(demo_repo, outside)
    assert seen["before"] != seen["after"]


def test_narrow_and_tiny_layouts(demo_repo):
    seen = {}

    def look(app):
        seen["classes"] = set(app.screen.classes)

    drive(demo_repo, look, size=(60, 20))
    assert "narrow" in seen["classes"]
    drive(demo_repo, "enter", look, size=(60, 20))
    assert "detail-open" in seen["classes"]
    drive(demo_repo, look, size=(30, 10))
    assert "tiny" in seen["classes"]


# --- CLI entry --------------------------------------------------------------------------


def test_bare_tv_prints_help_when_not_a_terminal():
    result = runner.invoke(cli, [])
    assert result.exit_code == 2
    assert "Usage" in result.output and "ui" in result.output


def test_ui_needs_a_content_repo(tmp_path):
    result = runner.invoke(cli, ["ui", "--content-dir", str(tmp_path / "nothing")])
    assert result.exit_code != 0
    assert "no tavla content repo" in result.output
