# tavla

A personal research operations tool: multi-project progress tracking, tasks,
deliverables and reading material — CLI-first, plain text, git-native.

> Status: Tier 1 complete (milestone 5) — capture, log, projects, tasks, `next`, `status`.

## Install (development)

```sh
uv venv && uv pip install -e '.[dev]'
```

## Quick start

```sh
tavla init                       # creates ~/.local/share/tavla/ as a git repo
tavla init --content-dir ~/notes/tavla

tavla project add "Adaptive sampling" --priority high --tags bayes,mcmc
tavla task add "Write introduction" --project adap --due fri
tavla task edit write-intro       # opens $EDITOR; validated and committed on save
tavla task list
tavla next                        # what to work on, across all active projects
tavla status                      # stale projects, blocked tasks, upcoming deadlines
tavla capture try parallel tempering   # quick inbox capture, quotes optional
tavla log adap "sampler converges"     # timestamped project log entry
tavla task done write-intro

# Try the read commands against the bundled demo tree:
tavla --content-dir example-content project list
tavla --content-dir example-content task list
tavla --content-dir example-content task show write-i   # unique id prefixes work
tavla --content-dir example-content project show project-a --json
```

Enable id tab-completion with `tavla --install-completion`.

Every change tavla makes is committed to the content repo's git history
automatically (`project: add …`, `task: edit …`), so `git log` is your audit
trail and `git revert` is your undo. Only the files tavla touched are
committed — anything else you have staged is left alone.

## Where your data lives

Your content (projects, tasks, notes) lives in a **separate** git repository
from this software. The content directory is resolved in this order:

1. `--content-dir` CLI flag
2. `TAVLA_CONTENT_DIR` environment variable
3. `content_dir` in `~/.config/tavla/config.toml`
4. `~/.local/share/tavla/`

`XDG_CONFIG_HOME` / `XDG_DATA_HOME` are respected.

## Development

```sh
pytest
ruff check .
```
