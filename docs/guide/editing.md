# Editing and ids

## Ids

Ids come from titles (`"Run baseline experiments"` → `run-baseline-experiments`)
unless you pass `--id`. They must be unique across **all** projects, goals and
tasks.

Wherever tavla expects an id, you can type:

1. the full id,
2. any **unique prefix** (`adap`, `run-b`), or
3. any **unique piece** of the id or title (`baseline`, `tempering`).

If more than one thing matches, tavla lists the candidates instead of guessing:

```console
$ tv task show run
error: ambiguous id 'run': matches run-ablations, run-baseline
```

!!! tip
    Pick short ids for things you type often: `--id intro`, `--id exp`. To
    rename later, run `tv task edit ID` (or `goal`/`project edit`) and change
    the `id:` line. Every task that pointed at the old id is updated. The file
    name stays the same, which is fine, because tavla goes by the `id:` field.

## Two ways to edit

**With flags,** to change specific fields without opening an editor:

```sh
tv task edit draft --due fri --priority high
tv task edit draft --status blocked
tv goal edit intro --title "Write the introduction"
tv project edit thesis --status paused
```

**In `$EDITOR`,** by running `edit` with no options. The whole file opens for
you to change instructions, subtasks and notes:

```sh
tv task edit outline
```

When you save, tavla checks the file (valid fields, known goal, known
dependencies, no cycles) and commits it. If something is wrong, it restores
the previous version and tells you why.

## List-valued options

`--tags` and `--after` take either a replacement list or a set of changes:

| You type | Effect |
| --- | --- |
| `--tags a,b` | tags become exactly `a, b` |
| `--tags +c` | add `c` |
| `--tags +c,-a` | add `c`, remove `a` |
| `--after none` | clear all dependencies |

`none` also clears `--due`, `--goal` and a task's `--priority`. The task then
inherits that value from its goal again.

## Values

| Field | Allowed values |
| --- | --- |
| priority | `high`, `med` (default), `low` |
| project status | `active` (default), `paused`, `done`, `archived` |
| goal and task status | `todo` (default), `doing`, `blocked`, `done` |

## Dates

`--due` accepts:

| Form | Examples |
| --- | --- |
| ISO | `2026-10-01` |
| Day-first, with year | `01.10.2026`, `01/10/26`, `01-10-2026` |
| Day-first, no year | `01.10` (the next 1 October) |
| Relative | `today`, `tomorrow`, `+3d`, `+2w` |
| Weekday | `fri`, `friday` (the next one) |

Files always store dates as `YYYY-MM-DD`. If you type a day-first date (with a
year) while editing a file by hand, tavla rewrites it as ISO when you save.

## Editing files directly

Every file is yours to edit with any tool. tavla reads the frontmatter, the
`# title`, the `## Subtasks` checkboxes and the `## Ideas` bullets. Everything
else is free text that tavla never rewrites.

!!! warning "Commit hand edits yourself"
    tavla only auto-commits its own changes. If you edit a file outside
    `tavla ... edit`, commit it in the content repo afterwards. To have tavla
    validate your change, open the file with `tavla ... edit` instead.

See [File formats](../reference/file-formats.md) for exactly what each file
contains.
