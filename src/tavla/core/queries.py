"""Id resolution, and (milestone 4) next/status aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from tavla.core.errors import AmbiguousIdError, NotFoundError


class HasId(Protocol):
    id: str


T = TypeVar("T", bound=HasId)


def resolve_id(query: str, items: Iterable[T], kind: str = "item") -> T:
    """Resolve ``query`` to exactly one item by exact id, else unique prefix.

    Raises NotFoundError if nothing matches and AmbiguousIdError (listing the
    candidates) if several do — never guesses.
    """
    items = list(items)
    exact = [i for i in items if i.id == query]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        # Duplicate ids on disk (e.g. a hand-edited file). Show where they are.
        raise AmbiguousIdError(query, [f"{i.id} ({getattr(i, 'path', '?')})" for i in exact])
    matches = [i for i in items if i.id.startswith(query)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFoundError(f"no {kind} matching '{query}'")
    raise AmbiguousIdError(query, sorted(i.id for i in matches))


def complete_ids(prefix: str, items: Iterable[HasId]) -> list[str]:
    return sorted({i.id for i in items if i.id.startswith(prefix)})
