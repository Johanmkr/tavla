# tavla

**tavla** is a personal research operations tool for one researcher juggling
several projects. It keeps track of goals, tasks, loose ideas and progress
logs, and answers one question across all of them: *what should I work on next?*

<div class="grid cards" markdown>

- **Plain text.** Everything is Markdown or YAML that you can read, grep and
  edit by hand. Nothing is locked in a database.
- **Git is the history.** Every change tavla makes is committed to your content
  repo automatically. `git log` is the audit trail and `git revert` is undo.
- **Your data is separate.** Your content lives in its own private git repo,
  never in the software repo.
- **CLI-first.** It's fast to type, and ids can be abbreviated. Tab-completion
  shows titles, and `--json` output makes it scriptable.

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

## Where to go from here

- **New to tavla?** Start with [Getting started](getting-started.md).
- **Want to see it used on something real?** See the worked
  [master's thesis example](examples/master-thesis.md).
- **Looking for a specific flag?** Go to the [command reference](reference/cli.md).
- **Stuck on something?** Check the [FAQ](faq.md).
