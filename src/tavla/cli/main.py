"""Entry point for the ``tavla`` CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from tavla import __version__, config
from tavla.cli import add, capture, deliverable, goal, idea, overview, project, task
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
from tavla.core.errors import EXIT_INVALID

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


@app.command(rich_help_panel=SETUP)
@handles_errors
def update(
    check: Annotated[
        bool, typer.Option("--check", help="Only show what's new; change nothing.")
    ] = False,
) -> None:
    """Update tavla to the latest version on the main branch (fast-forward only).

    Works when tavla is installed from a git clone (`uv tool install --editable`).
    Refuses to touch a clone with uncommitted changes, another branch checked
    out, or local commits that diverge from origin/main.
    """
    repo = self_update.source_repo()
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
