"""tavla — CLI-first, git-native research operations tool."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Set from the git tag when tavla is installed (see [tool.hatch.version]).
    __version__ = version("tavla")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0"
