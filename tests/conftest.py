from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Never touch the real user's config, data dir or git identity."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.delenv("TAVLA_CONTENT_DIR", raising=False)
    # Deterministic git identity; ignore the developer's global git config.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "tavla-test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.invalid")
    return home


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def basic_content() -> Path:
    """Read-only sample content tree. Copy it (see ``content_copy``) before writing."""
    return FIXTURES / "basic"


@pytest.fixture
def content_copy(tmp_path, basic_content) -> Path:
    dest = tmp_path / "content"
    shutil.copytree(basic_content, dest)
    return dest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def git_content(content_copy) -> Path:
    """Writable copy of the sample tree, as a git repo with one initial commit."""
    _git(content_copy, "init", "--quiet")
    _git(content_copy, "add", "--all")
    _git(content_copy, "commit", "--quiet", "-m", "initial")
    return content_copy


@pytest.fixture
def git():
    """``git(repo, *args) -> stdout`` helper for assertions."""
    return _git


@pytest.fixture
def editor(tmp_path, monkeypatch):
    """Point $EDITOR at a script that applies text replacements to the file.

    ``editor(("todo", "doing"), ...)`` installs it; the returned path is a log
    file with one line per editor invocation.
    """

    def install(*replacements: tuple[str, str]) -> Path:
        spec = tmp_path / "fake_editor.json"
        calls = tmp_path / "fake_editor_calls.txt"
        script = tmp_path / "fake_editor.py"
        spec.write_text(json.dumps(replacements))
        calls.write_text("")
        script.write_text(
            "import json, pathlib, sys\n"
            "path = pathlib.Path(sys.argv[1])\n"
            "text = path.read_text()\n"
            f"for old, new in json.loads(pathlib.Path({str(spec)!r}).read_text()):\n"
            "    text = text.replace(old, new)\n"
            "path.write_text(text)\n"
            f"with open({str(calls)!r}, 'a') as f:\n"
            "    f.write(sys.argv[1] + '\\n')\n"
        )
        monkeypatch.setenv("EDITOR", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}")
        return calls

    return install
