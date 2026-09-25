"""Error types and exit codes shared by every interface.

Exit codes:
    0  success
    1  generic error
    2  id not found
    3  ambiguous id / validation error
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_FOUND = 2
EXIT_INVALID = 3


class TavlaError(Exception):
    """Base class for all tavla errors. Carries the exit code to use."""

    exit_code = EXIT_ERROR


class NotFoundError(TavlaError):
    exit_code = EXIT_NOT_FOUND


class AmbiguousIdError(TavlaError):
    exit_code = EXIT_INVALID

    def __init__(self, prefix: str, candidates: list[str]):
        self.prefix = prefix
        self.candidates = candidates
        super().__init__(f"ambiguous id '{prefix}': matches {', '.join(candidates)}")


class ValidationError(TavlaError):
    exit_code = EXIT_INVALID


class GitError(TavlaError):
    pass
