# Changelog

What changed in each release of tavla. The newest release is at the top.

Versions follow `MAJOR.MINOR.PATCH`. While tavla is at `0.x`, a MINOR bump
(`0.2` → `0.3`) can change commands or behaviour, and a PATCH bump only fixes
bugs. If a release changes the content layout, it says so under **Upgrading**,
and you run `tavla migrate` once after updating.

Update with `tavla update` (`--check` to see what's new first).

## [Unreleased]

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
