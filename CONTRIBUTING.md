# Contributing

- All content parsing, querying and git logic belongs in `src/tavla/core/`.
  Interfaces (`cli/`, later TUI/web) are thin wrappers and must not touch the
  content directory directly.
- Core code never prints or parses CLI arguments; it raises `TavlaError`
  subclasses, which carry the exit code (`0` ok, `1` error, `2` not found,
  `3` ambiguous/invalid).
- Reading the content tree goes through `tavla.core.store.Content`; the
  filesystem is scanned at query time (no index).
- Content-dir paths are only ever resolved through `tavla.config.resolve_content_dir`.
- Tests run against `tmp_path` or `tests/fixtures/` — never a real content repo,
  and never with personal data. `tests/conftest.py` isolates `HOME`, XDG dirs
  and git identity automatically.
- Changing the on-disk layout means bumping `SCHEMA_VERSION` in
  `tavla.core.bootstrap` and adding a step to `tavla.core.migrate`, so existing
  content repos can be upgraded with `tavla migrate`. `tests/fixtures/v1` keeps
  a copy of the oldest layout for the migration tests; `tests/fixtures/basic`
  and `src/tavla/demo_content/` (what `tavla demo` copies) are always at the
  current layout.

## Working on tavla

Use the stable release for your real work and run the code in your clone
under a separate name, against a copy of your notes.

1. **`tv` is the stable release**, installed like any tester's:

   ```sh
   uv tool install --force git+https://github.com/Johanmkr/tavla@v0.2.0
   ```

   It uses your real content repo, and `tv update` moves it to new releases.
   (An editable install, `uv tool install --editable .`, would make `tv` run
   whatever the clone has checked out, so don't use one for daily work.)

2. **`tvdev` runs the clone**, whatever branch or uncommitted changes it has,
   from any directory and without reinstalling. Put this in your shell rc:

   ```sh
   alias tvdev='TAVLA_CONTENT_DIR=~/tavla-sandbox uv run --project ~/Documents/tavla tv'
   ```

3. **`~/tavla-sandbox` is a clone of your real content repo**, so testing
   happens on realistic data that `tvdev` can't touch the original of:

   ```sh
   git clone ~/.local/share/tavla ~/tavla-sandbox
   # reset it after a messy test:
   rm -rf ~/tavla-sandbox && git clone ~/.local/share/tavla ~/tavla-sandbox
   ```

   This matters most for layout changes: if a dev version's `tavla migrate`
   ran on your real notes, the stable `tv` would refuse to open them until
   the next release.

`tvdev --version` shows a development version (`0.2.1.dev3+g…`), so you can
always tell the two apart. Run the tests with `uv run pytest` in the clone.
After you release, run `tv update` to use the release yourself.

## Documentation

The user guide is a MkDocs site: Markdown in `docs/`, config in `mkdocs.yml`.
The command reference (`reference/cli.md`) is generated from the Typer app at
build time by `docs/hooks/cli_reference.py`, so help texts are the single
source for it. Preview locally with:

```sh
uv pip install -e '.[docs]'
.venv/bin/mkdocs serve
```

Pushes to `main` that touch `docs/`, `mkdocs.yml` or `src/tavla/cli/` rebuild
and publish the site via `.github/workflows/docs.yml`.

## Releasing

Releases are git tags on `main`; there is no release branch. The version is
never written by hand: hatch-vcs reads it from the latest tag (`v0.3.0` →
`0.3.0`; later commits build as `0.3.1.devN+g<sha>`).

1. Make sure `main` is green and `.venv/bin/pytest` passes locally.
2. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [0.3.0] - YYYY-MM-DD`
   and add a fresh empty `## [Unreleased]` above it. If the content layout
   changed, say so under **Upgrading** (and `SCHEMA_VERSION` must have been
   bumped with a migration, see above). Commit this.
3. Tag and push:

   ```sh
   git tag -a v0.3.0 -m "tavla 0.3.0"
   git push origin v0.3.0
   ```

4. `.github/workflows/release.yml` then runs the tests, builds the wheel,
   checks its version matches the tag, and creates the GitHub Release with the
   wheel attached and the changelog section as its notes. It fails if the
   changelog has no section for the version.

Testers install a release with
`uv tool install git+https://github.com/Johanmkr/tavla@v0.3.0`, and
`tavla update` moves them to the newest `vX.Y.Z` tag. Tags with a suffix
(`v1.0.0rc1`) become GitHub pre-releases and are skipped by `tavla update`.
Update the version in the install lines of `README.md`,
`docs/getting-started.md` and "Working on tavla" above when you release.
