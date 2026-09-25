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
