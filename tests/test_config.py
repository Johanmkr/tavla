from __future__ import annotations

from tavla import config


def test_default_is_xdg_data_home(isolated_env):
    assert config.resolve_content_dir() == (isolated_env / ".local/share/tavla").resolve()


def test_config_file_beats_default(isolated_env, tmp_path):
    config.save_config({"content_dir": str(tmp_path / "from-config")})
    assert config.resolve_content_dir() == (tmp_path / "from-config").resolve()


def test_env_beats_config(tmp_path, monkeypatch):
    config.save_config({"content_dir": str(tmp_path / "from-config")})
    monkeypatch.setenv("TAVLA_CONTENT_DIR", str(tmp_path / "from-env"))
    assert config.resolve_content_dir() == (tmp_path / "from-env").resolve()


def test_flag_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVLA_CONTENT_DIR", str(tmp_path / "from-env"))
    assert config.resolve_content_dir(tmp_path / "from-flag") == (tmp_path / "from-flag").resolve()


def test_tilde_is_expanded(isolated_env):
    assert config.resolve_content_dir("~/notes") == (isolated_env / "notes").resolve()


def test_relative_xdg_is_ignored(isolated_env, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    assert config.config_path() == isolated_env / ".config/tavla/config.toml"


def test_missing_config_is_empty():
    assert config.load_config() == {}
