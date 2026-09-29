# Changelog

What changed in each release of tavla. The newest release is at the top.

Versions follow `MAJOR.MINOR.PATCH`. While tavla is at `0.x`, a MINOR bump
(`0.2` → `0.3`) can change commands or behaviour, and a PATCH bump only fixes
bugs. If a release changes the content layout, it says so under **Upgrading**,
and you run `tavla migrate` once after updating.

Update with `tavla update` (`--check` to see what's new first).

## [Unreleased]

### Features
- `tavla flow PROJECT|GOAL`: a dependency board. It shows a project's goals,
  or a goal's tasks, in stages of work that can run in parallel, with arrows
  and `after:` notes for the dependencies. Use `--open` to show only what's
  left, and `--json` to get the board as data. Cards mark tasks in progress,
  flag overdue work and tasks due before their prerequisites, and a
  "Ready now" line lists what you can start. `--by status` shows a kanban
  board instead, and `--format mermaid` prints the board as a diagram.
- `tavla demo` sets up a playground content repo with example projects (a
  thesis, a teaching job, a paused paper), with dates moved to around today.
  Every command works there, and your own content is never touched.
- `tavla info` prints versions, paths and content details to paste into a
  bug report.
- `tavla goal list -p PROJECT` now lists the goals of each subproject
  under their own heading.
- Goal and task lists (and `show`) warn when a file's `project:` line names
  a different project than the folder it's in, which happens after editing
  the file by hand. `tavla check --fix` moves the file.

### Documentation
- Diagrams of how projects, goals, tasks and ideas relate, and of what a
  command does to your content repo; a terminal recording of a first session.
- A shorter README that points to the user guide, with the demo, install and
  a first session.
- New page with notes for alpha testers; the worked examples now use the demo
  content and include `flow` boards.
- Issue forms for bug reports and ideas; CONTRIBUTING reorganised for
  first-time contributors.

## [0.2.0] - 2026-09-29

The first tagged release, for testers.

### Features
- Projects and subprojects, goals, and tasks with `## Subtasks` checklists,
  dependencies (`--after`) and priority/due inherited from their goal.
- Ideas in the inbox or on a project, goal or task, with `#tags`; move, drop,
  or promote them to tasks and goals. `tavla capture` for quick inbox notes.
- Deliverables (papers, slides, datasets, code releases) with deadlines.
- `tavla next` and `tavla status` for a cross-project overview; `tavla log`
  for per-project progress notes.
- `tavla add`: add anything by answering questions, with a review screen to
  change any field (id, priority, due, …) before creating, and "add another".
- `tavla check [--fix]`: find problems in hand-edited files (files that don't
  load, duplicate ids, broken goal/dependency links, `project:` lines that
  disagree with the file's folder) and fix the project ones.
- Move goals and tasks between projects with `goal edit -p` / `task edit -p`,
  or by changing `project:` inside `tavla ... edit`. A goal's tasks move along.
- Every change is a git commit in your content repo; `tavla undo` reverts the
  last one.
- `tavla update` installs the newest release (or, in a development clone,
  fast-forwards to `origin/main`).

### Fixes
- Renaming a project's id now updates the `project:` lines of its goals and
  tasks.

### Upgrading
- Content repos from before the goal/task split (layout v1) need
  `tavla migrate` once. Run `tavla migrate --dry-run` first to see the plan.
