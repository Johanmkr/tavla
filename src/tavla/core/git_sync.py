"""Git integration for the content repo.

Every mutating operation in the core library ends with :func:`commit`, so all
interfaces (CLI, and later TUI/web) inherit auto-commit for free.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from tavla.core.errors import GitError


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        raise GitError("git executable not found on PATH") from e
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        raise GitError(f"git {' '.join(args)} failed: {msg}")
    return result


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()


def init_repo(path: Path) -> None:
    """Initialise a git repo at ``path`` if one doesn't already exist."""
    if not is_repo(path):
        _git(path, "init", "--quiet")


def commit(repo: Path, message: str, paths: Iterable[Path | str] | None = None) -> bool:
    """Stage ``paths`` (or everything) and commit with ``message``.

    Returns False without committing if there is nothing staged.
    """
    if paths is None:
        _git(repo, "add", "--all")
    else:
        _git(repo, "add", "--", *(str(p) for p in paths))
    staged = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--quiet"],
        check=False,
    )
    if staged.returncode == 0:
        return False
    _git(repo, "commit", "--quiet", "-m", message)
    return True
