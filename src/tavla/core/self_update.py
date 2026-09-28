"""Update tavla itself from the git clone it runs from (``tavla update``).

Only ever fast-forwards the local ``main`` to ``origin/main``: local commits,
other branches and uncommitted changes are never touched — the update is
refused instead, so nothing can be lost.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import tavla
from tavla.core import git_sync
from tavla.core.errors import TavlaError

REMOTE = "origin"
BRANCH = "main"
UPSTREAM = f"{REMOTE}/{BRANCH}"
# Files whose change means the installed tool must be reinstalled (new
# dependencies or entry points); code changes apply as-is to an editable install.
INSTALL_FILES = ("pyproject.toml",)


@dataclass
class UpdatePlan:
    repo: Path
    old: str  # current commit
    new: str  # origin/main
    commits: list[str]  # "sha subject" lines being pulled in, newest first
    reinstall: bool  # an INSTALL_FILES file changed

    @property
    def up_to_date(self) -> bool:
        return not self.commits


def source_repo() -> Path:
    """The git clone tavla is running from (an editable install)."""
    repo = Path(tavla.__file__).resolve().parents[2]  # <repo>/src/tavla/__init__.py
    if not ((repo / ".git").exists() and (repo / "pyproject.toml").is_file()):
        raise TavlaError(
            "tavla isn't running from a git clone, so it can't update itself; "
            "reinstall it from a clone (see the README)"
        )
    return repo


def _git(repo: Path, *args: str) -> str:
    return git_sync.run(repo, *args).stdout.strip()


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    try:
        git_sync.run(repo, "merge-base", "--is-ancestor", older, newer)
    except TavlaError:
        return False
    return True


def check(repo: Path) -> UpdatePlan:
    """Fetch ``origin/main`` and work out what an update would pull in.

    Raises TavlaError if the clone isn't in a state that can be fast-forwarded.
    """
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        raise TavlaError(f"{repo} is on '{branch}', not '{BRANCH}'; switch to {BRANCH} to update")
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise TavlaError(f"{repo} has uncommitted changes; commit or stash them first")

    git_sync.run(repo, "fetch", "--quiet", REMOTE, BRANCH)
    old = _git(repo, "rev-parse", "HEAD")
    new = _git(repo, "rev-parse", UPSTREAM)
    if old == new or _is_ancestor(repo, new, old):
        # Nothing new upstream (local main may be ahead: that's the user's business).
        return UpdatePlan(repo, old, old, [], False)
    if not _is_ancestor(repo, old, new):
        raise TavlaError(
            f"local {BRANCH} and {UPSTREAM} have diverged in {repo}; "
            "update by hand (tavla only fast-forwards)"
        )
    log = _git(repo, "log", "--format=%h %s", f"{old}..{new}")
    changed = _git(repo, "diff", "--name-only", old, new, "--", *INSTALL_FILES)
    return UpdatePlan(repo, old, new, log.splitlines(), bool(changed))


def apply(plan: UpdatePlan) -> None:
    """Fast-forward the clone to ``plan.new``."""
    if not plan.up_to_date:
        git_sync.run(plan.repo, "merge", "--ff-only", "--quiet", plan.new)


def reinstall_command(repo: Path) -> list[str]:
    return ["uv", "tool", "install", "--force", "--editable", str(repo)]


def reinstall(repo: Path) -> None:
    """Reinstall the tool from ``repo`` with uv, to pick up new dependencies
    or entry points. Raises TavlaError (with the command to run by hand) if uv
    is missing or the install fails."""
    cmd = reinstall_command(repo)
    manual = " ".join(cmd)
    if shutil.which("uv") is None:
        raise TavlaError(f"uv not found on PATH; the code is updated, finish with: {manual}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        raise TavlaError(
            f"reinstalling with uv failed: {msg}\nThe code is updated; finish with: {manual}"
        )
