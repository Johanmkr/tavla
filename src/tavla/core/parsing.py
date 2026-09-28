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


def section_span(lines: list[str], heading: str, start: int = 0) -> tuple[int, int] | None:
    """Find the ``## <heading>`` section in ``lines`` (searching from ``start``).

    Returns ``(heading_index, end)``, where ``end`` is the index of the next
    heading of the same or higher level (or ``len(lines)``). Headings inside
    fenced code blocks don't count; the heading name is case-insensitive.
    """
    level: int | None = None
    begin = 0
    in_code = False
    for i in range(start, len(lines)):
        line = lines[i]
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _HEADING_RE.match(line.rstrip("\n"))
        if not m:
            continue
        depth = len(m.group(1))
        if level is not None and depth <= level:
            return begin, i
        if level is None and m.group(2).strip().lower() == heading.lower():
            level, begin = depth, i
    return (begin, len(lines)) if level is not None else None


def checkbox_items(text: str, heading: str = SUBTASKS_HEADING) -> list[tuple[int, bool, str]]:
    """Checkbox items under ``## <heading>`` as ``(line_index, done, text)``.

    ``line_index`` indexes ``text.splitlines()`` (frontmatter included, if the
    text has any), so callers can rewrite the line. Nested items count too;
    items inside fenced code blocks don't.
    """
    lines = text.splitlines()
    span = section_span(lines, heading, frontmatter_lines(text))
    if span is None:
        return []
    items = []
    in_code = False
    for i in range(span[0] + 1, span[1]):
        line = lines[i]
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        cb = None if in_code else _CHECKBOX_RE.match(line)
        if cb:
            items.append((i, cb.group(1) in "xX", line[cb.end() :].strip()))
    return items


def count_subtasks(body: str, heading: str = SUBTASKS_HEADING) -> tuple[int, int]:
    """Return ``(done, total)`` checkbox counts under the ``## <heading>`` section.

    The section ends at the next heading of the same or higher level.
    """
    items = checkbox_items(body, heading)
    return sum(done for _, done, _ in items), len(items)


def set_checkbox(text: str, index: int, done: bool) -> str:
    """Tick (or untick) the checkbox on line ``index`` of ``text``."""
    lines = text.splitlines(keepends=True)
    cb = _CHECKBOX_RE.match(lines[index])
    if cb is None:
        raise ValidationError(f"line {index + 1} is not a checkbox item")
    mark = "x" if done else " "
    lines[index] = f"{lines[index][: cb.start(1)]}{mark}{lines[index][cb.end(1) :]}"
    return "".join(lines)


_BULLET_RE = re.compile(r"^[-*+]\s+(?:\[[ xX]\]\s+)?(.*\S)\s*$")


def section_bullets(
    text: str, heading: str, *, skip_frontmatter: bool = True
) -> list[tuple[int, str]]:
    """Top-level bullet items under ``## <heading>`` as ``(line_index, text)``.

    ``line_index`` indexes ``text.splitlines()`` (the whole file, frontmatter
    included), so callers can remove the line again. Indented lines are
    treated as continuations and skipped.
    """
    lines = text.splitlines()
    span = section_span(lines, heading, frontmatter_lines(text) if skip_frontmatter else 0)
    if span is None:
        return []
    items = []
    for i in range(span[0] + 1, span[1]):
        m = _BULLET_RE.match(lines[i])
        if m:
            items.append((i, m.group(1)))
    return items


def append_to_section(text: str, heading: str, line: str) -> str:
    """Add ``line`` as the last item of ``## <heading>`` (after frontmatter),
    creating the section at the end of the file if it doesn't exist."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    span = section_span([ln.rstrip("\n") for ln in lines], heading, frontmatter_lines(text))
    if span is None:
        while lines and not lines[-1].strip():
            lines.pop()
        return "".join([*lines, f"\n## {heading}\n", f"{line}\n"])
    at = span[1]
    while at > span[0] + 1 and not lines[at - 1].strip():
        at -= 1
    return "".join([*lines[:at], f"{line}\n", *lines[at:]])


def ensure_section(text: str, heading: str, before: tuple[str, ...] = ()) -> str:
    """Add an empty ``## <heading>`` section if there isn't one: in front of the
    first of the ``before`` sections that exists, else at the end of the file."""
    lines = text.splitlines(keepends=True)
    start = frontmatter_lines(text)
    stripped = [ln.rstrip("\n") for ln in lines]
    if section_span(stripped, heading, start) is not None:
        return text
    spans = [section_span(stripped, b, start) for b in before]
    found = [span[0] for span in spans if span is not None]
    if found:
        at = min(found)
        return "".join([*lines[:at], f"## {heading}\n\n", *lines[at:]])
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return "".join([*lines, f"\n## {heading}\n"])


def remove_line(text: str, index: int) -> str:
    lines = text.splitlines(keepends=True)
    del lines[index]
    return "".join(lines)


def frontmatter_lines(text: str) -> int:
    """Number of lines taken by a leading ``---`` frontmatter block (0 if none)."""
    m = _FRONTMATTER_RE.match(text)
    return m.group(0).count("\n") + (0 if m.group(0).endswith("\n") else 1) if m else 0


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


def remove_yaml_key(text: str, key: str) -> str:
    """Remove top-level ``key`` (and a block-style value) from a YAML mapping document."""
    lines = text.splitlines(keepends=True)
    key_re = re.compile(rf"^{re.escape(key)}\s*:")
    for i, line in enumerate(lines):
        if key_re.match(line):
            j = i + 1
            while j < len(lines) and lines[j].strip() and lines[j][0] in " \t-":
                j += 1
            return "".join([*lines[:i], *lines[j:]])
    return text


def _map_frontmatter(text: str, fn: Any) -> str:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValidationError("file has no YAML frontmatter block")
    return f"---\n{fn(m.group(1) or '')}---\n{text[m.end() :]}"


def set_frontmatter_key(text: str, key: str, value: Any) -> str:
    return _map_frontmatter(text, lambda inner: set_yaml_key(inner, key, value))


def remove_frontmatter_key(text: str, key: str) -> str:
    return _map_frontmatter(text, lambda inner: remove_yaml_key(inner, key))


def set_first_heading(text: str, title: str) -> str | None:
    """Replace the text of the first level-1 heading. Returns None if there is none."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 1:
            lines[i] = f"# {title}\n"
            return "".join(lines)
    return None
