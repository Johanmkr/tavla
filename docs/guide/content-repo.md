# Your content repo

## What happens when you run a command

```mermaid
--8<-- "machinery.mmd"
```

tavla reads and writes plain files, and commits every change it makes, so the
git history is the record of your work. You can edit the files yourself too;
`tv check` tells you if something no longer fits together.

## Layout

```
~/.local/share/tavla/
├── tavla.yaml                 # content layout version (maintained by tavla)
├── registry.yaml              # index of top-level projects (maintained by tavla)
├── inbox.md                   # `tavla capture` / `idea add` land here
├── library/                   # reading notes (planned: Zotero sync)
└── projects/
    └── adaptive-sampling/
        ├── project.yaml
        ├── log.md             # `tavla log` lands here
        ├── ideas.md           # the project's ideas
        ├── goals/
        │   └── intro.md
        ├── tasks/
        │   ├── outline.md     # points at its goal with `goal: intro`
        │   └── run-baseline-experiments.md
        ├── deliverables/      # *.yaml, managed with `tavla deliverable`
        └── subprojects/       # same shape, nested (`project add -p`)
```

Links between things always use **ids**, never paths. A goal's or task's
project is the folder it lives in, so moving a file to another project's
`goals/` or `tasks/` folder moves it to that project.

## Where tavla looks

The first match wins:

1. `--content-dir PATH` (before or after the command)
2. the `TAVLA_CONTENT_DIR` environment variable
3. `content_dir` in `~/.config/tavla/config.toml`
4. `~/.local/share/tavla/`

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` are respected.

## History and undo

Every change tavla makes is one commit with a readable message:

```console
$ git -C ~/.local/share/tavla log --oneline
2e9262e log: thesis: pipeline runs end to end on toy data
3f177b8 task: done pipeline
c0e2287 idea: move inbox -> exp: try mixed precision to speed up training
cacb4ba inbox: capture try mixed precision to speed up training
ca48ffc task: start pipeline
```

To undo the last change, run `tavla undo` (`-n` shows what it would undo first).
It adds a revert commit, so nothing is lost; run it again to go further back.

## Syncing between machines

tavla commits locally and never pushes. To sync, add a **private** remote and
push and pull as usual:

```sh
cd ~/.local/share/tavla
git remote add origin git@github.com:you/tavla-content.git   # keep it private
git push -u origin main
```

On a second machine, clone the repo and point tavla at it:

```sh
git clone git@github.com:you/tavla-content.git ~/.local/share/tavla
```

If you cloned it anywhere else, set `content_dir` in
`~/.config/tavla/config.toml` or `TAVLA_CONTENT_DIR`.

## Upgrading the layout

When a new tavla version changes the on-disk layout, it will tell you. Then run:

```sh
tavla migrate --dry-run     # show the plan
tavla migrate               # apply it as a single commit
```

The repo must have no uncommitted changes first. To undo the migration, run
`tavla undo`.

From layout v1 (tasks only), every task becomes a goal, and each of its
`## Subtasks` checkboxes becomes a task under that goal.
