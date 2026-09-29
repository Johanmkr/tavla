from __future__ import annotations

import datetime as dt

import pytest
from typer.testing import CliRunner

from tavla.cli.add import BACK, Cancelled, Wizard
from tavla.cli.main import app
from tavla.core.entities import DeliverableKind, Priority
from tavla.core.errors import EXIT_INVALID
from tavla.core.forms import FORMS, UNSET
from tavla.core.store import Content


class Scripted:
    """Answers prompts from a list, in order. A select answer is the option
    value; a text answer is the typed string; a checkbox answer the values."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked: list[str] = []
        self.options: dict[str, list] = {}

    def _next(self, message):
        self.asked.append(message)
        if not self.answers:
            raise AssertionError(f"unscripted prompt: {message}")
        answer = self.answers.pop(0)
        if answer is KeyboardInterrupt:
            raise Cancelled
        return answer

    def select(self, message, options, default=None):
        self.options[message] = [v for _, v in options]
        answer = self._next(message)
        assert answer in self.options[message], (answer, message)
        return answer

    def text(self, message, default, validate):
        return self._next(message)

    def checkbox(self, message, options, checked):
        return self._next(message)

    def confirm(self, message, default):
        return self._next(message)


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


def _run(content, *answers, kind=None):
    prompter = Scripted(*answers)
    out: list[str] = []
    done = Wizard(content, prompter, out.append).run(kind)
    assert prompter.answers == [], "script not used up"
    return done, prompter, out


def _field(kind, key):
    return next(f for f in FORMS[kind].fields if f.key == key)


def test_goal_with_defaults(content, git):
    done, prompter, _ = _run(content, "goal", "project-b", "Submit paper", "create", False)
    assert done == ["Added goal submit-paper to project-b"]
    goal = content.goal("submit-paper")
    assert (goal.project, goal.priority, goal.due) == ("project-b", Priority.MED, None)
    assert prompter.asked == [
        "What do you want to add?",
        "Project",
        "Title",
        "What next?",
        "Add another goal?",
    ]
    assert git(content.root, "log", "-1", "--format=%s").strip() == "goal: add submit-paper"


def test_change_optional_fields_in_review(content):
    priority, due = _field("goal", "priority"), _field("goal", "due")
    _run(
        content,
        "project-b",
        "Submit paper",
        "change",
        priority,
        Priority.HIGH,
        "change",
        due,
        "01.12.2026",
        "change",
        _field("goal", "id"),
        "sub",
        "create",
        False,
        kind="goal",
    )
    goal = content.goal("sub")
    assert (goal.priority, goal.due) == (Priority.HIGH, dt.date(2026, 12, 1))


def test_back_reasks_previous_question(content):
    # Go back from the title to the project, pick another, then continue.
    _, prompter, _ = _run(
        content, "project-a", "<", "project-b", "Paper", "create", False, kind="goal"
    )
    assert content.goal("paper").project == "project-b"
    assert prompter.asked[:4] == ["Project", "Title", "Project", "Title"]


def test_back_from_first_question_returns_to_kind_menu(content):
    _run(content, BACK, "project", "Neural fields", "create", False, kind="goal")
    assert content.project("neural-fields").parent is None


def test_back_from_review_reasks_last_required(content):
    _run(content, "project-b", "Paper", "back", "Better title", "create", False, kind="goal")
    assert content.goal("better-title").title == "Better title"


def test_invalid_text_is_asked_again(content):
    _, _, out = _run(content, "project-b", "  ", "Paper", "create", False, kind="goal")
    assert any("title must not be empty" in line for line in out)


def test_optional_select_can_be_reset_to_default(content):
    priority = _field("goal", "priority")
    _run(
        content,
        "project-b",
        "Paper",
        "change",
        priority,
        Priority.LOW,
        "change",
        priority,
        UNSET,
        "create",
        False,
        kind="goal",
    )
    assert content.goal("paper").priority == Priority.MED


def test_task_under_goal_skips_project_and_inherits(content):
    _, prompter, _ = _run(content, "write-intro", "Cite sources", "create", False, kind="task")
    task = content.task("cite-sources")
    assert (task.goal, task.project) == ("write-intro", "project-a")
    assert "priority" in task.inherited
    assert "Project" not in prompter.asked


def test_loose_task_asks_project_and_deps(content):
    _run(
        content,
        None,
        "project-a",
        "Tidy",
        "change",
        _field("task", "depends_on"),
        ["fix-plot-colors"],
        "create",
        False,
        kind="task",
    )
    task = content.task("tidy")
    assert (task.goal, task.project, task.depends_on) == (None, "project-a", ["fix-plot-colors"])


def test_changing_goal_to_loose_asks_for_project(content):
    goal = _field("task", "goal")
    _, prompter, _ = _run(
        content,
        "write-intro",
        "Tidy",
        "change",
        goal,
        None,
        "project-b",
        "create",
        False,
        kind="task",
    )
    assert content.task("tidy").project == "project-b"
    assert prompter.asked[-3] == "Project"


def test_add_another_keeps_where(content):
    done, prompter, _ = _run(
        content, "project-b", "One", "create", True, "Two", "create", False, kind="goal"
    )
    assert done == ["Added goal one to project-b", "Added goal two to project-b"]
    assert content.goal("two").project == "project-b"
    assert prompter.asked.count("Project") == 1


def test_subproject_idea_subtask_deliverable(content):
    _run(content, "project-a", "Ablations 2", "create", False, kind="subproject")
    assert content.project("ablations-2").parent == "project-a"

    _run(content, "write-intro", "try a log scale #plots", "create", False, kind="idea")
    assert "try a log scale #plots" in content.goal("write-intro").path.read_text()

    _run(content, "draft-related-work", "Read Smith 2020", "create", False, kind="subtask")
    assert content.task("draft-related-work").subtasks[-1].text == "Read Smith 2020"

    kind = _field("deliverable", "kind")
    _run(
        content,
        "project-b",
        "Group talk",
        "change",
        kind,
        DeliverableKind.SLIDES,
        "create",
        False,
        kind="deliverable",
    )
    assert content.deliverable("group-talk").kind == DeliverableKind.SLIDES


def test_taken_id_is_rejected_at_the_question(content):
    _, _, out = _run(
        content,
        "project-b",
        "Paper",
        "change",
        _field("goal", "id"),
        "write-intro",
        "fresh-id",
        "create",
        False,
        kind="goal",
    )
    assert any("already used" in line for line in out)
    assert content.goal("fresh-id")


def test_cancel(content, git):
    with pytest.raises(Cancelled):
        _run(content, "project-b", "Paper", "cancel", kind="goal")
    with pytest.raises(Cancelled):
        _run(content, "project-b", KeyboardInterrupt, kind="goal")
    assert git(content.root, "log", "-1", "--format=%s").strip() == "initial"


def test_cli_needs_a_terminal(git_content):
    result = CliRunner().invoke(app, ["--content-dir", str(git_content), "add", "goal"])
    assert result.exit_code == EXIT_INVALID
    assert "needs a terminal" in result.output


def test_cli_unknown_kind(git_content):
    result = CliRunner().invoke(app, ["--content-dir", str(git_content), "add", "gaol"])
    assert result.exit_code == EXIT_INVALID
    assert "unknown kind" in result.output


# --- the real prompts, driven by keystrokes -------------------------------------

DOWN, ENTER = "\x1b[B", "\r"


@pytest.fixture
def keys():
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from tavla.cli.add import QuestionaryPrompter

    with create_pipe_input() as inp:

        def prompter(*typed: str):
            inp.send_text("".join(typed))
            return QuestionaryPrompter(input=inp, output=DummyOutput())

        yield prompter


def test_questionary_select_maps_values(keys):
    options = [("none", None), ("a", "a"), ("b", "b")]
    assert keys(ENTER).select("?", options) is None
    assert keys(DOWN, DOWN, ENTER).select("?", options) == "b"
    assert keys(ENTER).select("?", options, default="a") == "a"
    # No default means the first option, even when another option's value is None.
    assert keys(ENTER).select("?", [("a", "a"), ("cancel", None)]) == "a"


def test_questionary_select_filters_long_lists(keys):
    options = [(f"item-{n}", n) for n in range(12)]
    assert keys("item-11", ENTER).select("?", options) == 11


def test_questionary_text_and_back(keys):
    no_errors = lambda raw: None
    assert keys("hello", ENTER).text("?", "", no_errors) == "hello"
    assert keys(ENTER).text("?", "kept", no_errors) == "kept"
    assert keys("<", ENTER).text("?", "", no_errors) == "<"


def test_questionary_ctrl_c_cancels(keys):
    with pytest.raises(Cancelled):
        keys("\x03").select("?", [("a", "a")])


def test_full_dialogue_with_keys(content):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from tavla.cli.add import QuestionaryPrompter

    # One chunk of keys per prompt, sent as that prompt opens.
    # kind: goal (3rd) -> project: project-b (3rd) -> title -> Create -> no more.
    chunks = [DOWN + DOWN + ENTER, DOWN + DOWN + ENTER, "Keyboard goal" + ENTER, ENTER, "n"]
    with create_pipe_input() as inp:
        real = QuestionaryPrompter(input=inp, output=DummyOutput())

        class Typing:
            def __getattr__(self, name):
                def prompt(*args, **kwargs):
                    inp.send_text(chunks.pop(0))
                    return getattr(real, name)(*args, **kwargs)

                return prompt

        done = Wizard(content, Typing(), lambda line: None).run()
    assert done == ["Added goal keyboard-goal to project-b"]
    assert chunks == []
