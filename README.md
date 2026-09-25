# tavla

A personal research operations tool: multi-project progress tracking, tasks,
deliverables and reading material — CLI-first, plain text, git-native.

> Status: early development (milestone 1 — scaffolding + `tavla init`).

## Install (development)

```sh
uv venv && uv pip install -e '.[dev]'
```

## Quick start

```sh
tavla init                       # creates ~/.local/share/tavla/ as a git repo
tavla init --content-dir ~/notes/tavla
```

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
