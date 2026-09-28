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
