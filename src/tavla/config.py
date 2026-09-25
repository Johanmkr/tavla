"""Content-dir resolution and config.toml handling.

This is the single place that decides where the content repo lives. Every
command must go through :func:`resolve_content_dir`; never hardcode a path
anywhere else.

Resolution order (first match wins):
    1. ``--content-dir`` CLI flag
    2. ``TAVLA_CONTENT_DIR`` environment variable
    3. ``content_dir`` key in ``$XDG_CONFIG_HOME/tavla/config.toml``
    4. Default: ``$XDG_DATA_HOME/tavla/`` (``~/.local/share/tavla/``)
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from tavla.core.errors import TavlaError

ENV_CONTENT_DIR = "TAVLA_CONTENT_DIR"


def _xdg_dir(env_var: str, fallback: str) -> Path:
    value = os.environ.get(env_var)
    # The XDG spec says relative paths are invalid and must be ignored.
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback


def config_dir() -> Path:
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / "tavla"


def config_path() -> Path:
    return config_dir() / "config.toml"


def default_content_dir() -> Path:
    return _xdg_dir("XDG_DATA_HOME", ".local/share") / "tavla"


def cache_dir() -> Path:
    return _xdg_dir("XDG_CACHE_HOME", ".cache") / "tavla"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Return the parsed config file, or an empty dict if it doesn't exist."""
    path = path or config_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise TavlaError(f"invalid config file {path}: {e}") from e


def save_config(data: dict[str, Any], path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(data, f)
    return path


def _expand(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def resolve_content_dir(cli_value: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the content directory using the documented precedence order."""
    if cli_value:
        return _expand(cli_value)
    env_value = os.environ.get(ENV_CONTENT_DIR)
    if env_value:
        return _expand(env_value)
    cfg_value = load_config().get("content_dir")
    if cfg_value:
        return _expand(cfg_value)
    return default_content_dir().resolve()
