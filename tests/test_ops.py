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
    # 'write-intro' is a goal id; a project can't take it.
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


# --- subprojects ----------------------------------------------------------------


def test_add_subproject(content, git):
    parent = content.project("project-a")
    project = ops.add_project(content, "Sensitivity study", parent=parent)
    assert project.parent == "project-a"
    assert project.path == parent.path / "subprojects/sensitivity-study"
    assert (project.path / "log.md").is_file()
    registry = parsing.read_yaml(content.root / "registry.yaml")
    assert "sensitivity-study" not in [e["id"] for e in registry]
    assert _subjects(git, content.root)[0] == "project: add sensitivity-study under project-a"
    assert _is_clean(git, content.root)


def test_add_nested_subproject(content):
    project = ops.add_project(content, "Deeper", parent=content.project("ablations"))
    assert project.parent == "ablations"
    assert [p.id for p in content.descendants(content.project("project-a"))] == [
        "ablations",
        "deeper",
    ]


def test_move_project_under_another(content, git):
    goal_ids = {g.id for g in content.goals(content.project("project-b"))}
    moved = ops.move_project(content, content.project("project-b"), content.project("project-a"))
    assert moved.parent == "project-a"
    assert moved.path == content.root / "projects/project-a/subprojects/project-b"
    assert not (content.root / "projects/project-b").exists()
    # Its goals follow it, and it drops out of the registry.
    assert {g.id for g in content.goals(moved)} == goal_ids
    assert {g.project for g in content.goals(moved)} == {"project-b"}
    registry = parsing.read_yaml(content.root / "registry.yaml")
    assert "project-b" not in [e["id"] for e in registry]
    assert _subjects(git, content.root)[0] == "project: move project-b under project-a"
    assert _is_clean(git, content.root)


def test_move_subproject_to_top_level(content, git):
    ablations = content.project("ablations")
    task_ids = {t.id for t in content.tasks(ablations)}
    moved = ops.move_project(content, ablations, None)
    assert moved.parent is None
    assert moved.path == content.root / "projects/ablations"
    assert {t.id for t in content.tasks(moved)} == task_ids
    # The now-empty subprojects/ folder is cleaned up.
    assert not (content.root / "projects/project-a/subprojects").exists()
    registry = parsing.read_yaml(content.root / "registry.yaml")
    assert "ablations" in [e["id"] for e in registry]
    assert _subjects(git, content.root)[0] == "project: move ablations to top level"
    assert _is_clean(git, content.root)


def test_move_project_carries_its_subprojects(content):
    moved = ops.move_project(content, content.project("project-a"), content.project("project-b"))
    assert moved.parent == "project-b"
    assert content.project("ablations").parent == "project-a"
    assert [p.id for p in content.descendants(content.project("project-b"))] == [
        "project-a",
        "ablations",
    ]


def test_move_project_to_same_place_is_noop(content, git):
    before = _subjects(git, content.root)
    assert (
        ops.move_project(content, content.project("ablations"), content.project("project-a"))
        is None
    )
    assert ops.move_project(content, content.project("project-b"), None) is None
    assert _subjects(git, content.root) == before


@pytest.mark.parametrize("target", ["project-a", "ablations"])
def test_move_project_into_itself_rejected(content, target):
    with pytest.raises(ValidationError, match="inside it"):
        ops.move_project(content, content.project("project-a"), content.project(target))
    assert (content.root / "projects/project-a").is_dir()


def test_move_project_directory_clash_rejected(content):
    (content.root / "projects/project-a/subprojects/project-b").mkdir()
    with pytest.raises(ValidationError, match="already exists"):
        ops.move_project(content, content.project("project-b"), content.project("project-a"))
    assert (content.root / "projects/project-b/project.yaml").is_file()


# --- add_goal / add_task ------------------------------------------------------


def test_add_goal(content, git):
    project = content.project("project-b")
    goal = ops.add_goal(
        content,
        "Submit review",
        project,
        priority=Priority.HIGH,
        due=dt.date(2026, 12, 1),
        today=TODAY,
    )
    assert goal.path == project.path / "goals/submit-review.md"
    assert goal.path.read_text() == (
        "---\nid: submit-review\nproject: project-b\nstatus: todo\npriority: high\n"
        "tags: []\ncreated: 2026-09-25\nupdated: 2026-09-25\ndue: 2026-12-01\n---\n\n"
        "# Submit review\n\n## Context\n\n## Ideas\n\n## Updates\n"
    )
    assert _subjects(git, content.root)[0] == "goal: add submit-review"
    assert _is_clean(git, content.root)


def test_add_loose_task(content, git):
    project = content.project("project-b")
    task = ops.add_task(
        content,
        "Read Gelman 1992",
        project,
        due=dt.date(2026, 10, 3),
        tags=["reading"],
        today=TODAY,
    )
    assert task.id == "read-gelman-1992"
    assert task.path == project.path / "tasks/read-gelman-1992.md"
    assert task.path.read_text() == (
        "---\nid: read-gelman-1992\nproject: project-b\nstatus: todo\npriority: med\n"
        "tags: [reading]\ncreated: 2026-09-25\nupdated: 2026-09-25\ndue: 2026-10-03\n---\n\n"
        "# Read Gelman 1992\n\n## Instructions\n\n## Subtasks\n\n## Ideas\n\n## Updates\n"
    )
    assert (task.status, task.title, task.goal, task.subtasks_total) == (
        TaskStatus.TODO,
        "Read Gelman 1992",
        None,
        0,
    )
    assert _subjects(git, content.root)[0] == "task: add read-gelman-1992"
    assert _is_clean(git, content.root)


def test_add_task_under_goal_inherits(content):
    goal = content.goal("write-intro")
    task = ops.add_task(
        content, "Polish prose", goal=goal, depends_on=["draft-related-work"], today=TODAY
    )
    assert (task.project, task.goal) == ("project-a", "write-intro")
    text = task.path.read_text()
    assert "goal: write-intro\n" in text and "priority" not in text
    assert "depends_on: [draft-related-work]\n" in text
    assert (task.priority, task.inherited) == (Priority.HIGH, ["priority", "due"])
    assert task.waiting_on == ["draft-related-work"]


def test_add_task_goal_in_other_project_rejected(content):
    with pytest.raises(ValidationError, match="belongs to project"):
        ops.add_task(content, "x", content.project("project-b"), goal=content.goal("write-intro"))


def test_add_task_unknown_dependency_rejected(content, git):
    with pytest.raises(ValidationError, match="unknown task 'nope'"):
        ops.add_task(content, "x", content.project("project-a"), depends_on=["nope"])
    assert not (content.root / "projects/project-a/tasks/x.md").exists()
    assert _is_clean(git, content.root)


def test_add_task_needs_goal_or_project(content):
    with pytest.raises(ValidationError, match="goal or a project"):
        ops.add_task(content, "x")


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


def test_edit_unchanged_is_noop(content, git):
    goal = content.goal("write-intro")
    session = ops.EditSession(goal.path)
    assert ops.finish_edit(content, goal, session, today=TODAY) is None
    assert _subjects(git, content.root) == ["initial"]


def test_task_edit_commits_and_bumps_updated(content, git):
    task = content.task("draft-related-work")
    session = ops.EditSession(task.path)
    _edit(task.path, "- [ ] Write two paragraphs", "- [x] Write two paragraphs")
    edited = ops.finish_edit(content, task, session, today=TODAY)
    assert edited.updated == TODAY
    assert edited.subtasks_done == 2
    assert _subjects(git, content.root)[0] == "task: edit draft-related-work"
    assert _is_clean(git, content.root)


def test_goal_edit_keeps_user_set_updated(content):
    goal = content.goal("write-intro")
    session = ops.EditSession(goal.path)
    _edit(goal.path, "updated: 2026-09-20", "updated: 2026-09-22")
    assert ops.finish_edit(content, goal, session, today=TODAY).updated == dt.date(2026, 9, 22)


def test_edit_normalizes_day_first_dates(content, git):
    goal = content.goal("write-intro")
    session = ops.EditSession(goal.path)
    _edit(goal.path, "due: 2026-10-01", "due: 03.10.26")
    assert ops.finish_edit(content, goal, session, today=TODAY).due == dt.date(2026, 10, 3)
    assert "due: 2026-10-03\n" in goal.path.read_text()
    assert _is_clean(git, content.root)


def test_edit_rejects_yearless_date_in_file(content):
    goal = content.goal("write-intro")
    session = ops.EditSession(goal.path)
    _edit(goal.path, "due: 2026-10-01", "due: 03.10")
    with pytest.raises(ValidationError, match="invalid due date"):
        ops.finish_edit(content, goal, session, today=TODAY)


def test_edit_invalid_is_not_committed(content, git):
    goal = content.goal("write-intro")
    session = ops.EditSession(goal.path)
    _edit(goal.path, "status: doing", "status: wip")
    with pytest.raises(ValidationError, match="wip"):
        ops.finish_edit(content, goal, session, today=TODAY)
    assert _subjects(git, content.root) == ["initial"]
    session.restore()
    assert _is_clean(git, content.root)


def test_edit_id_collision(content):
    goal = content.goal("write-intro")
    session = ops.EditSession(goal.path)
    _edit(goal.path, "id: write-intro", "id: fix-plot-colors")  # a task id: ids are global
    with pytest.raises(ValidationError, match="already used"):
        ops.finish_edit(content, goal, session, today=TODAY)


def test_goal_rename_updates_its_tasks(content, git):
    goal = content.goal("write-intro")
    session = ops.EditSession(goal.path)
    _edit(goal.path, "id: write-intro", "id: intro")
    assert ops.finish_edit(content, goal, session, today=TODAY).id == "intro"
    assert _subjects(git, content.root)[0] == "goal: rename write-intro -> intro"
    assert content.goal("intro").path.name == "write-intro.md"  # filename is irrelevant
    assert {t.id for t in content.goal_tasks(content.goal("intro"))} == {
        "outline-structure",
        "draft-related-work",
        "get-feedback-from-advisor",
    }
    assert _is_clean(git, content.root)


def test_task_rename_updates_dependents(content, git):
    task = content.task("draft-related-work")
    session = ops.EditSession(task.path)
    _edit(task.path, "id: draft-related-work", "id: draft")
    ops.finish_edit(content, task, session, today=TODAY)
    assert content.task("get-feedback").depends_on == ["draft"]
    assert _is_clean(git, content.root)


def test_task_edit_rejects_dependency_cycle(content):
    task = content.task("draft-related-work")
    session = ops.EditSession(task.path)
    _edit(task.path, "status: todo", "status: todo\ndepends_on: [get-feedback-from-advisor]")
    with pytest.raises(ValidationError, match="cycle: draft-related-work -> get-feedback"):
        ops.finish_edit(content, task, session, today=TODAY)


def test_task_edit_rejects_unknown_goal(content):
    task = content.task("fix-plot-colors")
    session = ops.EditSession(task.path)
    _edit(task.path, "status: todo", "status: todo\ngoal: nope")
    with pytest.raises(ValidationError, match="unknown goal 'nope'"):
        ops.finish_edit(content, task, session, today=TODAY)


def test_project_edit_syncs_registry(content, git):
    project = content.project("project-b")
    session = ops.EditSession(project.path / "project.yaml")
    _edit(project.path / "project.yaml", "status: paused", "status: active")
    assert ops.finish_project_edit(content, project, session).status == ProjectStatus.ACTIVE
    registry = {e["id"]: e["status"] for e in parsing.read_yaml(content.root / "registry.yaml")}
    assert registry["project-b"] == "active"
    assert _subjects(git, content.root)[0] == "project: edit project-b"
    assert _is_clean(git, content.root)


# --- field edits ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("x, y", ["x", "y"]), ("+c,-a", ["b", "c"]), ("+a", ["a", "b"]), ("-zzz", ["a", "b"])],
)
def test_apply_tags(spec, expected):
    assert ops.apply_list_spec(["a", "b"], spec) == expected


def test_apply_tags_mixed_is_error():
    with pytest.raises(ValidationError):
        ops.apply_list_spec([], "a,+b")


def test_set_fields_keeps_comments_and_order(content, git):
    goal = content.goal("write-intro")
    goal.path.write_text(goal.path.read_text().replace("priority: high", "priority: high  # !"))
    git(content.root, "commit", "-qam", "comment")
    content.refresh()
    ops.set_fields(content, content.goal("write-intro"), {"status": "blocked"}, today=TODAY)
    text = goal.path.read_text()
    assert "status: blocked\npriority: high  # !\n" in text
    assert "updated: 2026-09-25" in text
    assert _subjects(git, content.root)[0] == "goal: edit write-intro (status)"
    assert _is_clean(git, content.root)


def test_set_fields_invalid_restores(content, git):
    goal = content.goal("write-intro")
    before = goal.path.read_text()
    with pytest.raises(ValidationError):
        ops.set_fields(content, goal, {"status": "wip"}, today=TODAY)
    assert goal.path.read_text() == before


def test_set_fields_cycle_restores(content, git):
    task = content.task("draft-related-work")
    before = task.path.read_text()
    with pytest.raises(ValidationError, match="cycle"):
        ops.set_fields(content, task, {"depends_on": ["get-feedback-from-advisor"]}, today=TODAY)
    assert task.path.read_text() == before
    assert _is_clean(git, content.root)


def test_set_fields_moves_task_to_goal(content):
    task = ops.set_fields(content, content.task("fix-plot"), {"goal": "write-intro"}, today=TODAY)
    assert task.goal == "write-intro"
    assert content.goal("write-intro").tasks_total == 4
