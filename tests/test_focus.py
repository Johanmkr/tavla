"""Working on one task at a time: tv work / pause / done and the short commands."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import focus, ops
from tavla.core.check import find_problems
from tavla.core.entities import TaskStatus
from tavla.core.errors import EXIT_INVALID, TavlaError, ValidationError
from tavla.core.store import Content

runner = CliRunner()
START = dt.datetime(2026, 10, 12, 9, 30)  # noqa: DTZ001 — sessions store naive local time


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


@pytest.fixture
def run(git_content):
    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(git_content), *args])

    return _run


def _subjects(git, repo, n: int) -> list[str]:
    return git(repo, "log", f"-{n}", "--format=%s").splitlines()


def _clean(git, repo) -> bool:
    return git(repo, "status", "--porcelain") == ""


# --- core ----------------------------------------------------------------------


def test_enter_marks_doing_and_records_focus(content, git):
    current = focus.enter(content, content.task("draft-related-work"), now=START)
    assert current is not None
    assert (current.task_id, current.since) == ("draft-related-work", START)
    assert content.task("draft-related-work").status == TaskStatus.DOING
    assert _subjects(git, content.root, 1) == ["focus: work on draft-related-work"]
    assert _clean(git, content.root)


def test_enter_same_task_is_noop_and_other_is_refused(content):
    focus.enter(content, content.task("draft-related-work"), now=START)
    assert focus.enter(content, content.task("draft-related-work")) is None
    with pytest.raises(ValidationError, match="working on 'draft-related-work'"):
        focus.enter(content, content.task("fix-plot-colors"))


def test_pause_records_session(content, git):
    focus.enter(content, content.task("draft-related-work"), now=START)
    _, task, session = focus.pause(
        content, note=" first  pass ", now=START + dt.timedelta(minutes=95)
    )
    assert focus.current(content) is None
    assert task is not None
    assert "- 2026-10-12 09:30-11:05 (1h35m): first pass" in task.path.read_text()
    reloaded = content.task("draft-related-work")
    assert reloaded.status == TaskStatus.DOING
    assert reloaded.updated == START.date()
    assert focus.sessions(reloaded) == [session]
    assert _subjects(git, content.root, 1) == ["focus: pause draft-related-work (1h35m)"]
    assert _clean(git, content.root)


def test_session_over_midnight_and_total(content):
    task = content.task("draft-related-work")
    focus.enter(content, task, now=START)
    focus.pause(content, now=START + dt.timedelta(minutes=30))
    late = dt.datetime(2026, 10, 12, 23, 30)  # noqa: DTZ001
    focus.enter(content, task, now=late)
    focus.pause(content, now=late + dt.timedelta(hours=2))
    task = content.task("draft-related-work")
    assert "- 2026-10-12 23:30-2026-10-13 01:30 (2h00m)" in task.path.read_text()
    assert focus.total_time(task) == dt.timedelta(hours=2, minutes=30)


def test_pause_without_focus(content):
    with pytest.raises(TavlaError, match="aren't working"):
        focus.pause(content)


def test_finish_focused_task_in_one_commit(content, git):
    focus.enter(content, content.task("draft-related-work"), now=START)
    task, session = focus.finish(
        content, content.task("draft-related-work"), now=START + dt.timedelta(minutes=10)
    )
    assert task is not None and task.status == TaskStatus.DONE
    assert session is not None and session.duration == dt.timedelta(minutes=10)
    assert focus.current(content) is None
    assert _subjects(git, content.root, 1) == ["task: done draft-related-work"]
    assert _clean(git, content.root)


def test_finish_other_task_keeps_focus(content):
    focus.enter(content, content.task("draft-related-work"), now=START)
    task, session = focus.finish(content, content.task("fix-plot-colors"))
    assert task is not None and session is None
    assert focus.current(content).task_id == "draft-related-work"  # type: ignore[union-attr]
    assert focus.finish(content, content.task("build-container")) == (None, None)


def test_sessions_skip_unparseable_lines(content):
    task = content.task("fix-plot-colors")
    task.path.write_text(
        task.path.read_text()
        + "\n## Sessions\n- 2026-10-01 10:00-10:45 (wrong)\n- yesterday a while\n"
    )
    content.refresh()
    sessions = focus.sessions(content.task("fix-plot-colors"))
    assert [s.duration for s in sessions] == [dt.timedelta(minutes=45)]


def test_drop_and_rename_respect_focus(content):
    focus.enter(content, content.task("fix-plot-colors"), now=START)
    with pytest.raises(ValidationError, match="tv pause"):
        ops.check_droppable(content, content.task("fix-plot-colors"))
    ops.set_fields(content, content.task("fix-plot-colors"), {"id": "fix-colors"})
    assert focus.current(content).task_id == "fix-colors"  # type: ignore[union-attr]


def test_check_reports_unknown_focus(content):
    (content.root / focus.FOCUS_FILE).write_text("task: gone\nsince: 2026-10-12 09:30\n")
    assert any("unknown task 'gone'" in p.message for p in find_problems(content))
    (content.root / focus.FOCUS_FILE).write_text("task: gone\nsince: soon\n")
    assert any("invalid since" in p.message for p in find_problems(content))


def test_pause_clears_focus_on_missing_task(content, git):
    focus.enter(content, content.task("fix-plot-colors"), now=START)
    path = content.root / focus.FOCUS_FILE
    path.write_text(path.read_text().replace("fix-plot-colors", "gone"))
    current, task, _ = focus.pause(content)
    assert (current.task_id, task) == ("gone", None)
    assert not path.exists()
    assert _clean(git, content.root)


# --- CLI -----------------------------------------------------------------------


def test_cli_work_flow(run, git_content, git):
    result = run("work", "draft-rel")
    assert result.exit_code == 0, result.output
    assert "Working on draft-related-work" in result.output

    result = run("work", "fix-plot")
    assert result.exit_code == EXIT_INVALID
    assert "tv pause" in result.output

    result = run("subtask", "Find", "three", "papers")
    assert result.exit_code == 0, result.output
    assert "3. [ ] Find three papers" in result.output
    result = run("tick", "3")
    assert result.exit_code == 0, result.output
    assert "3. [x] Find three papers" in result.output
    assert run("untick", "three").exit_code == 0
    result = run("note", "found", "two")
    assert "Noted on draft-related-work: found two" in result.output

    result = run("work")
    assert "Working on draft-related-work" in result.output
    assert "Total on this task" in result.output
    data = json.loads(run("work", "--json").output)
    assert data["task"] == "draft-related-work"

    assert "Working on draft-related-work" in run("next").output
    assert "Working on draft-related-work" in run("status").output
    assert json.loads(run("next", "--json").output)["working_on"] == "draft-related-work"

    result = run("pause", "intro", "half", "done")
    assert result.exit_code == 0, result.output
    assert "Paused draft-related-work" in result.output
    assert "Not working on anything" in run("work").output
    assert json.loads(run("work", "--json").output) is None
    assert _clean(git, git_content)


def test_cli_short_commands_need_focus(run):
    result = run("tick", "1")
    assert result.exit_code != 0
    assert "tv work TASK" in result.output


def test_cli_done_defaults_to_focus(run, git_content, git):
    run("work", "draft-related-work")
    result = run("done", "-m", "sent")
    assert result.exit_code == 0, result.output
    assert "Done: draft-related-work" in result.output
    assert "Now unblocked: get-feedback-from-advisor" in result.output
    text = (git_content / "projects/project-a/tasks/draft-related-work.md").read_text()
    assert "): sent" in text
    assert run("done").exit_code != 0  # nothing being worked on any more
    assert "fix-plot-colors" in run("task", "done", "fix-plot-colors").output
