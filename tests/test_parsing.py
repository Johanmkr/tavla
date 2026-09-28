from __future__ import annotations

import datetime as dt

import pytest

from tavla.core import parsing
from tavla.core.errors import ValidationError


def test_count_subtasks_only_under_heading():
    body = """# Title

## Context
- [x] not a subtask

## Subtasks
- [x] one
- [X] two
* [ ] three
  - [ ] nested four

## Updates
- [ ] not a subtask either
"""
    assert parsing.count_subtasks(body) == (2, 4)


def test_count_subtasks_includes_deeper_headings_but_stops_at_sibling():
    body = """## Subtasks
- [x] a
### Phase 2
- [ ] b
## Next
- [ ] c
"""
    assert parsing.count_subtasks(body) == (1, 2)


def test_count_subtasks_ignores_code_blocks():
    body = "## Subtasks\n- [x] real\n```\n## Other\n- [ ] fake\n```\n- [ ] real two\n"
    assert parsing.count_subtasks(body) == (1, 2)


def test_count_subtasks_missing_heading():
    assert parsing.count_subtasks("# Title\n- [ ] x\n") == (0, 0)


def test_count_subtasks_heading_case_insensitive():
    assert parsing.count_subtasks("## subtasks\n- [ ] x\n") == (0, 1)


def test_first_heading():
    assert parsing.first_heading("intro\n## Sub\n# Real title\n") == "Real title"
    assert parsing.first_heading("no heading") is None


def test_markdown_round_trip_preserves_order_and_body(tmp_path):
    path = tmp_path / "t.md"
    meta = {"id": "x", "status": "todo", "due": dt.date(2026, 1, 2), "zeta": 1, "alpha": 2}
    body = "# Title\n\nFree **text** stays exactly.\n"
    parsing.write_markdown(path, meta, body)
    read_meta, read_body = parsing.read_markdown(path)
    assert list(read_meta) == ["id", "status", "due", "zeta", "alpha"]
    assert read_meta["due"] == dt.date(2026, 1, 2)
    assert read_body.strip() == body.strip()


def test_invalid_frontmatter_is_validation_error(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("---\nid: [unclosed\n---\nbody\n")
    with pytest.raises(ValidationError, match="bad.md"):
        parsing.read_markdown(path)


def test_yaml_round_trip(tmp_path):
    path = tmp_path / "x.yaml"
    parsing.write_yaml(path, [{"id": "a", "path": "projects/a"}])
    assert parsing.read_yaml(path) == [{"id": "a", "path": "projects/a"}]


# --- sections ----------------------------------------------------------------------

DOC = """---
id: x
# Ideas: a YAML comment, not a heading
---

# Title

## Ideas
- one
  continuation
- two

## Updates
- 2026-01-01: not an idea
"""


def test_section_bullets_skip_frontmatter_and_continuations():
    assert parsing.section_bullets(DOC, "Ideas") == [(8, "one"), (10, "two")]
    assert parsing.section_bullets(DOC, "Missing") == []


def test_append_to_section_before_next_heading():
    out = parsing.append_to_section(DOC, "Ideas", "- three")
    assert "- two\n- three\n\n## Updates" in out


def test_append_to_section_creates_it():
    out = parsing.append_to_section("---\nid: x\n---\n# T\n\n", "Ideas", "- a")
    assert out == "---\nid: x\n---\n# T\n\n## Ideas\n- a\n"


def test_remove_line():
    assert parsing.remove_line("a\nb\nc\n", 1) == "a\nc\n"


def test_frontmatter_lines():
    assert parsing.frontmatter_lines(DOC) == 4
    assert parsing.frontmatter_lines("# no frontmatter\n") == 0


def test_remove_frontmatter_key_with_block_value():
    text = "---\nid: x\ntags:\n  - a\n  - b\ndue: 2026-01-01\n---\nbody\n"
    assert (
        parsing.remove_frontmatter_key(text, "tags") == "---\nid: x\ndue: 2026-01-01\n---\nbody\n"
    )
    assert parsing.remove_frontmatter_key(text, "nope") == text


def test_set_first_heading():
    assert (
        parsing.set_first_heading("## Sub\n# Old\n# Other\n", "New") == "## Sub\n# New\n# Other\n"
    )
    assert parsing.set_first_heading("no heading\n", "New") is None
