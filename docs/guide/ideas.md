# Ideas and the inbox

Ideas are one-line thoughts you don't want to lose but aren't ready to act on.
Each idea belongs to exactly one place:

| Scope | Stored in |
| --- | --- |
| the inbox (default) | `inbox.md` |
| a project | `projects/<id>/ideas.md` |
| a goal or task | the `## Ideas` section of its file |

## Capturing

```sh
tv capture "look into parallel tempering #mcmc"
tv idea add "compare with HMC" -g exp        # straight into a goal
```

`capture` is shorthand for `idea add` into the inbox. The quotes are optional,
because the words get joined together. But see the FAQ on
[`#tags` and your shell](../faq.md#my-tag-disappeared): without quotes, some
shells drop everything after `#`.

Any `#word` in an idea is a **tag**:

```console
$ tv idea list --tag mcmc
inbox
   1. look into parallel tempering #mcmc
```

## Referring to an idea

Ideas have no ids. You refer to one with `[SCOPE:]N` or `[SCOPE:]TEXT`:

| Ref | Means |
| --- | --- |
| `3` | inbox idea number 3 (as numbered by `idea list`) |
| `exp:1` | idea 1 of the goal/task/project `exp` |
| `intro:tempering` | the idea in `intro` containing "tempering" |

## Triage

Go through the inbox every so often:

```sh
tv idea list                    # the inbox
tv idea move 1 -g exp           # file it under a goal
tv idea drop 2                  # not worth keeping
tv idea list --all              # every idea, everywhere
```

## Promoting

When an idea turns into real work:

```console
$ tv idea promote exp:1 -g exp
Promoted to task try-mixed-precision-to-speed-up-training: try mixed precision to speed up training
```

- Use `-p PROJECT` instead of `-g` for a task without a goal.
- Add `--as-goal` to make a goal instead of a task.
- The idea's `#tags` become the new item's tags.

The generated id is long. To rename it, run `tv task edit ID` and change the
`id:` line (see [Ids](editing.md#ids)).
