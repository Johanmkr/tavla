"""Update tavla itself (``tavla update``), in one of two ways:

- **Release install** (``uv tool install git+REPO_URL@vX.Y.Z``, what testers
  use): find the newest ``vX.Y.Z`` tag on GitHub and reinstall from it with uv.
- **Clone install** (``uv tool install --editable <clone>``, for development):
  fast-forward the clone's ``main`` to ``origin/main``. Local commits, other
  branches and uncommitted changes are never touched — the update is refused
  instead, so nothing can be lost.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import tavla
from tavla.core import git_sync
from tavla.core.errors import TavlaError

REPO_URL = "https://github.com/Johanmkr/tavla"
RELEASE_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")  # pre-releases (v1.0.0rc1) are skipped
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
    _run_uv(reinstall_command(repo), "the code is updated")


def _run_uv(cmd: list[str], state: str) -> None:
    manual = " ".join(cmd)
    if shutil.which("uv") is None:
        raise TavlaError(f"uv not found on PATH; {state}, finish with: {manual}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        raise TavlaError(f"installing with uv failed: {msg}\n{state.capitalize()}; run: {manual}")


# --- release installs ---------------------------------------------------------


@dataclass
class ReleasePlan:
    current: str  # installed version, e.g. "0.2.0"
    latest: str | None  # newest release tag, e.g. "v0.3.0" (None: no releases yet)

    @property
    def up_to_date(self) -> bool:
        return self.latest is None or version_key(self.latest[1:]) <= version_key(self.current)

    @property
    def notes_url(self) -> str:
        return f"{REPO_URL}/releases/tag/{self.latest}"


def version_key(version: str) -> tuple[int, int, int, int]:
    """Order ``X.Y.Z`` versions; a development build (``0.2.1.dev3+g...``) comes
    before the release it leads up to. Unparseable versions sort first."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(.*)", version)
    if not m:
        return (0, 0, 0, 0)
    major, minor, patch, rest = m.groups()
    return (int(major), int(minor), int(patch), 0 if "dev" in rest else 1)


def latest_release(url: str | None = None) -> str | None:
    """The newest ``vX.Y.Z`` tag at ``url`` (default REPO_URL), via ``git ls-remote``."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", url or REPO_URL],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as e:
        raise TavlaError("git executable not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise TavlaError(f"timed out asking {url or REPO_URL} for releases") from e
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        raise TavlaError(f"couldn't list releases at {url or REPO_URL}: {msg}")
    tags = [line.rsplit("refs/tags/", 1)[-1] for line in result.stdout.splitlines()]
    releases = [t for t in tags if RELEASE_TAG_RE.match(t)]
    return max(releases, key=lambda t: version_key(t[1:]), default=None)


def check_release(current: str | None = None) -> ReleasePlan:
    return ReleasePlan(current or tavla.__version__, latest_release())


def release_install_command(tag: str) -> list[str]:
    return ["uv", "tool", "install", "--force", f"git+{REPO_URL}@{tag}"]


def install_release(tag: str) -> None:
    """Replace the installed tool with release ``tag``, using uv."""
    _run_uv(release_install_command(tag), "nothing was changed")
