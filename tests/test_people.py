"""People on goals and tasks: the people: list, --person, people/mail commands."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import ops, parsing, people
from tavla.core.check import find_problems
from tavla.core.entities import Person
from tavla.core.errors import EXIT_INVALID, AmbiguousIdError, NotFoundError, ValidationError
from tavla.core.store import Content

runner = CliRunner()
KARI = "Kari Nordmann <kari.nordmann@example.org>"


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


@pytest.fixture
def run(git_content):
    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(git_content), *args])

    return _run


@pytest.mark.parametrize(
    ("text", "name", "email"),
    [
        (KARI, "Kari Nordmann", "kari.nordmann@example.org"),
        ("ana@example.org", None, "ana@example.org"),
        ("  Ana   Berg ", "Ana Berg", None),
        ('"Berg, Ana" <ana@example.org>', "Berg, Ana", "ana@example.org"),
        ("<ana@example.org>", None, "ana@example.org"),
    ],
)
def test_parse_person(text, name, email):
    assert Person.parse(text) == Person(name, email)


@pytest.mark.parametrize("text", ["Ana <not-an-address>", "", "<>"])
def test_parse_person_rejects(text):
    with pytest.raises(ValidationError):
        Person.parse(text)


def _set_people(path, block: str) -> None:
    text = path.read_text()
    path.write_text(text.replace("\n---\n", f"\n{block}---\n", 1))


def test_load_people_and_goal_inheritance(content):
    goal = content.goal("write-intro")
    _set_people(goal.path, "people:\n  - name: Ana\n    email: ana@example.org\n")
    task = content.task("draft-related-work")
    _set_people(task.path, f"people:\n  - {KARI}\n  - ana@example.org\n")
    content.refresh()
    task = content.task("draft-related-work")
    assert task.people == [
        Person("Kari Nordmann", "kari.nordmann@example.org"),
        Person(None, "ana@example.org"),
    ]
    assert task.goal_people == [Person("Ana", "ana@example.org")]
    # Ana is listed on both; she appears once, as the task lists her.
    assert [str(p) for p in task.everyone] == [KARI, "ana@example.org"]


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ("people: Kari\n", "must be a list"),
        ("people:\n  - email: nope\n", "people entry 1"),
        ("people:\n  - phone: 123\n", "unknown field"),
        ("people:\n  - 42\n", "people entry 1"),
    ],
)
def test_malformed_people_reported_by_check(content, block, message):
    _set_people(content.task("fix-plot-colors").path, block)
    assert any(message in p.message for p in find_problems(content))


def test_people_written_block_style_and_round_trip(content, git):
    task = ops.add_task(
        content, "Meet Kari", content.project("project-a"), people=[Person.parse(KARI)]
    )
    text = task.path.read_text()
    assert "people:\n  - name: Kari Nordmann\n    email: kari.nordmann@example.org\n" in text
    edited = ops.set_fields(content, task, {"tags": ["x"]})
    assert edited is not None and edited.people == task.people
    edited = ops.set_fields(content, edited, {"people": None})
    assert edited is not None and edited.people == []
    assert "people" not in edited.path.read_text()


def test_yaml_entry_replaces_block_value():
    text = "id: a\npeople:\n  - name: A\n    email: a@b.c\ntags: []\n"
    out = parsing.set_yaml_key(text, "people", [{"name": "B"}])
    assert out == "id: a\npeople:\n  - name: B\ntags: []\n"


def test_resolve_reuses_known_people(content):
    ops.add_task(content, "One", content.project("project-a"), people=[Person.parse(KARI)])
    ops.add_task(content, "Two", content.project("project-a"), people=[Person("Kari Berg", None)])
    content.refresh()
    assert str(people.resolve(content, "nordmann")) == KARI
    assert str(people.resolve(content, "kari.nordmann@example.org")) == KARI
    assert people.resolve(content, "Kari Berg") == Person("Kari Berg", None)
    with pytest.raises(AmbiguousIdError):
        people.resolve(content, "kari")
    assert people.resolve(content, "Carl") == Person("Carl", None)  # new, name only


def test_apply_specs(content):
    task = ops.add_task(content, "T", content.project("project-a"), people=[Person.parse(KARI)])
    assert people.apply_specs(content, task, ["+carl@example.com"]) == [
        Person.parse(KARI),
        Person(None, "carl@example.com"),
    ]
    assert people.apply_specs(content, task, ["-kari"]) == []
    assert people.apply_specs(content, task, ["none"]) == []
    assert people.apply_specs(content, task, ["Ana <ana@example.org>"]) == [
        Person("Ana", "ana@example.org")
    ]
    with pytest.raises(ValidationError, match="either"):
        people.apply_specs(content, task, ["+a@b.c", "Ana"])
    with pytest.raises(NotFoundError):
        people.apply_specs(content, task, ["-carl"])


def test_mailto():
    url = people.mailto(
        [Person.parse(KARI), Person("Ana", None), Person(None, "c+d@example.com")], "Hi & bye"
    )
    assert url == "mailto:kari.nordmann@example.org,c%2Bd@example.com?subject=Hi%20%26%20bye"
    with pytest.raises(ValidationError):
        people.mailto([Person("Ana", None)])


# --- CLI -----------------------------------------------------------------------


def test_cli_add_show_people_mail(run, git_content):
    result = run("goal", "edit", "write-intro", "--person", "Ana Berg <ana@example.org>")
    assert result.exit_code == 0, result.output
    result = run(
        "task",
        "add",
        "Meet Kari",
        "-g",
        "write-intro",
        "--person",
        KARI,
        "--person",
        "carl@example.com",
    )
    assert result.exit_code == 0, result.output

    shown = run("task", "show", "meet-kari").output
    assert f"people:   {KARI}" in shown
    assert "Ana Berg <ana@example.org> (from goal)" in shown

    assert run("task", "people", "meet-kari", "-e").output.split() == [
        "kari.nordmann@example.org",
        "carl@example.com",
        "ana@example.org",
    ]
    data = json.loads(run("task", "people", "meet-kari", "--json").output)
    assert [d["from_goal"] for d in data] == [False, False, True]

    result = run("task", "edit", "meet-kari", "--person", "-ana")
    assert result.exit_code == EXIT_INVALID
    assert "comes from goal write-intro" in result.output

    result = run("task", "mail", "meet-kari", "--print")
    assert result.stdout.strip() == (
        "mailto:kari.nordmann@example.org,carl@example.com,ana@example.org?subject=Meet%20Kari"
    )
    assert "Ana Berg <ana@example.org>" in run("goal", "people", "write-intro").output


def test_cli_people_listing_and_reuse(run):
    run("task", "add", "Meet Kari", "-p", "project-a", "--person", KARI)
    result = run("task", "add", "Follow up", "-p", "project-a", "--person", "nordmann")
    assert result.exit_code == 0, result.output
    assert KARI in run("task", "show", "follow-up").output
    listing = run("people").output
    assert f"{KARI}  (follow-up, meet-kari)" in listing
    assert run("people", "kari", "-e").output.strip() == "kari.nordmann@example.org"
    assert "No one found" in run("people", "nobody").output


def test_cli_mail_without_addresses(run):
    run("task", "add", "Lunch", "-p", "project-a", "--person", "Ana")
    result = run("task", "mail", "lunch", "--print")
    assert result.exit_code == EXIT_INVALID
    assert "no one here has an email address" in result.output
