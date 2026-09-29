# tavla

[![ci](https://github.com/Johanmkr/tavla/actions/workflows/ci.yml/badge.svg)](https://github.com/Johanmkr/tavla/actions/workflows/ci.yml)
[![docs](https://github.com/Johanmkr/tavla/actions/workflows/docs.yml/badge.svg)](https://johanmkr.github.io/tavla/)
[![release](https://img.shields.io/github/v/release/Johanmkr/tavla?sort=semver)](https://github.com/Johanmkr/tavla/releases)
[![python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FJohanmkr%2Ftavla%2Fmain%2Fpyproject.toml)](pyproject.toml)
[![license](https://img.shields.io/github/license/Johanmkr/tavla)](LICENSE)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

A research operations tool for one researcher juggling several projects:
goals, tasks, loose ideas and progress logs, and one question answered across
all of them: *what should I work on next?* CLI-first, plain text, git-native.

- **Plain text.** Everything is Markdown or YAML you can read, grep and edit by hand.
- **Git is the history.** Every change tavla makes is committed to your content
  repo, so `git log` is the audit trail and `tavla undo` reverts the last change.
- **Your data is separate.** Your content lives in its own private git repo,
  never in this software repo, and nothing is ever sent anywhere.

![tv next, then tv task done, then tv flow, on the demo content](docs/assets/demo.gif)

## How it fits together

```mermaid
flowchart LR
  project["<b>Project</b><br/>project.yaml<br/><i>status · priority · tags</i>"]
  sub["<b>Subproject</b><br/>same shape, nested inside"]
  goal["<b>Goal</b><br/>goals/ID.md<br/><i>an outcome, often with a due date</i>"]
  loose["<b>Task without a goal</b><br/>tasks/ID.md"]
  extras["<b>Log · Ideas · Deliverables</b><br/>log.md · ideas.md · deliverables/"]
  task["<b>Task</b><br/>tasks/ID.md<br/><i>goal: GOAL</i>"]
  later["<b>Task</b><br/>tasks/ID.md<br/><i>goal: GOAL</i><br/><i>depends_on: [TASK]</i>"]
  subtasks["<b>Subtasks</b><br/>a checklist inside<br/>the task file"]
  idea(["<b>Idea</b>: one line with #tags<br/>in the inbox, a project,<br/>a goal or a task"])

  project --> sub
  project --> goal
  project --> loose
  project --> extras
  goal -- "priority and due<br/>are inherited" --> task
  goal --> later
  task -. "unblocks" .-> later
  task --> subtasks
  idea -. "tv idea promote" .-> loose

  classDef container stroke:#00897b,stroke-width:2px
  classDef work stroke:#43a047,stroke-width:2px
  classDef side stroke:#9e9e9e,stroke-dasharray:4
  class project,sub,goal container
  class task,later,loose,subtasks work
  class extras,idea side
```

A task that waits for others is left out of `next` until they're done, and
`tv flow` draws how it all depends on each other. See
[Organising work](https://johanmkr.github.io/tavla/guide/organising-work/)
for the details.

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and
`git`; uv fetches a suitable Python by itself. Then:

```sh
uv tool install git+https://github.com/Johanmkr/tavla@v0.3.0   # puts `tavla` and `tv` on your PATH
tv --install-completion                                        # optional: tab-completion
```

`tavla update` moves you to the newest release later, and
`uv tool uninstall tavla` removes it (your content stays where it is).
Linux and macOS are tested; Windows isn't yet.

## Try it without your own data

```sh
tv demo                                    # a playground repo with example projects
export TAVLA_CONTENT_DIR=~/.cache/tavla/demo
tv next                                    # what to work on, across all projects
tv flow thesis                             # how the thesis work depends on itself
tv task done run-baseline                  # write commands work too; tv undo reverts
unset TAVLA_CONTENT_DIR                    # back to your own content
```

## A first session

```sh
tv init                                    # creates ~/.local/share/tavla, a git repo
tv project add "Master thesis" --priority high --id thesis
tv goal add "Experiments" -p thesis --due 01.12.26 --id exp
tv task add "Set up the pipeline" -g exp --id pipeline
tv task add "Run the baseline" -g exp --after pipeline   # waits for pipeline
tv next                                    # only "pipeline" can start
tv task done pipeline                      # -> Now unblocked: run-the-baseline
tv capture "try mixed precision #speed"    # a quick thought, into the inbox
tv status                                  # stale projects, what's waiting, what's due
```

`tv` is short for `tavla`. Ids can be abbreviated to any unique prefix or
piece of the title, and `tv COMMAND -h` shows every option with examples.
[Getting started](https://johanmkr.github.io/tavla/getting-started/) walks
through this properly.

## Status

tavla is in **alpha**: it's used every day, but commands may still change
between releases. Your content is plain files in git, and every change to the
file layout comes with a `tavla migrate` step, so upgrading never strands it.

**Works today:** projects and subprojects, goals, tasks with subtasks and
dependencies, ideas and the inbox, progress logs, deliverables, `next`,
`status`, the `flow` board, `undo`, `check`, `demo` and `--json` output.
**Next:** an interactive terminal UI. **Later:** links to code repos and a
reading library synced with Zotero.

## Learn more

The [user guide](https://johanmkr.github.io/tavla/) has everything else:

- [Getting started](https://johanmkr.github.io/tavla/getting-started/) and two worked
  examples ([a master's thesis](https://johanmkr.github.io/tavla/examples/master-thesis/),
  [several projects](https://johanmkr.github.io/tavla/examples/several-projects/))
- the [daily workflow](https://johanmkr.github.io/tavla/guide/daily-workflow/):
  `next`, `status`, `flow`, `log`
- the [command reference](https://johanmkr.github.io/tavla/reference/cli/) and
  [file formats](https://johanmkr.github.io/tavla/reference/file-formats/)
- [notes for alpha testers](https://johanmkr.github.io/tavla/alpha/) and the
  [FAQ](https://johanmkr.github.io/tavla/faq/)

Found a bug or have an idea? [Open an issue](https://github.com/Johanmkr/tavla/issues/new/choose).
To work on tavla itself, see [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed.
