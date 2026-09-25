"""Frontmatter + markdown and plain YAML read/write.

Only frontmatter and the ``## Subtasks`` section are structural; the rest of a
markdown body is opaque text that is never rewritten.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import frontmatter
import yaml

from tavla.core.errors import ValidationError

SUBTASKS_HEADING = "Subtasks"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s")


def read_markdown(path: Path) -> tuple[dict[str, Any], str]:
    """Return ``(frontmatter, body)`` for a markdown file."""
    try:
        post = frontmatter.load(path)
    except yaml.YAMLError as e:
        raise ValidationError(f"{path}: invalid frontmatter: {e}") from e
    if not isinstance(post.metadata, dict):
        raise ValidationError(f"{path}: frontmatter must be a mapping")
    return dict(post.metadata), post.content


def write_markdown(path: Path, meta: dict[str, Any], body: str) -> None:
    post = frontmatter.Post(body, **meta)
    text = frontmatter.dumps(post, sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n")


def read_yaml(path: Path) -> Any:
    try:
        with path.open() as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValidationError(f"{path}: invalid YAML: {e}") from e


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def first_heading(body: str) -> str | None:
    """Return the text of the first level-1 heading, if any."""
    for line in body.splitlines():
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 1:
            return m.group(2)
    return None


def count_subtasks(body: str, heading: str = SUBTASKS_HEADING) -> tuple[int, int]:
    """Return ``(done, total)`` checkbox counts under the ``## <heading>`` section.

    The section ends at the next heading of the same or higher level.
    """
    done = total = 0
    level: int | None = None
    in_code = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _HEADING_RE.match(line)
        if m:
            depth = len(m.group(1))
            if level is not None and depth <= level:
                break
            if level is None and m.group(2).strip().lower() == heading.lower():
                level = depth
            continue
        if level is None:
            continue
        cb = _CHECKBOX_RE.match(line)
        if cb:
            total += 1
            if cb.group(1) in "xX":
                done += 1
    return done, total


# --- minimal, formatting-preserving edits -----------------------------------
#
# Rewriting a whole file through a YAML dumper would drop the user's comments
# and reorder/reformat their fields. For tool-driven changes (bumping
# ``updated``, flipping ``status``) we edit just the one top-level line instead.

_TRAILING_COMMENT_RE = re.compile(r"^[^#\"']*?(\s+#.*)$")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.DOTALL)


def yaml_inline(value: Any) -> str:
    """Render ``value`` as a single-line YAML scalar or flow collection."""
    text = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10**9)
    return text.removesuffix("\n...\n").strip()


def set_yaml_key(text: str, key: str, value: Any) -> str:
    """Set top-level ``key`` in a YAML mapping document, touching only its line(s)."""
    lines = text.splitlines(keepends=True)
    key_re = re.compile(rf"^{re.escape(key)}\s*:")
    new_line = f"{key}: {yaml_inline(value)}\n"
    for i, line in enumerate(lines):
        if key_re.match(line):
            j = i + 1
            # Swallow a block-style value (indented lines or unindented "- item" lines).
            while j < len(lines) and lines[j].strip() and lines[j][0] in " \t-":
                j += 1
            # Keep a trailing "# comment" on a single-line value, unless quotes
            # make it unclear where the value ends.
            comment = _TRAILING_COMMENT_RE.match(line.rstrip("\n"))
            if j == i + 1 and comment:
                new_line = f"{new_line.rstrip()}{comment.group(1)}\n"
            return "".join([*lines[:i], new_line, *lines[j:]])
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return "".join([*lines, new_line])


def set_frontmatter_key(text: str, key: str, value: Any) -> str:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValidationError("file has no YAML frontmatter block")
    inner = set_yaml_key(m.group(1) or "", key, value)
    return f"---\n{inner}---\n{text[m.end() :]}"
