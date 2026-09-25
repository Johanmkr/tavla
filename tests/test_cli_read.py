from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core.errors import EXIT_ERROR, EXIT_INVALID, EXIT_NOT_FOUND

runner = CliRunner()


@pytest.fixture
def run(basic_content):
    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(basic_content), *args])

    return _run


def test_project_list_hides_archived(run):
    result = run("project", "list")
    assert result.exit_code == 0, result.output
    assert "project-a" in result.output
    assert "  ablations" in result.output  # indented subproject
    assert "project-c" not in result.output


def test_project_list_all_and_status(run):
    assert "project-c" in run("project", "list", "--all").output
    out = run("project", "list", "--status", "paused").output
    assert "project-b" in out and "project-a" not in out


def test_project_list_json(run):
    result = run("project", "list", "--json")
    data = json.loads(result.output)
    assert [p["id"] for p in data] == ["project-a", "ablations", "project-b"]
    assert data[0]["path"] == "projects/project-a"


def test_global_json_flag(basic_content):
    result = runner.invoke(app, ["--content-dir", str(basic_content), "--json", "task", "list"])
    assert isinstance(json.loads(result.output), list)


def test_project_show(run):
    result = run("project", "show", "project-a")
    assert result.exit_code == 0, result.output
    assert "Adaptive sampling for X" in result.output
    assert "ablations" in result.output
    assert "neurips-paper" in result.output
    assert "First results" in result.output


def test_project_show_json(run):
    data = json.loads(run("project", "show", "project-a", "--json").output)
    assert data["subprojects"] == ["ablations"]
    assert {t["id"] for t in data["tasks"]} >= {"write-intro", "run-ablations"}


def test_task_list_sorted_and_hides_done(run):
    result = run("task", "list")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()[1:]
    ids = [line.split()[0] for line in lines]
    assert ids == ["write-intro", "write-methods", "run-ablations", "write-review"]
    assert "1/3" in lines[0]


def test_task_list_filters(run):
    assert "setup-env" in run("task", "list", "--status", "done").output
    assert "setup-env" in run("task", "list", "--all").output
    out = run("task", "list", "--project", "project-b").output
    assert "write-review" in out and "write-intro" not in out


def test_task_list_invalid_status(run):
    result = run("task", "list", "--status", "wip")
    assert result.exit_code != 0


def test_task_show_by_prefix(run):
    result = run("task", "show", "write-i")
    assert result.exit_code == 0, result.output
    assert "Write introduction section" in result.output
    assert "## Approach" not in result.output  # body shown verbatim, no invented sections
    assert "Drafted outline" in result.output


def test_task_show_json_includes_body(run):
    data = json.loads(run("task", "show", "write-intro", "--json").output)
    assert data["subtasks_total"] == 3
    assert "## Subtasks" in data["body"]


def test_ambiguous_id_exit_code(run):
    result = run("task", "show", "write-")
    assert result.exit_code == EXIT_INVALID
    assert "write-intro" in result.output and "write-methods" in result.output


def test_not_found_exit_code(run):
    assert run("task", "show", "nope").exit_code == EXIT_NOT_FOUND
    assert run("project", "show", "nope").exit_code == EXIT_NOT_FOUND


def test_uninitialized_content_dir(tmp_path):
    result = runner.invoke(app, ["--content-dir", str(tmp_path), "task", "list"])
    assert result.exit_code == EXIT_ERROR
    assert "tavla init" in result.output


def test_invalid_file_is_reported_with_path(content_copy):
    (content_copy / "projects/project-a/tasks/bad.md").write_text(
        "---\nid: bad\nstatus: wip\n---\n"
    )
    result = runner.invoke(app, ["--content-dir", str(content_copy), "task", "list"])
    assert result.exit_code == EXIT_INVALID
    assert "bad.md" in result.output


def test_content_dir_accepted_after_command(basic_content):
    for args in (
        ["task", "list"],
        ["project", "show", "project-a"],
        ["next"],
        ["status"],
    ):
        result = runner.invoke(app, [*args, "--content-dir", str(basic_content)])
        assert result.exit_code == 0, (args, result.output)


def test_content_dir_after_command_overrides_global(basic_content, tmp_path):
    result = runner.invoke(
        app,
        ["--content-dir", str(tmp_path), "task", "list", "--content-dir", str(basic_content)],
    )
    assert result.exit_code == 0, result.output
    assert "write-intro" in result.output


def test_content_dir_option_is_hidden_on_subcommands():
    result = runner.invoke(app, ["task", "list", "--help"])
    assert "--content-dir" not in result.output
