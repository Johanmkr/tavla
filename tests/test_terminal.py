"""Task terminals: tv work -t, the tv session wrapper, colours and terminal commands."""

from __future__ import annotations

import datetime as dt
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tavla.cli.main import app
from tavla.core import colours, focus, terminal
from tavla.core.entities import TaskStatus
from tavla.core.errors import TavlaError, ValidationError
from tavla.core.store import Content

runner = CliRunner()
START = dt.datetime(2026, 10, 22, 9, 30)  # noqa: DTZ001 — sessions store naive local time
END = START + dt.timedelta(minutes=95)


@pytest.fixture
def content(git_content) -> Content:
    return Content.open(git_content)


@pytest.fixture
def run(git_content):
    def _run(*args: str):
        return runner.invoke(app, ["--content-dir", str(git_content), *args])

    return _run


@pytest.fixture
def launched(monkeypatch):
    """Pretend kitty is installed and capture what would be started."""
    calls: list[list[str]] = []
    monkeypatch.setenv(terminal.ENV_TERMINAL, "kitty")
    monkeypatch.setattr(terminal.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(terminal, "spawn", lambda cmd, cwd: calls.append(cmd))
    return calls


def _subjects(git, repo, n: int) -> list[str]:
    return git(repo, "log", f"-{n}", "--format=%s").splitlines()


# --- colours ---------------------------------------------------------------------


def test_default_colour_is_stable_and_overridable():
    assert colours.default_name("fix-plots") == colours.default_name("fix-plots")
    assert colours.default_name("fix-plots") in colours.ACCENTS
    picked = colours.scheme("fix-plots", "mauve")
    assert (picked.name, picked.accent) == ("mauve", "#cba6f7")
    assert colours.blend("#ffffff", "#000000", 0.5) == "#808080"


def test_colour_is_validated_and_edited(run, content):
    result = run("task", "edit", "fix-plot-colors", "--colour", "Teal")
    assert result.exit_code == 0, result.output
    assert Content.open(content.root).task("fix-plot-colors").colour == "teal"
    assert run("task", "edit", "fix-plot-colors", "--colour", "beige").exit_code != 0
    assert run("task", "edit", "fix-plot-colors", "--colour", "none").exit_code == 0
    assert Content.open(content.root).task("fix-plot-colors").colour is None


# --- choosing and building the command -------------------------------------------


def _window(argv: list[str] | None = None) -> terminal.Window:
    return terminal.Window("Fix plots", Path("/work"), colours.scheme("x", "red"), argv or ["sh"])


def test_kitty_command_sets_title_folder_and_colours():
    cmd = terminal.command("kitty", _window())
    assert cmd[:5] == ["kitty", "--title", "Fix plots", "--directory", "/work"]
    assert f"background={colours.scheme('x', 'red').background}" in cmd
    assert "cursor=#f38ba8" in cmd
    assert cmd[-1] == "sh"


def test_every_known_terminal_runs_the_session_last():
    for name in terminal.TERMINALS:
        assert terminal.command(name, _window(["tv", "session", "x"]))[-3:] == [
            "tv",
            "session",
            "x",
        ]


def test_command_template_fills_placeholders():
    cmd = terminal.command("myterm --name '{title}' --bg {background}", _window())
    assert cmd == [
        "myterm",
        "--name",
        "Fix plots",
        "--bg",
        colours.scheme("x", "red").background,
        "sh",
    ]
    with pytest.raises(TavlaError, match="invalid terminal command"):
        terminal.command("myterm {nope}", _window())


def test_choose_prefers_setting_then_running_terminal(monkeypatch):
    monkeypatch.setattr(terminal.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert terminal.choose({"TAVLA_TERMINAL": "foot"}) == "foot"
    assert terminal.choose({"DISPLAY": ":0", "GHOSTTY_RESOURCES_DIR": "/x"}) == "ghostty"
    assert terminal.choose({"DISPLAY": ":0"}) == "kitty"
    if sys.platform != "darwin":
        with pytest.raises(TavlaError, match="no graphical session"):
            terminal.choose({})


# --- opening ---------------------------------------------------------------------


def test_open_task_marks_doing_and_launches(content, launched, git):
    task = content.task("draft-related-work")
    assert terminal.open_task(content, task) == "kitty"
    assert Content.open(content.root).task(task.id).status == TaskStatus.DOING
    assert _subjects(git, content.root, 1) == ["task: start draft-related-work"]
    (cmd,) = launched
    assert cmd[cmd.index("--title") + 1] == task.title
    assert cmd[-4:] == ["--content-dir", str(content.root), "session", task.id]


def test_open_subtask_titles_window_and_refuses_finished(content, launched):
    task = content.task("draft-related-work")
    terminal.open_task(content, task, task.subtasks[1])
    assert launched[0][launched[0].index("--title") + 1].endswith(f"› {task.subtasks[1].text}")
    assert launched[0][-2:] == ["--subtask", "2"]
    with pytest.raises(ValidationError, match="already ticked"):
        terminal.open_task(content, task, task.subtasks[0])
    with pytest.raises(ValidationError, match="already done"):
        terminal.open_task(content, content.task("outline-structure"))


def test_cli_work_terminal(run, launched):
    result = run("work", "-t", "draft-related-work", "-s", "Write two")
    assert result.exit_code == 0, result.output
    assert "closing the terminal ticks it" in result.output
    assert launched[0][-2:] == ["--subtask", "2"]
    assert run("work", "-s", "2").exit_code != 0  # -s needs -t


# --- sessions --------------------------------------------------------------------


def test_closing_marks_done_and_logs_session(content, git):
    task = content.task("draft-related-work")
    session = focus.start_terminal(content, task, now=START)
    assert [s.task_id for s in focus.terminal_sessions(content)] == [task.id]
    message = focus.end_terminal(content, session, now=END)
    assert message == "done draft-related-work after 1h35m"
    task = Content.open(content.root).task(task.id)
    assert task.status == TaskStatus.DONE
    assert [s.duration for s in focus.sessions(task)] == [dt.timedelta(minutes=95)]
    assert _subjects(git, content.root, 1) == [f"session: {message}"]
    assert not session.path.exists()


def test_closing_subtask_terminal_ticks_it(content):
    task = content.task("draft-related-work")
    session = focus.start_terminal(content, task, task.subtasks[1].text, now=START)
    focus.end_terminal(content, session, now=END)
    task = Content.open(content.root).task(task.id)
    assert task.subtasks[1].done
    assert task.status != TaskStatus.DONE


def test_paused_terminal_only_logs(content, run, monkeypatch):
    task = content.task("draft-related-work")
    session = focus.start_terminal(content, task, now=START)
    monkeypatch.setenv(focus.ENV_SESSION, str(session.path))
    monkeypatch.setenv(focus.ENV_TASK, task.id)
    result = run("pause")
    assert "not finish it" in result.output
    # The short commands act on the terminal's task.
    assert run("note", "halfway").exit_code == 0
    assert focus.end_terminal(content, session, now=END).startswith("logged 1h35m")
    task = Content.open(content.root).task(task.id)
    assert task.status != TaskStatus.DONE
    assert len(focus.sessions(task)) == 1


def test_dead_sessions_are_cleaned_up(content):
    session = focus.start_terminal(content, content.task("draft-related-work"), pid=2**22 + 7)
    assert focus.terminal_sessions(content) == []
    assert not session.path.exists()


def test_work_lists_open_terminals(content, run):
    focus.start_terminal(content, content.task("draft-related-work"), now=START)
    result = run("work")
    assert "Open task terminals:" in result.output
    assert "draft-related-work, since 09:30" in result.output


# --- the wrapper, for real --------------------------------------------------------


def _wrapper(content: Content, shell: str, *extra: str) -> subprocess.Popen[bytes]:
    env = {**os.environ, "SHELL": shell}
    argv = [sys.executable, "-m", "tavla", "--content-dir", str(content.root), "session", *extra]
    return subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, start_new_session=True)


def test_session_wrapper_finishes_when_shell_exits(content):
    proc = _wrapper(content, "/bin/true", "draft-related-work")
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0
    assert b"Closing this terminal marks it done" in out
    assert Content.open(content.root).task("draft-related-work").status == TaskStatus.DONE


def test_session_wrapper_survives_hangup(content, tmp_path):
    shell = tmp_path / "shell"
    shell.write_text("#!/bin/sh\nexec sleep 60\n")
    shell.chmod(0o755)
    proc = _wrapper(content, str(shell), "draft-related-work", "--subtask", "2")
    deadline = time.monotonic() + 30
    while not focus.terminal_sessions(content):  # wait until the shell runs
        assert time.monotonic() < deadline
        time.sleep(0.1)
    time.sleep(0.3)
    os.killpg(proc.pid, signal.SIGHUP)  # what closing the window does
    proc.wait(timeout=30)
    assert proc.returncode == 0
    assert Content.open(content.root).task("draft-related-work").subtasks[1].done
