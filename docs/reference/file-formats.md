# File formats

All files are plain text. Dates are always stored as `YYYY-MM-DD`.

## Task: `tasks/<id>.md`

tavla reads the frontmatter, the `# title`, the `## Subtasks` checkboxes, the
`## Ideas` bullets and the `## Sessions` lines. Everything else is yours and is
never rewritten.

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
people:                         # optional; who is involved (goals too)
  - name: Kari Nordmann
    email: kari.nordmann@example.org
  - name: Ana Berg              # a name, an email, or both
---

# Draft related work

## Instructions
What to do, links, acceptance criteria — anything you like.

## Subtasks
- [x] Collect papers
- [ ] Write two paragraphs      <- counted as 1/2 in `next` and `task list`

## Ideas
- Contrast with #tempering methods

## Sessions
- 2026-09-26 09:30-11:05 (1h35m): first pass   <- added by `tv pause` / `tv done`

## Updates
- 2026-09-26: found the key survey
```

Each `people:` entry needs a name, an email address, or both. You can also
write an entry on one line, as `- Kari Nordmann <kari.nordmann@example.org>`.
`tv check` reports entries it can't read. A task's goal's people count as
involved in the task too.

The `## Sessions` section appears after your first `tv work` session ends.
Each line is one stretch of work. A session that runs past midnight has the
end date as well (`2026-09-26 23:30-2026-09-27 01:00`). The duration in
brackets is only for you to read; tavla works it out from the times.

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
repo_path: ~/code/project-a   # or a list: [~/code/project-a, ~/papers/a]
created: 2026-01-10
```

`repo_path` lists the folders where the project's code or files live (`tv
project link` adds one). Inside one of them, `tv next` and `tv task list` show
only this project.

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

## Todos: `todo.md`

A checklist at the root of the content repo. `tv todo` adds, ticks and
removes the lines. A plain `- text` bullet counts as an open todo.

```markdown
# Todo

- [ ] Buy HDMI cables #lab
- [x] Return library books
```

## Log: `log.md`

`tavla log` appends one timestamped line per call. You can also add lines by
hand.

## Maintained by tavla

`tavla.yaml` (the layout version) and `registry.yaml` (the index of top-level
projects) are managed by tavla. Don't edit them by hand.

`focus.yaml` exists only while you are working on a task (`tv work`). It names
the task and when you started, and `tv pause` or `tv done` removes it:

```yaml
task: draft-related-work
since: 2026-09-26 09:30
```
