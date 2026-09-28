# Scripting

## JSON output

Read commands accept `--json`: `next`, `status`, `project/goal/task list`,
`project/goal/task show` and `idea list`. The flag works before or after the
command.

```console
$ tv next --json -n 1
{
  "tasks": [
    {
      "id": "run-baseline",
      "project": "thesis",
      "title": "Run baseline",
      "status": "todo",
      "priority": "high",
      "goal": "exp",
      "depends_on": ["pipeline"],
      "due": null,
      "subtasks_done": 0,
      "subtasks_total": 0,
      "waiting_on": [],
      "inherited": ["priority"],
      ...
    }
  ],
  "goals_without_tasks": [ ... ]
}
```

`inherited` lists the fields that came from the task's goal.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | general error |
| `2` | id not found |
| `3` | ambiguous id, or invalid data |

## Examples

Show the top task in your shell prompt or status bar:

```sh
tv next --json -n 1 | jq -r '.tasks[0].title // "nothing to do"'
```

Count open tasks per project:

```sh
tv task list --json | jq -r 'group_by(.project)[] | "\(.[0].project): \(length)"'
```

Skip confirmation prompts in scripts with `-y`/`--yes`.
