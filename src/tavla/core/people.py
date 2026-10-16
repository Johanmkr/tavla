"""People involved in goals and tasks (the ``people:`` frontmatter list).

People are written inline in each file, so a file says who is involved on
its own. To save retyping, ``--person`` with a piece of a name or address
reuses someone already listed anywhere in the content repo.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import quote

from tavla.core.entities import Goal, Person, Task
from tavla.core.errors import AmbiguousIdError, NotFoundError, ValidationError
from tavla.core.store import Content

CLEAR_WORDS = ("none", "-")


def known(content: Content) -> list[Person]:
    """Everyone listed on any goal or task, once each (by address, else name),
    sorted by name. An entry with both name and address wins over one
    with only one of them."""
    by_key: dict[str, Person] = {}
    for item in [*content.goals(), *content.tasks()]:
        for person in item.people:
            current = by_key.get(person.key)
            if current is None or (person.name and person.email and not current.name):
                by_key[person.key] = person
    return sorted(by_key.values(), key=lambda p: str(p).lower())


def resolve(content: Content, spec: str) -> Person:
    """A ``--person`` value as a person.

    ``Name <email>`` or a bare address is taken as written (filling in the
    name from an earlier entry with the same address). Anything else is
    first matched against the people already in the repo, by a piece of
    their name or address; with no match it becomes a new name-only person.
    """
    given = Person.parse(spec)
    people = known(content)
    if given.email:
        if not given.name:
            same = next(
                (p for p in people if p.email and p.email.lower() == given.email.lower()), None
            )
            if same is not None:
                return same
        return given
    matches = [p for p in people if p.matches(spec)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        exact = [p for p in matches if (p.name or "").lower() == spec.strip().lower()]
        if len(exact) == 1:
            return exact[0]
        raise AmbiguousIdError(spec, [str(p) for p in matches])
    return given


def resolve_all(content: Content, specs: Iterable[str]) -> list[Person]:
    """Several ``--person`` values (as on ``add``), each person once."""
    return _unique(resolve(content, s) for s in specs if s.strip())


def _find(people: list[Person], query: str) -> Person:
    matches = [p for p in people if p.matches(query)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFoundError(f"no one matching '{query}'")
    raise AmbiguousIdError(query, [str(p) for p in matches])


def apply_specs(content: Content, item: Goal | Task, specs: Iterable[str]) -> list[Person]:
    """The item's new people after ``--person`` options: plain values replace
    the list, ``+X`` adds and ``-X`` removes (by a piece of the name or
    address), and ``none`` clears it."""
    specs = [s.strip() for s in specs if s.strip()]
    if any(s.lower() in CLEAR_WORDS for s in specs):
        if len(specs) > 1:
            raise ValidationError("--person none can't be combined with other --person values")
        return []
    signed = [s[0] in "+-" for s in specs]
    if any(signed) and not all(signed):
        raise ValidationError("--person: use either NAME (replace) or +NAME/-NAME (adjust)")
    if not any(signed):
        return resolve_all(content, specs)
    people = list(item.people)
    for spec in specs:
        query = spec[1:].strip()
        if spec[0] == "+":
            people = _unique([*people, resolve(content, query)])
            continue
        try:
            people.remove(_find(people, query))
        except NotFoundError:
            inherited = isinstance(item, Task) and any(p.matches(query) for p in item.goal_people)
            if inherited:
                raise ValidationError(
                    f"'{query}' comes from goal {item.goal}; remove them there"  # type: ignore[union-attr]
                ) from None
            raise
    return people


def _unique(people: Iterable[Person]) -> list[Person]:
    out: dict[str, Person] = {}
    for p in people:
        out.setdefault(p.key, p)
    return list(out.values())


def to_yaml(people: list[Person]) -> list[dict[str, str]] | None:
    """The ``people:`` value to write (None removes the key)."""
    return [p.to_yaml() for p in people] or None


def mailto(people: Iterable[Person], subject: str = "") -> str:
    """A ``mailto:`` link to everyone with an address (addresses only: mail
    programs disagree on how to read names in a link)."""
    to = ",".join(quote(p.email, safe="@") for p in people if p.email)
    if not to:
        raise ValidationError("no one here has an email address")
    return f"mailto:{to}" + (f"?subject={quote(subject)}" if subject else "")


def open_mailto(url: str) -> bool:
    """Hand ``url`` to the desktop's mail program. False if nothing opened it.

    The one place that launches it, so ``tv task mail`` and the TUI behave the
    same. ``typer`` is imported here rather than at module level: the core
    library stays usable without the CLI framework.
    """
    import typer

    return typer.launch(url) == 0
