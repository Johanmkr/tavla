# File formats

All files are plain text. Dates are always stored as `YYYY-MM-DD`.

## Task: `tasks/<id>.md`

tavla reads the frontmatter, the `# title`, the `## Subtasks` checkboxes and
the `## Ideas` bullets. Everything else is yours and is never rewritten.

```markdown
---
id: draft-related-work
project: adaptive-sampling
goal: intro                     # optional; leave out for a task without a goal
status: todo
depends_on: [outline]           # optional; waits until these tasks are done
tags: []
created: 2026-09-25
updated: 2026-09-26
# priority / due: optional; inherited from the goal when left out
---

# Draft related work

## Instructions
What to do, links, acceptance criteria — anything you like.

## Subtasks
- [x] Collect papers
- [ ] Write two paragraphs      <- counted as 1/2 in `next` and `task list`

## Ideas
- Contrast with #tempering methods

## Updates
- 2026-09-26: found the key survey
```

## Goal: `goals/<id>.md`

A goal file has the same shape as a task file, but without `goal`,
`depends_on` and `## Subtasks`. Its `priority` and `due` apply to any of its
tasks that don't set their own.

## Project: `project.yaml`

```yaml
id: project-a
title: "Adaptive sampling for X"
status: active          # active | paused | done | archived
priority: high          # high | med | low
tags: [bayesian, sampling]
related: [project-b]
repo_path: ~/code/project-a
created: 2026-01-10
```

## Deliverable: `deliverables/<id>.yaml`

`project show` and `status` read these files. For now you create them by hand.

```yaml
id: neurips-paper
title: "Adaptive sampling paper"
kind: paper
status: drafting
venue: NeurIPS 2027
deadline: 2027-05-15
coauthors: [advisor-name]
```

## Ideas: `inbox.md` and `ideas.md`

Each idea is one bullet line. Any `#word` in it is a tag.

```markdown
- Try importance sampling on the toy model
- Look into parallel tempering #mcmc
```

## Log: `log.md`

`tavla log` appends one timestamped line per call. You can also add lines by
hand.

## Maintained by tavla

`tavla.yaml` (the layout version) and `registry.yaml` (the index of top-level
projects) are managed by tavla. Don't edit them by hand.
