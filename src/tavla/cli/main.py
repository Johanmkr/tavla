"""Entry point for the ``tavla`` CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tavla import __version__, config
from tavla.cli import add, capture, deliverable, flow, goal, idea, overview, project, task
from tavla.cli.common import (
    HELP_SETTINGS,
    JsonOpt,
    State,
    emit_json,
    examples,
    handles_errors,
    state,
)
from tavla.core import bootstrap, history, migrate, self_update
from tavla.core import check as checks
from tavla.core import demo as demos
from tavla.core import info as infos
from tavla.core.errors import EXIT_INVALID, TavlaError

app = typer.Typer(
    name="tavla",
    help="Research operations: projects, tasks, deliverables and reading, in plain text + git.",
    no_args_is_help=True,
    context_settings=HELP_SETTINGS,
)

DAILY = "Daily"
ITEMS = "Projects and what's in them"
SETUP = "Setup and maintenance"

app.command("next", rich_help_panel=DAILY)(overview.next_)
app.command("status", rich_help_panel=DAILY)(overview.status)
app.command(
    "flow",
    rich_help_panel=DAILY,
    epilog=examples(
        "tv flow project-a # goals of a project, in dependency order",
        "tv flow write-intro # tasks of one goal, with their subtasks",
        "tv flow project-a --open # only what's left",
    ),
)(flow.flow_)
app.command("add", rich_help_panel=DAILY)(add.add)
app.command("capture", rich_help_panel=DAILY)(capture.capture)
app.command("log", rich_help_panel=DAILY)(capture.log)
app.add_typer(project.app, name="project", rich_help_panel=ITEMS)
app.add_typer(goal.app, name="goal", rich_help_panel=ITEMS)
app.add_typer(task.app, name="task", rich_help_panel=ITEMS)
app.add_typer(idea.app, name="idea", rich_help_panel=ITEMS)
app.add_typer(deliverable.app, name="deliverable", rich_help_panel=ITEMS)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tavla {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    content_dir: Annotated[
        Path | None,
        typer.Option("--content-dir", help="Override content dir for this invocation."),
    ] = None,
    json_out: Annotated[
        bool, typer.Option("--json", help="Machine-readable output on read commands.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompts.")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Verbose output.")] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    ctx.obj = State(content_dir, json_out, yes, verbose)


@app.command(rich_help_panel=SETUP)
@handles_errors
def init(
    ctx: typer.Context,
    content_dir: Annotated[
        Path | None,
        typer.Option("--content-dir", help="Where to create the content repo."),
    ] = None,
) -> None:
    """Bootstrap a content dir, git-init it, and write a default config."""
    st = state(ctx)
    if content_dir is not None:
        st.content_dir_flag = content_dir
    result = bootstrap.init_content_dir(st.content_dir)
    typer.echo(f"Initialized tavla content repo at {result.content_dir}")
    if result.config_written:
        typer.echo(f"Wrote config to {result.config_written}")
    elif st.verbose:
        typer.echo(f"Existing config left untouched: {config.config_path()}")


@app.command("migrate", rich_help_panel=SETUP)
@handles_errors
def migrate_(
    ctx: typer.Context,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would change; write nothing.")
    ] = False,
    content_dir: Annotated[Path | None, typer.Option("--content-dir", hidden=True)] = None,
) -> None:
    """Upgrade the content repo to the layout this tavla uses (one git commit).

    v1 -> v2: each task becomes a goal (tasks/ -> goals/), and each of its
    subtask checkboxes becomes a task under that goal.
    """
    st = state(ctx, content_dir=content_dir)
    plan = migrate.plan(st.content_dir)
    if not plan.needed:
        typer.echo(f"Already at layout v{plan.from_version}; nothing to do.")
        return
    typer.secho(
        f"Migrating {plan.root} from layout v{plan.from_version} to v{plan.to_version}", bold=True
    )
    for move in plan.moves:
        typer.echo(
            f"  goal  {move.goal_id}: {move.old.relative_to(plan.root)} -> "
            f"{move.new.relative_to(plan.root)}"
        )
        for t in move.tasks:
            state_ = "done" if t.done else "todo"
            typer.echo(f"    task  {t.id} [{state_}]  {t.title}")
    if not plan.moves:
        typer.echo("  (no task files to convert)")
    if dry_run:
        typer.echo("Dry run: nothing written.")
        return
    migrate.apply(plan)
    typer.echo("Done. Committed as one change; `tavla undo` reverts it.")


@app.command(
    rich_help_panel=DAILY,
    epilog=examples(
        "tv undo -n # show what would be undone",
        "tv undo; tv undo # the last two changes",
    ),
)
@handles_errors
def undo(
    ctx: typer.Context,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would be undone; change nothing.")
    ] = False,
    content_dir: Annotated[Path | None, typer.Option("--content-dir", hidden=True)] = None,
) -> None:
    """Undo the last change to the content repo (as a new commit, so nothing is lost).

    Run it again to undo the change before that.
    """
    root = state(ctx, content_dir=content_dir).content().root
    change = history.last_change(root)
    if change is None:
        typer.echo("Nothing to undo.")
        return
    typer.echo(f"{'Would undo' if dry_run else 'Undoing'}: {change.subject}  ({change.when})")
    for f in change.files:
        typer.echo(f"  {f}")
    if not dry_run:
        history.undo(root, change)


@app.command(
    rich_help_panel=SETUP,
    epilog=examples(
        "tv check # report problems",
        "tv check --fix # also fix what can be fixed",
    ),
)
@handles_errors
def check(
    ctx: typer.Context,
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Fix project: lines by moving files or resetting the line."),
    ] = False,
    json_out: JsonOpt = False,
    content_dir: Annotated[Path | None, typer.Option("--content-dir", hidden=True)] = None,
) -> None:
    """Check the content repo for problems, e.g. after editing files by hand.

    Finds files that don't load, duplicate ids, unknown goals or dependencies,
    dependency cycles, and goals/tasks whose project: line disagrees with the
    project folder they are in. --fix moves each such file to the project its
    line names, or resets a line naming no known project; one commit each.
    Exits with status 3 while problems remain.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    fixed, failed = checks.fix(content) if fix else ([], [])
    failed_paths = {p.path for p in failed}
    problems = failed + [p for p in checks.find_problems(content) if p.path not in failed_paths]

    if st.json:
        emit_json(
            {
                "fixed": fixed,
                "problems": [
                    {
                        "path": str(p.path.relative_to(content.root)),
                        "message": p.message,
                        "fixable": p.fixable,
                    }
                    for p in problems
                ],
            }
        )
    else:
        for line in fixed:
            typer.echo(line)
        for p in problems:
            typer.secho(f"{p.path.relative_to(content.root)}: {p.message}", fg=typer.colors.RED)
        if not problems:
            typer.echo("No problems found.")
        elif any(p.fixable for p in problems):
            typer.echo("Run `tv check --fix` to fix the project: problems.")
    if problems:
        raise typer.Exit(EXIT_INVALID)


@app.command(
    rich_help_panel=SETUP,
    epilog=examples(
        "tv demo # set it up and show how to use it",
        "tv demo --reset # start over with fresh content",
    ),
)
@handles_errors
def demo(
    directory: Annotated[
        Path | None,
        typer.Argument(help="Where to put it (default: tavla's cache directory)."),
    ] = None,
    reset: Annotated[
        bool, typer.Option("--reset", help="Replace an existing demo with fresh content.")
    ] = False,
) -> None:
    """Set up a playground with example projects, to try every command safely.

    The demo is a separate content repo (a PhD thesis, a teaching job, a
    paused paper) with its dates moved to around today. Your own content is
    never touched: point tavla at the demo with TAVLA_CONTENT_DIR or
    --content-dir, and unset it to go back.
    """
    dest = (directory or config.cache_dir() / "demo").expanduser().resolve()
    if demos.exists(dest) and not reset:
        typer.echo(f"The demo is already set up at {dest} (--reset starts over).")
    else:
        demos.create(dest, reset=reset)
        typer.echo(f"Demo content ready at {dest}")
    shown = str(dest).replace(str(Path.home()), "~", 1)
    typer.echo(
        "\nTry it in this shell (your own notes are untouched):\n\n"
        f"  export TAVLA_CONTENT_DIR={shown}\n"
        "  tv next\n"
        "  tv status\n"
        "  tv flow thesis\n"
        "  tv task done draft-methods   # write commands work too\n"
        "  unset TAVLA_CONTENT_DIR      # back to your own content\n\n"
        f"Or for a single command: tv --content-dir {shown} next"
    )


@app.command("info", rich_help_panel=SETUP)
@handles_errors
def info_(
    ctx: typer.Context,
    json_out: JsonOpt = False,
    content_dir: Annotated[Path | None, typer.Option("--content-dir", hidden=True)] = None,
) -> None:
    """Versions, paths and content details, for bug reports.

    Paste the output into an issue. It shows file paths (which may include your
    user name) but nothing from your notes.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    info = infos.gather(st.content_dir_flag)
    if st.json:
        emit_json(info)
        return
    if info.layout is None:
        layout = "-"
    elif info.layout == info.layout_expected:
        layout = f"v{info.layout}"
    else:
        layout = f"v{info.layout} (this tavla uses v{info.layout_expected})"
    content = f"{info.content_dir} (from {info.content_source})"
    if not info.content_initialized:
        content += ", not initialized: run `tavla init`"
    rows = [
        ("tavla", f"{info.tavla} ({info.install})"),
        ("python", info.python),
        ("platform", info.platform),
        ("git", info.git or "not found"),
        ("uv", info.uv or "not found"),
        ("editor", info.editor or "not set ($EDITOR)"),
        ("config", f"{info.config_file}{'' if info.config_exists else ' (not created)'}"),
        ("content", content),
        ("layout", layout),
    ]
    if info.counts:
        rows.append(("contents", " · ".join(f"{n} {k}" for k, n in info.counts.items())))
    if info.problem:
        rows.append(("problem", info.problem))
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        typer.echo(f"{key:<{width}}  {value}")


@app.command(rich_help_panel=SETUP)
@handles_errors
def update(
    check: Annotated[
        bool, typer.Option("--check", help="Only show what's new; change nothing.")
    ] = False,
) -> None:
    """Update tavla to the latest release.

    Installed from a release (`uv tool install git+…@vX.Y.Z`): reinstalls the
    newest vX.Y.Z tag with uv. Installed from a git clone (`uv tool install
    --editable`): fast-forwards the clone to origin/main instead, refusing if
    it has uncommitted changes, another branch checked out, or local commits
    that diverge from origin/main.
    """
    try:
        repo = self_update.source_repo()
    except TavlaError:
        _update_release(check)
    else:
        _update_clone(repo, check)


def _update_release(check: bool) -> None:
    plan = self_update.check_release()
    if plan.latest is None:
        typer.echo(f"tavla {plan.current}; no releases published yet.")
        return
    if plan.up_to_date:
        typer.echo(f"tavla {plan.current} is up to date (latest release: {plan.latest}).")
        return
    typer.secho(f"tavla {plan.latest} is available (you have {plan.current}).", bold=True)
    typer.echo(f"What's new: {plan.notes_url}")
    if check:
        typer.echo("Run `tavla update` to install it.")
        return
    typer.echo(f"Installing {plan.latest} with uv...")
    self_update.install_release(plan.latest)
    typer.echo(f"Updated tavla {plan.current} -> {plan.latest[1:]}.")


def _update_clone(repo: Path, check: bool) -> None:
    plan = self_update.check(repo)
    if plan.up_to_date:
        typer.echo(f"tavla is up to date ({plan.old[:7]}).")
        return
    n = len(plan.commits)
    typer.secho(f"{n} new commit{'s' * (n != 1)} on {self_update.UPSTREAM}:", bold=True)
    for line in plan.commits:
        typer.echo(f"  {line}")
    if check:
        typer.echo("Run `tavla update` to install them.")
        return
    self_update.apply(plan)
    typer.echo(f"Updated tavla in {repo}: {plan.old[:7]} -> {plan.new[:7]}")
    if plan.reinstall:
        typer.echo("Dependencies or commands changed; reinstalling with uv...")
        self_update.reinstall(repo)
        typer.echo("Reinstalled.")
