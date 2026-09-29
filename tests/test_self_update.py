from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import self_update
from tavla.core.errors import TavlaError

runner = CliRunner()


@pytest.fixture
def clones(tmp_path, git):
    """A bare ``origin`` plus two clones of it: ``local`` (the one being
    updated) and ``upstream`` (where new commits are made and pushed)."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(origin))
    upstream = tmp_path / "upstream"
    git(tmp_path, "clone", "--quiet", str(origin), str(upstream))
    git(upstream, "checkout", "--quiet", "-b", "main")
    (upstream / "pyproject.toml").write_text("[project]\nname = 'tavla'\n")
    (upstream / "README.md").write_text("v1\n")
    git(upstream, "add", "--all")
    git(upstream, "commit", "--quiet", "-m", "initial")
    git(upstream, "push", "--quiet", "origin", "main")
    local = tmp_path / "local"
    git(tmp_path, "clone", "--quiet", str(origin), str(local))
    return local, upstream


def _push(git, upstream: Path, name: str, text: str, message: str) -> None:
    (upstream / name).write_text(text)
    git(upstream, "commit", "--quiet", "-am", message)
    git(upstream, "push", "--quiet", "origin", "main")


def _head(git, repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def test_up_to_date(clones):
    local, _ = clones
    plan = self_update.check(local)
    assert plan.up_to_date
    assert not plan.reinstall


def test_fast_forwards_to_origin_main(clones, git):
    local, upstream = clones
    _push(git, upstream, "README.md", "v2\n", "second")
    _push(git, upstream, "README.md", "v3\n", "third")
    plan = self_update.check(local)
    assert [line.split(" ", 1)[1] for line in plan.commits] == ["third", "second"]
    assert not plan.reinstall
    assert (local / "README.md").read_text() == "v1\n"  # check changes nothing
    self_update.apply(plan)
    assert (local / "README.md").read_text() == "v3\n"
    assert _head(git, local) == _head(git, upstream)


def test_pyproject_change_asks_for_reinstall(clones, git):
    local, upstream = clones
    _push(git, upstream, "pyproject.toml", "[project]\nname = 'tavla'\n# new dep\n", "deps")
    assert self_update.check(local).reinstall


def test_local_commits_ahead_are_left_alone(clones, git):
    local, _ = clones
    (local / "README.md").write_text("mine\n")
    git(local, "commit", "--quiet", "-am", "local work")
    before = _head(git, local)
    plan = self_update.check(local)
    assert plan.up_to_date
    self_update.apply(plan)
    assert _head(git, local) == before


def test_diverged_is_refused(clones, git):
    local, upstream = clones
    _push(git, upstream, "README.md", "theirs\n", "upstream work")
    (local / "notes.txt").write_text("mine\n")
    git(local, "add", "notes.txt")
    git(local, "commit", "--quiet", "-m", "local work")
    with pytest.raises(TavlaError, match="diverged"):
        self_update.check(local)


def test_uncommitted_changes_are_refused(clones, git):
    local, upstream = clones
    _push(git, upstream, "README.md", "v2\n", "second")
    (local / "README.md").write_text("edited\n")
    with pytest.raises(TavlaError, match="uncommitted"):
        self_update.check(local)
    assert (local / "README.md").read_text() == "edited\n"


def test_other_branch_is_refused(clones, git):
    local, _ = clones
    git(local, "checkout", "--quiet", "-b", "feature")
    with pytest.raises(TavlaError, match="'feature', not 'main'"):
        self_update.check(local)


def test_source_repo_is_this_checkout():
    repo = self_update.source_repo()
    assert (repo / "src/tavla/__init__.py").is_file()


class FakeUv:
    """Stands in for ``uv`` so tests never reinstall anything for real."""

    def __init__(self, monkeypatch, *, installed=True, returncode=0, stderr=""):
        self.calls: list[list[str]] = []
        self.returncode, self.stderr = returncode, stderr
        self.real_run = subprocess.run
        monkeypatch.setattr(
            self_update.shutil, "which", lambda name: "/usr/bin/uv" if installed else None
        )
        monkeypatch.setattr(self_update.subprocess, "run", self)

    def __call__(self, cmd, **kwargs):
        if cmd[0] != "uv":  # git and anything else run for real
            return self.real_run(cmd, **kwargs)
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


def test_reinstall_runs_uv(monkeypatch, tmp_path):
    uv = FakeUv(monkeypatch)
    self_update.reinstall(tmp_path)
    assert uv.calls == [["uv", "tool", "install", "--force", "--editable", str(tmp_path)]]


def test_reinstall_without_uv(monkeypatch, tmp_path):
    uv = FakeUv(monkeypatch, installed=False)
    with pytest.raises(TavlaError, match="uv not found.*finish with: uv tool install"):
        self_update.reinstall(tmp_path)
    assert uv.calls == []


def test_reinstall_failure(monkeypatch, tmp_path):
    FakeUv(monkeypatch, returncode=2, stderr="resolution failed")
    with pytest.raises(TavlaError, match="resolution failed"):
        self_update.reinstall(tmp_path)


def test_cli_update(clones, git, monkeypatch):
    local, upstream = clones
    monkeypatch.setattr(self_update, "source_repo", lambda: local)

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output

    _push(git, upstream, "pyproject.toml", "[project]\nname = 'tavla'\n# dep\n", "new dep")
    result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0, result.output
    assert "1 new commit on origin/main" in result.output
    assert "new dep" in result.output
    assert _head(git, local) != _head(git, upstream)

    uv = FakeUv(monkeypatch)
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert "Updated tavla" in result.output
    assert "Reinstalled." in result.output
    assert uv.calls == [["uv", "tool", "install", "--force", "--editable", str(local)]]
    assert _head(git, local) == _head(git, upstream)


def test_cli_update_without_install_change_skips_reinstall(clones, git, monkeypatch):
    local, upstream = clones
    monkeypatch.setattr(self_update, "source_repo", lambda: local)
    _push(git, upstream, "README.md", "v2\n", "docs only")
    uv = FakeUv(monkeypatch)
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert "Reinstall" not in result.output
    assert uv.calls == []


def test_cli_update_refusal_exit_code(clones, git, monkeypatch):
    local, _ = clones
    monkeypatch.setattr(self_update, "source_repo", lambda: local)
    git(local, "checkout", "--quiet", "-b", "feature")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "switch to main" in result.output


# --- release installs ---------------------------------------------------------


@pytest.fixture
def releases(clones, git, monkeypatch):
    """Make the test origin stand in for GitHub; ``tag(name)`` adds a tag there."""
    _, upstream = clones
    origin = upstream.parent / "origin.git"
    monkeypatch.setattr(self_update, "REPO_URL", str(origin))

    def tag(name: str) -> None:
        git(upstream, "tag", name)
        git(upstream, "push", "--quiet", "origin", name)

    return tag


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.2.0", "0.10.0"),
        ("0.2.1.dev3+gabc", "0.2.1"),
        ("0.2.0", "0.2.1.dev3+gabc"),
        ("0.0.0", "0.1.0"),
    ],
)
def test_version_order(older, newer):
    assert self_update.version_key(older) < self_update.version_key(newer)


def test_latest_release_picks_highest_final_tag(releases):
    assert self_update.latest_release() is None
    for name in ["v0.2.0", "v0.10.0", "v0.9.1", "v1.0.0rc1", "experiment"]:
        releases(name)
    assert self_update.latest_release() == "v0.10.0"


def test_release_plan(releases):
    releases("v0.3.0")
    assert not self_update.check_release("0.2.0").up_to_date
    assert not self_update.check_release("0.3.0.dev4+gabc").up_to_date
    assert self_update.check_release("0.3.0").up_to_date
    assert self_update.check_release("0.3.1.dev1+gabc").up_to_date


def test_latest_release_bad_url(monkeypatch, tmp_path):
    monkeypatch.setattr(self_update, "REPO_URL", str(tmp_path / "missing.git"))
    with pytest.raises(TavlaError, match="couldn't list releases"):
        self_update.latest_release()


def _release_install(monkeypatch, version: str) -> None:
    def not_a_clone():
        raise TavlaError("not a clone")

    monkeypatch.setattr(self_update, "source_repo", not_a_clone)
    monkeypatch.setattr(self_update.tavla, "__version__", version)


def test_cli_update_release(releases, monkeypatch):
    _release_install(monkeypatch, "0.2.0")
    result = runner.invoke(app, ["update"])
    assert "no releases published yet" in result.output

    releases("v0.2.0")
    assert "is up to date" in runner.invoke(app, ["update"]).output

    releases("v0.3.0")
    result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0, result.output
    assert "tavla v0.3.0 is available (you have 0.2.0)" in result.output
    assert "/releases/tag/v0.3.0" in result.output

    uv = FakeUv(monkeypatch)
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert "Updated tavla 0.2.0 -> 0.3.0." in result.output
    assert uv.calls == [["uv", "tool", "install", "--force", f"git+{self_update.REPO_URL}@v0.3.0"]]


def test_cli_update_release_uv_failure(releases, monkeypatch):
    _release_install(monkeypatch, "0.2.0")
    releases("v0.3.0")
    FakeUv(monkeypatch, returncode=1, stderr="no network")
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
    assert "no network" in result.output
    assert "Nothing was changed; run: uv tool install --force git+" in result.output
