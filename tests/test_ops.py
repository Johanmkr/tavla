from __future__ import annotations

import datetime as dt

import pytest

from tavla.core import ops, parsing
from tavla.core.entities import Priority, ProjectStatus, TaskStatus
from tavla.core.errors import GitError, ValidationError
from tavla.core.store import Content

TODAY = dt.date(2026, 9, 25)


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


def _subjects(git, repo) -> list[str]:
    return git(repo, "log", "--format=%s").splitlines()


def _is_clean(git, repo) -> bool:
    return git(repo, "status", "--porcelain") == ""


# --- add_project -------------------------------------------------------------


def test_add_project(content, git):
    project = ops.add_project(
        content, "Gaussian processes", priority=Priority.HIGH, tags=["gp"], today=TODAY
    )
    assert project.id == "gaussian-processes"
    assert project.status == ProjectStatus.ACTIVE
    assert project.priority == Priority.HIGH
    assert project.created == TODAY
    assert (project.path / "log.md").is_file()
    assert (project.path / "project.yaml").read_text() == (
        "id: gaussian-processes\ntitle: Gaussian processes\nstatus: active\n"
        "priority: high\ntags: [gp]\nrelated: []\ncreated: 2026-09-25\n"
    )
    registry = parsing.read_yaml(content.root / "registry.yaml")
    assert {
        "id": "gaussian-processes",
        "path": "projects/gaussian-processes",
        "status": "active",
    } in registry
    assert "ablations" not in [e["id"] for e in registry]  # subprojects aren't in the registry
    assert _subjects(git, content.root)[0] == "project: add gaussian-processes"
    assert _is_clean(git, content.root)


def test_add_project_dedupes_derived_id(content):
    assert ops.add_project(content, "Project A").id == "project-a-2"


def test_add_project_explicit_id_collision(content):
    with pytest.raises(ValidationError, match="already used"):
        ops.add_project(content, "Whatever", id="project-a")


def test_ids_are_global_across_entity_types(content):
    # 'write-intro' is a task id; a project can't take it.
    with pytest.raises(ValidationError, match="already used"):
        ops.add_project(content, "x", id="write-intro")


def test_add_project_requires_git_repo(content_copy):
    content = Content.open(content_copy)
    with pytest.raises(GitError, match="not a git repository"):
        ops.add_project(content, "New")
    assert not (content_copy / "projects/new").exists()


def test_empty_title_rejected(content):
    with pytest.raises(ValidationError, match="empty"):
        ops.add_project(content, "   ")


# --- add_task ----------------------------------------------------------------


def test_add_task(content, git):
    project = content.project("project-b")
    task = ops.add_task(
        content,
        "Read Gelman 1992",
        project,
        priority=Priority.HIGH,
        due=dt.date(2026, 10, 3),
        tags=["reading"],
        today=TODAY,
    )
    assert task.id == "read-gelman-1992"
    assert task.path == project.path / "tasks/read-gelman-1992.md"
    assert task.path.read_text() == (
        "---\nid: read-gelman-1992\nproject: project-b\nstatus: todo\npriority: high\n"
        "tags: [reading]\ncreated: 2026-09-25\nupdated: 2026-09-25\ndue: 2026-10-03\n---\n\n"
        "# Read Gelman 1992\n\n## Context\n\n## Subtasks\n\n## Updates\n"
    )
    assert (task.status, task.title, task.subtasks_total) == (
        TaskStatus.TODO,
        "Read Gelman 1992",
        0,
    )
    assert _subjects(git, content.root)[0] == "task: add read-gelman-1992"
    assert _is_clean(git, content.root)


def test_add_task_into_subproject(content):
    task = ops.add_task(content, "Sweep seeds", content.project("ablations"))
    assert task.project == "ablations"
    assert "subprojects/ablations/tasks" in task.path.as_posix()


def test_commit_leaves_unrelated_staged_changes_alone(content, git):
    (content.root / "inbox.md").write_text("# Inbox\n\n- staged by the user\n")
    git(content.root, "add", "inbox.md")
    ops.add_task(content, "New thing", content.project("project-a"))
    changed = git(content.root, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == ["projects/project-a/tasks/new-thing.md"]
    assert "M  inbox.md" in git(content.root, "status", "--porcelain")


# --- edits -------------------------------------------------------------------


def _edit(path, old, new):
    path.write_text(path.read_text().replace(old, new))


def test_task_edit_unchanged_is_noop(content, git):
    task = content.task("write-intro")
    session = ops.EditSession(task.path)
    assert ops.finish_task_edit(content, task, session, today=TODAY) is None
    assert _subjects(git, content.root) == ["initial"]


def test_task_edit_commits_and_bumps_updated(content, git):
    task = content.task("write-intro")
    session = ops.EditSession(task.path)
    _edit(task.path, "- [ ] Draft related work", "- [x] Draft related work")
    edited = ops.finish_task_edit(content, task, session, today=TODAY)
    assert edited.updated == TODAY
    assert edited.subtasks_done == 2
    assert _subjects(git, content.root)[0] == "task: edit write-intro"
    assert _is_clean(git, content.root)


def test_task_edit_keeps_user_set_updated(content):
    task = content.task("write-intro")
    session = ops.EditSession(task.path)
    _edit(task.path, "updated: 2026-09-20", "updated: 2026-09-22")
    assert ops.finish_task_edit(content, task, session, today=TODAY).updated == dt.date(2026, 9, 22)


def test_task_edit_invalid_is_not_committed(content, git):
    task = content.task("write-intro")
    session = ops.EditSession(task.path)
    _edit(task.path, "status: doing", "status: wip")
    with pytest.raises(ValidationError, match="wip"):
        ops.finish_task_edit(content, task, session, today=TODAY)
    assert _subjects(git, content.root) == ["initial"]
    session.restore()
    assert _is_clean(git, content.root)


def test_task_edit_id_collision(content):
    task = content.task("write-intro")
    session = ops.EditSession(task.path)
    _edit(task.path, "id: write-intro", "id: write-methods")
    with pytest.raises(ValidationError, match="already used"):
        ops.finish_task_edit(content, task, session, today=TODAY)


def test_task_edit_rename(content, git):
    task = content.task("write-intro")
    session = ops.EditSession(task.path)
    _edit(task.path, "id: write-intro", "id: intro")
    assert ops.finish_task_edit(content, task, session, today=TODAY).id == "intro"
    assert _subjects(git, content.root)[0] == "task: rename write-intro -> intro"
    assert content.task("intro").path.name == "write-intro.md"  # filename is irrelevant


def test_project_edit_syncs_registry(content, git):
    project = content.project("project-b")
    session = ops.EditSession(project.path / "project.yaml")
    _edit(project.path / "project.yaml", "status: paused", "status: active")
    assert ops.finish_project_edit(content, project, session).status == ProjectStatus.ACTIVE
    registry = {e["id"]: e["status"] for e in parsing.read_yaml(content.root / "registry.yaml")}
    assert registry["project-b"] == "active"
    assert _subjects(git, content.root)[0] == "project: edit project-b"
    assert _is_clean(git, content.root)
