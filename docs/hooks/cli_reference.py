"""MkDocs hook: generate reference/cli.md from the Typer app at build time.

The page is never written to disk, so it can't drift from the code and
`mkdocs serve` doesn't loop on its own output.
"""

import re
import subprocess
import sys

from mkdocs.structure.files import File

PAGE = "reference/cli.md"
HEADING = re.compile(r"^#+ ")

INTRO = """\
# Command reference

Generated from `tavla --help` on every docs build. `tv` accepts exactly the
same commands. For the ideas behind them, see the [user guide](../guide/organising-work.md).

"""


def _typer_docs() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "typer", "tavla.cli.main", "utils", "docs", "--name", "tavla"],
        capture_output=True,
        text=True,
        check=True,
    )
    body = result.stdout
    # Drop Typer's own H1; the intro above provides the page title.
    first, _, rest = body.partition("\n")
    if first.startswith("# "):
        body = rest
    # Escape docstring lines like "#tags in the idea..." that Markdown would
    # otherwise read as headings.
    lines = []
    in_examples = False
    for line in body.splitlines():
        # An "Examples:" epilog (see tavla.cli.common.examples) runs until the
        # next blank line; render it as a console block instead of a paragraph.
        if line == "Examples:":
            in_examples = True
            lines += ["**Examples**:", "", "```console"]
            continue
        if in_examples:
            if line:
                lines.append(f"$ {line}")
                continue
            in_examples = False
            lines.append("```")
        if line.startswith("#") and not HEADING.match(line):
            line = "\\" + line
        lines.append(line)
    if in_examples:
        lines.append("```")
    return "\n".join(lines)


def on_files(files, config):
    files.append(File.generated(config, PAGE, content=INTRO + _typer_docs() + "\n"))
    return files
