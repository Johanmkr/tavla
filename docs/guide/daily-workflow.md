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
    tv idea list            # triage the inbox: move, promote or drop
    tv goal list            # any goals ready to close or re-plan?
    ```
