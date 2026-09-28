from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import ideas
from tavla.core.entities import Idea
from tavla.core.errors import EXIT_INVALID, AmbiguousIdError, NotFoundError, ValidationError
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


def _head(git, repo) -> str:
    return git(repo, "log", "-1", "--format=%s").strip()


def _clean(git, repo) -> bool:
    return git(repo, "status", "--porcelain") == ""


def _texts(scope) -> list[str]:
    return [r.idea.text for r in ideas.read(scope)]


# --- model -------------------------------------------------------------------------


def test_idea_tags():
    idea = Idea("Try #mcmc tempering, see #mcmc and #big-idea (not issue#3 or ##x)")
    assert idea.tags == ["mcmc", "big-idea"]
    assert idea.text_without_tags() == "Try tempering, see and (not issue#3 or ##x)"


def test_read_scopes(content):
    assert _texts(ideas.scope_of(content, None)) == [
        "Try importance sampling on the toy model",
        "Email advisor about the conference budget",
    ]
    assert _texts(ideas.scope_of(content, content.project("project-a"))) == [
        "Adaptive step size based on the acceptance rate"
    ]
    assert _texts(ideas.scope_of(content, content.goal("write-intro"))) == [
        "Open with the #mcmc failure case",
        "Mention the toy model",
    ]
    assert _texts(ideas.scope_of(content, content.task("fix-plot"))) == []


def test_idea_line_starting_with_tag_is_not_a_heading(content):
    (content.root / "inbox.md").write_text("# Inbox\n\n#mcmc look into NUTS\n")
    assert _texts(ideas.scope_of(content, None)) == ["#mcmc look into NUTS"]


@pytest.mark.parametrize(
    ("ref", "text"),
    [
        ("2", "Email advisor about the conference budget"),
        ("inbox:1", "Try importance sampling on the toy model"),
        ("write-i:2", "Mention the toy model"),
        ("write-intro:FAILURE", "Open with the #mcmc failure case"),
        ("project-a:1", "Adaptive step size based on the acceptance rate"),
        ("advisor", "Email advisor about the conference budget"),
    ],
)
def test_resolve(content, ref, text):
    assert ideas.resolve(content, ref).idea.text == text


def test_resolve_errors(content):
    with pytest.raises(NotFoundError, match="no idea 3 in inbox"):
        ideas.resolve(content, "3")
    with pytest.raises(NotFoundError):
        ideas.resolve(content, "write-intro:nothing like this")
    with pytest.raises(AmbiguousIdError):
        ideas.resolve(content, "write-intro:m")
    with pytest.raises(NotFoundError):
        ideas.resolve(content, "nope:1")


# --- writes ------------------------------------------------------------------------


def test_add_to_goal_section(content, git):
    goal = content.goal("write-intro")
    ideas.add(content, ideas.scope_of(content, goal), "Quote   Gelman")
    assert _texts(ideas.scope_of(content, goal))[-1] == "Quote Gelman"
    text = goal.path.read_text()
    assert "- Mention the toy model\n- Quote Gelman\n\n## Updates" in text
    assert _head(git, content.root) == "idea: add to write-intro: Quote Gelman"
    assert _clean(git, content.root)


def test_add_creates_missing_section(content):
    task = content.task("fix-plot-colors")
    task.path.write_text(task.path.read_text().replace("## Ideas\n\n", ""))
    ideas.add(content, ideas.scope_of(content, task), "viridis?")
    assert task.path.read_text().endswith("## Updates\n\n## Ideas\n- viridis?\n")
    assert _texts(ideas.scope_of(content, task)) == ["viridis?"]


def test_add_to_project_without_ideas_file(content):
    project = content.project("ablations")
    ideas.add(content, ideas.scope_of(content, project), "grid over seeds")
    assert (project.path / "ideas.md").read_text() == "# Ideas\n\n- grid over seeds\n"


def test_move_inbox_to_task(content, git):
    ref = ideas.resolve(content, "advisor")
    target = ideas.scope_of(content, content.task("get-feedback"))
    ideas.move(content, ref, target)
    assert _texts(ideas.scope_of(content, None)) == ["Try importance sampling on the toy model"]
    assert _texts(target) == ["Email advisor about the conference budget"]
    assert _head(git, content.root) == (
        "idea: move inbox -> get-feedback-from-advisor: Email advisor about the conference budget"
    )
    assert _clean(git, content.root)


def test_move_to_same_scope_rejected(content):
    ref = ideas.resolve(content, "1")
    with pytest.raises(ValidationError, match="already"):
        ideas.move(content, ref, ref.scope)


def test_drop_from_goal(content, git):
    goal = content.goal("write-intro")
    ideas.drop(content, ideas.resolve(content, "write-intro:1"))
    assert _texts(ideas.scope_of(content, goal)) == ["Mention the toy model"]
    assert "Free text the parser ignores." in goal.path.read_text()
    assert _clean(git, content.root)


def test_promote_to_task_carries_tags(content, git):
    ref = ideas.resolve(content, "write-intro:failure")
    task = ideas.promote(content, ref, goal=content.goal("write-intro"))
    assert (task.id, task.title, task.tags, task.goal) == (
        "open-with-the-failure-case",
        "Open with the failure case",
        ["mcmc"],
        "write-intro",
    )
    assert _texts(ideas.scope_of(content, content.goal("write-intro"))) == ["Mention the toy model"]
    changed = git(content.root, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [
        "projects/project-a/goals/write-intro.md",
        "projects/project-a/tasks/open-with-the-failure-case.md",
    ]
    assert _clean(git, content.root)


def test_promote_to_goal(content):
    ref = ideas.resolve(content, "importance")
    goal = ideas.promote(content, ref, project=content.project("project-a"), as_goal=True)
    assert goal.id == "try-importance-sampling-on-the-toy-model"
    assert len(content.inbox()) == 1


def test_promote_failure_keeps_idea(content, git):
    ref = ideas.resolve(content, "importance")
    with pytest.raises(ValidationError):
        ideas.promote(content, ref, as_goal=True)  # no project
    assert len(Content.open(content.root).inbox()) == 2
    assert _clean(git, content.root)


# --- CLI ---------------------------------------------------------------------------


def test_cli_add_and_list(run, git_content):
    assert run("idea", "add", "use", "#jax", "for", "speed", "-p", "project-a").exit_code == 0
    out = run("idea", "list", "-p", "project-a").output
    assert "   2. use #jax for speed" in out
    assert "1. Try importance sampling" in run("idea", "list").output


def test_cli_list_all_and_tag(run):
    out = run("idea", "list", "--all").output
    assert "inbox\n" in out and "write-intro (goal)\n" in out and "project-a (project)\n" in out
    tagged = run("idea", "list", "--tag", "#mcmc").output
    assert "write-intro (goal)" in tagged and "Open with the #mcmc" in tagged
    assert "inbox" not in tagged


def test_cli_list_json(run):
    data = json.loads(run("idea", "list", "--tag", "mcmc", "--json").output)
    assert data == [
        {
            "ref": "write-intro:1",
            "scope": "goal",
            "text": "Open with the #mcmc failure case",
            "tags": ["mcmc"],
        }
    ]


def test_cli_move_drop_promote(run, git_content):
    result = run("idea", "move", "advisor", "-g", "write-intro")
    assert result.exit_code == 0, result.output
    assert "Moved to write-intro: Email advisor" in result.output
    result = run("idea", "move", "write-intro:advisor", "--inbox")
    assert "Moved to inbox" in result.output
    assert "Dropped from inbox: Email advisor" in run("idea", "drop", "2").output
    result = run("idea", "promote", "1", "-p", "project-a")
    assert "Promoted to task try-importance-sampling-on-the-toy-model" in result.output
    assert "No ideas." in run("idea", "list").output


def test_cli_move_needs_one_target(run):
    assert run("idea", "move", "1").exit_code != 0
    assert run("idea", "move", "1", "-p", "project-a", "--inbox").exit_code != 0


def test_cli_ambiguous_idea(run):
    result = run("idea", "drop", "write-intro:m")
    assert result.exit_code == EXIT_INVALID
    assert "write-intro:1" in result.output and "write-intro:2" in result.output
