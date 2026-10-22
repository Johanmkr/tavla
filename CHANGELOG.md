# Changelog

What changed in each release of tavla. The newest release is at the top.

Versions follow `MAJOR.MINOR.PATCH`. While tavla is at `0.x`, a MINOR bump
(`0.2` → `0.3`) can change commands or behaviour, and a PATCH bump only fixes
bugs. If a release changes the content layout, it says so under **Upgrading**,
and you run `tavla migrate` once after updating.

Update with `tavla update` (`--check` to see what's new first).

## [Unreleased]

## [0.4.0] - 2026-10-22

The full-screen release. `tavla ui`, or just `tavla`/`tv` in a terminal, shows
all of your projects in one view, with single keys for the daily commands.
It also adds working on one task at a time (issue #21), a todo list and inbox
triage, people with email addresses (issue #22), search, and project
lifecycle commands.

### Upgrading
- **Run `tavla migrate` once after updating.** The content layout goes from
  v2 to v3, and only the version in `tavla.yaml` changes: v3 adds an
  optional `order:` line to task files, and nothing needs rewriting.
  `tavla migrate --dry-run` shows what it would do.
- tavla now depends on Textual, for `tavla ui`. Other commands don't load
  it.
- In `--json` output, projects have `repo_paths` (a list) instead of
  `repo_path`.

### The full-screen view (`tavla ui`)
- A drill-down view, `PROJECT | GOAL | TASK | preview`. `1`-`4` switch
  between a project, `next`, the inbox and the agenda. Piped or in scripts,
  bare `tavla` still prints help. See
  [The full-screen view](https://johanmkr.github.io/tavla/guide/tui/).
- Single keys do what the commands do, each as its own commit, so `u` undoes
  them:
  - `space` marks done and `x` reopens. On a subtask in the preview it ticks;
    on a deliverable it picks the status.
  - `w` starts or pauses work and `W` opens a task terminal.
  - `o`/`O` add an item, `n` adds a note, `e` opens `$EDITOR` and `R`
    renames.
  - `t` sets the due date and `!` cycles the priority.
  - `m` moves, `D` drops (a subproject goes with its contents, and the
    question counts them), and `a`/`A` add and remove dependencies.
  - `@` handles people. `c` captures an idea and `C` a chore from anywhere.
  - `y` copies the id under the cursor, for a CLI command.
- `v`/`V` mark rows so a verb acts on all of them. `J`/`K` rearrange a list
  and write `order:`. `/` filters every column, `f` shows the flow board full
  screen, and `i` jumps to the next overdue, blocked or stale item.
- `T` triages the inbox: chores first, then ideas, one at a time. One key
  turns each item into a task, goal, project or subtask, files it under a
  project or goal for later, marks it done or drops it.
- Subprojects are listed at the top of a project's goal column: `enter`
  opens one and `h` goes back. Pickers filter as you type.
- It reloads by itself whenever the content repo changes. The header shows
  the scopes as tabs, where you are, the task you are working on and what
  needs attention, and `?` lists every key and symbol. The colours follow
  your terminal's theme, and `NO_COLOR` is respected.

### Working on a task
- `tavla work TASK` marks a task doing and makes it the current task. Until
  you `tavla pause` or `tavla done`:
  - `tick`, `untick`, `subtask` and `note` act on it;
  - `next` and `status` show it at the top;
  - starting another task is refused.

  Each stretch of work is logged in the task's `## Sessions` with its
  duration.
- `tavla done [TASK]` finishes the current task, or the one given.
- `tavla work -t TASK` (`W` in the full-screen view) opens the task in a
  terminal of its own, titled with the task and in its own colour. Closing
  the terminal logs the session and marks the task done (`-s N`: ticks one
  subtask). Several can be open at once.
- `tavla project link PROJECT [FOLDER]` links a folder to a project. Inside a
  linked folder, `next`, `task list` and `log` show just that project (`-G`
  shows everything).

### Todos, the inbox and search
- `tavla todo TEXT` adds to `todo.md`, a checklist for small things outside
  any project. `tavla todo` lists it, and `done`, `reopen`, `drop`, `clear`
  and `promote` manage it.
- `tavla inbox` lists the chores and ideas waiting to be sorted.
  `tavla inbox review` goes through them one at a time, with the same keys
  as `T`.
- `tavla idea promote` and `tavla todo promote` can also make a project
  (`--as-project`) or a subtask (`--subtask-of`).
- `tavla find WORDS` searches projects, goals, tasks (with their notes),
  deliverables, ideas, todos and logs, and shows the line that matched.

### Projects
- `tavla project pause|resume|done|archive ID` change a project's status.
- `tavla project drop ID` deletes a project. It is refused while the project
  has subprojects or tasks elsewhere depend on its tasks; `--force` is needed
  while it still has goals, tasks or deliverables.
- `tavla log PROJECT` without text shows the project's log, newest first.
  `tavla log` on its own shows the log of the project whose folder you are
  in, or of every project.
- `repo_path:` in `project.yaml` can be a list of folders.

### People
- Goals and tasks can list the people involved in a `people:` list, set with
  `--person "Name <email>"` on `add` and `edit` (`+X`/`-X` adjust,
  `none` clears). Someone already in tavla is reused from a piece of their
  name or address, and a task also counts its goal's people.
- `tavla task|goal people ID` lists who is involved, `tavla task|goal mail
  ID` starts an email to all of them, and `tavla people` lists everyone.

### Other changes
- Tasks accept an optional `order:` number that sets their place in their
  goal's list, ahead of priority and due date. `task list`, `next` and
  `flow` follow it, and `tavla task edit ID --order N` sets it.
- Dropping the task you are working on is refused until you `tavla pause`.
- `tavla check` reports a `focus.yaml` that names an unknown task.
- The demo has chores, people, work sessions and an ordered goal.

## [0.3.0] - 2026-09-29

The alpha-testing release. `tavla flow` draws how your work depends on
itself, `tavla demo` gives you a safe playground to try everything, and the
docs were reworked for new users. No content layout change: nothing to
migrate.

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
