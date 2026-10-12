"""Project folders (repo_path): tv project link/unlink and folder-scoped listings."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import ops, queries
from tavla.core.errors import NotFoundError, ValidationError
from tavla.core.store import Content

runner = CliRunner()


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


@pytest.fixture
def run(git_content):
    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(git_content), *args])

    return _run


@pytest.fixture
def code(isolated_env) -> Path:
    """``~/code`` with a folder per project (HOME is the test's home)."""
    root = isolated_env / "code"
    for name in ("b", "b/nested", "c"):
        (root / name).mkdir(parents=True)
    return root


def test_repo_path_accepts_one_or_a_list(content):
    assert content.project("project-a").repo_paths == ["~/code/project-a"]
    assert content.project("project-b").repo_paths == []


def test_link_stores_home_relative_and_appends(content, code, git):
    project = content.project("project-b")
    ops.link_folder(content, project, code / "b")
    assert content.project("project-b").repo_paths == ["~/code/b"]
    assert (
        git(content.root, "log", "-1", "--format=%s").strip()
        == "project: link project-b to ~/code/b"
    )
    ops.link_folder(content, content.project("project-b"), code / "c")
    assert content.project("project-b").repo_paths == ["~/code/b", "~/code/c"]
    assert ops.link_folder(content, content.project("project-b"), code / "c") is None


def test_link_refuses_missing_folder_and_taken_folder(content, code):
    with pytest.raises(ValidationError, match="not a folder"):
        ops.link_folder(content, content.project("project-b"), code / "nope")
    ops.link_folder(content, content.project("project-b"), code / "b")
    with pytest.raises(ValidationError, match="already linked to project project-b"):
        ops.link_folder(content, content.project("project-c"), code / "b")


def test_unlink(content, code):
    ops.link_folder(content, content.project("project-b"), code / "b")
    ops.link_folder(content, content.project("project-b"), code / "c")
    assert ops.unlink_folder(content, content.project("project-b"), code / "b") == ["~/code/b"]
    with pytest.raises(NotFoundError):
        ops.unlink_folder(content, content.project("project-b"), code / "b")
    assert ops.unlink_folder(content, content.project("project-b")) == ["~/code/c"]
    assert "repo_path" not in content.project("project-b").meta


def test_project_for_dir_deepest_wins(content, code):
    ops.link_folder(content, content.project("project-b"), code / "b")
    ops.link_folder(content, content.project("project-c"), code / "b" / "nested")
    found = queries.project_for_dir(content, code / "b" / "nested")
    assert found is not None and found[0].id == "project-c"
    found = queries.project_for_dir(content, code / "b")
    assert found is not None and found[0].id == "project-b"
    assert queries.project_for_dir(content, code / "c") is None


def test_cli_next_and_task_list_follow_cwd(run, code, monkeypatch):
    result = run("project", "link", "project-b", str(code / "b"))
    assert result.exit_code == 0, result.output
    assert "Linked ~/code/b to project project-b" in result.output
    monkeypatch.chdir(code / "b" / "nested")

    result = run("next", "-n", "0")
    assert "Project project-b (you are in ~/code/b)" in result.output
    assert "project-a" not in result.stdout
    assert "project-a" in run("next", "-G", "-n", "0").stdout
    assert "project-a" in run("next", "-p", "project-a").stdout

    listed = run("task", "list").stdout
    assert "fix-plot-colors" not in listed
    assert "fix-plot-colors" in run("task", "list", "--global").stdout


def test_cli_link_defaults_to_cwd(run, code, monkeypatch):
    monkeypatch.chdir(code / "c")
    assert "Linked ~/code/c to project project-c" in run("project", "link", "project-c").output
    assert "already linked" in run("project", "link", "project-c").output
    assert "repo_path: ~/code/c" in run("project", "show", "project-c").output
    assert "Unlinked ~/code/c" in run("project", "unlink", "project-c").output
    assert "no linked folders" in run("project", "unlink", "project-c").output
