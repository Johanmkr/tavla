from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from tavla.core.errors import AmbiguousIdError, NotFoundError, TavlaError
from tavla.core.queries import complete_ids, resolve_id
from tavla.core.store import Content


def test_open_requires_initialized_dir(tmp_path):
    with pytest.raises(TavlaError, match="tavla init"):
        Content.open(tmp_path)


def test_projects_include_subprojects_after_parent(basic_content):
    content = Content.open(basic_content)
    ids = [(p.id, p.parent) for p in content.projects()]
    assert ids == [
        ("project-a", None),
        ("ablations", "project-a"),
        ("project-b", None),
        ("project-c", None),
    ]


def test_open_refuses_old_layout(content_copy):
    (content_copy / "tavla.yaml").unlink()
    with pytest.raises(TavlaError, match="tavla migrate"):
        Content.open(content_copy)


def test_open_refuses_newer_layout(content_copy):
    (content_copy / "tavla.yaml").write_text("schema_version: 99\n")
    with pytest.raises(TavlaError, match="update tavla"):
        Content.open(content_copy)


def test_goals_recursive_by_default(basic_content):
    content = Content.open(basic_content)
    project_a = content.project("project-a")
    assert {g.id for g in content.goals(project_a)} == {
        "setup-env",
        "write-intro",
        "write-methods",
        "run-ablations",
    }
    assert "run-ablations" not in {g.id for g in content.goals(project_a, recursive=False)}


def test_tasks_recursive_by_default(basic_content):
    content = Content.open(basic_content)
    project_a = content.project("project-a")
    assert {t.id for t in content.tasks(project_a)} == {
        "request-cluster-account",
        "build-container",
        "outline-structure",
        "draft-related-work",
        "get-feedback-from-advisor",
        "fix-plot-colors",
        "wait-for-cluster-allocation",
    }
    assert "wait-for-cluster-allocation" not in {
        t.id for t in content.tasks(project_a, recursive=False)
    }


def test_subproject_items_belong_to_subproject(basic_content):
    content = Content.open(basic_content)
    assert content.goal("run-ablations").project == "ablations"
    assert content.task("wait-for").project == "ablations"


def test_goal_progress_counts_its_tasks(basic_content):
    content = Content.open(basic_content)
    goal = content.goal("write-intro")
    assert (goal.tasks_done, goal.tasks_total) == (1, 3)
    assert [t.id for t in content.goal_tasks(goal)] == [
        "draft-related-work",
        "get-feedback-from-advisor",
        "outline-structure",
    ]
    assert content.goal("write-methods").tasks_total == 0


def test_task_inherits_priority_and_due_from_goal(basic_content):
    content = Content.open(basic_content)
    task = content.task("draft-related-work")
    assert (task.priority, task.due) == ("high", dt.date(2026, 10, 1))
    assert task.inherited == ["priority", "due"]
    loose = content.task("fix-plot-colors")
    assert (loose.goal, loose.priority, loose.inherited) == (None, "low", [])


def test_own_priority_wins_over_goal(content_copy):
    path = content_copy / "projects/project-a/tasks/draft-related-work.md"
    path.write_text(path.read_text().replace("status: todo", "status: todo\npriority: low"))
    task = Content.open(content_copy).task("draft-related-work")
    assert task.priority == "low"
    assert task.inherited == ["due"]


def test_subtask_rollup_from_fixture(basic_content):
    task = Content.open(basic_content).task("draft-related-work")
    assert (task.subtasks_done, task.subtasks_total) == (1, 2)


def test_waiting_on_unfinished_dependencies(content_copy):
    content = Content.open(content_copy)
    assert content.task("get-feedback").waiting_on == ["draft-related-work"]
    path = content_copy / "projects/project-a/tasks/draft-related-work.md"
    path.write_text(path.read_text().replace("status: todo", "status: done"))
    content.refresh()
    assert content.task("get-feedback").waiting_on == []


def test_unknown_dependency_counts_as_waiting(content_copy):
    path = content_copy / "projects/project-a/tasks/fix-plot-colors.md"
    path.write_text(path.read_text().replace("status: todo", "status: todo\ndepends_on: [gone]"))
    assert Content.open(content_copy).task("fix-plot").waiting_on == ["gone"]


def test_other_project_files(basic_content):
    content = Content.open(basic_content)
    project = content.project("project-a")
    assert [d.id for d in content.deliverables(project)] == ["neurips-paper"]
    assert [e.text for e in content.log(project)][-1].startswith("First results")
    assert [r.id for r in content.references(project)] == ["vaswani2017attention"]
    assert len(content.ideas(project)) == 1
    assert len(content.inbox()) == 2
    assert content.sources()[0].year == 2017


def test_demo_content_is_valid():
    """The demo content (``tavla demo``, the docs' examples) must stay loadable
    and pass ``tavla check``."""
    from tavla.core import check

    root = Path(__file__).parent.parent / "src/tavla/demo_content"
    content = Content.open(root)
    assert {p.id for p in content.projects()} >= {"thesis", "ablations", "teaching"}
    assert content.tasks() and content.goals() and content.deliverables()
    assert check.find_problems(content) == []


class _Item:
    def __init__(self, id_: str, title: str = ""):
        self.id = id_
        self.title = title
        self.path = f"/{id_}"


ITEMS = [
    _Item("write-intro", "Write introduction"),
    _Item("write-methods", "Write methods section"),
    _Item("write", "Write"),
    _Item("setup-env", "Set up compute environment"),
]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("setup", "setup-env"),
        ("write-i", "write-intro"),
        ("write", "write"),
        ("methods", "write-methods"),  # substring of the id
        ("COMPUTE", "setup-env"),  # substring of the title, any case
    ],
)
def test_resolve_id(query, expected):
    assert resolve_id(query, ITEMS).id == expected


def test_resolve_id_ambiguous_lists_candidates():
    with pytest.raises(AmbiguousIdError) as exc:
        resolve_id("write-", ITEMS)
    assert exc.value.candidates == ["write-intro", "write-methods"]


def test_resolve_id_not_found():
    with pytest.raises(NotFoundError):
        resolve_id("nope", ITEMS, "task")


def test_resolve_id_duplicate_exact_is_ambiguous():
    with pytest.raises(AmbiguousIdError):
        resolve_id("dup", [_Item("dup"), _Item("dup")])


def test_resolve_id_loose_match_ambiguous():
    with pytest.raises(AmbiguousIdError) as exc:
        resolve_id("on", ITEMS)
    assert exc.value.candidates == ["setup-env", "write-intro", "write-methods"]


def test_complete_ids():
    assert complete_ids("write-", ITEMS) == [
        ("write-intro", "Write introduction"),
        ("write-methods", "Write methods section"),
    ]
    assert [i for i, _ in complete_ids("wr", ITEMS)] == ["write", "write-intro", "write-methods"]
    assert complete_ids("environment", ITEMS) == []
