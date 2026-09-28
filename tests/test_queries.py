from __future__ import annotations

import datetime as dt

import pytest

from tavla.core import queries
from tavla.core.entities import Priority
from tavla.core.store import Content

TODAY = dt.date(2026, 9, 25)


@pytest.fixture
def content(basic_content) -> Content:
    return Content.open(basic_content)


def _write_task(content_root, project_dir, id_, **fields):
    fm = "".join(f"{k}: {v}\n" for k, v in {"id": id_, **fields}.items())
    path = content_root / project_dir / "tasks" / f"{id_}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n\n# {id_}\n")


# --- active_projects / last_activity -------------------------------------------


def test_active_projects(content):
    assert [p.id for p in queries.active_projects(content)] == ["project-a", "ablations"]


def test_subproject_of_paused_project_is_inactive(content_copy):
    path = content_copy / "projects/project-a/project.yaml"
    path.write_text(path.read_text().replace("status: active", "status: paused"))
    assert queries.active_projects(Content.open(content_copy)) == []


def test_last_activity_includes_subprojects(content):
    project_a = content.project("project-a")
    ablations = content.project("ablations")
    assert queries.last_activity(content, project_a) == dt.date(2026, 9, 20)
    assert queries.last_activity(content, ablations) == dt.date(2026, 8, 1)


def test_last_activity_uses_log(content_copy):
    (content_copy / "projects/project-a/subprojects/ablations/log.md").write_text(
        "- 2026-09-24: kicked off grid\n"
    )
    content = Content.open(content_copy)
    assert queries.last_activity(content, content.project("ablations")) == dt.date(2026, 9, 24)


# --- next ----------------------------------------------------------------------


def test_next_excludes_done_waiting_and_inactive(content):
    # get-feedback-from-advisor waits on draft-related-work; project-b is paused.
    ids = [t.id for t in queries.next_tasks(content)]
    assert ids == ["draft-related-work", "wait-for-cluster-allocation", "fix-plot-colors"]


def test_next_includes_task_once_dependency_done(content_copy):
    path = content_copy / "projects/project-a/tasks/draft-related-work.md"
    path.write_text(path.read_text().replace("status: todo", "status: done"))
    ids = [t.id for t in queries.next_tasks(Content.open(content_copy))]
    assert ids[0] == "get-feedback-from-advisor"


def test_goals_without_tasks(content):
    assert [g.id for g in queries.goals_without_tasks(content)] == ["write-methods"]
    project_b = content.project("project-b")
    assert [g.id for g in queries.goals_without_tasks(content, project=project_b)] == [
        "write-review"
    ]


def test_next_explicit_project_includes_paused(content_copy):
    _write_task(content_copy, "projects/project-b", "read-papers", status="todo")
    content = Content.open(content_copy)
    project_b = content.project("project-b")
    assert [t.id for t in queries.next_tasks(content, project=project_b)] == ["read-papers"]


def test_next_min_priority(content):
    ids = [t.id for t in queries.next_tasks(content, min_priority=Priority.MED)]
    assert ids == ["draft-related-work", "wait-for-cluster-allocation"]


def test_next_ordering(content_copy):
    a = "projects/project-a"
    _write_task(content_copy, a, "high-todo-late", priority="high", status="todo", due="2026-12-01")
    _write_task(content_copy, a, "high-todo-soon", priority="high", status="todo", due="2026-09-30")
    _write_task(content_copy, a, "high-todo-undated", priority="high", status="todo")
    _write_task(content_copy, a, "high-doing", priority="high", status="doing")
    _write_task(content_copy, a, "low-doing", priority="low", status="doing")
    ids = [t.id for t in queries.next_tasks(Content.open(content_copy))]
    assert ids == [
        "high-doing",
        "high-todo-soon",
        "draft-related-work",  # high and due 2026-10-01, both inherited from its goal
        "high-todo-late",
        "high-todo-undated",
        "wait-for-cluster-allocation",  # med
        "low-doing",
        "fix-plot-colors",
    ]


def test_next_breaks_ties_by_project_priority(content_copy):
    # ablations is med priority, project-a high: same task priority/status/due.
    _write_task(content_copy, "projects/project-a/subprojects/ablations", "a-sub", priority="med")
    _write_task(content_copy, "projects/project-a", "z-top", priority="med")
    ids = [t.id for t in queries.next_tasks(Content.open(content_copy))]
    assert ids.index("z-top") < ids.index("a-sub")


# --- status --------------------------------------------------------------------


def test_status(content):
    report = queries.status(content, today=TODAY)
    assert report.active_projects == 2
    assert (report.open_tasks, report.doing_tasks) == (4, 0)
    assert [(s.project.id, s.days_idle) for s in report.stale] == [("ablations", 55)]
    assert report.blocked == []
    assert [t.id for t in report.waiting] == ["get-feedback-from-advisor"]
    assert [t.id for t in report.due_tasks] == ["draft-related-work", "get-feedback-from-advisor"]
    assert [g.id for g in report.due_goals] == ["write-intro"]
    assert report.goals_ready == []
    assert report.deadlines == []
    assert report.inbox == 2


def test_status_blocked_task(content_copy):
    path = content_copy / "projects/project-a/tasks/fix-plot-colors.md"
    path.write_text(path.read_text().replace("status: todo", "status: blocked"))
    report = queries.status(Content.open(content_copy), today=TODAY)
    assert [t.id for t in report.blocked] == ["fix-plot-colors"]


def test_status_goal_ready_to_close(content_copy):
    for name in ("draft-related-work", "get-feedback-from-advisor"):
        path = content_copy / f"projects/project-a/tasks/{name}.md"
        path.write_text(path.read_text().replace("status: todo", "status: done"))
    report = queries.status(Content.open(content_copy), today=TODAY)
    assert [g.id for g in report.goals_ready] == ["write-intro"]


def test_status_thresholds(content):
    report = queries.status(content, today=TODAY, stale_days=60, deadline_days=365)
    assert report.stale == []
    assert [d.id for d in report.deadlines] == ["neurips-paper"]


def test_status_overdue_items_included(content):
    report = queries.status(content, today=dt.date(2027, 6, 1))
    assert {t.id for t in report.due_tasks} == {"draft-related-work", "get-feedback-from-advisor"}
    assert {g.id for g in report.due_goals} == {"write-intro", "write-methods"}
    assert [d.id for d in report.deadlines] == ["neurips-paper"]


def test_status_ignores_finished_deliverables(content_copy):
    path = content_copy / "projects/project-a/deliverables/neurips-paper.yaml"
    path.write_text(path.read_text().replace("status: drafting", "status: accepted"))
    report = queries.status(Content.open(content_copy), today=dt.date(2027, 5, 1))
    assert report.deadlines == []


def test_status_project_without_any_dates_is_stale(content_copy):
    d = content_copy / "projects/empty"
    d.mkdir()
    (d / "project.yaml").write_text("id: empty\nstatus: active\n")
    report = queries.status(Content.open(content_copy), today=TODAY)
    assert report.stale[0].project.id == "empty"
    assert report.stale[0].last_activity is None
