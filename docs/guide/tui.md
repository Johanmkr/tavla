# The full-screen view

`tv ui` (or just `tv` in a terminal) opens everything in one screen, laid
out like lazygit: a stack of lists on the left, and the detail of whatever
is selected on the right. It's made to sit open in a terminal tab or tmux
pane all day.

```
╭─ Status ──────────────────────╮╭─ run-baseline ──────────────────────────────╮
│▶ run-baseline           1h12m ││▶ Run the NUTS baseline                      │
│! 1 overdue · ✗ 1 blocked      ││run-baseline · thesis · goal experiments     │
╰───────────────────────────────╯│high (goal) · doing · due 2026-10-19 (in 7d) │
╭─ Projects ────────────────────╮│after   ✓ set-up-pipeline                    │
│teaching                      4││blocks  compare-methods, run-adaptive        │
│thesis                        9││                                             │
│  ablations                   2││Subtasks 2/4                                 │
╰───────────────────────────────╯│  ✓ Toy model                                │
╭─ Goals ───────────────────────╮│  ✓ Logistic regression                      │
│▶ experiments        in 32d 1/5││  ● Hierarchical model                       │
│● write-up           14 Dec 0/3││  ● Save traces to results/baseline/         │
│(loose)                       2││                                             │
╰───────────────────────────────╯│Instructions                                 │
╭─ Tasks│Ideas│Deliv ───────────╮│  Default NUTS settings, 4 chains.           │
│▶ run-baseline        in 7d 2/4││                                             │
│○ run-adaptive       in 32d 0/3││                                             │
╰────────────────── experiments ─╯╰─────────────────────────────────────────────╯
 space done  s start  w work  n note  a add  e edit  t due  D drop   ? help  ↻ 4s ago
```

## The panes

- **Status** (`1`): the task you are working on and for how long, what
  needs attention (overdue, blocked, inbox), and your open
  [todos](daily-workflow.md). While it has focus, the Tasks pane shows the
  `next` list across all projects and the right side shows a `status`
  summary. `enter` on the working line jumps to that task.
- **Projects** (`2`): active projects, with subprojects indented and the
  number of open tasks. The right side shows the project's
  [flow board](organising-work.md).
- **Goals** (`3`): the selected project's goals, plus `(loose)` for tasks
  without a goal. The right side shows the goal's flow board.
- **Tasks** (`4`): follows whichever of the three panes above you used
  last: the `next` list, a project's tasks (ready ones first) or a goal's
  tasks in dependency order. `[` and `]` switch to the **Ideas** (inbox,
  project or goal ideas) and **Deliverables** tabs.
- **Detail** (`0`, or `enter` on a task): the task with its dependencies,
  subtasks, work sessions and notes. Here `j`/`k` move between subtasks and
  `space` ticks them.

Done tasks and goals and paused projects are hidden; `.` shows them.

## Keys

Press `?` inside for the full list. The line at the bottom always shows the
keys for the pane you are in.

| Key | What it does |
|---|---|
| `j` `k` / arrows, `g` `G` | move, top, bottom |
| `tab`, `1`–`4`, `0` | next pane, jump to a pane, detail |
| `enter` / `esc` | go into the next pane / back out (or clear a filter) |
| `space` or `x` | done / reopen (tasks, goals, todos, subtasks) |
| `s` | start: mark doing |
| `w` | work on the task (`tv work`); again to pause |
| `n` | note in `## Updates` (on a project: a log line) |
| `a` | add a task, goal, project, idea, todo or subtask, depending on the pane |
| `e` | open in `$EDITOR`; checked and committed as with `tv task edit` |
| `!` | cycle priority high → med → low |
| `t` | due date (`today`, `+3d`, `fri`, `2026-11-01`; `none` clears) |
| `p` | promote an idea to a task |
| `D` | drop (asks first; refused while other tasks depend on it) |
| `u` | undo the last change (asks first, shows what) |
| `/` | filter the list you are in |
| `r`, `ctrl-p`, `q` | reload, command palette (themes), quit |

Every change goes through the same code as the CLI, so it is checked and
committed the same way, and `u` (or `tv undo`) takes it back.

## Staying up to date

The view reloads by itself within a couple of seconds whenever something
commits to the content repo: the CLI in another shell, `tv undo`, Claude
with the tavla skill, or a `git pull`. The `↻` at the bottom right says when
it last reloaded. Edits you saved by hand but haven't committed show up when
you press `r`.

## Small terminals

Below 80 columns the panes stack: the one you are in grows and the others
shrink to their selected line, and `enter` on a task opens its detail
full-screen (`esc` goes back). Below 40×12 it asks for a bigger window.

Colours come from your terminal's own palette, so it matches your theme,
light or dark. `NO_COLOR` is respected; focus and selection are still shown
by the bold pane title and reversed row.
