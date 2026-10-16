"""People on goals and tasks: shared pieces of ``task|goal people/mail`` and
the ``tavla people`` listing."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from tavla.cli.common import ContentDirOpt, JsonOpt, State, emit_json, handles_errors, state
from tavla.core import people
from tavla.core.entities import Goal, Person, Task

PersonOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--person",
        help='Someone involved: "Name <email>", an email, or a name. A piece of the name '
        "or address of someone already in tavla reuses their entry. Repeatable.",
    ),
]
PersonEditOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--person",
        help="People: NAME replaces the list, +NAME adds, -NAME removes, 'none' clears. "
        "Repeatable.",
    ),
]
EmailsOpt = Annotated[
    bool, typer.Option("--emails", "-e", help="Only the addresses, one per line.")
]
PrintOpt = Annotated[
    bool, typer.Option("--print", help="Print the mailto: link instead of opening it.")
]


def everyone(item: Goal | Task) -> list[tuple[Person, bool]]:
    """``(person, from_goal)`` for everyone involved in ``item``."""
    if isinstance(item, Task):
        own = {p.key for p in item.people}
        return [(p, p.key not in own) for p in item.everyone]
    return [(p, False) for p in item.people]


def print_people_field(item: Goal | Task, width: int = 10) -> None:
    """``people:`` lines for ``show``, one person per line."""
    for i, (person, inherited) in enumerate(everyone(item)):
        label = "people:" if i == 0 else ""
        note = " (from goal)" if inherited else ""
        typer.echo(f"  {label:<{width}}{person}{note}")


def show_people(st: State, item: Goal | Task, emails: bool) -> None:
    rows = everyone(item)
    if st.json:
        emit_json(
            [{"name": p.name, "email": p.email, "from_goal": inherited} for p, inherited in rows]
        )
        return
    if emails:
        for p, _ in rows:
            if p.email:
                typer.echo(p.email)
        return
    if not rows:
        typer.echo(f"No one listed on {item.id}. Add someone: --person on `edit`.")
    for p, inherited in rows:
        typer.echo(f"{p}{' (from goal)' if inherited else ''}")


def mail(item: Goal | Task, print_only: bool) -> None:
    involved = [p for p, _ in everyone(item)]
    url = people.mailto(involved, item.title)
    missing = [str(p) for p in involved if not p.email]
    if missing:
        typer.secho(f"note: no address for {', '.join(missing)}", fg=typer.colors.YELLOW, err=True)
    if print_only:
        typer.echo(url)
        return
    typer.echo(f"Opening a new email to {sum(bool(p.email) for p in involved)} people…")
    if not people.open_mailto(url):
        typer.echo(url)


@handles_errors
def people_(
    ctx: typer.Context,
    query: Annotated[
        str | None, typer.Argument(help="Only people whose name or address contains this.")
    ] = None,
    emails: EmailsOpt = False,
    json_out: JsonOpt = False,
    content_dir: ContentDirOpt = None,
) -> None:
    """Everyone listed on a goal or task, with where they appear.

    Use a piece of a name or address from here with --person to reuse that
    person's entry.
    """
    st = state(ctx, json_out=json_out, content_dir=content_dir)
    content = st.content()
    found = [p for p in people.known(content) if not query or p.matches(query)]
    items: list[Any] = [*content.goals(), *content.tasks()]
    where = {p.key: [i.id for i in items if any(q.key == p.key for q in i.people)] for p in found}
    if st.json:
        emit_json([{"name": p.name, "email": p.email, "on": where[p.key]} for p in found])
        return
    if emails:
        for p in found:
            if p.email:
                typer.echo(p.email)
        return
    if not found:
        typer.echo("No one found." if query else "No people yet. Add them with --person.")
    for p in found:
        typer.echo(f"{p}  ({', '.join(where[p.key])})")
