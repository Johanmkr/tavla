# tavla

**tavla** is a personal research operations tool for one researcher juggling
several projects. It keeps track of goals, tasks, loose ideas and progress
logs, and answers one question across all of them: *what should I work on next?*

![tv next, then tv task done, then tv flow, on the demo content](assets/demo.gif)

<div class="grid cards" markdown>

- **Plain text.** Everything is Markdown or YAML that you can read, grep and
  edit by hand. Nothing is locked in a database.
- **Git is the history.** Every change tavla makes is committed to your content
  repo automatically. `git log` is the audit trail and `tavla undo` reverts the last change.
- **Your data is separate.** Your content lives in its own private git repo,
  never in the software repo.
- **CLI-first, with a full-screen view.** Commands are fast to type, ids can
  be abbreviated, and `--json` makes them scriptable. `tv` on its own opens
  everything on one screen, with single keys for the same changes.

</div>

## A 30-second tour

```console
$ tv project add "Master thesis" --priority high --id thesis
$ tv goal add "Experiments" -p thesis --id exp
$ tv task add "Set up training pipeline" -g exp --id pipeline
$ tv task add "Run baseline" -g exp --after pipeline      # waits for pipeline
$ tv next
ID        PRIORITY  STATUS  DUE  SUBTASKS  GOAL  PROJECT  TITLE
pipeline  med       todo    -    -         exp   thesis   Set up training pipeline
$ tv task done pipeline
Done: pipeline (Set up training pipeline)
Now unblocked: run-baseline
```

`tv` is a short alias for `tavla`. Both work everywhere.

## Or all of it on one screen

`tv` with no command opens [the full-screen view](guide/tui.md): columns of
projects, goals and tasks with a preview, and `next`, the inbox and the agenda
one key away. It is made to sit open in a tmux pane all day and reloads by
itself when anything changes.

![tv ui on the demo: a goal's tasks, ticking a subtask, the flow board, next, inbox, agenda and a quick capture](assets/tui.gif)

## How it fits together

```mermaid
--8<-- "model.mmd"
```

Projects hold goals, goals are reached through tasks, and tasks can wait for
each other. [Organising work](guide/organising-work.md) explains each part.

## Where to go from here

- **New to tavla?** Start with [Getting started](getting-started.md).
- **Want to see it used on something real?** See the worked
  [master's thesis example](examples/master-thesis.md).
- **Rather use the keyboard than commands?** Read [The full-screen view](guide/tui.md).
- **Looking for a specific flag?** Go to the [command reference](reference/cli.md).
- **Testing tavla for someone?** Read the [notes for alpha testers](alpha.md).
- **Stuck on something?** Check the [FAQ](faq.md).
