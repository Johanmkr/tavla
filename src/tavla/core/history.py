"""Undo: revert the most recent change to the content repo.

Every tavla write is one commit, so undoing one is a ``git revert`` — a new
commit, so nothing is lost. Repeated undos walk back through history: undo
commits themselves, and the commits they reverted, are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tavla.core import git_sync
from tavla.core.errors import GitError, TavlaError

UNDO_PREFIX = "undo: "
MAX_HISTORY = 1000

_REVERTS_RE = re.compile(r"This reverts commit ([0-9a-f]{40})")


@dataclass
class Change:
    commit: str
    subject: str
    when: str  # "YYYY-MM-DD HH:MM"
    files: list[str] = field(default_factory=list)


def last_change(root: Path) -> Change | None:
    """The most recent commit that hasn't been undone, or None if there is
    nothing left to undo (the repo's first commit is never undone)."""
    git_sync.require_repo(root)
    log = git_sync.run(
        root,
        "log",
        f"-{MAX_HISTORY}",
        "--date=format:%Y-%m-%d %H:%M",
        "--format=%H%x00%P%x00%ad%x00%s%x00%b%x1e",
    ).stdout
    undone: set[str] = set()
    for record in log.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, parents, when, subject, body = record.split("\x00", 4)
        reverted = _REVERTS_RE.findall(body)
        if reverted:
            undone.update(reverted)
            continue
        if sha in undone:
            continue
        if not parents:
            return None
        if " " in parents:
            raise TavlaError(f"the last change ({subject}) is a merge; undo it with git")
        files = git_sync.run(root, "show", "--name-only", "--format=", sha).stdout.split("\n")
        return Change(sha, subject, when, [f for f in files if f])
    return None


def undo(root: Path, change: Change) -> None:
    """Revert ``change`` as a new ``undo: <subject>`` commit."""
    dirty = git_sync.run(root, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        raise TavlaError(f"{root} has uncommitted changes; commit or discard them first")
    try:
        git_sync.run(root, "revert", "--no-commit", change.commit)
    except GitError as e:
        try:
            git_sync.run(root, "revert", "--abort")
        except GitError:
            pass
        raise TavlaError(
            f"can't undo '{change.subject}': later changes touch the same lines"
        ) from e
    git_sync.run(
        root,
        "commit",
        "--quiet",
        "-m",
        f"{UNDO_PREFIX}{change.subject}",
        "-m",
        f"This reverts commit {change.commit}.",
    )
