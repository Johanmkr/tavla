# Example: a master's thesis

This walkthrough plans a thesis from scratch and follows it through the first
few days of work. Every command and output below comes from a real session.

## 1. Set up the project and its goals

Start with the big outcomes, not the tasks. A thesis usually splits into a
literature review, experiments, and the writing itself:

```console
$ tv project add "Master thesis" --priority high --tags thesis --id thesis
Added project thesis
$ tv goal add "Literature review" -p thesis --due 15.11.26 --id litrev
Added goal litrev to thesis
$ tv goal add "Experiments" -p thesis --priority high --id exp
Added goal exp to thesis
$ tv goal add "Write thesis" -p thesis --due 01.06.27 --id write
Added goal write to thesis
```

The short `--id`s pay off quickly, since you'll type them a lot.

## 2. Break goals into tasks

Only break down what you can see clearly. `write` can stay empty for now:

```console
$ tv task add "Collect key papers" -g litrev
Added task collect-key-papers to goal litrev
$ tv task add "Write review chapter draft" -g litrev --after collect
Added task write-review-chapter-draft to goal litrev
$ tv task add "Set up training pipeline" -g exp --priority high --id pipeline
Added task pipeline to goal exp
$ tv task add "Run baseline" -g exp --after pipeline
Added task run-baseline to goal exp
$ tv task add "Run ablations" -g exp --after run-baseline
Added task run-ablations to goal exp
$ tv task add "Book meeting with supervisor" -p thesis --due fri
Added task book-meeting-with-supervisor to project thesis
```

Notice:

- `--after collect` resolved to `collect-key-papers`.
- The experiments form a chain: pipeline → baseline → ablations.
- The supervisor meeting doesn't serve any goal, so it goes straight into the
  project with `-p`.

## 3. Ask what's next

```console
$ tv next
ID                            PRIORITY  STATUS  DUE                  SUBTASKS  GOAL    PROJECT  TITLE
pipeline                      high      todo    -                    -         exp     thesis   Set up training pipeline
book-meeting-with-supervisor  med       todo    2026-10-02 (in 4d)   -         -       thesis   Book meeting with supervisor
collect-key-papers            med       todo    2026-11-15 (in 48d)  -         litrev  thesis   Collect key papers

Goals with no tasks yet (1)
  write  [med]  [thesis]  Write thesis  due 2027-06-01 (in 246d)
```

- `run-baseline`, `run-ablations` and the review draft are missing, because
  they're waiting on other tasks.
- `collect-key-papers` shows the literature review's due date, which it
  inherited from its goal.
- `write` is listed as a goal that still needs breaking down.

## 4. Work, capture, log

```console
$ tv task start pipeline
Started: pipeline (Set up training pipeline) — was todo
$ tv capture "try mixed precision to speed up training #perf"
Captured: try mixed precision to speed up training #perf
$ tv task done pipeline
Done: pipeline (Set up training pipeline)
Now unblocked: run-baseline
$ tv log thesis "pipeline runs end to end on toy data"
Logged to thesis: pipeline runs end to end on toy data
```

The thought that came up mid-work went to the inbox without breaking your
focus.

## 5. Triage the idea

Later, file the idea under the goal it belongs to, and when you're ready to
act on it, promote it:

```console
$ tv idea move 1 -g exp
Moved to exp: try mixed precision to speed up training #perf
$ tv idea promote exp:1 -g exp
Promoted to task try-mixed-precision-to-speed-up-training: ...
```

## 6. See how the experiments fit together

`next` shows what you can start; `flow` shows the whole chain:

```console
$ tv flow exp --width 100
Goal: Experiments  (exp)  ▸ 1/4 tasks done

STAGE 1                   STAGE 2                   STAGE 3                   GOAL
╭─ try-mixed-precis─╮
│ ● try mixed       │
│ precision to      │
│ speed up training │
│ high              │
╰───────────────────╯
╭─ pipeline ────────╮     ╭─ run-baseline ────╮     ╭─ run-ablations ───╮     ╭─ exp ─────────────╮
│ ✓ Set up training │ ──▶ │ ● Run baseline    │ ──▶ │ ○ Run ablations   │ ══▶ │ ● Experiments     │
│ pipeline          │     │ high              │     │ high              │     │ high · 1/4        │
│ high              │     ╰───────────────────╯     ╰───────────────────╯     ╰───────────────────╯
╰───────────────────╯
Ready now: ● run-baseline  ● try-mixed-precision-to-speed-up-training
✓ done   ▶ doing   ● ready   ○ waiting   ✗ blocked   ? missing   ↗ elsewhere   ! date problem
```

- The pipeline is done, so the baseline is ready, and the ablations wait for
  it. Each stage only depends on earlier ones.
- The promoted idea has no dependencies, so it sits in stage 1: it can be done
  in parallel with everything else.
- `tv flow thesis` shows the same for the whole project, one card per goal.

## 7. Check the overall health

```console
$ tv status
tavla status — 2026-09-28
1 active project · 5 open tasks (0 doing) · 0 blocked
...
Waiting on dependencies (2)
  run-ablations  [thesis]  Run ablations  (after run-baseline)
  write-review-chapter-draft  [thesis]  Write review chapter draft  (after collect-key-papers)

Tasks due within 7 days (1)
  book-meeting-with-supervisor  2026-10-02 (in 4d)  [thesis]  Book meeting with supervisor
```

```console
$ tv project show thesis
Master thesis
  id:        thesis
  status:    active
  priority:  high
  ...

Goals
  exp  [todo]  1/3 tasks  Experiments
  litrev  [todo]  0/2 tasks  Literature review
  write  [todo]  - tasks  Write thesis

Tasks
  todo: 5  doing: 0  blocked: 0  done: 1
  book-meeting-with-supervisor  [todo]  Book meeting with supervisor  (no goal)

Recent log
  2026-09-28  pipeline runs end to end on toy data
```

## 8. Look at the history

Every step above is a commit in your content repo:

```console
$ git -C ~/.local/share/tavla log --oneline
b07fa1b task: add try-mixed-precision-to-speed-up-training
2e9262e log: thesis: pipeline runs end to end on toy data
3f177b8 task: done pipeline
c0e2287 idea: move inbox -> exp: try mixed precision to speed up training #perf
cacb4ba inbox: capture try mixed precision to speed up training #perf
ca48ffc task: start pipeline
...
```

## Where to take it from here

- Open a task with `tv task edit collect` and fill in `## Instructions` and a
  `## Subtasks` checklist. Its progress will show in `next`.
- When the chapter structure is clear, break the `write` goal into one task
  per chapter, chained with `--after` if order matters.
- Run `tv status` once a week, and `tv flow thesis --open` when you plan.
