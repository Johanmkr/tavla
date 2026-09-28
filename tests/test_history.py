from __future__ import annotations

import pytest

from tavla.core import history, ops
from tavla.core.errors import TavlaError
from tavla.core.store import Content


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


def _subjects(git, repo) -> list[str]:
    return git(repo, "log", "--format=%s").splitlines()


def test_nothing_to_undo_in_a_fresh_repo(content):
    assert history.last_change(content.root) is None


def test_undo_reverts_the_last_change(content, git):
    ops.add_project(content, "Temp")
    change = history.last_change(content.root)
    assert change.subject == "project: add temp"
    assert "projects/temp/project.yaml" in change.files

    history.undo(content.root, change)
    assert not (content.root / "projects/temp").exists()
    assert _subjects(git, content.root)[0] == "undo: project: add temp"
    assert git(content.root, "status", "--porcelain") == ""


def test_repeated_undo_walks_back(content, git):
    ops.add_update(content, content.task("draft-r"), "first")
    ops.add_update(content, content.task("draft-r"), "second")
    original = git(content.root, "show", "HEAD~2:projects/project-a/tasks/draft-related-work.md")

    history.undo(content.root, history.last_change(content.root))
    change = history.last_change(content.root)
    assert change.subject == "task: note draft-related-work: first"
    history.undo(content.root, change)

    path = content.root / "projects/project-a/tasks/draft-related-work.md"
    assert path.read_text() == original
    assert history.last_change(content.root) is None  # only the initial commit is left


def test_undo_refuses_with_uncommitted_changes(content):
    ops.add_update(content, content.task("draft-r"), "note")
    path = content.root / "projects/project-a/tasks/draft-related-work.md"
    path.write_text(path.read_text() + "hand edit\n")
    with pytest.raises(TavlaError, match="uncommitted changes"):
        history.undo(content.root, history.last_change(content.root))
    assert path.read_text().endswith("hand edit\n")


def test_undo_conflict_leaves_repo_untouched(content, git):
    task = content.task("draft-r")
    ops.add_update(content, task, "tavla note")
    target = history.last_change(content.root)
    # A later hand-made commit changing the same lines.
    path = task.path
    path.write_text(path.read_text().replace("tavla note", "reworded"))
    git(content.root, "commit", "-qam", "manual edit")
    with pytest.raises(TavlaError, match="later changes"):
        history.undo(content.root, target)
    assert git(content.root, "status", "--porcelain") == ""
    assert _subjects(git, content.root)[0] == "manual edit"
