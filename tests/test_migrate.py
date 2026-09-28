from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import bootstrap, migrate
from tavla.core.errors import TavlaError
from tavla.core.store import Content

runner = CliRunner()
V1 = Path(__file__).parent / "fixtures" / "v1"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def v1(tmp_path) -> Path:
    """A v1 (tasks-only) content repo with one initial commit."""
    dest = tmp_path / "v1"
    shutil.copytree(V1, dest)
    _git(dest, "init", "--quiet")
    _git(dest, "add", "--all")
    _git(dest, "commit", "--quiet", "-m", "initial")
    return dest


def test_plan(v1):
    plan = migrate.plan(v1)
    assert (plan.from_version, plan.to_version, plan.needed) == (1, 2, True)
    moves = {m.goal_id: [(t.id, t.done) for t in m.tasks] for m in plan.moves}
    assert moves == {
        "setup-env": [("request-cluster-account", True), ("build-container", True)],
        "write-intro": [
            ("outline-structure", True),
            ("draft-related-work", False),
            ("get-feedback-from-advisor", False),
        ],
        "write-methods": [],
        "run-ablations": [("wait-for-cluster-allocation", False)],
        "write-review": [],
    }
    assert not (v1 / "tavla.yaml").exists()  # planning writes nothing


def test_apply(v1):
    assert migrate.apply(migrate.plan(v1))
    assert _git(v1, "log", "--format=%s").splitlines() == [
        "migrate: content layout v1 -> v2",
        "initial",
    ]
    assert _git(v1, "status", "--porcelain") == ""
    assert bootstrap.schema_version(v1) == 2

    content = Content.open(v1)
    goal = content.goal("write-intro")
    assert goal.path == v1 / "projects/project-a/goals/write-intro.md"
    assert (goal.status, goal.priority, goal.tasks_done, goal.tasks_total) == (
        "doing",
        "high",
        1,
        3,
    )
    text = goal.path.read_text()
    assert "## Subtasks" not in text
    assert "- [ ] this checkbox is not a subtask" in text  # outside ## Subtasks: untouched
    assert "## Ideas\n\n## Updates\n- 2026-09-15: Drafted outline" in text

    task = content.task("draft-related-work")
    assert (task.goal, task.project, task.status) == ("write-intro", "project-a", "todo")
    assert (task.created, task.updated) == (goal.created, goal.updated)  # keeps staleness
    assert task.inherited == ["priority", "due"]
    assert content.task("wait-for").project == "ablations"
    assert not list(v1.glob("projects/*/tasks/setup-env.md"))


def test_apply_is_idempotent(v1):
    migrate.apply(migrate.plan(v1))
    plan = migrate.plan(v1)
    assert not plan.needed
    assert migrate.apply(plan) is False


def test_nested_checkboxes_become_subtasks_and_notes_survive(v1):
    path = v1 / "projects/project-a/tasks/write-intro.md"
    path.write_text(
        path.read_text().replace(
            "- [ ] Draft related work\n",
            "- [ ] Draft related work\n  - [x] find papers\n  - [ ] summarize\nKeep this note.\n",
        )
    )
    _git(v1, "commit", "-qam", "nested")
    migrate.apply(migrate.plan(v1))
    content = Content.open(v1)
    task = content.task("draft-related-work")
    assert (task.subtasks_done, task.subtasks_total) == (1, 2)
    goal_text = content.goal("write-intro").path.read_text()
    assert "## Subtasks\nKeep this note.\n" in goal_text  # non-checkbox content kept


def test_ids_stay_unique(v1):
    path = v1 / "projects/project-a/tasks/write-methods.md"
    path.write_text(path.read_text() + "\n## Subtasks\n- [ ] Write methods\n- [ ] setup env\n")
    _git(v1, "commit", "-qam", "clash")
    migrate.apply(migrate.plan(v1))
    content = Content.open(v1)
    assert [t.id for t in content.goal_tasks(content.goal("write-methods"))] == [
        "setup-env-2",
        "write-methods-2",
    ]


def test_refuses_dirty_repo(v1):
    (v1 / "inbox.md").write_text("# Inbox\n\n- uncommitted\n")
    with pytest.raises(TavlaError, match="uncommitted"):
        migrate.apply(migrate.plan(v1))
    assert (v1 / "projects/project-a/tasks/write-intro.md").exists()


def test_cli_dry_run_then_apply(v1):
    base = ["--content-dir", str(v1)]
    result = runner.invoke(app, [*base, "migrate", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "goal  write-intro: projects/project-a/tasks/write-intro.md" in result.output
    assert "task  outline-structure [done]  Outline structure" in result.output
    assert "Dry run" in result.output
    assert bootstrap.schema_version(v1) == 1

    result = runner.invoke(app, [*base, "migrate"])
    assert result.exit_code == 0, result.output
    assert "tavla undo" in result.output
    assert "nothing to do" in runner.invoke(app, [*base, "migrate"]).output
    assert runner.invoke(app, [*base, "next"]).exit_code == 0


def test_init_writes_current_version(tmp_path):
    result = runner.invoke(app, ["init", "--content-dir", str(tmp_path / "c")])
    assert result.exit_code == 0, result.output
    assert bootstrap.schema_version(tmp_path / "c") == bootstrap.SCHEMA_VERSION
