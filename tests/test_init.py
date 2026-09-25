from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from tavla import config
from tavla.cli.main import app
from tavla.core.errors import EXIT_ERROR

runner = CliRunner()


def _log(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%s"], capture_output=True, text=True, check=True
    ).stdout.splitlines()


def test_init_creates_skeleton_and_commits(tmp_path):
    content = tmp_path / "content"
    result = runner.invoke(app, ["init", "--content-dir", str(content)])
    assert result.exit_code == 0, result.output

    assert (content / "registry.yaml").is_file()
    assert (content / "inbox.md").is_file()
    assert (content / "library").is_dir()
    assert (content / "projects").is_dir()
    assert (content / ".git").is_dir()
    assert _log(content) == ["init: content repo"]
    status = subprocess.run(
        ["git", "-C", str(content), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == ""


def test_init_writes_default_config(tmp_path):
    content = tmp_path / "content"
    runner.invoke(app, ["init", "--content-dir", str(content)])
    assert config.load_config()["content_dir"] == str(content.resolve())
    assert config.resolve_content_dir() == content.resolve()


def test_init_does_not_overwrite_existing_config(tmp_path):
    config.save_config({"content_dir": "/somewhere/else", "other": 1})
    runner.invoke(app, ["init", "--content-dir", str(tmp_path / "content")])
    assert config.load_config() == {"content_dir": "/somewhere/else", "other": 1}


def test_global_content_dir_flag_is_honoured(tmp_path):
    content = tmp_path / "global-flag"
    result = runner.invoke(app, ["--content-dir", str(content), "init"])
    assert result.exit_code == 0, result.output
    assert (content / "registry.yaml").is_file()


def test_init_uses_env_var(tmp_path, monkeypatch):
    content = tmp_path / "from-env"
    monkeypatch.setenv("TAVLA_CONTENT_DIR", str(content))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (content / "registry.yaml").is_file()


def test_init_twice_fails(tmp_path):
    content = tmp_path / "content"
    runner.invoke(app, ["init", "--content-dir", str(content)])
    result = runner.invoke(app, ["init", "--content-dir", str(content)])
    assert result.exit_code == EXIT_ERROR
    assert "already initialized" in result.output


def test_init_into_existing_nonempty_dir_keeps_files(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    (content / "inbox.md").write_text("existing idea\n")
    result = runner.invoke(app, ["init", "--content-dir", str(content)])
    assert result.exit_code == 0, result.output
    assert (content / "inbox.md").read_text() == "existing idea\n"
