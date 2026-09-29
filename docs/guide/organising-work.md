# Organising work

## The hierarchy

```mermaid
--8<-- "model.mmd"
```

Each box is a file (or a part of one) in your content repo; see
[Your content repo](content-repo.md) for the full layout.

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

tavla refuses unknown ids, self-dependencies and cycles. To see the whole
picture, `tv flow GOAL` draws the tasks as a board of stages (see
[`flow`](daily-workflow.md#flow)).

!!! note "Waiting vs. blocked"
    *Waiting* is computed from dependencies. *Blocked* is a status you set by
    hand (`tv task edit ID --status blocked`) for things that are stuck for
    reasons outside tavla, like waiting on an email or a cluster allocation.

## Changing your mind

- **A goal turned out to be a single task:** `tv goal to-task ID` converts it
  and keeps its fields and notes. Add `-g OTHER` to put it under another goal
  in the same project. This is refused while the goal still has tasks.
- **An idea turned out to be real work:** see [promoting ideas](ideas.md#promoting).
- **A task or goal belongs in another project:** `tv task edit ID -p PROJECT`
  or `tv goal edit ID -p PROJECT` (a goal's tasks come along). See
  [Moving to another project](editing.md#moving-to-another-project).

## Subprojects

A project can contain subprojects, each with the same structure as a
top-level project. They're useful for a self-contained strand of work inside
a bigger project, like the ablation studies for a paper or one chapter of a
thesis.

```console
$ tv project add "Ablation studies" -p thesis --id ablations
Added project ablations under thesis
$ tv goal add "Run grid" -p ablations
Added goal run-grid to ablations
```

Subprojects can be nested as deeply as you like. `project list` indents them
under their parent, and `project show` lists them.

How subprojects behave:

- **Everything else works on them as normal.** Goals, tasks, ideas, logs and
  ids work exactly as they do in any other project.
- **`-p` includes them.** `next -p`, `goal list -p`, `task list -p` and
  `flow` on a parent include its subprojects; `goal list -p` shows each
  subproject's goals under its own heading.
- **They follow their parent's pause.** A subproject of a paused project
  counts as paused.
- **Activity counts for the parent.** A parent isn't flagged as stale while
  one of its subprojects is active.

### Moving projects around

`project edit -p` moves a project under another one, or back to the top level
with `none`:

```console
$ tv project edit side -p thesis
Moved project side under thesis
$ tv project edit side -p none
Moved project side to top level
```

The project's folder moves with everything in it, including its own
subprojects. Its goals and tasks keep their ids, so nothing else needs to
change. tavla refuses to move a project into itself or into one of its own
subprojects.
