"""The TUI (`tv ui`): the pure row/detail model, and the app driven headless."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from rich.text import Text
from textual.widgets import Static
from typer.testing import CliRunner

from tavla.cli.main import app as cli
from tavla.core import dates, demo, focus, ideas, ops, queries, todos
from tavla.core.entities import TaskStatus
from tavla.core.store import Content
from tavla.tui import model
from tavla.tui.app import TavlaApp
from tavla.tui.screens import FlowScreen

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


def test_hints_keep_context_keys_and_drop_extras_first():
    fit = model.fit_hints
    assert (
        fit("space done  s start", ["v mark", "/ filter"], 40)
        == "space done  s start  v mark  ? help"
    )
    assert fit("space done  s start  w work", ["v mark"], 20) == "space done …  ? help"
    assert fit("", ["v mark"], 30) == "v mark  ? help"


def test_help_splits_hints_into_keys_and_actions():
    from tavla.tui.screens import _split_hint

    assert _split_hint("J K order")[::2] == ("J K", "order")
    assert _split_hint("space done")[::2] == ("space", "done")
    assert _split_hint("enter go to item")[::2] == ("enter", "go to item")
    assert _split_hint("/ filter")[::2] == ("/", "filter")


def test_help_starts_with_the_keys_for_where_you_are(demo_repo):
    seen: dict[str, Any] = {}

    def grab(app):
        seen["here"] = app.screen.here

    drive(demo_repo, "question_mark", grab, "G", "g")
    assert seen["here"].startswith("enter tasks")


def test_goal_column_ends_with_deliverables_and_loose(demo_repo):
    content = Content.open(demo_repo)
    rows = model.goal_column_rows(content, content.project("thesis"), today=demo.ANCHOR)
    assert keys(rows)[-2:] == ["deliverables:thesis", "loose:thesis"]
    assert "goal:lit-review" not in keys(rows)  # done
    assert all(r.column == "goal" for r in rows)
    # A project with no loose tasks still gets the deliverables row, so `o` has
    # somewhere to point even in a fresh project.
    only = model.goal_column_rows(content, content.project("teaching"), today=demo.ANCHOR)
    assert "deliverables:teaching" in keys(only)


def test_next_column_is_the_ranking_then_goals_without_tasks(demo_repo):
    content = Content.open(demo_repo)
    rows = model.next_column_rows(content, today=demo.ANCHOR)
    ranked = queries.next_tasks(content)
    assert keys(rows)[: len(ranked)] == [f"task:{t.id}" for t in ranked]
    assert all(r.column == "list" for r in rows)
    with_done = model.next_column_rows(content, show_all=True, today=demo.ANCHOR)
    done = [t for t in content.tasks() if t.status == TaskStatus.DONE]
    assert f"task:{done[0].id}" in keys(with_done)


def test_inbox_rows_section_ideas_chores_then_filed_ideas(demo_repo):
    content = Content.open(demo_repo)
    todos.add(content, "buy milk")
    rows = model.inbox_rows(content, today=demo.ANCHOR)
    assert [r.key for r in rows if r.kind == "heading"] == [
        "heading:ideas",
        "heading:chores",
        "heading:filed",
    ]
    filed = keys(rows)[keys(rows).index("heading:filed") + 1 :]
    assert filed and all(not k.startswith("idea:inbox:") for k in filed)
    assert keys(rows)[keys(rows).index("heading:filed") - 1] == "todo:1"
    assert all(r.disabled for r in rows if r.kind == "heading")


def test_t_on_a_filed_idea_starts_the_filed_pass(demo_repo):
    seen: dict[str, str] = {}

    def on_filed(app):
        rows = app.column("list").rows
        app.column("list").select_key(rows[[r.key for r in rows].index("heading:filed") + 1].key)

    drive(demo_repo, "3", on_filed, "T", lambda app: seen.__setitem__("card", triage_card(app)))
    assert "Filed ideas · 1 of" in seen["card"]


def test_agenda_rows_status_then_today_then_dates(demo_repo):
    content = Content.open(demo_repo)
    todos.add(content, "buy milk")
    today = dates.local_today()
    rows = model.agenda_rows(content, today=today)
    assert keys(rows)[0] == "heading:status"
    today_at = keys(rows).index("heading:today")
    assert rows[today_at + 1].key == "todo:1"
    report = queries.status(content, today=today)
    assert report.due_tasks
    assert f"due:{report.due_tasks[0].id}" in keys(rows)
    assert any(r.key.startswith("deadline:") for r in rows)
    # everything but a heading points at the item it came from, so `enter` can
    # jump into the hierarchy
    for row in rows:
        if row.kind == "heading":
            assert row.disabled and row.ref is None
        else:
            assert row.ref is not None


def test_agenda_shows_the_running_session(demo_repo):
    content = Content.open(demo_repo)
    focus.enter(content, content.task("draft-methods"))
    rows = model.agenda_rows(Content.open(demo_repo), today=demo.ANCHOR)
    assert "session:draft-methods" in keys(rows)


def test_task_detail_lists_subtasks_as_selectable_lines(demo_repo):
    content = Content.open(demo_repo)
    lines = model.task_detail(content, content.task("run-baseline"))
    subtasks = [line for line in lines if line.subtask]
    assert [s.subtask.text for s in subtasks][:2] == ["Toy model", "Logistic regression"]
    text = plain(lines)
    assert "Run the NUTS baseline" in text
    assert "blocks" in text and "run-adaptive" in text
    assert "[x] Toy model" in text and "[ ] Hierarchical model" in text


def test_task_without_subtasks_says_what_to_do(demo_repo):
    content = Content.open(demo_repo)
    assert "No subtasks · o add one" in plain(
        model.task_detail(content, content.task("enter-grades"))
    )


def test_task_detail_labels_its_fields(demo_repo):
    content = Content.open(demo_repo)
    text = plain(model.task_detail(content, content.task("grade-problems")))
    assert "priority  med  (from goal)" in text
    assert "status    doing" in text


def test_preview_is_the_widest_column_and_goals_stay_narrow(demo_repo):
    seen: dict[str, Any] = {}

    def grab(app):
        seen.update(app.layout(120))

    drive(demo_repo, grab)
    assert seen["preview"] > seen["mid"] > seen["list"]
    assert seen["list"] <= 34


def test_marking_a_row_survives_a_two_column_grid():
    row = model.Row("k", "task", model.two_columns(model.dim("hello"), model.dim("2")))
    row.mark()
    assert row.marked


def test_flow_lines_side_by_side_or_stacked(demo_repo):
    content = Content.open(demo_repo)
    board = model.flow.project_board(content, content.project("thesis"))
    wide = plain(model.flow_lines(board, 120))
    assert "Stage 1" in wide and "Stage 2" in wide.splitlines()[0]
    narrow = plain(model.flow_lines(board, 30))
    assert narrow.splitlines()[0].strip() == "Stage 1"
    assert all(len(line) <= 30 for line in narrow.splitlines() if "Ready" not in line)


def test_flow_lines_carry_card_ids(demo_repo):
    content = Content.open(demo_repo)
    board = model.flow.project_board(content, content.project("thesis"))
    lines = model.flow_lines(board, 120)
    assert "experiments" in {line.card for line in lines if line.card}
    assert all(
        line.card is None for line in model.flow_lines(board, 30) if "Stage" in plain([line])
    )


# --- app ------------------------------------------------------------------------------


def drive(root: Path, *steps: Any, size=(120, 36)) -> dict[str, Any]:
    """Run the app headless, pressing keys (``type:text`` types text).

    Returns a snapshot of the app taken while it is still mounted: scope,
    columns and their rows, header and hint lines, layout state.
    """

    async def run() -> dict[str, Any]:
        app = TavlaApp(root)
        snapshot: dict[str, Any] = {}
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
                try:
                    # A refused write (a dependency cycle) surfaces as a worker
                    # error the app has already toasted: it must not fail the
                    # test, which asserts on the repo afterwards.
                    await app.workers.wait_for_complete()
                except Exception:  # noqa: BLE001, S110 - the app reported it
                    pass
                await pilot.pause()
            snapshot = contents(app)
        return snapshot

    return asyncio.run(run())


def contents(app: TavlaApp) -> dict[str, Any]:
    """What a test may assert on, read while the app is mounted."""
    return {
        "scope": app.scope,
        "project": app.project_id,
        "filter": app.filter,
        "marked": set(app.marked),
        "focused": app.focused.id if app.focused is not None else None,
        "list_source": app.list_source,
        "visible": app.visible_columns(),
        "hidden": app.hidden_columns(),
        "rows": {name: [r.key for r in app.column(name).rows] for name in ("list", "mid")},
        "current": {
            name: (app.column(name).current.key if app.column(name).current else None)
            for name in ("list", "mid")
        },
        "preview": app.preview().border_title,
        "preview_rows": [r.key for r in app.preview().rows if not r.disabled],
        "breadcrumb": app.breadcrumb(),
        "header": render(app.query_one("#header", Static)),
        "hints": render(app.query_one("#hints", Static)),
        "screen": type(app.screen).__name__,
        "screen_view": getattr(app.screen, "view", None),
        "classes": set(app.screen.classes),
    }


def render(widget: Static) -> str:
    console = Console(width=200)
    with console.capture() as capture:
        console.print(widget.content)
    return capture.get().rstrip()


def pick_option(app: TavlaApp, prefix: str) -> None:
    """Highlight the option of the open picker whose id starts with ``prefix``."""
    options = app.screen.query_one("#choices")
    ids = [str(o.id) for o in options.options]
    options.highlighted = next(n for n, i in enumerate(ids) if i.startswith(prefix))


def to_thesis(app: TavlaApp) -> None:
    app.project_id = "thesis"
    app.reload()


def last_commit(git, repo: Path) -> str:
    return git(repo, "log", "-1", "--format=%s").strip()


def test_starts_in_project_scope_on_the_first_active_project(demo_repo):
    seen = drive(demo_repo)
    content = Content.open(demo_repo)
    assert seen["scope"] == "project"
    assert seen["project"] == queries.active_projects(content)[0].id
    goals = content.goals(content.project(seen["project"]))
    assert seen["current"]["list"] == f"goal:{goals[0].id}"
    assert seen["focused"] == "list"
    assert seen["preview"] == f"{goals[0].id} · flow"


def test_scope_2_puts_the_next_ranking_in_column_one(demo_repo):
    seen = drive(demo_repo, "2")
    first = queries.next_tasks(Content.open(demo_repo))[0]
    assert seen["scope"] == "next"
    assert seen["current"]["list"] == f"task:{first.id}"
    assert seen["preview"] == first.id


def test_header_shows_the_scopes_as_tabs(demo_repo):
    snap = drive(demo_repo, "3")
    text = Text.from_ansi(snap["header"]).plain
    assert "1 Project  2 Next  3 Inbox  4 Agenda" in text


def test_narrow_header_keeps_the_breadcrumb_and_shortens_alerts(demo_repo):
    snap = drive(demo_repo, "enter", size=(80, 24))
    text = Text.from_ansi(snap["header"]).plain
    assert "teaching › grade-hw2" in text
    assert "!1 ✗1" in text and "overdue" not in text


def test_i_visits_the_alerts_in_the_agenda(demo_repo):
    first = drive(demo_repo, "i")
    assert first["scope"] == "agenda"
    report = queries.status(Content.open(demo_repo))
    keys = model.alert_keys(report)
    assert len(keys) >= 2 and keys[0].startswith("due:")
    seen: list[str] = []

    def grab(app):
        seen.append(app.column("list").current.key)

    drive(demo_repo, "i", grab, "i", grab)
    assert seen == keys[:2]


def test_blocked_tasks_show_in_the_agenda(demo_repo):
    report = queries.status(Content.open(demo_repo))
    rows = model.agenda_rows(Content.open(demo_repo), today=report.today)
    assert [r.key for r in rows if r.key.startswith("blocked:")] == [
        f"blocked:{t.id}" for t in report.blocked
    ]


def test_scope_keys_and_tab_switch(demo_repo):
    assert drive(demo_repo, "3")["scope"] == "inbox"
    assert drive(demo_repo, "4")["scope"] == "agenda"
    assert drive(demo_repo, "tab")["scope"] == "next"
    assert drive(demo_repo, "shift+tab")["scope"] == "agenda"


def test_scope_3_lists_ideas_then_chores_and_ticks_one(demo_repo, git):
    content = Content.open(demo_repo)
    todos.add(content, "buy milk")
    todos.add(content, "water plants")
    seen = drive(demo_repo, "3")
    assert seen["rows"]["list"].index("heading:ideas") < seen["rows"]["list"].index(
        "heading:chores"
    )
    assert "todo:1" in seen["rows"]["list"]

    drive(demo_repo, "3", lambda app: app.column("list").select_key("todo:1"), "space")
    assert (demo_repo / "todo.md").read_text().count("- [x]") == 1
    assert last_commit(git, demo_repo) == "todo: done buy milk"


def idea_texts(root: Path) -> list[str]:
    return [r.idea.text for r in ideas.read(ideas.scope_of(Content.open(root), None))]


def test_d_drops_ideas_and_space_marks_one_done(demo_repo, git):
    _, second, third = idea_texts(demo_repo)
    drive(demo_repo, "3", lambda app: app.column("list").select_key("idea:inbox:1"), "D", "y")
    assert idea_texts(demo_repo) == [second, third]
    assert last_commit(git, demo_repo).startswith("idea: drop from inbox:")

    drive(demo_repo, "3", lambda app: app.column("list").select_key("idea:inbox:1"), "space")
    assert idea_texts(demo_repo) == [third]
    assert last_commit(git, demo_repo).startswith("idea: done inbox:")


def test_marked_ideas_drop_together(demo_repo):
    drive(
        demo_repo,
        "3",
        lambda app: app.column("list").select_key("idea:inbox:1"),
        "v",
        "j",
        "D",
        "y",
    )
    assert len(idea_texts(demo_repo)) == 1


def test_p_promotes_a_chore_into_a_goal(demo_repo):
    todos.add(Content.open(demo_repo), "Write the methods section")

    def pick(app):
        pick_option(app, "thesis|write-up")

    drive(demo_repo, "3", lambda app: app.column("list").select_key("todo:1"), "p", pick, "enter")
    content = Content.open(demo_repo)
    task = next(t for t in content.tasks() if t.title == "Write the methods section")
    assert task.goal == "write-up"
    assert todos.read(content) == []


def test_promote_picker_groups_goals_under_their_project(demo_repo):
    homes = model.task_homes(Content.open(demo_repo))
    labels = [label for _, label, _ in homes]
    at = labels.index("thesis  (no goal)")
    assert labels[at + 1].startswith("thesis › ")


def test_inbox_header_has_no_idea_number(demo_repo):
    seen = drive(demo_repo, "3", "j")
    assert seen["breadcrumb"] == []


def triage_card(app: TavlaApp) -> str:
    return str(app.screen.query_one("#card").content)


def with_chores(root: Path) -> Path:
    content = Content.open(root)
    todos.add(content, "Book the dentist")
    todos.add(content, "Draft the methods intro #writing")
    return root


def test_triage_goes_through_chores_then_offers_the_ideas(demo_repo):
    with_chores(demo_repo)
    seen: dict[str, str] = {}

    def look(name):
        return lambda app: seen.__setitem__(name, triage_card(app))

    drive(
        demo_repo,
        "3",
        lambda app: app.column("list").select_key("todo:1"),
        "T",
        look("first"),
        "x",
        look("second"),
        "D",
        look("empty"),
        "enter",
        look("ideas"),
    )
    assert "Chores · 1 of 2" in seen["first"] and "Book the dentist" in seen["first"]
    assert "Chores · 1 of 1" in seen["second"]
    assert "nothing left" in seen["empty"] and "go through the ideas (3)" in seen["empty"]
    assert "Ideas · 1 of 3" in seen["ideas"]
    assert todos.open_todos(Content.open(demo_repo)) == []


def test_triage_switches_passes_with_c_and_i(demo_repo):
    with_chores(demo_repo)
    seen: dict[str, str] = {}
    drive(
        demo_repo,
        "3",
        "T",
        "c",
        lambda app: seen.__setitem__("c", triage_card(app)),
        "i",
        lambda app: seen.__setitem__("i", triage_card(app)),
    )
    assert "Chores ·" in seen["c"] and "Ideas ·" in seen["i"]


def test_triage_t_makes_a_task_with_an_edited_title(demo_repo):
    with_chores(demo_repo)

    def pick(app):
        pick_option(app, "thesis|write-up")

    drive(
        demo_repo,
        "3",
        lambda app: app.column("list").select_key("todo:2"),
        "T",
        "n",  # skip the dentist
        "t",
        pick,
        "enter",
        "ctrl+u",
        "type:Draft the intro",
        "enter",
    )
    content = Content.open(demo_repo)
    task = next(t for t in content.tasks() if t.title == "Draft the intro")
    assert task.goal == "write-up" and task.tags == ["writing"]
    assert [t.text for t in todos.open_todos(content)] == ["Book the dentist"]


def test_triage_p_makes_a_subproject_and_l_files_for_later(demo_repo):
    with_chores(demo_repo)

    def under_thesis(app):
        pick_option(app, "thesis")

    drive(demo_repo, "3", "T", "c", "P", under_thesis, "enter", "enter")
    content = Content.open(demo_repo)
    assert next(p for p in content.projects() if p.title == "Book the dentist").parent == "thesis"

    drive(demo_repo, "3", "T", "c", "l", under_thesis, "enter")
    filed = ideas.read(ideas.resolve_scope(Content.open(demo_repo), "thesis"))
    assert "Draft the methods intro #writing" in [r.idea.text for r in filed]


def test_scope_4_shows_status_and_the_overdue_task(demo_repo):
    seen = drive(demo_repo, "4")
    assert seen["rows"]["list"][0] == "heading:status"
    report = queries.status(Content.open(demo_repo))
    assert report.due_tasks
    assert f"due:{report.due_tasks[0].id}" in seen["rows"]["list"]


def test_space_marks_done_and_advances_the_selection(demo_repo, git):
    content = Content.open(demo_repo)
    ranked = queries.next_tasks(content)
    first, second = ranked[0].id, ranked[1].id
    seen = drive(demo_repo, "2", "space")
    assert Content.open(demo_repo).task(first).status == TaskStatus.DONE
    assert last_commit(git, demo_repo) == f"task: done {first}"
    assert seen["current"]["list"] == f"task:{second}"  # the row that took its place


def test_space_on_a_goal_completes_it(demo_repo, git):
    seen = drive(
        demo_repo,
        lambda app: app.column("list").select_key("goal:grade-hw2"),
        "space",
    )
    assert last_commit(git, demo_repo) == "goal: done grade-hw2"
    assert seen["current"]["list"] != "goal:grade-hw2"


def test_x_reopens_a_done_task(demo_repo, git):
    def pick(app):
        app.jump_to("set-up-pipeline")  # done: the jump reveals it

    drive(demo_repo, pick, "x")
    assert last_commit(git, demo_repo) == "task: reopen set-up-pipeline"


def test_visual_mark_space_done_commits_each(demo_repo, git):
    def pick(app):
        app.jump_to("run-baseline")
        app.column("mid").focus()

    seen = drive(demo_repo, pick, "v", "j", "space")
    subjects = git(demo_repo, "log", "-2", "--format=%s").splitlines()
    assert subjects[0] in ("task: done run-baseline", "task: done make-figures")
    assert all(s.startswith("task: done ") for s in subjects)
    assert seen["marked"] == set()  # marks clear once the writes land


def test_a_bulk_verb_over_three_rows_asks_first(demo_repo, git):
    def pick(app):
        app.jump_to("run-baseline")
        app.column("mid").focus()

    before = last_commit(git, demo_repo)
    drive(demo_repo, pick, "v", "j", "j", "j", "space", "n")
    assert last_commit(git, demo_repo) == before  # answered no: nothing written


def test_reorder_writes_order_and_moves_the_row(demo_repo, git):
    def pick(app):
        app.jump_to("run-baseline")  # the experiments goal's task column
        app.column("mid").focus()

    seen = drive(demo_repo, pick, "J")
    assert last_commit(git, demo_repo).startswith("task: reorder in experiments (")
    assert seen["current"]["mid"] == "task:run-baseline"  # the row follows the cursor
    assert seen["rows"]["mid"].index("task:run-baseline") == 1
    assert "order: 1" in (demo_repo / "projects/thesis/tasks/run-baseline.md").read_text()


def test_k_moves_a_row_up_in_the_goal_column(demo_repo, git):
    def pick(app):
        app.jump_to("send-draft")
        app.column("mid").focus()

    seen = drive(demo_repo, pick, "K")
    assert seen["current"]["mid"] == "task:send-draft"
    assert seen["rows"]["mid"].index("task:send-draft") == 1
    assert "order: 1" in (demo_repo / "projects/thesis/tasks/send-draft.md").read_text()


def test_reorder_is_unbound_in_the_next_scope(demo_repo, git):
    before = last_commit(git, demo_repo)
    drive(demo_repo, "2", "J")
    assert last_commit(git, demo_repo) == before


def test_reordering_a_subtask_in_the_preview(demo_repo, git):
    def pick(app):
        app.jump_to("run-baseline")
        app.preview().focus()
        app.preview().select_key("sub:1")  # Toy model

    seen = drive(demo_repo, pick, "J")
    assert last_commit(git, demo_repo) == "task: edit run-baseline (subtasks reordered)"
    subtasks = [s.text for s in Content.open(demo_repo).task("run-baseline").subtasks]
    assert subtasks[:2] == ["Logistic regression", "Toy model"]
    assert seen["preview"] == "run-baseline"
    assert seen["focused"] == "preview"


def test_subtask_reorder_stops_at_the_edges(demo_repo, git):
    def pick(app):
        app.jump_to("run-baseline")
        app.preview().focus()
        app.preview().select_key("sub:1")

    before = last_commit(git, demo_repo)
    drive(demo_repo, pick, "K")  # already first: nothing to do
    assert last_commit(git, demo_repo) == before


def test_dependency_edge_adds_an_after(demo_repo, git):
    def pick(app):
        app.jump_to("draft-methods")  # goal write-up
        app.column("mid").focus()

    drive(demo_repo, pick, "a", lambda app: pick_option(app, "draft-results"), "enter")
    task = Content.open(demo_repo).task("draft-methods")
    assert "draft-results" in task.depends_on
    assert last_commit(git, demo_repo) == "task: edit draft-methods (depends_on)"


def test_dependency_cycle_leaves_a_toast_and_no_commit(demo_repo, git):
    def pick(app):
        app.jump_to("draft-methods")
        app.column("mid").focus()

    before = last_commit(git, demo_repo)
    # send-draft already waits on draft-methods: this edge would close a cycle.
    drive(demo_repo, pick, "a", lambda app: pick_option(app, "send-draft"), "enter")
    assert last_commit(git, demo_repo) == before
    assert "send-draft" not in Content.open(demo_repo).task("draft-methods").depends_on


def test_dependency_edge_can_be_removed(demo_repo, git):
    def pick(app):
        app.jump_to("compare-methods")  # waits on run-baseline and run-adaptive
        app.column("mid").focus()

    drive(demo_repo, pick, "A", lambda app: pick_option(app, "run-baseline"), "enter")
    task = Content.open(demo_repo).task("compare-methods")
    assert task.depends_on == ["run-adaptive"]
    assert last_commit(git, demo_repo) == "task: edit compare-methods (depends_on)"


def test_move_a_loose_task_to_another_project(demo_repo, git):
    def pick(app):
        to_thesis(app)
        app.jump_to("renew-cluster-account")

    drive(demo_repo, pick, "m", lambda app: pick_option(app, "teaching|"), "enter")
    moved = Content.open(demo_repo).task("renew-cluster-account")
    assert (moved.project, moved.goal) == ("teaching", None)
    assert last_commit(git, demo_repo) == "task: move renew-cluster-account -> project teaching"
    assert not (demo_repo / "projects/thesis/tasks/renew-cluster-account.md").exists()
    assert (demo_repo / "projects/teaching/tasks/renew-cluster-account.md").is_file()


def test_move_a_task_into_a_goal(demo_repo, git):
    def pick(app):
        to_thesis(app)
        app.jump_to("renew-cluster-account")

    drive(demo_repo, pick, "m", lambda app: pick_option(app, "thesis|write-up"), "enter")
    moved = Content.open(demo_repo).task("renew-cluster-account")
    assert (moved.project, moved.goal) == ("thesis", "write-up")
    assert last_commit(git, demo_repo) == "task: move renew-cluster-account"


def test_move_a_goal_to_another_project_takes_its_tasks(demo_repo, git):
    def pick(app):
        to_thesis(app)
        app.column("list").focus()
        app.column("list").select_key("goal:grade-hw2" if False else "goal:write-up")

    drive(demo_repo, pick, "m", lambda app: pick_option(app, "teaching|"), "enter")
    content = Content.open(demo_repo)
    goal = content.goal("write-up")
    assert goal.project == "teaching"
    assert all(t.project == "teaching" for t in content.goal_tasks(goal))


def test_flow_board_opens_toggles_and_pops(demo_repo):
    opened = drive(demo_repo, to_thesis, "f")
    assert opened["screen"] == "FlowScreen"
    assert opened["screen_view"] == "stage"
    toggled = drive(demo_repo, to_thesis, "f", "f")
    assert toggled["screen_view"] == "status"
    assert drive(demo_repo, to_thesis, "f", "escape")["screen"] == "Screen"


def test_flow_board_jumps_back_to_the_hierarchy(demo_repo):
    def on_board(app):
        assert isinstance(app.screen, FlowScreen)

    seen = drive(demo_repo, to_thesis, "f", on_board, "enter")
    assert seen["scope"] == "project"
    assert seen["project"] == "thesis"
    assert seen["current"]["list"] is not None


def test_goal_column_special_rows_fill_the_right_columns(demo_repo):
    """`◆ deliverables` lists the project's deliverables; `loose tasks` its loose
    tasks. Both are separate rows in the goal column, and the preview follows
    whichever column has focus."""

    def deliverables(app):
        to_thesis(app)
        app.column("list").focus()
        app.column("list").select_key("deliverables:thesis")

    seen = drive(demo_repo, deliverables)
    assert seen["rows"]["mid"] == ["deliverable:workshop-talk", "deliverable:icml-paper"]
    assert seen["preview"] == "deliverables"

    def loose(app):
        to_thesis(app)
        app.column("list").focus()
        app.column("list").select_key("loose:thesis")

    seen = drive(demo_repo, loose)
    content = Content.open(demo_repo)
    loose_ids = {t.id for t in model.loose_tasks(content, content.project("thesis"))}
    assert set(seen["rows"]["mid"]) == {f"task:{i}" for i in loose_ids}
    assert seen["preview"] == model.LOOSE


def test_narrow_drops_the_goal_column_and_says_so(demo_repo):
    wide = drive(demo_repo, to_thesis)
    assert wide["visible"] == ["list", "mid", "preview"]
    narrow = drive(demo_repo, to_thesis, size=(80, 24))
    assert narrow["visible"] == ["mid", "preview"]
    assert narrow["hidden"] == ["list"]
    assert narrow["breadcrumb"][0] == "thesis"
    assert narrow["focused"] in ("mid", "preview")
    sixty = drive(demo_repo, to_thesis, size=(60, 20))
    assert sixty["visible"] == ["mid", "preview"]
    assert sixty["breadcrumb"][0] == "thesis"


def test_selected_row_has_a_bar_bright_in_the_focused_column(demo_repo):
    seen: dict[str, object] = {}

    def look(app):
        for name in ("list", "mid"):
            column = app.column(name)
            lines = [column.render_line(y) for y in range(2)]
            seen[name] = [line.text[0] for line in lines]
            seen[name + " colour"] = lines[0]._segments[0].style.color

    drive(demo_repo, to_thesis, "enter", look)
    assert seen["list"] == ["▌", " "]
    assert seen["mid"] == ["▌", " "]
    assert seen["list colour"] != seen["mid colour"]  # dim where focus isn't


def test_subprojects_are_listed_and_open_with_enter(demo_repo):
    seen = drive(demo_repo, to_thesis)
    assert seen["rows"]["list"][0] == "sub:ablations"

    seen = drive(demo_repo, to_thesis, "enter")
    assert seen["project"] == "ablations"
    assert seen["breadcrumb"] == ["thesis", "ablations"]
    assert Text.from_ansi(seen["hints"]).plain.strip().startswith("h back to thesis")

    seen = drive(demo_repo, to_thesis, "enter", "h")
    assert seen["project"] == "thesis"
    assert seen["current"]["list"] == "sub:ablations"


def test_space_and_x_on_a_subproject_finish_and_reopen_it(demo_repo, git):
    drive(demo_repo, to_thesis, "space")
    assert last_commit(git, demo_repo) == "project: done ablations"
    assert Content.open(demo_repo).project("ablations").status == "done"
    drive(demo_repo, to_thesis, "x")
    assert last_commit(git, demo_repo) == "project: reopen ablations"
    assert Content.open(demo_repo).project("ablations").status == "active"


def test_d_drops_a_subproject_with_what_is_in_it(demo_repo, git):
    content = Content.open(demo_repo)
    tasks = len(content.tasks(content.project("ablations")))

    def question(app):
        assert app.screen.question.startswith("Drop project ablations with")
        assert f"{tasks} tasks" in app.screen.question

    drive(demo_repo, to_thesis, "D", question, "y")
    assert last_commit(git, demo_repo) == "project: drop ablations"
    assert not (demo_repo / "projects" / "thesis" / "subprojects" / "ablations").exists()


def test_tiny_layout_asks_for_a_bigger_window(demo_repo):
    seen = drive(demo_repo, size=(30, 10))
    assert "tiny" in seen["classes"]


def test_help_project_picker_and_people_list_open(demo_repo):
    assert drive(demo_repo, "?")["screen"] == "Help"
    assert drive(demo_repo, "P")["screen"] == "Picker"
    assert drive(demo_repo, "2", "at", "l")["screen"] == "ListScreen"
    assert drive(demo_repo, "2", "at", "a")["screen"] == "Picker"


def test_project_picker_switches_project(demo_repo):
    def choose(app):
        pick_option(app, "teaching")

    seen = drive(demo_repo, "P", choose, "enter")
    assert seen["project"] == "teaching"


def picker_ids(app: TavlaApp) -> list[str]:
    return [str(o.id) for o in app.screen.query_one("#choices").options if not o.disabled]


def test_typing_in_a_picker_filters_it(demo_repo):
    seen: dict[str, list[str]] = {}

    def look(name):
        return lambda app: seen.__setitem__(name, picker_ids(app))

    drive(demo_repo, "P", look("all"), "type:teach", look("teach"), "type:zzz", look("none"))
    assert len(seen["all"]) > 1
    assert seen["teach"] == ["teaching"]
    assert seen["none"] == []


def test_picker_enter_takes_the_first_match_and_esc_clears_first(demo_repo):
    seen = drive(demo_repo, "P", "type:teach", "enter")
    assert seen["project"] == "teaching"
    seen = drive(demo_repo, "P", "type:teach", "escape")
    assert seen["screen"] == "Picker"
    assert drive(demo_repo, "P", "type:teach", "escape", "escape")["screen"] != "Picker"


def test_picker_letters_filter_and_arrows_move(demo_repo):
    # j and k are text here: they don't move the cursor
    seen: dict[str, object] = {}
    drive(
        demo_repo,
        "P",
        "down",
        lambda app: seen.__setitem__("at", app.screen.query_one("#choices").highlighted),
        "type:j",
        lambda app: seen.__setitem__("typed", app.screen.query_one("#filter").value),
    )
    assert seen == {"at": 1, "typed": "j"}


def test_filter_keeps_the_parent_of_a_matching_task(demo_repo):
    def set_filter(app):
        to_thesis(app)
        app.filter = "baseline"
        app.reload()

    seen = drive(demo_repo, set_filter)
    # the goal that holds it stays, and a dim marker counts what went
    assert seen["rows"]["list"][0] == "goal:experiments"
    assert "hidden:list" in seen["rows"]["list"]
    assert "task:run-baseline" in seen["rows"]["mid"]
    assert seen["filter"] == "baseline"


def test_filter_with_no_match_shows_nothing(demo_repo):
    def set_filter(app):
        to_thesis(app)
        app.filter = "zzzz-nothing"
        app.reload()

    seen = drive(demo_repo, set_filter)
    assert "task:" not in " ".join(seen["rows"]["mid"])


def test_g_and_gg_move_in_a_column(demo_repo):
    start = drive(demo_repo, "2")["current"]["list"]
    last = drive(demo_repo, "2", "G")["current"]["list"]
    assert last != start
    assert drive(demo_repo, "2", "G", "g", "g")["current"]["list"] == start


def test_work_and_pause(demo_repo, git):
    def pick(app):
        app.column("list").focus()
        app.column("list").select_key("task:run-baseline")

    drive(demo_repo, "2", pick, "w")
    assert focus.current(Content.open(demo_repo)) is not None
    assert last_commit(git, demo_repo).startswith("focus: work on run-baseline")

    drive(demo_repo, "2", pick, "w")  # on the task being worked on: pause
    assert focus.current(Content.open(demo_repo)) is None
    assert last_commit(git, demo_repo).startswith("focus: pause run-baseline")


def test_preview_cursor_lands_on_the_first_open_subtask(demo_repo, git):
    def pick(app):
        app.column("list").focus()
        app.column("list").select_key("task:run-baseline")

    before = Content.open(demo_repo).task("run-baseline").subtasks
    assert [s.done for s in before[:3]] == [True, True, False]
    drive(demo_repo, "2", pick, "l", "space")
    after = Content.open(demo_repo).task("run-baseline").subtasks
    assert [s.done for s in after[:3]] == [True, True, True]


def test_shift_w_opens_a_task_terminal(demo_repo, git, monkeypatch):
    from tavla.core import terminal

    launched: list[list[str]] = []
    monkeypatch.setenv(terminal.ENV_TERMINAL, "kitty")
    monkeypatch.setattr(terminal.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(terminal, "spawn", lambda cmd, cwd: launched.append(cmd))

    def pick(app):
        app.column("list").focus()
        app.column("list").select_key("task:run-baseline")

    drive(demo_repo, "2", pick, "W")
    assert launched[0][-2:] == ["session", "run-baseline"]
    assert Content.open(demo_repo).task("run-baseline").status == TaskStatus.DOING
    assert focus.current(Content.open(demo_repo)) is None  # not the one-task focus


def test_note_appends_to_updates(demo_repo, git):
    def pick(app):
        app.column("list").focus()
        app.column("list").select_key("task:run-baseline")

    drive(demo_repo, "2", pick, "n", "type:outline checked", "enter")
    assert "outline checked" in Content.open(demo_repo).task("run-baseline").body
    assert last_commit(git, demo_repo).startswith("task: note run-baseline")


def test_due_prompt_replaces_the_old_date(demo_repo):
    def pick(app):
        app.column("list").focus()
        app.column("list").select_key("task:run-baseline")

    drive(demo_repo, "2", pick, "t", "type:2030-01-31", "enter")
    assert str(Content.open(demo_repo).task("run-baseline").due) == "2030-01-31"


def test_priority_cycles(demo_repo, git):
    def pick(app):
        app.column("list").focus()
        app.column("list").select_key("task:run-baseline")

    before = Content.open(demo_repo).task("run-baseline").priority
    drive(demo_repo, "2", pick, "exclamation_mark")
    assert Content.open(demo_repo).task("run-baseline").priority != before
    assert last_commit(git, demo_repo) == "task: edit run-baseline (priority)"


def test_drop_asks_and_refuses_with_dependents(demo_repo, git):
    def pick(task_id):
        def choose(app):
            app.column("list").focus()
            app.column("list").select_key(f"task:{task_id}")

        return choose

    before = last_commit(git, demo_repo)
    drive(demo_repo, "2", pick("run-baseline"), "D")  # depended on: refused, no question
    assert last_commit(git, demo_repo) == before

    drive(demo_repo, "2", pick("renew-cluster-account"), "D", "n")
    assert last_commit(git, demo_repo) == before

    drive(demo_repo, "2", pick("renew-cluster-account"), "D", "y")
    assert last_commit(git, demo_repo) == "task: drop renew-cluster-account"
    drive(demo_repo, "u", "y")
    assert last_commit(git, demo_repo) == "undo: task: drop renew-cluster-account"
    assert Content.open(demo_repo).task("renew-cluster-account")


def test_tick_subtask_from_the_preview(demo_repo):
    def pick(app):
        app.jump_to("run-baseline")
        app.preview().focus()
        app.preview().select_key("sub:3")  # the first unchecked subtask

    drive(demo_repo, pick, "space")
    task = Content.open(demo_repo).task("run-baseline")
    assert [s.done for s in task.subtasks] == [True, True, True, False]


def test_adding_a_task_with_o(demo_repo, git):
    def on_a_task(app):
        app.jump_to("draft-results")  # the write-up goal's task column

    drive(demo_repo, on_a_task, "o", "type:Polish figures", "enter")
    content = Content.open(demo_repo)
    assert content.task("polish-figures").goal == "write-up"
    assert last_commit(git, demo_repo).startswith("task: add polish-figures")


def test_adding_a_subtask_with_o_in_the_preview(demo_repo):
    def on_a_subtask(app):
        app.jump_to("run-baseline")
        app.preview().focus()
        app.preview().select_key("sub:1")

    drive(demo_repo, on_a_subtask, "o", "type:Sanity check", "enter")
    subtasks = [s.text for s in Content.open(demo_repo).task("run-baseline").subtasks]
    assert subtasks[-1] == "Sanity check"


def test_adding_a_goal_with_big_o_from_a_task(demo_repo, git):
    def on_a_task(app):
        app.jump_to("run-baseline")

    drive(demo_repo, on_a_task, "O", "type:Polish figures", "enter")
    assert Content.open(demo_repo).goal("polish-figures").project == "thesis"
    assert last_commit(git, demo_repo).startswith("goal: add polish-figures")


def test_reloads_when_something_else_commits(demo_repo):
    seen = {}

    def outside(app):
        content = Content.open(demo_repo)
        task_id = app.column("list").current.ref.id
        ops.complete(content, content.task(task_id))
        seen["before"] = app.column("list").current.key
        app.poll()
        seen["after"] = app.column("list").current.key

    drive(demo_repo, "2", outside)
    assert seen["before"] != seen["after"]


# --- CLI entry --------------------------------------------------------------------------


def test_bare_tv_prints_help_when_not_a_terminal():
    result = runner.invoke(cli, [])
    assert result.exit_code == 2
    assert "Usage" in result.output and "ui" in result.output


def test_ui_needs_a_content_repo(tmp_path):
    result = runner.invoke(cli, ["ui", "--content-dir", str(tmp_path / "nothing")])
    assert result.exit_code != 0
    assert "no tavla content repo" in result.output
