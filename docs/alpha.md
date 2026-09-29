# Notes for alpha testers

Thanks for trying tavla! It's used every day, but it's still **alpha**:
commands and output may change between releases, and your feedback decides
what changes. This page covers what to expect and how to help.

## Getting going

1. [Install it](getting-started.md#install) and run `tv demo`. It sets up a
   playground with example projects where every command, including the ones
   that change things, is safe to try.
2. When you're ready, `tv init` creates your own content repo, and the
   [everyday loop](getting-started.md#the-everyday-loop) is all you need.
3. Run `tv update --check` now and then. New releases are listed in the
   [changelog](https://github.com/Johanmkr/tavla/blob/main/CHANGELOG.md).

## Your data is safe

- **It's plain files.** Your content is Markdown and YAML in an ordinary git
  repo (`~/.local/share/tavla` unless you chose another place). You can read
  and edit it without tavla, and it stays readable if you stop using tavla.
- **Every change is a commit.** `tv undo` reverts the last one, and
  `git log` shows everything tavla ever did.
- **Upgrades never strand it.** If a release changes the file layout, tavla
  asks you to run `tavla migrate`, which converts your content in a single
  commit (so `tv undo` reverts that too).
- **Back it up.** Push the content repo to a *private* remote now and then;
  see [Syncing between machines](guide/content-repo.md#syncing-between-machines).
  tavla never pushes by itself.
- **Nothing leaves your machine.** There is no telemetry and no account. The
  only network access is `tv update`, which asks GitHub for the newest
  release.

## What feedback helps most

- **Does `tv next` pick what you would pick?** If not, what did it get wrong?
- **Does `tv flow` help you plan,** or is it noise? What's missing on it?
- **Where did you get stuck?** A confusing message, a command you expected
  to exist, a flag you had to look up every time.
- **What do you do outside tavla** that you wish you could do in it?

Small things count: a typo in a message is worth an issue too.

## Reporting a problem

[Open an issue](https://github.com/Johanmkr/tavla/issues/new/choose) and pick
**Bug report** or **Idea or wish**. For a bug:

- Paste the output of `tv info`. It lists versions and paths (which may
  include your user name) but nothing from your notes.
- If you can, reproduce it in the demo (`tv demo --reset`), so the steps
  work for anyone and you don't need to share your own content.

## Known limitations

- **Platforms:** Linux and macOS are tested on every change. Windows isn't
  tested yet.
- **No interactive interface yet.** Everything is commands for now; a
  terminal UI is the next big step.
- **One writer at a time.** If you use tavla on two machines, pull before you
  start and push when you're done. Changes made on both at once have to be
  merged with git by hand.
- **Planned, not built yet:** links to code repos and a reading library
  synced with Zotero. The `library/` folder in your content repo is reserved
  for it.

## Uninstalling

```sh
uv tool uninstall tavla
```

This removes the program only. Your content repo, the config file
(`~/.config/tavla/config.toml`) and the demo (`~/.cache/tavla/demo`) stay
where they are; delete them yourself if you want them gone.
