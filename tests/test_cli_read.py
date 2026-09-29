from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tavla.cli.common import examples
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


def test_project_show_lists_goals_loose_tasks_and_ideas(run):
    out = run("project", "show", "project-a").output
    assert "write-intro  [doing]  1/3 tasks" in out
    assert "fix-plot-colors  [todo]  Fix plot colors  (no goal)" in out
    assert "1. Adaptive step size" in out


def test_project_show_json(run):
    data = json.loads(run("project", "show", "project-a", "--json").output)
    assert data["subprojects"] == ["ablations"]
    assert {g["id"] for g in data["goals"]} >= {"write-intro", "run-ablations"}
    assert {t["id"] for t in data["tasks"]} >= {"draft-related-work", "fix-plot-colors"}
    assert data["ideas"] == ["Adaptive step size based on the acceptance rate"]


def test_goal_list(run):
    result = run("goal", "list")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()[1:]
    assert [line.split()[0] for line in lines] == [
        "write-intro",
        "write-methods",
        "run-ablations",
        "write-review",
    ]
    assert "1/3" in lines[0]
    assert "setup-env" in run("goal", "list", "--all").output


def test_goal_list_groups_subprojects(run):
    out = run("goal", "list", "-p", "project-a").output
    parent, sub = out.split("\n\n")
    assert parent.startswith("project-a — Adaptive sampling for X")
    assert "write-intro" in parent and "run-ablations" not in parent
    assert sub.startswith("project-a / ablations — ")
    assert "run-ablations" in sub
    assert "PROJECT" not in out


def test_goal_list_project_without_subprojects(run):
    out = run("goal", "list", "-p", "project-b").output
    assert out.splitlines()[0].split()[:2] == ["ID", "STATUS"]
    assert "write-review" in out


def test_goal_show(run):
    result = run("goal", "show", "write-i")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "tasks:    1/3" in out
    assert "[x] outline-structure" in out
    assert "get-feedback-from-advisor  [todo]  Get feedback from advisor  (after draft" in out
    assert "Open with the #mcmc failure case" in out  # body, including ## Ideas


def test_task_list_sorted_and_hides_done(run):
    result = run("task", "list")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()[1:]
    ids = [line.split()[0] for line in lines]
    assert ids == [
        "draft-related-work",
        "get-feedback-from-advisor",
        "wait-for-cluster-allocation",
        "fix-plot-colors",
    ]
    assert "1/2" in lines[0] and "write-intro" in lines[0]
    assert "todo*" in lines[1]  # waiting on a dependency
    assert lines[3].split()[5] == "-"  # no goal


def test_task_list_filters(run):
    assert "outline-structure" in run("task", "list", "--status", "done").output
    assert "outline-structure" in run("task", "list", "--all").output
    out = run("task", "list", "--goal", "write-i").output
    assert "draft-related-work" in out and "fix-plot-colors" not in out
    assert "No tasks." in run("task", "list", "--project", "project-b").output


def test_task_list_invalid_status(run):
    result = run("task", "list", "--status", "wip")
    assert result.exit_code != 0


def test_task_show_by_prefix(run):
    result = run("task", "show", "get-f")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Get feedback from advisor" in out
    assert "goal:     write-intro" in out
    assert "priority: high (from goal)" in out
    assert "after:    draft-related-work [todo]" in out
    assert "## Instructions" in out


def test_task_show_json_includes_body(run):
    data = json.loads(run("task", "show", "draft-related-work", "--json").output)
    assert data["subtasks_total"] == 2
    assert data["inherited"] == ["priority", "due"]
    assert "## Subtasks" in data["body"]


def test_ambiguous_id_exit_code(run):
    result = run("goal", "show", "write-")
    assert result.exit_code == EXIT_INVALID
    assert "write-intro" in result.output and "write-methods" in result.output


def test_not_found_exit_code(run):
    assert run("task", "show", "nope").exit_code == EXIT_NOT_FOUND
    assert run("goal", "show", "nope").exit_code == EXIT_NOT_FOUND
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
        ["goal", "list"],
        ["idea", "list"],
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
    assert "draft-related-work" in result.output


def test_old_layout_asks_for_migrate(content_copy):
    (content_copy / "tavla.yaml").unlink()
    result = runner.invoke(app, ["--content-dir", str(content_copy), "task", "list"])
    assert result.exit_code == EXIT_ERROR
    assert "tavla migrate" in result.output


def test_content_dir_option_is_hidden_on_subcommands():
    result = runner.invoke(app, ["task", "list", "--help"])
    assert "--content-dir" not in result.output


@pytest.mark.parametrize("args", [[], ["goal"], ["task", "add"]])
def test_short_help_flag_at_every_level(args):
    result = runner.invoke(app, [*args, "-h"])
    assert result.exit_code == 0, result.output
    assert result.output == runner.invoke(app, [*args, "--help"]).output


def test_top_level_help_groups_commands_into_panels():
    result = runner.invoke(app, ["--help"])
    for panel in ("Daily", "Projects and what's in them", "Setup and maintenance"):
        assert panel in result.output


def test_help_shows_examples():
    result = runner.invoke(app, ["idea", "move", "--help"])
    assert "Examples:" in result.output
    assert "tv idea move 3 -g intro" in result.output


def test_examples_aligns_notes():
    assert examples("tv a # one", "tv abc # two", "tv x") == (
        "Examples:\ntv a    # one\ntv abc  # two\ntv x"
    )
