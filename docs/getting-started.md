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

### Updating tavla

```console
$ tv update --check        # see what's new, change nothing
2 new commits on origin/main:
  1a2b3c4 ADD: ...
  5d6e7f8 FIX: ...
Run `tavla update` to install them.
$ tv update
...
Updated tavla in /home/you/tavla: 9f8e7d6 -> 1a2b3c4
```

`update` pulls the latest `main` into the clone you installed from. It only
fast-forwards, so it never merges, rebases or overwrites anything. It refuses
to run, and tells you why, if the clone has uncommitted changes, has a branch
other than `main` checked out, or has local commits that diverge from
`origin/main`.

Code changes take effect immediately. If the update changes `pyproject.toml`
(new dependencies or commands), tavla also reinstalls itself with
`uv tool install --force --editable <clone>`. If uv isn't on your PATH, or the
reinstall fails, tavla says so and prints the command to run by hand. The
code update itself has already been applied at that point.

If a new version changes the content layout, tavla will ask you to run
`tavla migrate` (see [Upgrading the layout](guide/content-repo.md#upgrading-the-layout)).

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
