# Example: juggling several projects

This example uses the demo content that ships in the repo's `example-content/`
folder. You can follow along without touching your own data:

```sh
cd tavla                                   # the software repo
export TAVLA_CONTENT_DIR=$PWD/example-content
```

(`example-content/` isn't a git repo, so only read commands work there.)

## The situation

```console
$ tv project list --all
ID           STATUS    PRIORITY  GOALS  TASKS  TITLE
project-a    active    high      4      7      Adaptive sampling for X
  ablations  active    med       1      1      Ablation studies
project-b    paused    low       1      0      Literature review on MCMC diagnostics
project-c    archived  low       0      0      Old side project
```

- **project-a** is the main paper. It has a subproject, `ablations`, and a
  NeurIPS deliverable.
- **project-b** is on hold, so it's `paused`.
- **project-c** is finished and `archived`. Archived projects are hidden
  unless you pass `--all`.

## One list across everything

```console
$ tv next
ID                           PRIORITY  STATUS  DUE                 SUBTASKS  GOAL           PROJECT    TITLE
draft-related-work           high      todo    2026-10-01 (in 3d)  1/2       write-intro    project-a  Draft related work
wait-for-cluster-allocation  med       todo    -                   -         run-ablations  ablations  Wait for cluster allocation
fix-plot-colors              low       todo    -                   -         -              project-a  Fix plot colors

Goals with no tasks yet (1)
  write-methods  [med]  [project-a]  Write methods section  due 2026-10-15 (in 17d)
```

The paused project-b contributes nothing here, even though it has an open
goal. Pausing is how you say "not now" without deleting anything. To look
at a paused project anyway, use `tv next -p project-b`.

## What needs attention

```console
$ tv status --deadline-days 365
tavla status — 2026-09-28
2 active projects · 4 open tasks (0 doing) · 0 blocked

Stale projects (idle 14+ days) (1)
  ablations  last activity 2026-08-01 (58d ago)

Waiting on dependencies (1)
  get-feedback-from-advisor  [project-a]  Get feedback from advisor  (after draft-related-work)

Goals due within 7 days (1)
  write-intro  2026-10-01 (in 3d)  [project-a]  1/3 tasks  Write introduction section

Tasks due within 7 days (2)
  draft-related-work  2026-10-01 (in 3d)  [project-a]  Draft related work
  get-feedback-from-advisor  2026-10-01 (in 3d)  [project-a]  Get feedback from advisor

Deliverable deadlines within 365 days (1)
  neurips-paper  2027-05-15 (in 229d)  [project-a]  drafting  Adaptive sampling paper

2 ideas in the inbox (tavla idea list)
```

What this tells you:

- **ablations is stale.** Either work on it, log why it's stuck, or pause it:
  `tv project edit ablations --status paused`.
- **The advisor feedback is due in 3 days,** but it can't start until the
  related-work draft is done. That makes the draft the real bottleneck.
- **Two inbox ideas** are waiting to be triaged.

## Drilling into one project

```console
$ tv project show project-a
Adaptive sampling for X
  id:        project-a
  status:    active
  priority:  high
  tags:      bayesian, sampling
  related:   project-b
  repo_path: ~/code/project-a
  ...

Subprojects
  ablations  [active]  Ablation studies

Goals
  setup-env  [done]  2/2 tasks  Set up compute environment
  write-intro  [doing]  1/3 tasks  Write introduction section
  write-methods  [todo]  - tasks  Write methods section
  run-ablations  [blocked]  0/1 tasks  Run ablation grid

Deliverables
  neurips-paper  [drafting]  due 2027-05-15  Adaptive sampling paper

Recent log
  2026-09-01  Kicked off the paper draft
  2026-09-18  First results on the toy model look promising
```

## Ideas everywhere

```console
$ tv idea list --all
inbox
   1. Try importance sampling on the toy model
   2. Email advisor about the conference budget

project-a (project)
   1. Adaptive step size based on the acceptance rate

write-intro (goal)
   1. Open with the #mcmc failure case
   2. Mention the toy model
```

## Things to try

Browse the files under `example-content/projects/project-a/` and compare them
with what the commands show. In particular:

- `tasks/draft-related-work.md` has subtasks, which is where the `1/2` comes
  from.
- `deliverables/neurips-paper.yaml` is the deliverable format.
- `subprojects/ablations/` shows the nested layout.
