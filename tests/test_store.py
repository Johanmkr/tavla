from __future__ import annotations

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


def test_tasks_recursive_by_default(basic_content):
    content = Content.open(basic_content)
    project_a = content.project("project-a")
    assert {t.id for t in content.tasks(project_a)} == {
        "write-intro",
        "write-methods",
        "setup-env",
        "run-ablations",
    }
    assert "run-ablations" not in {t.id for t in content.tasks(project_a, recursive=False)}


def test_subproject_task_belongs_to_subproject(basic_content):
    assert Content.open(basic_content).task("run-ablations").project == "ablations"


def test_subtask_rollup_from_fixture(basic_content):
    task = Content.open(basic_content).task("write-intro")
    assert (task.subtasks_done, task.subtasks_total) == (1, 3)


def test_other_project_files(basic_content):
    content = Content.open(basic_content)
    project = content.project("project-a")
    assert [d.id for d in content.deliverables(project)] == ["neurips-paper"]
    assert [e.text for e in content.log(project)][-1].startswith("First results")
    assert [r.id for r in content.references(project)] == ["vaswani2017attention"]
    assert len(content.ideas(project)) == 1
    assert len(content.inbox()) == 2
    assert content.sources()[0].year == 2017


def test_example_content_is_valid():
    """example-content/ must stay loadable — it's what the docs demo."""
    root = Path(__file__).parent.parent / "example-content"
    content = Content.open(root)
    content.tasks()
    content.deliverables()
    content.sources()


class _Item:
    def __init__(self, id_: str):
        self.id = id_
        self.path = f"/{id_}"


ITEMS = [_Item(i) for i in ("write-intro", "write-methods", "write", "setup-env")]


@pytest.mark.parametrize(
    ("query", "expected"),
    [("setup", "setup-env"), ("write-i", "write-intro"), ("write", "write")],
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


def test_complete_ids():
    assert complete_ids("write-", ITEMS) == ["write-intro", "write-methods"]
