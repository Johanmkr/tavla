# Getting started

## Install

tavla needs Python 3.11+ and `git`.

```sh
git clone https://github.com/Johanmkr/tavla.git && cd tavla
uv tool install --editable .     # puts `tavla` and `tv` on your PATH
```

Tab-completion is optional, but it's worth having. It completes command names
and ids, and shows each title next to its id:

```sh
tavla --install-completion
tv --install-completion
```

Restart your shell afterwards.

## Create your content repo

```console
$ tavla init
Initialized tavla content repo at /home/you/.local/share/tavla
Wrote config to /home/you/.config/tavla/config.toml
```

This creates a git repo for your content, with an initial commit, and a config
file that points at it. To keep your content somewhere else:

```sh
tavla init --content-dir ~/notes/tavla
```

!!! tip "Try it without touching your own data"
    The software repo ships with demo content. From the repo root:

    ```sh
    tv --content-dir example-content next
    tv --content-dir example-content project show project-a
    ```

    `example-content/` is not a git repo, so only read commands work there.

## Your first project

```console
$ tv project add "Adaptive sampling" --priority high --tags bayes,mcmc
Added project adaptive-sampling
$ tv goal add "Write introduction" -p adap --due 02.10.26 --id intro
Added goal intro to adaptive-sampling
$ tv task add "Outline" -g intro
Added task outline to goal intro
$ tv task add "Draft related work" -g intro --after outline
Added task draft-related-work to goal intro
```

This example shows a few things you'll use all the time:

- **Ids come from titles.** "Adaptive sampling" becomes `adaptive-sampling`.
  Use `--id` to choose a shorter one.
- **Abbreviations work.** `-p adap` finds `adaptive-sampling`, because any
  unique prefix or fragment of an id or title will do.
- **Dates can be typed day-first.** `02.10.26` means 2 October 2026. Relative
  dates like `fri`, `+2w` and `tomorrow` also work.
- **`--after` makes a task wait.** `draft-related-work` won't show up in
  `next` until `outline` is done.

## The everyday loop

```sh
tv next                          # what to work on, across all projects
tv task start outline            # todo -> doing
tv task edit outline             # open the task file in $EDITOR
tv log adap "outline agreed with supervisor"
tv task done outline             # -> Now unblocked: draft-related-work
tv capture "look into parallel tempering #mcmc"   # quick thought -> inbox
tv status                        # what's stale, waiting, or due soon
```

Every one of these commands makes a git commit in your content repo, so you
never need to "save".

## Next steps

- [Organising work](guide/organising-work.md) covers projects, goals, tasks,
  subtasks and dependencies.
- [Daily workflow](guide/daily-workflow.md) explains how `next` and `status`
  decide what to show you.
- [A master's thesis](examples/master-thesis.md) is a complete worked example.
