"""Opening a task in a terminal of its own (``tv work -t``, ``W`` in ``tv ui``).

The new window is titled with the task (``Task › subtask`` for a subtask),
coloured with the task's Catppuccin accent (see :mod:`tavla.core.colours`),
starts in the project's linked folder, and runs ``tv session``: that keeps
the session file, runs your shell, and finishes the task when the window
closes (see :func:`tavla.core.focus.end_terminal`).

Which terminal: ``$TAVLA_TERMINAL``, else ``terminal`` in config.toml, else
the one tavla is running in, else the first one installed. The setting is a
name from :data:`TERMINALS`, or a command with ``{title}``, ``{cwd}``,
``{background}``, ``{foreground}`` and ``{accent}`` placeholders; the session
command is appended to it.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tavla import config
from tavla.core import colours, ops, queries
from tavla.core.entities import Subtask, Task, TaskStatus
from tavla.core.errors import TavlaError, ValidationError
from tavla.core.store import Content

ENV_TERMINAL = "TAVLA_TERMINAL"
TERMINALS = (
    "kitty",
    "ghostty",
    "wezterm",
    "alacritty",
    "foot",
    "gnome-terminal",
    "konsole",
    "xterm",
)
# Environment variables that tell which terminal we are running in.
_RUNNING_IN = (
    ("KITTY_WINDOW_ID", "kitty"),
    ("GHOSTTY_RESOURCES_DIR", "ghostty"),
    ("WEZTERM_PANE", "wezterm"),
    ("ALACRITTY_WINDOW_ID", "alacritty"),
    ("KONSOLE_VERSION", "konsole"),
    ("VTE_VERSION", "gnome-terminal"),
)


@dataclass
class Window:
    title: str
    cwd: Path
    scheme: colours.Scheme
    argv: list[str]  # what runs inside


def command(terminal: str, window: Window) -> list[str]:
    """The command line that opens ``window`` in ``terminal`` (a name from
    :data:`TERMINALS`, or a command template)."""
    t, cwd, argv = window.title, str(window.cwd), window.argv
    bg, fg, accent = window.scheme.background, window.scheme.foreground, window.scheme.accent
    if terminal == "kitty":
        # --title wins over titles the shell sets.
        opts = {
            "background": bg,
            "foreground": fg,
            "cursor": accent,
            "selection_background": accent,
            "selection_foreground": bg,
            "active_tab_background": accent,
            "active_tab_foreground": bg,
        }
        flags = [x for k, v in opts.items() for x in ("-o", f"{k}={v}")]
        return ["kitty", "--title", t, "--directory", cwd, *flags, *argv]
    if terminal == "ghostty":
        return [
            "ghostty",
            f"--title={t}",
            f"--working-directory={cwd}",
            f"--background={bg}",
            f"--foreground={fg}",
            f"--cursor-color={accent}",
            f"--selection-background={accent}",
            f"--selection-foreground={bg}",
            "-e",
            *argv,
        ]
    if terminal == "alacritty":
        opts = {
            "window.dynamic_title": "false",
            "colors.primary.background": f'"{bg}"',
            "colors.primary.foreground": f'"{fg}"',
            "colors.cursor.cursor": f'"{accent}"',
        }
        flags = [x for k, v in opts.items() for x in ("-o", f"{k}={v}")]
        return ["alacritty", "--title", t, "--working-directory", cwd, *flags, "-e", *argv]
    if terminal == "wezterm":
        return ["wezterm", "start", "--always-new-process", "--cwd", cwd, "--", *argv]
    if terminal == "foot":
        return ["foot", "--title", t, "--working-directory", cwd, *argv]
    if terminal == "gnome-terminal":
        return ["gnome-terminal", f"--working-directory={cwd}", "--", *argv]
    if terminal == "konsole":
        return ["konsole", "--workdir", cwd, "-p", f"tabtitle={t}", "-e", *argv]
    if terminal == "xterm":
        return ["xterm", "-T", t, "-bg", bg, "-fg", fg, "-cr", accent, "-e", *argv]
    fields = {"title": t, "cwd": cwd, "background": bg, "foreground": fg, "accent": accent}
    try:
        return [part.format(**fields) for part in shlex.split(terminal)] + argv
    except (KeyError, ValueError) as e:
        raise TavlaError(f"invalid terminal command {terminal!r}: {e}") from None


def choose(environ: dict[str, str] | None = None) -> str:
    """Which terminal to open (see the module docstring)."""
    env = os.environ if environ is None else environ
    chosen = env.get(ENV_TERMINAL) or config.load_config().get("terminal")
    if chosen:
        return str(chosen)
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY") or sys.platform == "darwin"):
        raise TavlaError("no graphical session to open a terminal in")
    for var, name in _RUNNING_IN:
        if env.get(var) and shutil.which(name):
            return name
    for name in TERMINALS:
        if shutil.which(name):
            return name
    raise TavlaError(
        f"no terminal found; set ${ENV_TERMINAL} or `terminal` in {config.config_path()}"
    )


def title(task: Task, subtask: Subtask | None = None) -> str:
    return f"{task.title} › {subtask.text}" if subtask else task.title


def folder(content: Content, task: Task) -> Path:
    """Where the terminal starts: the project's (or a parent project's) first
    linked folder that exists, else the current directory."""
    project_id: str | None = task.project
    while project_id:
        project = content.project(project_id)
        for entry in project.repo_paths:
            path = queries.expand_folder(entry)
            if path.is_dir():
                return path
        project_id = project.parent
    return Path.cwd()


def session_argv(content: Content, task: Task, subtask: Subtask | None) -> list[str]:
    argv = [sys.executable, "-m", "tavla", "--content-dir", str(content.root), "session", task.id]
    return [*argv, "--subtask", str(subtask.number)] if subtask else argv


def open_task(content: Content, task: Task, subtask: Subtask | None = None) -> str:
    """Open ``task`` (or one of its subtasks) in a terminal of its own and
    mark it doing. Returns the terminal's name."""
    if task.status == TaskStatus.DONE:
        raise ValidationError(f"{task.id} is already done")
    if subtask is not None and subtask.done:
        raise ValidationError(f"'{subtask.text}' is already ticked")
    terminal = choose()
    window = Window(
        title(task, subtask),
        folder(content, task),
        colours.scheme(task.id, task.colour),
        session_argv(content, task, subtask),
    )
    cmd = command(terminal, window)
    if shutil.which(cmd[0]) is None:
        raise TavlaError(f"terminal not found: {cmd[0]!r}")
    ops.start(content, task)
    spawn(cmd, window.cwd)
    return terminal.split()[0]


def spawn(cmd: list[str], cwd: Path) -> None:
    """Start the terminal on its own: it outlives tavla, and its output goes nowhere."""
    subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
