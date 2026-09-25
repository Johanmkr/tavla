from __future__ import annotations

import shutil
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
