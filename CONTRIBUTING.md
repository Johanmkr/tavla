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
  and `example-content/` are always at the current layout.

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
Update the version in the install lines of `README.md` and
`docs/getting-started.md` when you release.
