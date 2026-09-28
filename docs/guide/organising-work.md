# Organising work

## The hierarchy

```
Project            e.g. "Adaptive sampling"          project.yaml
└── Goal           an outcome: "Write introduction"   goals/<id>.md
    └── Task       a unit of work, with instructions  tasks/<id>.md
        └── subtasks   a checklist inside the task file
```

Project
:   A body of work with its own status (`active`, `paused`, `done`,
    `archived`), priority and tags. Only **active** projects feed into `next`.

Goal
:   An *outcome* you are working towards, like "Write introduction" or "Get
    ethics approval". A goal is finished when its tasks are, and `status` tells
    you when a goal's tasks are all done so you can close it.

Task
:   A concrete piece of work you can *start* and *finish*. Its file holds
    instructions, a subtask checklist, ideas and an updates log.

Subtask
:   A checkbox line under `## Subtasks` in the task file. Subtasks have no ids
    and no status of their own. They show up as progress (`1/3`) in `next` and
    `task list`.

!!! question "Goal, task or subtask?"
    Ask yourself whether you would ever want to see it in `next` on its own.
    If yes, make it a **task**. If it only makes sense while you're already
    working on something bigger, make it a **subtask**. If it can't be done in
    one sitting and needs breaking down, make it a **goal**.

## Tasks without a goal

Not everything serves a bigger outcome. Use `-p` instead of `-g` to put a task
directly in a project:

```sh
tv task add "Book meeting with supervisor" -p thesis --due fri
```

Later, you can attach it to a goal with `tv task edit ID -g GOAL`, or detach
it with `-g none`.

## Inheritance

A task that doesn't set its own **priority** or **due date** takes them from
its goal. `task show` marks inherited values:

```console
$ tv task show mixed
  ...
  priority: high (from goal)
```

To make a task inherit again after you've given it its own value, use
`tv task edit ID --priority none` (or `--due none`).

## Dependencies

`--after` makes a task wait for other tasks:

```sh
tv task add "Run baseline" -g exp --after pipeline
tv task add "Run ablations" -g exp --after run-baseline
```

While any of those tasks is unfinished, the task is **waiting**:

- `next` leaves it out.
- `task list` marks its status with `*` (`todo*`).
- `status` lists it under *Waiting on dependencies*.

When you finish a task, tavla tells you what it unblocked:

```console
$ tv task done pipeline
Done: pipeline (Set up training pipeline)
Now unblocked: run-baseline
```

To change dependencies later:

```sh
tv task edit run-ablations --after +collect-key-papers   # add one
tv task edit run-ablations --after -collect-key-papers   # remove one
tv task edit run-baseline  --after none                  # clear all
```

tavla refuses unknown ids, self-dependencies and cycles.

!!! note "Waiting vs. blocked"
    *Waiting* is computed from dependencies. *Blocked* is a status you set by
    hand (`tv task edit ID --status blocked`) for things that are stuck for
    reasons outside tavla, like waiting on an email or a cluster allocation.

## Changing your mind

- **A goal turned out to be a single task:** `tv goal to-task ID` converts it
  and keeps its fields and notes. Add `-g OTHER` to put it under another goal
  in the same project. This is refused while the goal still has tasks.
- **An idea turned out to be real work:** see [promoting ideas](ideas.md#promoting).
- **A task belongs in another project:** move its file into the other
  project's `tasks/` folder. A task's project is simply the folder it lives
  in. Commit the move yourself.

## Subprojects

A project can contain subprojects under `subprojects/<id>/`, with the same
structure as a top-level project. For now you create them by hand (copy a
`project.yaml` and make `goals/` and `tasks/` folders). Everything else works
on them as normal, and a subproject of a paused project counts as paused.
