# Daily workflow

Three commands do most of the work: `next` shows what to do, `log` records
what you did, and `status` checks on the health of your projects.

## `next`: what to work on

```console
$ tv next
ID                            PRIORITY  STATUS  DUE                  SUBTASKS  GOAL    PROJECT  TITLE
pipeline                      high      todo    -                    -         exp     thesis   Set up training pipeline
book-meeting-with-supervisor  med       todo    2026-10-02 (in 4d)   -         -       thesis   Book meeting with supervisor
collect-key-papers            med       todo    2026-11-15 (in 48d)  -         litrev  thesis   Collect key papers

Goals with no tasks yet (1)
  write  [med]  [thesis]  Write thesis  due 2027-06-01 (in 246d)
```

### How `next` decides

1. It considers `todo` and `doing` tasks in **active** projects. A subproject
   of a paused project counts as paused.
2. It leaves out tasks that are **waiting** on unfinished dependencies.
3. It sorts by:
    1. priority (`high` > `med` > `low`)
    2. `doing` before `todo`
    3. soonest due date
    4. project priority

    Priority and due date are the task's own, or its goal's if the task
    doesn't set them.
4. Under the tasks, it lists **open goals with no tasks yet**, because those
   still need breaking down (or doing).

### Useful options

```sh
tv next -n 0                 # show everything, not just the top 10
tv next -p thesis            # one project (works even if it's paused)
tv next --priority med       # med and above
```

## `start` and `done`

```sh
tv task start pipeline       # todo -> doing
tv task done pipeline        # -> done, and reports what it unblocked
tv goal start exp
tv goal done exp
```

For any other status (`blocked`, or going back to `todo`), use
`tv task edit ID --status STATUS`.

## Subtasks and notes

```sh
tv task check pipeline          # list the subtasks, numbered
tv task check pipeline 2        # tick one off (or give a piece of its text)
tv task uncheck pipeline 2
tv task subtask pipeline Add a smoke test
tv task note pipeline "toy data works; real data OOMs"   # -> ## Updates
```

`note` is for what happened on this one task (it goes in the task file);
`log` is for news about the whole project.

## Mistakes

```sh
tv undo -n                      # what would be undone
tv undo                         # revert the last change
tv task drop scratch            # delete a task (asks first)
```

## `log`: record progress

```console
$ tv log thesis "pipeline runs end to end on toy data"
Logged to thesis: pipeline runs end to end on toy data
```

This appends a timestamped line to the project's `log.md`. It's the
lowest-effort way to leave a trail, and it keeps the project from being
flagged as stale. `project show` includes the most recent log entries.

## `status`: a health check

```console
$ tv status
tavla status — 2026-09-28
1 active project · 5 open tasks (0 doing) · 0 blocked

Stale projects (idle 14+ days) (0)

Blocked tasks (0)

Waiting on dependencies (2)
  run-ablations  [thesis]  Run ablations  (after run-baseline)
  write-review-chapter-draft  [thesis]  Write review chapter draft  (after collect-key-papers)

Goals due within 7 days (0)

Tasks due within 7 days (1)
  book-meeting-with-supervisor  2026-10-02 (in 4d)  [thesis]  Book meeting with supervisor

Deliverable deadlines within 30 days (0)
```

An active project is **stale** when nothing has happened in it for 14 days,
meaning no `log.md` entry and no goal or task created or updated, including in
its subprojects. `status` also points out goals whose tasks are all done, so
you can close them.

Change the time windows with `--stale-days N` and `--deadline-days N`.

## `flow`

`tv flow` draws a board of how work depends on other work. Give it a project
to see its goals, or a goal to see its tasks:

```console
$ tv flow write-methods
Goal: Write methods section  (write-methods)  ▸ 0/1 tasks done

STAGE 1                               STAGE 2                               GOAL
╭─ get-feedback-from-advisor ───╮     ╭─ describe-sampler ────────────╮     ╭─ write-methods ───────────────╮
│ ○ ↗ Get feedback from advisor │ ──▶ │ ○ Describe sampler            │ ══▶ │ ○ Write methods section       │
│ project-a                     │     │ med · due 2026-10-15 · 1/2    │     │ med · due 2026-10-15 · 0/1    │
╰───────────────────────────────╯     │   ✓ Pseudocode                │     ╰───────────────────────────────╯
                                      │   ☐ Complexity                │
                                      ╰───────────────────────────────╯
✓ done   ● ready   ○ waiting on others   ✗ blocked   ? missing   ↗ outside this board
```

- Cards are grouped into **stages**. A card depends only on cards in earlier
  stages, so the cards in one stage can be done in parallel.
- An arrow means "this unblocks that". If a dependency can't be drawn as an
  arrow, the card lists it as `after: ...`.
- On a project board each goal is one card, with its tasks listed in order.
  A goal comes after another goal when one of its tasks depends on a task in
  that other goal. A task with no goal gets its own card.
- A card marked `↗` is outside the board: a dependency in another goal or
  project, shown so you can see what the first stage is waiting on.

```sh
tv flow thesis --open        # hide finished goals, tasks and subtasks
tv flow exp -n 0             # list every subtask (default: 6 lines per card)
tv flow thesis --json        # the board as data
```

If the stages don't fit in the terminal, they are printed one below the
other. Set the width yourself with `--width N`.

## A suggested rhythm

=== "Daily"

    ```sh
    tv next                 # pick something
    tv task start ID
    # ...work...
    tv log PROJECT "what happened"
    tv task done ID
    ```

=== "Weekly"

    ```sh
    tv status               # stale projects, due soon, waiting
    tv flow PROJECT         # what depends on what, and what can run in parallel
    tv idea list            # triage the inbox: move, promote or drop
    tv goal list            # any goals ready to close or re-plan?
    ```
