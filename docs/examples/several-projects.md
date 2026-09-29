# Example: juggling several projects

This example uses the demo content that ships with tavla: a PhD student with
a thesis (and an ablation-study subproject), a teaching job, a paused review
paper and an archived course. Set it up and follow along; your own content is
never touched:

```sh
tv demo                                   # prints the line below
export TAVLA_CONTENT_DIR=~/.cache/tavla/demo
```

The demo moves its dates to around the day you create it, so your "in 3d" and
"overdue" will match the output below even though the dates themselves differ.
Write commands work too, and `tv demo --reset` starts over.

## The situation

```console
$ tv project list --all
ID            STATUS    PRIORITY  GOALS  TASKS  TITLE
bayes-course  archived  low       0      0      Course: Bayesian data analysis
review-paper  paused    low       1      1      Review paper on MCMC diagnostics
teaching      active    med       1      4      TA: Statistics 101
thesis        active    high      4      14     PhD thesis: adaptive MCMC
  ablations   active    med       1      2      Ablation studies
```

- **thesis** is the main work. It has a subproject, `ablations`, and two
  deliverables: an ICML paper and a workshop talk.
- **teaching** is a TA job with a homework to grade this week.
- **review-paper** is on hold, so it's `paused`.
- **bayes-course** is finished and `archived`. Archived projects are hidden
  unless you pass `--all`.

## One list across everything

```console
$ tv next
ID                        PRIORITY  STATUS  DUE                      SUBTASKS  GOAL         PROJECT   TITLE
run-baseline              high      doing   2026-10-05 (in 7d)       2/4       experiments  thesis    Run the NUTS baseline
renew-cluster-account     high      todo    2026-09-20 (8d overdue)  -         -            thesis    Renew the cluster account
prepare-exercise-session  high      todo    2026-10-01 (in 3d)       -         -            teaching  Prepare Thursday's exercise session
draft-methods             high      todo    2026-11-30 (in 63d)      0/2       write-up     thesis    Draft the methods chapter
grade-problems            med       doing   2026-10-03 (in 5d)       2/4       grade-hw2    teaching  Grade problems 1-4
book-supervisor-meeting   med       todo    2026-10-02 (in 4d)       -         -            thesis    Book the next supervisor meeting
```

Work from both active projects is mixed into one list, most important first.
The paused review paper contributes nothing, even though it has an open task.
Pausing is how you say "not now" without deleting anything; to look at a
paused project anyway, use `tv next -p review-paper`.

Tasks waiting on others (like `run-adaptive`, which needs the baseline) are
left out: `next` only shows what you can actually start.

## What needs attention

```console
$ tv status --deadline-days 365
tavla status — 2026-09-28
3 active projects · 14 open tasks (2 doing) · 1 blocked

Stale projects (idle 14+ days) (1)
  ablations  last activity 2026-08-10 (49d ago)

Blocked tasks (1)
  request-gpu-hours  [ablations]  Request GPU hours  since 2026-08-10

Waiting on dependencies (8)
  compare-methods  [thesis]  Compare the two samplers  (after run-baseline, run-adaptive)
  draft-results  [thesis]  Draft the results chapter  (after make-figures)
  make-figures  [thesis]  Make the result figures  (after compare-methods)
  run-adaptive  [thesis]  Run the adaptive sampler  (after run-baseline)
  send-draft  [thesis]  Send the full draft to the supervisor  (after draft-methods, draft-results)
  enter-grades  [teaching]  Enter grades in the learning platform  (after grade-problems)
  post-solutions  [teaching]  Post the solutions  (after grade-problems)
  run-grid  [ablations]  Run the ablation grid  (after request-gpu-hours, run-baseline)

Goals due within 7 days (1)
  grade-hw2  2026-10-03 (in 5d)  [teaching]  0/3 tasks  Grade homework 2

Tasks due within 7 days (7)
  renew-cluster-account  2026-09-20 (8d overdue)  [thesis]  Renew the cluster account
  prepare-exercise-session  2026-10-01 (in 3d)  [teaching]  Prepare Thursday's exercise session
  book-supervisor-meeting  2026-10-02 (in 4d)  [thesis]  Book the next supervisor meeting
  enter-grades  2026-10-03 (in 5d)  [teaching]  Enter grades in the learning platform
  grade-problems  2026-10-03 (in 5d)  [teaching]  Grade problems 1-4
  post-solutions  2026-10-03 (in 5d)  [teaching]  Post the solutions
  run-baseline  2026-10-05 (in 7d)  [thesis]  Run the NUTS baseline

Deliverable deadlines within 365 days (2)
  workshop-talk  2026-10-20 (in 22d)  [thesis]  drafting  Talk: tuning HMC without tears
  icml-paper  2027-01-28 (in 122d)  [thesis]  drafting  Adaptive step sizes for Hamiltonian Monte Carlo

3 ideas in the inbox (tavla idea list)
```

What this tells you:

- **ablations is stale,** and its only real task is blocked on IT. Either
  chase it, log why it's stuck (`tv log ablations "..."`), or pause it with
  `tv project edit ablations --status paused`.
- **The cluster account is overdue,** and it's high priority. Do it first.
- **The baseline is the bottleneck:** the adaptive run, the comparison, the
  figures, the results chapter and the ablation grid all wait on it.

## How the thesis fits together

`status` lists what's waiting; `flow` shows the shape of it:

```console
$ tv flow thesis --open --width 110
Project: PhD thesis: adaptive MCMC  (thesis)

STAGE 1                               STAGE 1                               STAGE 2
╭─ renew-cluster-account ───────╮     ╭─ experiments ─────────────────╮     ╭─ write-up ────────────────────╮
│ ● Renew the cluster account   │     │ ▶ Experiments chapter         │ ──▶ │ ● Write the thesis draft      │
│ high · due 2026-09-20         │     │ high · due 2026-10-30 · 1/5   │     │ high · due 2026-11-30 · 0/3   │
│ ! overdue (due 2026-09-20)    │     │   ▶ Run the NUTS baseline     │     │   ● Draft the methods chapter │
╰───────────────────────────────╯     │   ○ Run the adaptive sampler  │     │   ○ Draft the results chapter │
                                      │   ○ Compare the two samplers  │     │   ○ Send the full draft to t… │
                                      │   ○ Make the result figures   │     │ ! draft-results: due before   │
                                      ╰───────────────────────────────╯     │ make-figures (2026-10-20)     │
                                                                            ╰───────────────────────────────╯
╭─ book-supervisor-meeting ─────╮                                           ╭─ ablation-grid ───────────────╮
│ ● Book the next supervisor    │                                           │ ○ Ablation grid over          │
│ meeting                       │                                           │ step-size schedules           │
│ med · due 2026-10-02          │                                           │ med · 0/2                     │
╰───────────────────────────────╯                                           │   ✗ Request GPU hours         │
                                                                            │   ○ Run the ablation grid     │
                                                                            │ after: experiments            │
                                                                            ╰───────────────────────────────╯
Ready now: ▶ run-baseline  ● renew-cluster-account  ● draft-methods  ● book-supervisor-meeting
✓ done   ▶ doing   ● ready   ○ waiting   ✗ blocked   ? missing   ↗ elsewhere   ! date problem
```

- Stage 1 holds what can happen in parallel now. The write-up is in stage 2
  because one of its tasks waits on the experiments.
- The ablation grid lives in the subproject, but one of its tasks waits on
  the baseline, so it also comes after the experiments.
- The results chapter is due on 15 October, but the figures it needs are due
  on the 20th. `flow` flags that, so you can fix one of the dates.

Try `tv flow experiments` for the task-by-task chain inside one goal, and
`tv flow thesis --by status` for a kanban board.

## Drilling into one project

```console
$ tv project show thesis
PhD thesis: adaptive MCMC
  id:        thesis
  status:    active
  priority:  high
  tags:      phd, mcmc
  created:   2025-09-01
  path:      projects/thesis

Subprojects
  ablations  [active]  Ablation studies

Goals
  experiments  [doing]  1/5 tasks  Experiments chapter
  lit-review  [done]  2/2 tasks  Literature review chapter
  write-up  [todo]  0/3 tasks  Write the thesis draft
  ablation-grid  [todo]  0/2 tasks  Ablation grid over step-size schedules

Tasks
  todo: 9  doing: 1  blocked: 1  done: 3
  book-supervisor-meeting  [todo]  Book the next supervisor meeting  (no goal)
  renew-cluster-account  [todo]  Renew the cluster account  (no goal)

Deliverables
  icml-paper  [drafting]  due 2027-01-28  Adaptive step sizes for Hamiltonian Monte Carlo
  workshop-talk  [drafting]  due 2026-10-20  Talk: tuning HMC without tears

Ideas
   1. Try a #tempering ladder for the multimodal target
   2. Reuse the baseline trace plots in the #teaching slides

Recent log
  2026-09-10  Pipeline runs end to end on the toy model
  2026-09-22  Baseline converges on logistic regression; hierarchical model is slow
  2026-09-26  Supervisor meeting: aim for a full draft by the end of November
```

## Ideas everywhere

```console
$ tv idea list --all
inbox
   1. Look into parallel tempering for the bimodal target #mcmc
   2. Ask the department about a travel grant for the workshop
   3. Check whether ArviZ has a faster ESS estimator #tools

thesis (project)
   1. Try a #tempering ladder for the multimodal target
   2. Reuse the baseline trace plots in the #teaching slides

experiments (goal)
   1. Run the big models on the #gpu cluster once the allocation is through
```

`tv idea promote` turns one into a task when it's ready; see
[Ideas and the inbox](../guide/ideas.md).

## Things to try

Browse the files under `~/.cache/tavla/demo/projects/thesis/` and compare
them with what the commands show. In particular:

- `tasks/run-baseline.md` has instructions, subtasks and updates, which is
  where the `2/4` comes from.
- `tasks/run-adaptive.md` has `depends_on: [run-baseline]`.
- `deliverables/icml-paper.yaml` is the deliverable format.
- `subprojects/ablations/` shows the nested layout.

Then change things and watch the views update: `tv task done run-baseline`
unblocks two tasks, and `tv undo` puts it back.
