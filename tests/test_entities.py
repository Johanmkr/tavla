from __future__ import annotations

import datetime as dt

import pytest

from tavla.core.entities import (
    Priority,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    parse_ideas,
    parse_log,
    to_dict,
)
from tavla.core.errors import ValidationError


def _task(tmp_path, frontmatter: str, body: str = "# T\n"):
    path = tmp_path / "t.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}")
    return path


def test_task_defaults(tmp_path):
    task = Task.load(_task(tmp_path, "id: t1"), "proj")
    assert task.status == TaskStatus.TODO
    assert task.priority == Priority.MED
    assert task.title == "T"
    assert task.project == "proj"


def test_task_project_comes_from_directory_not_frontmatter(tmp_path):
    task = Task.load(_task(tmp_path, "id: t1\nproject: stale"), "actual")
    assert task.project == "actual"


def test_task_missing_id(tmp_path):
    with pytest.raises(ValidationError, match="missing required field 'id'"):
        Task.load(_task(tmp_path, "status: todo"), "p")


def test_task_invalid_status_lists_allowed_values(tmp_path):
    with pytest.raises(ValidationError, match="todo | doing | blocked | done"):
        Task.load(_task(tmp_path, "id: t\nstatus: wip"), "p")


def test_enum_values_are_case_insensitive(tmp_path):
    task = Task.load(_task(tmp_path, "id: t\nstatus: DOING\npriority: High"), "p")
    assert (task.status, task.priority) == (TaskStatus.DOING, Priority.HIGH)


def test_invalid_date(tmp_path):
    with pytest.raises(ValidationError, match="due"):
        Task.load(_task(tmp_path, "id: t\ndue: next week"), "p")


def test_string_date_is_parsed(tmp_path):
    task = Task.load(_task(tmp_path, "id: t\ndue: '2026-10-01'"), "p")
    assert task.due == dt.date(2026, 10, 1)


def test_title_falls_back_to_id(tmp_path):
    assert Task.load(_task(tmp_path, "id: t9", body="no heading"), "p").title == "t9"


def test_project_unknown_fields_kept_in_meta(tmp_path):
    (tmp_path / "project.yaml").write_text("id: p\nfunding: grant-123\n")
    project = Project.load(tmp_path)
    assert project.status == ProjectStatus.ACTIVE
    assert project.meta["funding"] == "grant-123"


def test_parse_log():
    entries = parse_log(
        "# Log\n\n- 2026-09-01: one\n- 2026-09-02 9:05: two\n* 2026-09-03 — three\nnot an entry\n"
    )
    assert [(e.date.day, e.text) for e in entries] == [(1, "one"), (2, "two"), (3, "three")]
    assert entries[1].time == dt.time(9, 5)


def test_parse_ideas():
    ideas = parse_ideas("# Inbox\n\n- one\n* [ ] two\nthree\n1. four\n")
    assert [i.text for i in ideas] == ["one", "two", "three", "four"]


def test_to_dict(tmp_path):
    task = Task.load(_task(tmp_path, "id: t\ndue: 2026-10-01"), "p")
    data = to_dict(task, tmp_path, exclude=("meta", "body"))
    assert data["path"] == "t.md"
    assert data["due"] == "2026-10-01"
    assert data["status"] == "todo"
    assert "body" not in data and "meta" not in data
