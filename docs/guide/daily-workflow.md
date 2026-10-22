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

### Inside a project folder

Link a project to the folder where its code or files live:

```sh
cd ~/code/thesis
tv project link thesis          # or: tv project link thesis ~/code/thesis
```

From then on, `tv next` and `tv task list` run anywhere inside that folder show
only that project, with a note saying so. Use `-G` (`--global`) to see
everything, or `-p` to pick another project. A project can have several
folders. When folders are nested, the deepest one wins. `tv project unlink
thesis` removes the links.

## Working on one task: `work`, `pause`, `done`

```console
$ tv work pipeline
Working on pipeline (Set up training pipeline). `tv pause` or `tv done` when you stop.
$ tv tick 2                     # tick subtask 2 of the task you're on
$ tv subtask Add a smoke test
$ tv note "toy data works; real data OOMs"
$ tv work                       # what am I on? (time so far, subtasks)
$ tv pause "loader done, model next"
Paused pipeline after 1h35m. `tv work pipeline` to pick it up again.
```

`tv work TASK` marks the task `doing` and makes it *the* task you are on.
Until you `tv pause` or `tv done`:

- `tick`, `untick`, `subtask` and `note` act on it, so you don't type its id.
- `tv next` and `tv status` show it at the top.
- `tv work OTHER` is refused, so you finish or pause one thing before you
  start the next.

Each stretch of work (start, end, duration and an optional note) is added to
the task's `## Sessions` section when you pause or finish. `tv done` with no
id finishes the task you are on, and `-m "..."` adds a note to the session.

### A terminal per task: `work -t`

```console
$ tv work -t pipeline
Opened pipeline (Set up training pipeline) in kitty; closing the terminal marks it done.
$ tv work -t pipeline -s 2      # for subtask 2 only; closing ticks it
```

`tv work -t TASK` opens a new terminal window for the task: titled with the
task (`Task › subtask` with `-s`), in the task's own Catppuccin colour, and
started in the project's linked folder. The task is marked `doing`. Inside
it, `tick`, `untick`, `subtask`, `note` and `done` act on that task.

When you close the terminal (`exit`, Ctrl-D or the window's close button),
the session is logged in `## Sessions` and the task is marked done, or with
`-s` the subtask is ticked. Changed your mind? Run `tv pause` in the terminal
first: closing it then only logs the session.

Any number of task terminals can be open at once; they don't use the
one-task rule of `tv work`. `tv work` on its own lists them.

- **Colour:** picked from the task id, so a task always gets the same one.
  `tv task edit TASK --colour mauve` picks another (rosewater, flamingo, pink,
  mauve, red, maroon, peach, yellow, green, teal, sky, sapphire, blue,
  lavender); `--colour none` goes back to the default.
- **Terminal:** the one tavla runs in (kitty, ghostty, wezterm, alacritty,
  foot, gnome-terminal, konsole or xterm), else the first one installed. Set
  `$TAVLA_TERMINAL` or `terminal = "ghostty"` in `config.toml` to choose. It
  can also be a command with `{title}`, `{cwd}`, `{background}`,
  `{foreground}` and `{accent}` in it; tavla appends what runs inside.

## `start` and `done`

```sh
tv task start pipeline       # todo -> doing
tv task done pipeline        # -> done, and reports what it unblocked
tv goal start exp
tv goal done exp
```

`tv task start` only changes the status. Use `tv work` when you sit down to
work on the task. For any other status (`blocked`, or going back to `todo`),
use `tv task edit ID --status STATUS`.

## `todo`: small things outside any project

```sh
tv todo buy HDMI cables #lab    # add one (quotes optional)
tv todo                         # list open todos, numbered
tv todo done 2                  # tick off (by number or a piece of the text)
tv todo reopen 2
tv todo promote 3 -p thesis     # turn it into a task (-g for a goal's task)
tv todo promote 3 --as-project  # or a project (-p PARENT: a subproject)
tv todo promote 3 --subtask-of run-baseline
tv todo drop 4
tv todo clear                   # remove the ticked-off ones
```

Todos are for small chores and things you need to write down quickly. Ideas
(`tv capture`) are for thoughts to think about later. Todos keep their
numbers when you tick them off, so `tv todo done 2 5` does what you expect. To
add a todo that starts with a command word, use `tv todo add list the
cables`. `tv status` shows how many are open.

## `inbox`: emptying it

```sh
tv inbox                        # the chores and ideas waiting to be sorted
tv inbox --filed                # ideas filed under projects, goals and tasks
tv inbox review                 # go through them one at a time: chores, then ideas
tv inbox review --ideas         # one kind only (--chores, --ideas, --filed)
```

`review` shows one item at a time and asks for one key: `t` task, `g` goal,
`P` project, `s` subtask, `l` file it under a project or goal for later, `x`
done already, `D` drop, `n` skip, `q` quit. Then it asks where (an id or a
prefix; `?` lists them) and the title, with the item's text filled in. Each
decision is one commit. The full-screen view does the same with `T` in the
inbox.

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
flagged as stale.

Without the text, `tv log` reads the log back, newest first: `tv log thesis`
shows that project's last ten entries, and `tv log` on its own shows those of
the project whose folder you are in, or of every project (`-n 0` shows all of
them, `-G` ignores the folder).

```console
$ tv log thesis -n 2
2026-10-20        Supervisor meeting: aim for a full draft by the end of November
2026-10-16 14:10  Baseline converges on logistic regression; hierarchical model is slow
```

## `find`: search everything

```console
$ tv find baseline
Goals (1)
  experiments  [doing]  Experiments chapter  (thesis)
               … Compare the adaptive sampler against the NUTS baseline on three models.
Tasks (1)
  run-baseline  [doing]  Run the NUTS baseline  (thesis)
Ideas (1)
  thesis:2  Reuse the baseline trace plots in the #teaching slides
Log (1)
  2026-10-16 14:10  Baseline converges on logistic regression; hierarchical model is slow  (thesis)
```

Every word has to appear, in any case. `find` looks through projects, goals
and tasks (their titles, tags and the whole file: instructions, notes,
ideas), deliverables, the inbox and project ideas, todos and the logs.
Finished items are included and shown dim, and `-p` keeps to one project and
its subprojects. The first column is what to type in the next command:
`tv task show run-baseline`, `tv idea promote thesis:2`.

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
to see its goals, or a goal to see its tasks. Here is the write-up goal from
the [demo](../examples/several-projects.md):

```console
$ tv flow write-up --width 110
Goal: Write the thesis draft  (write-up)  ▸ 0/3 tasks done

STAGE 1                     STAGE 2                     STAGE 3                     GOAL
╭─ make-figures ──────╮     ╭─ draft-results ─────╮     ╭─ send-draft ────────╮     ╭─ write-up ──────────╮
│ ○ ↗ Make the result │ ──▶ │ ○ Draft the results │ ──▶ │ ○ Send the full     │ ══▶ │ ● Write the thesis  │
│ figures             │     │ chapter             │     │ draft to the        │     │ draft               │
│ thesis              │     │ high · due          │     │ supervisor          │     │ high · due          │
╰─────────────────────╯     │ 2026-10-15          │     │ high · due          │     │ 2026-11-30 · 0/3    │
                            │ ! due before        │     │ 2026-11-30          │     ╰─────────────────────╯
                            │ make-figures        │     │ after: draft-metho… │
                            │ (2026-10-20)        │     ╰─────────────────────╯
                            ╰─────────────────────╯
╭─ set-up-pipeline ───╮     ╭─ draft-methods ─────╮
│ ✓ ↗ Set up the      │ ──▶ │ ● Draft the methods │
│ experiment pipeline │     │ chapter             │
│ thesis              │     │ high · due          │
╰─────────────────────╯     │ 2026-11-30 · 0/2    │
                            │   ☐ Describe the m… │
                            │   ☐ Describe the a… │
                            ╰─────────────────────╯
Ready now: ● draft-methods
✓ done   ▶ doing   ● ready   ○ waiting   ✗ blocked   ? missing   ↗ elsewhere   ! date problem
```

- Cards are grouped into **stages**. A card depends only on cards in earlier
  stages, so the cards in one stage can be done in parallel.
- An arrow means "this unblocks that". If a dependency can't be drawn as an
  arrow, the card lists it as `after: ...`.
- On a project board each goal is one card, with its tasks listed in order.
  A goal comes after another goal when one of its tasks depends on a task in
  that other goal. A task with no goal gets its own card.
- A card marked `↗` is outside the board: a dependency in another goal or
  project (here the experiments goal), shown so you can see what the first
  stage is waiting on.
- `!` lines point out dates that don't work: something overdue, or a task due
  before one of its prerequisites is (the results chapter above is due before
  the figures it needs).
- **Ready now** lists the tasks you can start, in the same order as `tv next`.

When the terminal is wide, a stage with many cards spreads over several
columns. When it's too narrow, the stages are printed one below the other.
Set the width yourself with `--width N`.

### Other views

```sh
tv flow thesis --by status     # kanban: todo / doing / blocked / done columns
tv flow thesis --open          # hide finished goals, tasks and subtasks
tv flow exp -n 0               # list every subtask (default: 6 lines per card)
tv flow thesis -f mermaid      # a Mermaid flowchart, for notes or GitHub
tv flow thesis --json          # the board as data
```

`--format mermaid` prints text that GitHub, Obsidian, MkDocs and many other
tools draw as a diagram. Paste it inside a ```` ```mermaid ```` block.

## A suggested rhythm

=== "Daily"

    ```sh
    tv next                 # pick something (inside a linked folder: that project)
    tv work ID
    # ...work, tv tick N, tv note "..."...
    tv pause "where I stopped"   # or: tv done
    tv log PROJECT "what happened"
    tv todo                 # the small stuff
    ```

=== "Weekly"

    ```sh
    tv status               # stale projects, due soon, waiting
    tv flow PROJECT         # what depends on what, and what can run in parallel
    tv inbox review         # sort the chores and ideas, one at a time
    tv inbox review --filed # look over the ideas filed under projects
    tv todo clear           # remove the ticked-off todos
    tv goal list            # any goals ready to close or re-plan?
    ```
