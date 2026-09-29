# tavla

[![docs](https://github.com/Johanmkr/tavla/actions/workflows/docs.yml/badge.svg)](https://johanmkr.github.io/tavla/)

A personal research operations tool for one researcher juggling several
projects: goals, tasks, loose ideas, progress logs and a cross-project "what
next?" view. CLI-first, plain text, git-native.

- **Plain text.** Everything is Markdown or YAML you can read, grep and edit by hand.
- **Git is the history.** Every change tavla makes is auto-committed to your
  content repo, so `git log` is the audit trail and `tavla undo` reverts the last change.
- **Your data is separate.** Content lives in its own (private) git repo, never
  in this software repo.

**User guide:** <https://johanmkr.github.io/tavla/> — concepts, worked
examples, a full command reference and an FAQ.

> **Status:** Tier 1 complete — projects and subprojects, goals, tasks (with
> subtasks and dependencies), ideas, capture, log, `next`, `status`.
> Deliverables, code-repo links and Zotero sync are planned (Tier 2).

## How work is organised

```
Project            e.g. "Adaptive sampling"          project.yaml
└── Goal           an outcome: "Write introduction"   goals/<id>.md
    └── Task       a unit of work, with instructions  tasks/<id>.md
        └── subtasks   a checklist inside the task file
```

- A **task** can belong to a goal (`-g`) or sit directly in a project (`-p`)
  when it doesn't serve a bigger goal.
- A task can **depend on** other tasks (`--after`). Until they're done it is
  *waiting*: `next` leaves it out and `status` lists it.
- A task without its own priority or due date **inherits** them from its goal.
- **Ideas** are single lines that can belong to the inbox, a project, a goal or
  a task, and be moved, dropped or promoted to a task/goal later. `#words` in an
  idea are tags.
- Projects can have **subprojects** with the same structure (`project add -p`),
  and a project can be moved under another one or back out (`project edit -p`).

## Install

Requires Python 3.11+, `git` and [uv](https://docs.astral.sh/uv/). Install the
latest [release](https://github.com/Johanmkr/tavla/releases):

```sh
uv tool install git+https://github.com/Johanmkr/tavla@v0.2.0   # puts `tavla` (and the short alias `tv`) on your PATH
tavla --install-completion       # optional: tab-completion for commands and ids
tv --install-completion          # ...and the same for `tv`
```

To update later, run `tavla update` (`--check` to just see what's new). It
reinstalls the newest release with uv; see [CHANGELOG.md](CHANGELOG.md) for
what changed.

For development, install a clone instead: `uv tool install --editable .`
inside it. `tavla update` then fast-forwards the clone to `origin/main` (and
reinstalls with uv if dependencies changed), refusing if you have local
changes, another branch checked out, or commits that diverge from `main`.

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

tv goal add "Write introduction" -p adap --due 02.10.26 --id intro
tv task add "Outline" -g intro
tv task add "Draft related work" -g intro --after outline   # waits for "outline"
tv task add "Run baseline experiments" -p adap --priority high   # no goal
#  -> Added task run-baseline-experiments to project adaptive-sampling

tv next                             # what to work on, across all active projects
tv task start outline               # todo -> doing
tv task edit outline                # opens $EDITOR: instructions, subtasks, notes
tv task edit draft --due fri --priority high   # change fields without an editor
tv log adap "baseline converges on the toy model"
tv capture look into parallel tempering #mcmc  # quick thought -> inbox
tv idea promote tempering -g intro  # ...later: turn it into a task
tv task done outline                #  -> Now unblocked: draft-related-work
tv status                           # stale projects, waiting tasks, what's due
```

`tv` is short for `tavla`; both work everywhere. Ids are derived from titles
(`"Run baseline experiments"` → `run-baseline-experiments`) unless you pass
`--id`, and must be unique across projects, goals and tasks. Anywhere an id is
expected you can type **any unique prefix** (`adap`, `run-b`) or, failing that,
**any unique piece of the id or title** (`baseline`, `tempering`). If several
match, tavla lists the candidates instead of guessing. Tab-completion completes
id prefixes and shows each title next to its id.

## Commands

| Command | What it does |
| --- | --- |
| `tavla init [--content-dir PATH]` | Create the content repo and default config |
| `tavla migrate [--dry-run]` | Upgrade an older content repo to the current layout (one commit) |
| `tavla update [--check]` | Update tavla itself to the newest release (in a development clone: fast-forward to `main`) |
| `tavla check [--fix]` | Find problems in hand-edited files (unloadable files, duplicate ids, broken links, `project:` lines that disagree with the folder); `--fix` moves those files, or resets a line naming no known project |
| `tavla add [KIND]` | Add a project, subproject, goal, task, subtask, idea or deliverable by answering questions, with a review to change any field before creating |
| `tavla capture TEXT…` | Add an idea to the inbox (quotes optional) |
| `tavla log PROJECT TEXT…` | Append a timestamped line to the project's `log.md` |
| `tavla undo [-n]` | Undo the last change as a new commit (`-n`: only show it); run again to go further back |
| `tavla next [-p PROJECT] [--priority P] [-n N]` | Open tasks not waiting on others, most important first (default 10; `-n 0` for all), then goals with no tasks yet |
| `tavla status [--stale-days N] [--deadline-days N]` | Stale projects, blocked and waiting tasks, goals/tasks due within 7 days, goals ready to close, deliverable deadlines, inbox size |
| **Projects** | |
| `tavla project add NAME [-p PARENT] [--priority P] [--tags a,b] [--id ID]` | Create a project, or with `-p` a subproject |
| `tavla project list [--status S] [--all]` | List projects (archived hidden unless `--all`) |
| `tavla project show ID` | Metadata, subprojects, goals, loose tasks, deliverables, ideas, recent log |
| `tavla project edit ID [--title T] [--status S] [--priority P] [--tags …] [-p PARENT\|none]` | Change the given fields (`-p` moves it under another project; `none` makes it top-level); with no options, edit `project.yaml` in `$EDITOR` |
| **Goals** | |
| `tavla goal add TITLE -p PROJECT [--priority P] [--due DATE] [--tags a,b] [--id ID]` | Create a goal |
| `tavla goal list [-p PROJECT] [--status S] [--all]` | List goals with task progress (done hidden unless `--all`) |
| `tavla goal show ID` | Metadata, its tasks, and the goal file |
| `tavla goal edit ID [--title T] [--status S] [--priority P] [--due DATE\|none] [--tags …] [-p PROJECT]` | Change the given fields (`-p` moves it and its tasks); with no options, edit the goal file in `$EDITOR` |
| `tavla goal start ID` / `goal done ID` | Mark a goal `doing` / `done` |
| `tavla goal note ID TEXT…` | Add a timestamped line to the goal's `## Updates` |
| `tavla goal drop ID [-y]` | Delete a goal (asks first). Refused while tasks still belong to it |
| `tavla goal to-task ID [-g OTHER_GOAL]` | Turn a goal into a task (loose, or under another goal); keeps its fields and notes. Refused while tasks still belong to it |
| **Tasks** | |
| `tavla task add TITLE (-g GOAL \| -p PROJECT) [--after IDS] [--priority P] [--due DATE] [--tags a,b] [--id ID]` | Create a task under a goal, or directly in a project |
| `tavla task list [-p PROJECT] [-g GOAL] [--status S] [--all]` | List tasks (done hidden unless `--all`; `*` = waiting on dependencies) |
| `tavla task show ID` | Metadata (incl. dependencies and inherited fields) plus the task file |
| `tavla task edit ID [--title T] [--status S] [--priority P\|none] [--due DATE\|none] [-g GOAL\|none] [--after …] [--tags …] [-p PROJECT]` | Change the given fields (`-p` moves it); with no options, edit the task file in `$EDITOR` |
| `tavla task start ID` / `task done ID` | Mark a task `doing` / `done` (`done` reports tasks it unblocks) |
| `tavla task check ID [N\|TEXT…]` / `task uncheck ID N\|TEXT…` | Tick / untick subtasks by number or text; with none, `check` lists them numbered |
| `tavla task subtask ID TEXT…` | Add an unchecked subtask |
| `tavla task note ID TEXT…` | Add a timestamped line to the task's `## Updates` |
| `tavla task drop ID [-y]` | Delete a task (asks first). Refused while other tasks depend on it |
| **Ideas** | |
| `tavla idea add TEXT… [-p P \| -g G \| -t T]` | Add an idea (default: the inbox) |
| `tavla idea list [-p P \| -g G \| -t T \| --all] [--tag TAG]` | Numbered ideas: the inbox, one scope, or everything |
| `tavla idea move REF (-p P \| -g G \| -t T \| --inbox)` | Move an idea somewhere else |
| `tavla idea promote REF (-g GOAL \| -p PROJECT) [--as-goal]` | Turn an idea into a task (or a goal); its `#tags` become tags |
| `tavla idea drop REF` | Delete an idea |
| **Deliverables** | |
| `tavla deliverable add TITLE -p PROJECT [--kind K] [--venue V] [--deadline DATE] [--coauthors a,b] [--id ID]` | Create a paper, slides, dataset or code release (status `drafting`) |
| `tavla deliverable list [-p PROJECT] [--status S] [--all]` | List by deadline (accepted/published hidden unless `--all`) |
| `tavla deliverable show ID` | All its fields |
| `tavla deliverable edit ID [--title T] [--status S] [--kind K] [--venue V\|none] [--deadline DATE\|none] [--coauthors …]` | Change the given fields; with no options, edit the YAML file in `$EDITOR` |
| `tavla deliverable drop ID [-y]` | Delete a deliverable (asks first) |

An idea **REF** is `[SCOPE:]N` or `[SCOPE:]TEXT`: SCOPE is `inbox` (the default)
or a project/goal/task id, N the number `idea list` shows, TEXT any unique piece
of the idea. So `3`, `intro:2` and `intro:tempering` all work.

List options (`--tags`, `--after`) take `a,b` to replace the list or `+a,-b` to
add/remove items; `none` clears `--after`, `--due`, `--goal` and a task's
`--priority` (which then inherits from its goal again).

`tavla COMMAND --help` (or `-h`) shows every option, with examples for the trickier commands.

Global options: `--content-dir PATH`, `--json`, `-y/--yes`, `-v/--verbose`.
`--content-dir` and `--json` work before or after the command
(`tavla --json next` and `tavla next --json` are the same).

### Values

| Field | Allowed values |
| --- | --- |
| priority | `high`, `med` (default), `low` |
| project status | `active` (default), `paused`, `done`, `archived` |
| goal and task status | `todo` (default), `doing`, `blocked`, `done` |
| dates (`--due`) | `2026-10-01`; day-first `01.10.2026`, `01/10/26`, `01-10-2026` (`.`, `/` or `-`, 2- or 4-digit year); `01.10` (next 1 October); `today`, `tomorrow`, `+3d`, `+2w`, `fri`/`friday` (the next one) |

`start` and `done` cover the everyday status changes. For anything else, use
flags on `edit`, e.g. `tv task edit ID --status blocked --due fri`.
Files always store dates as `YYYY-MM-DD`; if you type a day-first date (with a
year) while editing a file by hand, tavla rewrites it to ISO when you save.

### How `next` and `status` decide

- `next` shows `todo`/`doing` tasks from **active** projects (a subproject of a
  paused project counts as paused) that aren't waiting on unfinished
  dependencies, ordered by priority, then `doing` before `todo`, then soonest
  due date, then project priority. Priority and due date are the task's own,
  or its goal's when the task leaves them out. Open goals without any tasks are
  listed underneath, since they still need breaking down (or doing).
  `--priority med` means "med and above". `-p` shows a project even if paused.
- `status` flags an active project as **stale** when nothing has happened for
  14 days — "something" being a `log.md` entry or a goal/task created/updated,
  including in its subprojects. `tavla log` is the easiest way to keep a
  project fresh. It also points out goals whose tasks are all done, so you can
  close them.

## Your content

```
~/.local/share/tavla/
├── tavla.yaml                 # content layout version (maintained by tavla)
├── registry.yaml              # index of top-level projects (maintained by tavla)
├── inbox.md                   # `tavla capture` / `idea add` land here
├── library/                   # reading notes (Tier 2: Zotero sync)
└── projects/
    └── adaptive-sampling/
        ├── project.yaml
        ├── log.md             # `tavla log` lands here
        ├── ideas.md           # the project's ideas
        ├── goals/
        │   └── intro.md
        ├── tasks/
        │   ├── outline.md     # points at its goal with `goal: intro`
        │   └── run-baseline-experiments.md
        ├── deliverables/      # *.yaml, managed with `tavla deliverable`
        └── subprojects/       # same shape, nested (`project add -p`)
```

A task file. tavla reads the frontmatter, the `# title`, the `## Subtasks`
checkboxes and the `## Ideas` bullets; everything else is yours and is never
rewritten:

```markdown
---
id: draft-related-work
project: adaptive-sampling
goal: intro                     # optional; leave out for a task without a goal
status: todo
depends_on: [outline]           # optional; waits until these tasks are done
tags: []
created: 2026-09-25
updated: 2026-09-26
# priority / due: optional; inherited from the goal when left out
---

# Draft related work

## Instructions
What to do, links, acceptance criteria — anything you like.

## Subtasks
- [x] Collect papers
- [ ] Write two paragraphs      <- counted as 1/2 in `next` and `task list`

## Ideas
- Contrast with #tempering methods

## Updates
- 2026-09-26: found the key survey
```

A goal file looks the same without `goal`/`depends_on` and `## Subtasks`; its
`priority` and `due` apply to its tasks unless they set their own.

You can edit any file by hand. If you do, commit it yourself (tavla only
auto-commits its own changes); `tavla goal/task/project edit` validate the file
(including unknown goals, unknown dependencies and dependency cycles) and
commit for you, and restore it if you save something invalid. Renaming an id
via `edit` updates the tasks that point at it.

A goal's or task's project is the folder it lives in — you can move the file to
another project's `goals/` or `tasks/` folder and it follows. Changing only the
`project:` line doesn't move it; `tavla check` finds those files and
`tavla check --fix` moves them (a goal's tasks go along). Links between things
use ids, never paths.

### Upgrading from an older layout

If tavla says your content uses an older layout, run `tavla migrate --dry-run`
to see the plan, then `tavla migrate`. From layout v1 (tasks only), every task
becomes a goal and each of its `## Subtasks` checkboxes becomes a task under
that goal. It is one commit in the content repo, so `tavla undo` reverts
it. The repo must have no uncommitted changes.

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

Read commands (`next`, `status`, `project/goal/task list/show`, `idea list`)
accept `--json`. Exit codes: `0` success, `1` error, `2` id not found, `3` ambiguous
id or invalid data.

## Try it on the demo content

From the repo root, without touching your own data:

```sh
tavla --content-dir example-content next
tavla --content-dir example-content status --deadline-days 365
tavla --content-dir example-content project show project-a
tavla --content-dir example-content goal show write-i
tavla --content-dir example-content task show feedback
tavla --content-dir example-content idea list --all
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
