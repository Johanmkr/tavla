"""Bootstrapping a fresh content directory (``tavla init``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from tavla import config
from tavla.core import git_sync
from tavla.core.errors import TavlaError

REGISTRY_FILE = "registry.yaml"
INBOX_FILE = "inbox.md"
LIBRARY_DIR = "library"
PROJECTS_DIR = "projects"
SCHEMA_FILE = "tavla.yaml"

# Version of the content layout. 1: tasks only (no tavla.yaml). 2: goals/,
# tasks/ with goal pointers, depends_on, ## Ideas sections.
SCHEMA_VERSION = 2

REGISTRY_HEADER = "# Master index of top-level projects — managed by tavla.\n"
_REGISTRY_TEMPLATE = REGISTRY_HEADER + "[]\n"
_INBOX_TEMPLATE = "# Inbox\n\n"


@dataclass
class InitResult:
    content_dir: Path
    config_written: Path | None
    committed: bool


def is_initialized(content_dir: Path) -> bool:
    return (content_dir / REGISTRY_FILE).exists()


def schema_version(content_dir: Path) -> int:
    """The content layout version recorded in ``tavla.yaml`` (1 if absent)."""
    path = content_dir / SCHEMA_FILE
    if not path.is_file():
        return 1
    data = yaml.safe_load(path.read_text()) or {}
    try:
        return int(data.get("schema_version", 1))
    except (AttributeError, TypeError, ValueError):
        raise TavlaError(f"{path}: invalid schema_version") from None


def write_schema_version(content_dir: Path, version: int = SCHEMA_VERSION) -> Path:
    path = content_dir / SCHEMA_FILE
    path.write_text(f"# Content layout version — managed by tavla.\nschema_version: {version}\n")
    return path


def init_content_dir(content_dir: Path, *, write_config: bool = True) -> InitResult:
    """Create the content skeleton, git-init it, and make the first commit.

    If ``write_config`` is true and no config file exists yet, a default
    config pointing at ``content_dir`` is written. An existing config is never
    overwritten.
    """
    if is_initialized(content_dir):
        raise TavlaError(f"content dir already initialized: {content_dir}")
    if content_dir.exists() and not content_dir.is_dir():
        raise TavlaError(f"content dir path is not a directory: {content_dir}")

    content_dir.mkdir(parents=True, exist_ok=True)
    (content_dir / REGISTRY_FILE).write_text(_REGISTRY_TEMPLATE)
    write_schema_version(content_dir)
    inbox = content_dir / INBOX_FILE
    if not inbox.exists():
        inbox.write_text(_INBOX_TEMPLATE)
    for sub in (LIBRARY_DIR, PROJECTS_DIR):
        (content_dir / sub).mkdir(exist_ok=True)
        # Git doesn't track empty directories.
        (content_dir / sub / ".gitkeep").touch()

    config_written = None
    if write_config and not config.config_path().exists():
        config_written = config.save_config({"content_dir": str(content_dir)})

    git_sync.init_repo(content_dir)
    committed = git_sync.commit(content_dir, "init: content repo")
    return InitResult(content_dir, config_written, committed)
