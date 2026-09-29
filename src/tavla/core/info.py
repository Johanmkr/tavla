"""``tavla info``: the facts a bug report needs, in one place."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import tavla
from tavla import config
from tavla.core import bootstrap, self_update
from tavla.core.errors import TavlaError
from tavla.core.store import Content


@dataclass
class Info:
    tavla: str
    install: str  # "release", or "clone at <path>"
    python: str
    platform: str
    git: str | None
    uv: str | None
    editor: str | None
    config_file: Path
    config_exists: bool
    content_dir: Path
    content_source: str  # which rule picked the content dir
    content_initialized: bool
    layout: int | None  # the content's layout version
    layout_expected: int
    counts: dict[str, int] | None  # projects/goals/tasks, if the content loads
    problem: str | None  # why the content couldn't be read


def _version(cmd: str) -> str | None:
    if shutil.which(cmd) is None:
        return None
    try:
        out = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def gather(content_dir_flag: str | os.PathLike[str] | None = None) -> Info:
    """Collect versions and paths. Never raises for a missing or broken
    content repo: that is exactly what a bug report may be about."""
    try:
        install = f"clone at {self_update.source_repo()}"
    except TavlaError:
        install = "release"
    content_dir, source = config.content_dir_and_source(content_dir_flag)
    initialized = bootstrap.is_initialized(content_dir)
    layout = counts = problem = None
    if initialized:
        try:
            layout = bootstrap.schema_version(content_dir)
            content = Content.open(content_dir)
            counts = {
                "projects": len(content.projects()),
                "goals": len(content.goals()),
                "tasks": len(content.tasks()),
            }
        except (TavlaError, OSError) as e:
            problem = str(e)
    return Info(
        tavla=tavla.__version__,
        install=install,
        python=f"{platform.python_version()} ({sys.executable})",
        platform=platform.platform(),
        git=_version("git"),
        uv=_version("uv"),
        editor=os.environ.get("VISUAL") or os.environ.get("EDITOR"),
        config_file=config.config_path(),
        config_exists=config.config_path().is_file(),
        content_dir=content_dir,
        content_source=source,
        content_initialized=initialized,
        layout=layout,
        layout_expected=bootstrap.SCHEMA_VERSION,
        counts=counts,
        problem=problem,
    )
