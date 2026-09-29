"""Keep the hand-written docs in step with the code and with each other."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
INSTALL_RE = re.compile(r"git\+https://github\.com/Johanmkr/tavla@v(\d+\.\d+\.\d+)")
INSTALL_DOCS = ["README.md", "docs/getting-started.md", "CONTRIBUTING.md"]


def latest_release() -> str:
    """The newest ``## [X.Y.Z]`` section in CHANGELOG.md."""
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", (ROOT / "CHANGELOG.md").read_text(), re.MULTILINE)
    assert match, "CHANGELOG.md has no release section"
    return match[1]


def test_install_lines_point_at_the_latest_release():
    """Bump these together when releasing (see CONTRIBUTING.md, Releasing)."""
    latest = latest_release()
    for doc in INSTALL_DOCS:
        versions = set(INSTALL_RE.findall((ROOT / doc).read_text()))
        assert versions == {latest}, f"{doc} installs {versions}, latest release is {latest}"


def mermaid_blocks(text: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL)


def test_readme_diagram_matches_the_docs():
    """GitHub can't include files, so the README carries a copy of the model
    diagram; the docs include docs/diagrams/model.mmd."""
    source = (ROOT / "docs/diagrams/model.mmd").read_text()
    assert source in mermaid_blocks((ROOT / "README.md").read_text())


def test_docs_include_existing_diagrams():
    for page in (ROOT / "docs").rglob("*.md"):
        for block in mermaid_blocks(page.read_text()):
            for name in re.findall(r'--8<-- "(.+?)"', block):
                assert (ROOT / "docs/diagrams" / name).is_file(), f"{page}: missing {name}"
