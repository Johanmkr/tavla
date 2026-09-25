from __future__ import annotations

import datetime as dt

import pytest

from tavla.core import parsing
from tavla.core.dates import parse_date
from tavla.core.errors import ValidationError
from tavla.core.ops import parse_tags, slugify, validate_id

# --- text-level YAML edits ---------------------------------------------------


def test_set_yaml_key_replaces_only_that_line():
    text = "# my notes\nid: a\nstatus: todo\ntitle: 'x'  # keep me\n"
    out = parsing.set_yaml_key(text, "status", "done")
    assert out == "# my notes\nid: a\nstatus: done\ntitle: 'x'  # keep me\n"


def test_set_yaml_key_keeps_trailing_comment():
    text = "status: doing                   # todo | doing | blocked | done\n"
    assert parsing.set_yaml_key(text, "status", "done") == (
        "status: done                   # todo | doing | blocked | done\n"
    )


def test_set_yaml_key_replaces_block_list():
    text = "tags:\n- a\n- b\nnext: 1\n"
    assert parsing.set_yaml_key(text, "tags", ["c"]) == "tags: [c]\nnext: 1\n"


def test_set_yaml_key_appends_missing_key():
    assert parsing.set_yaml_key("id: a", "due", dt.date(2026, 1, 2)) == "id: a\ndue: 2026-01-02\n"


def test_set_yaml_key_does_not_match_prefix_or_nested_keys():
    text = "updated_by: me\nnested:\n  updated: old\n"
    out = parsing.set_yaml_key(text, "updated", "new")
    assert out == text + "updated: new\n"


def test_set_frontmatter_key_leaves_body_alone():
    text = "---\nid: t\nupdated: 2026-01-01\n---\n\n# Title\nupdated: not frontmatter\n"
    out = parsing.set_frontmatter_key(text, "updated", dt.date(2026, 2, 2))
    assert out == "---\nid: t\nupdated: 2026-02-02\n---\n\n# Title\nupdated: not frontmatter\n"


def test_set_frontmatter_key_requires_frontmatter():
    with pytest.raises(ValidationError):
        parsing.set_frontmatter_key("# no frontmatter\n", "a", 1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("plain", "plain"), ("yes", "'yes'"), ("a: b", "'a: b'"), ([], "[]"), (["x", "y"], "[x, y]")],
)
def test_yaml_inline(value, expected):
    assert parsing.yaml_inline(value) == expected


# --- dates -------------------------------------------------------------------

TODAY = dt.date(2026, 9, 25)  # a Friday


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-01", dt.date(2026, 10, 1)),
        ("today", TODAY),
        ("Tomorrow", dt.date(2026, 9, 26)),
        ("+3d", dt.date(2026, 9, 28)),
        ("+2w", dt.date(2026, 10, 9)),
        ("mon", dt.date(2026, 9, 28)),
        ("friday", dt.date(2026, 10, 2)),  # next Friday, never today
    ],
)
def test_parse_date(value, expected):
    assert parse_date(value, TODAY) == expected


@pytest.mark.parametrize("value", ["soon", "2026-13-01", "+3x", "mo"])
def test_parse_date_invalid(value):
    with pytest.raises(ValidationError):
        parse_date(value, TODAY)


# --- ids & tags --------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Write introduction section", "write-introduction-section"),
        ("  NeurIPS 2027: camera-ready!  ", "neurips-2027-camera-ready"),
        ("Skriv innføring på særemne", "skriv-innforing-pa-saeremne"),
        ("Ünïcödé", "unicode"),
        ("a" * 50, "a" * 40),
        ("one two three four five six seven eight nine", "one-two-three-four-five-six-seven-eight"),
        ("!!!", ""),
    ],
)
def test_slugify(title, slug):
    assert slugify(title) == slug


@pytest.mark.parametrize("bad", ["", "-lead", "has space", "a/b", "æ"])
def test_validate_id_rejects(bad):
    with pytest.raises(ValidationError):
        validate_id(bad)


def test_parse_tags():
    assert parse_tags(" a, b,,a ,c") == ["a", "b", "c"]
    assert parse_tags(None) == []
