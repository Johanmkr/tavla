# Getting started

## Install

tavla needs Python 3.11+, `git` and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Install the latest release (see the
[releases page](https://github.com/Johanmkr/tavla/releases) for its number):

```sh
uv tool install git+https://github.com/Johanmkr/tavla@v0.2.0   # puts `tavla` and `tv` on your PATH
tv --version
```

Tab-completion is optional, but it's worth having. It completes command names
and ids, and shows each title next to its id:

```sh
tavla --install-completion
tv --install-completion
```

Restart your shell afterwards.

!!! tip "Back up your content"
    Your projects live in their own git repo (created by `tavla init` below).
    Push it to a **private** remote now and then, so a lost laptop doesn't
    lose your notes: `git -C ~/.local/share/tavla push`.

### Updating tavla

```console
$ tv update --check        # see what's new, change nothing
tavla v0.3.0 is available (you have 0.2.0).
What's new: https://github.com/Johanmkr/tavla/releases/tag/v0.3.0
Run `tavla update` to install it.
$ tv update
Installing v0.3.0 with uv...
Updated tavla 0.2.0 -> 0.3.0.
```

`update` finds the newest release and reinstalls it with
`uv tool install --force git+https://github.com/Johanmkr/tavla@<tag>`. If uv
isn't on your PATH or the install fails, nothing is changed and tavla prints
the command to run by hand. What changed in each release is in the
[changelog](https://github.com/Johanmkr/tavla/blob/main/CHANGELOG.md).

If a new version changes the content layout, tavla will ask you to run
`tavla migrate` (see [Upgrading the layout](guide/content-repo.md#upgrading-the-layout)).

### Installing from a clone (for development)

To work on tavla itself, install your clone in editable mode instead. Code
changes then apply immediately:

```sh
git clone https://github.com/Johanmkr/tavla.git && cd tavla
uv tool install --editable .
```

For such an install, `tv update` fast-forwards the clone to the latest `main`
rather than to a release. It only fast-forwards, so it never merges, rebases or
overwrites anything, and it refuses (and says why) if the clone has
uncommitted changes, another branch checked out, or local commits that
diverge from `origin/main`. If `pyproject.toml` changed (new dependencies or
commands), it also reinstalls with `uv tool install --force --editable <clone>`.

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

### Or let tavla ask

If you'd rather not remember flags, run `tv add` (or `tv add goal` to skip
the first question). It asks what you're adding and where it goes, picked
from a menu (type to filter long lists). Then it shows a review of every
field, with optional ones at their defaults:

```console
$ tv add goal
? Project project-b  Literature review on MCMC diagnostics
? Title  (< back) Try it out

  New goal
    project   project-b
    title     Try it out
    id        try-it-out  (from the title)
    priority  med
    due       –
    tags      –

? What next? Create it
Added goal try-it-out to project-b
? Add another goal? No
```

- **Go back** with `← back` in a menu, or by typing `<` in a text question.
  Your answers are kept.
- **Change any field** from the review, including optional ones like `id`,
  `due` or a task's dependencies. Bad input (an unknown date, a taken id) is
  caught at the question.
- **Add another** starts again in the same place (the same project, goal or
  task), so adding several goals only asks for their titles.
- **Ctrl-C** cancels at any point without adding anything.

`tv add` handles projects, subprojects, goals, tasks, subtasks, ideas and
deliverables. It needs a terminal; in scripts, use the `tv <kind> add`
commands.

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
