# Contributing

Thanks for helping with tavla! Bug reports and ideas go in
[issues](https://github.com/Johanmkr/tavla/issues/new/choose); this page is
about changing the code.

## Setup

You need [uv](https://docs.astral.sh/uv/) and `git`.

```sh
git clone https://github.com/Johanmkr/tavla
cd tavla
uv sync --extra dev          # creates .venv with tavla and the dev tools
uv run pytest                # the tests (a few seconds)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run tv --help             # run the CLI from your clone
```

CI runs the same lint, format check and tests on Linux and macOS with Python
3.11–3.13 for every push and pull request.

## Workflow

1. Branch off `main` (`yourname/short-topic`).
2. Make the change with tests. Behaviour that users see also needs its help
   text, the docs page that covers it, and a line under `## [Unreleased]` in
   `CHANGELOG.md`.
3. Commit with a prefix that says what kind of change it is:
   `ADD:` a feature, `FIX:` a bug, `DOC:` documentation only. The subject says
   what changed; the body says why, if that isn't obvious.
4. Open a pull request against `main`. CI must be green before merging.

## Where things live

```
src/tavla/
├── config.py          where the content repo is (the only place that decides)
├── core/              everything that reads or changes content; no printing
│   ├── entities.py    the file shapes: Project, Goal, Task, Deliverable, ...
│   ├── parsing.py     frontmatter, Markdown sections, YAML
│   ├── store.py       Content: read access to a content repo
│   ├── queries.py     id resolution, next, status
│   ├── ops.py         every change: add, edit, move, start/done, drop, ...
│   ├── flow.py        dependency and status boards (tv flow)
│   ├── ideas.py       the inbox and ideas in projects, goals and tasks
│   ├── git_sync.py    commits in the content repo; history.py: undo
│   ├── check.py       consistency checks (tv check)
│   ├── migrate.py     layout upgrades (tv migrate); bootstrap.py: tv init
│   ├── demo.py        the playground (tv demo); info.py: tv info
│   └── self_update.py tv update
├── cli/               the typer commands: thin wrappers over core
└── demo_content/      the example content that tv demo copies
tests/                 pytest; fixtures/ holds sample content trees
docs/                  the MkDocs user guide
```

## Rules the code follows

- All content parsing, querying and git logic belongs in `src/tavla/core/`.
  Interfaces (`cli/`, later a TUI) are thin wrappers and never touch the
  content directory directly.
- Core code never prints or parses CLI arguments. It raises `TavlaError`
  subclasses, which carry the exit code (`0` ok, `1` error, `2` not found,
  `3` ambiguous/invalid).
- Reading the content tree goes through `tavla.core.store.Content`; the
  filesystem is scanned at query time (no index).
- Content-dir paths are only ever resolved through `tavla.config.resolve_content_dir`.
- Tests run against `tmp_path` or `tests/fixtures/`, never a real content repo
  and never with personal data. `tests/conftest.py` isolates `HOME`, the XDG
  dirs and the git identity automatically.
- Changing the on-disk layout means bumping `SCHEMA_VERSION` in
  `tavla.core.bootstrap` and adding a step to `tavla.core.migrate`, so existing
  content repos can be upgraded with `tavla migrate`. `tests/fixtures/v1`
  keeps a copy of the oldest layout for the migration tests;
  `tests/fixtures/basic` and `src/tavla/demo_content/` are always at the
  current layout.

## Using a development version next to the stable one

Use the stable release for your real work, and run development code under
another name against a copy of your notes.

1. **`tv` is the stable release**, installed like any tester's:

   ```sh
   uv tool install --force git+https://github.com/Johanmkr/tavla@v0.2.0
   ```

   It uses your real content repo, and `tv update` moves it to new releases.
   Don't use an editable install (`uv tool install --editable .`) for daily
   work: `tv` would then run whatever the clone has checked out.

2. **`tvdev` runs your clone**, whatever branch or uncommitted changes it has,
   from any directory and without reinstalling. **`tvmain`** runs the latest
   commit on GitHub's `main` without a clone. Put these in your shell rc,
   with the path to your clone:

   ```sh
   alias tvdev='TAVLA_CONTENT_DIR=~/tavla-sandbox uv run --project ~/path/to/tavla tv'
   alias tvmain='TAVLA_CONTENT_DIR=~/tavla-sandbox uvx --refresh-package tavla --from git+https://github.com/Johanmkr/tavla@main tv'
   ```

3. **`~/tavla-sandbox` is a clone of your real content repo**, so testing
   happens on realistic data without touching the original:

   ```sh
   git clone ~/.local/share/tavla ~/tavla-sandbox
   # reset it after a messy test:
   rm -rf ~/tavla-sandbox && git clone ~/.local/share/tavla ~/tavla-sandbox
   ```

   This matters most for layout changes: if a development version's
   `tavla migrate` ran on your real notes, the stable `tv` would refuse to
   open them until the next release. (`tv demo` is the other safe place to
   try things.)

`tvdev --version` shows a development version (`0.2.1.dev3+g…`), so you can
always tell them apart.

## Documentation

The user guide is a MkDocs site: Markdown in `docs/`, config in `mkdocs.yml`.
Preview it with:

```sh
uv run --extra docs mkdocs serve
```

- The **command reference** (`reference/cli.md`) is generated from the Typer
  app at build time by `docs/hooks/cli_reference.py`, so help texts are its
  only source.
- **Diagrams** are Mermaid files in `docs/diagrams/`, included into pages
  with `--8<-- "model.mmd"` inside a `mermaid` block. The README can't
  include files, so it carries a copy of `model.mmd`; a test fails if they
  drift apart.
- **The terminal recording** (`docs/assets/demo.gif`) comes from
  `docs/assets/demo.tape`. After changing what those commands print,
  re-record it from the repo root with [vhs](https://github.com/charmbracelet/vhs):
  `vhs docs/assets/demo.tape`. (If Chromium can't start its sandbox, as on
  recent Ubuntu, prefix `VHS_NO_SANDBOX=true`.)
- Example output in the guide comes from the demo content. Update it when
  the output changes.

Pushes to `main` that touch `docs/`, `mkdocs.yml` or `src/tavla/cli/` rebuild
and publish the site via `.github/workflows/docs.yml`.

## Releasing (maintainers)

Releases are git tags on `main`; there is no release branch. The version is
never written by hand: hatch-vcs reads it from the latest tag (`vX.Y.Z` →
`X.Y.Z`; later commits build as `X.Y.(Z+1).devN+g<sha>`).

1. Make sure `main` is green and `uv run pytest` passes locally.
2. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`
   and add a fresh empty `## [Unreleased]` above it. If the content layout
   changed, say so under **Upgrading** (and `SCHEMA_VERSION` must have been
   bumped with a migration, see above).
3. Update the install lines to the new tag in `README.md`,
   `docs/getting-started.md` and this file. `tests/test_docs.py` fails until
   they match the newest changelog section. Commit this with the changelog.
4. Tag and push:

   ```sh
   git tag -a vX.Y.Z -m "tavla X.Y.Z"
   git push origin vX.Y.Z
   ```

5. `.github/workflows/release.yml` then runs the tests, builds the wheel,
   checks its version matches the tag, and creates the GitHub Release with the
   wheel attached and the changelog section as its notes. It fails if the
   changelog has no section for the version.

Testers install a release with the install line from the README, and
`tavla update` moves them to the newest `vX.Y.Z` tag. Tags with a suffix
(`v1.0.0rc1`) become GitHub pre-releases and are skipped by `tavla update`.
