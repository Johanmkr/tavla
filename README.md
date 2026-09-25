# tavla

A personal research operations tool for one researcher juggling several
projects: tasks, progress logs, quick capture and a cross-project "what next?"
view. CLI-first, plain text, git-native.

- **Plain text.** Everything is Markdown or YAML you can read, grep and edit by hand.
- **Git is the history.** Every change tavla makes is auto-committed to your
  content repo, so `git log` is the audit trail and `git revert` is undo.
- **Your data is separate.** Content lives in its own (private) git repo, never
  in this software repo.

> **Status:** Tier 1 complete — projects, tasks, capture, log, `next`, `status`.
> Subprojects via the CLI, deliverables, code-repo links and Zotero sync are
> planned (Tier 2).

## Install

Requires Python 3.11+ and `git`.

```sh
git clone <this repo> && cd tavla
uv tool install --editable .     # puts `tavla` on your PATH; `git pull` updates it
tavla --install-completion       # optional: tab-completion for commands and ids
```

## Getting started

```sh
tavla init
```

This creates your content repo at `~/.local/share/tavla/` (a git repo with an
initial commit) and writes `~/.config/tavla/config.toml` pointing at it. To put
it somewhere else, run `tavla init --content-dir ~/notes/tavla` instead.

A typical first session:

```sh
tavla project add "Adaptive sampling" --priority high --tags bayes,mcmc
#  -> Added project adaptive-sampling

tavla task add "Write introduction" --project adap --due fri --id intro
tavla task add "Run baseline experiments" -p adap --priority high
#  -> Added task run-baseline-experiments to adaptive-sampling

tavla next                          # what to work on, across all active projects
tavla task edit intro               # opens $EDITOR: add subtasks, notes, set status
tavla log adap "baseline converges on the toy model"
tavla capture look into parallel tempering    # quick thought -> inbox
tavla task done intro
tavla status                        # stale projects, blocked tasks, what's due
```

Ids are derived from titles (`"Run baseline experiments"` →
`run-baseline-experiments`) unless you pass `--id`. Anywhere an id is expected
you can type **any unique prefix** — `adap`, `run-b`. If a prefix is ambiguous
tavla lists the candidates instead of guessing.

## Commands

| Command | What it does |
| --- | --- |
| `tavla init [--content-dir PATH]` | Create the content repo and default config |
| `tavla capture TEXT…` | Append a line to `inbox.md` (quotes optional) |
| `tavla log PROJECT TEXT…` | Append a timestamped line to the project's `log.md` |
| `tavla next [-p PROJECT] [--priority P] [-n N]` | Open tasks, most important first (default 10; `-n 0` for all) |
| `tavla status [--stale-days N] [--deadline-days N]` | Stale projects, blocked tasks, tasks due within 7 days, deliverable deadlines |
| `tavla project add NAME [--priority P] [--tags a,b] [--id ID]` | Create a project |
| `tavla project list [--status S] [--all]` | List projects (archived hidden unless `--all`) |
| `tavla project show ID` | Metadata, subprojects, task counts, deliverables, recent log |
| `tavla project edit ID` | Edit `project.yaml` in `$EDITOR` |
| `tavla task add TITLE -p PROJECT [--priority P] [--due DATE] [--tags a,b] [--id ID]` | Create a task |
| `tavla task list [-p PROJECT] [--status S] [--all]` | List tasks (done hidden unless `--all`) |
| `tavla task show ID` | Metadata plus the full task file |
| `tavla task edit ID` | Edit the task file in `$EDITOR` |
| `tavla task done ID` | Mark a task done |

`tavla COMMAND --help` shows every option.

**Global options go before the command:** `tavla --content-dir DIR task list`,
not `tavla task list --content-dir DIR`. They are `--content-dir`, `--json`,
`-y/--yes` and `-v/--verbose`. (`--json` is also accepted after any read command.)

### Values

| Field | Allowed values |
| --- | --- |
| priority | `high`, `med` (default), `low` |
| project status | `active` (default), `paused`, `done`, `archived` |
| task status | `todo` (default), `doing`, `blocked`, `done` |
| dates (`--due`) | `2026-10-01`, `today`, `tomorrow`, `+3d`, `+2w`, `fri`/`friday` (the next one) |

To change a task's status other than to `done` — e.g. `todo` → `doing` or
`blocked` — run `tavla task edit ID` and change the `status:` line.

### How `next` and `status` decide

- `next` shows `todo`/`doing` tasks from **active** projects (a subproject of a
  paused project counts as paused), ordered by task priority, then `doing`
  before `todo`, then soonest due date, then project priority.
  `--priority med` means "med and above". `-p` shows a project even if paused.
- `status` flags an active project as **stale** when nothing has happened for
  14 days — "something" being a `log.md` entry or a task created/updated,
  including in its subprojects. `tavla log` is the easiest way to keep a
  project fresh.

## Your content

```
~/.local/share/tavla/
├── registry.yaml              # index of top-level projects (maintained by tavla)
├── inbox.md                   # `tavla capture` lands here
├── library/                   # reading notes (Tier 2: Zotero sync)
└── projects/
    └── adaptive-sampling/
        ├── project.yaml
        ├── log.md             # `tavla log` lands here
        ├── ideas.md
        ├── tasks/
        │   └── intro.md
        ├── deliverables/      # *.yaml, read by `project show` and `status`
        └── subprojects/       # same shape, nested (create by hand for now)
```

A task file — only the frontmatter and the `## Subtasks` checkboxes are read
by tavla; everything else is yours and is never rewritten:

```markdown
---
id: intro
project: adaptive-sampling
status: doing
priority: med
tags: []
created: 2026-09-25
updated: 2026-09-26
due: 2026-10-02
---

# Write introduction

## Context
Anything you like.

## Subtasks
- [x] Outline structure
- [ ] Draft related work        <- counted as 1/2 in `next` and `task list`

## Updates
- 2026-09-26: outline done
```

You can edit any file by hand. If you do, commit it yourself (tavla only
auto-commits its own changes); `tavla task edit` / `project edit` validate the
file and commit for you, and restore it if you save something invalid.

A task's project is the folder it lives in — you can move a task file to
another project's `tasks/` folder and it follows. Links between things use ids,
never paths.

### Where the content repo is found

First match wins:

1. `--content-dir PATH`
2. the `TAVLA_CONTENT_DIR` environment variable
3. `content_dir` in `~/.config/tavla/config.toml`
4. `~/.local/share/tavla/`

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` are respected.

### Syncing between machines

tavla commits locally and never pushes. To sync, add a **private** remote to
the content repo and push/pull as usual:

```sh
cd ~/.local/share/tavla
git remote add origin git@github.com:you/tavla-content.git   # keep it private
git push -u origin main
```

## Scripting

Read commands (`next`, `status`, `project list/show`, `task list/show`) accept
`--json`. Exit codes: `0` success, `1` error, `2` id not found, `3` ambiguous
id or invalid data.

## Try it on the demo content

From the repo root, without touching your own data:

```sh
tavla --content-dir example-content next
tavla --content-dir example-content status --deadline-days 365
tavla --content-dir example-content project show project-a
tavla --content-dir example-content task show write-i
```

(Read commands only — `example-content/` is not its own git repo, so write
commands will refuse to run there.)

## Development

```sh
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how the code is organised.
