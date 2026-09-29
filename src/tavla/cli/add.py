"""``tv add``: add anything through a dialogue instead of flags.

The required fields are asked in order, with a way back at every question;
then a review shows every field (optional ones at their defaults) and lets
you change any of them before creating. Afterwards you can add another of the
same kind, which starts at the same place (project, goal, ...).

The prompts go through a :class:`Prompter`, so tests can script them.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Protocol

import typer

from tavla.cli.common import ContentDirOpt, handles_errors, state
from tavla.core.errors import EXIT_INVALID, TavlaError, ValidationError
from tavla.core.forms import FORMS, UNSET, Answers, Field, Form
from tavla.core.store import Content

BACK: Any = type("Back", (), {"__repr__": lambda self: "BACK"})()
BACK_TEXT = "<"
NO_DEFAULT: Any = type("NoDefault", (), {})()  # None can be a real option value


class Cancelled(Exception):
    """The user pressed Ctrl-C or chose Cancel."""


class Prompter(Protocol):
    def select(
        self, message: str, options: Sequence[tuple[str, Any]], default: Any = NO_DEFAULT
    ) -> Any: ...

    def text(self, message: str, default: str, validate: Callable[[str], str | None]) -> str: ...

    def checkbox(
        self, message: str, options: Sequence[tuple[str, Any]], checked: Sequence[Any]
    ) -> list[Any]: ...

    def confirm(self, message: str, default: bool) -> bool: ...


class QuestionaryPrompter:
    """Arrow-key menus with type-to-filter, via questionary. Ctrl-C cancels.

    ``io`` (prompt_toolkit ``input``/``output``) is passed to every prompt, for tests.
    """

    def __init__(self, **io: Any) -> None:
        import questionary

        self.q = questionary
        self.io = io

    def _ask(self, question: Any) -> Any:
        answer = question.ask()
        if answer is None:
            raise Cancelled
        return answer

    def select(
        self, message: str, options: Sequence[tuple[str, Any]], default: Any = NO_DEFAULT
    ) -> Any:
        # Values go through their index: questionary treats a None value as "use the title".
        choices = [self.q.Choice(label, value=str(i)) for i, (label, _) in enumerate(options)]
        start = next((c for c, (_, v) in zip(choices, options, strict=True) if v == default), None)
        question = self.q.select(
            message,
            choices,
            default=start,
            use_search_filter=len(options) > 8,
            use_jk_keys=False,
            instruction="(↑↓ enter, type to filter)" if len(options) > 8 else "(↑↓ enter)",
            **self.io,
        )
        return options[int(self._ask(question))][1]

    def text(self, message: str, default: str, validate: Callable[[str], str | None]) -> str:
        question = self.q.text(
            message,
            default=default,
            validate=lambda raw: validate(raw) or True,
            instruction=f"({BACK_TEXT} back)",
            **self.io,
        )
        return self._ask(question)

    def checkbox(
        self, message: str, options: Sequence[tuple[str, Any]], checked: Sequence[Any]
    ) -> list[Any]:
        choices = [
            self.q.Choice(label, value=str(i), checked=value in checked)
            for i, (label, value) in enumerate(options)
        ]
        picked = self._ask(
            self.q.checkbox(
                message, choices, instruction="(space toggles, enter accepts)", **self.io
            )
        )
        return [options[int(i)][1] for i in picked]

    def confirm(self, message: str, default: bool) -> bool:
        return self._ask(self.q.confirm(message, default=default, **self.io))


BACK_OPTION = ("← back", BACK)


class Wizard:
    def __init__(
        self, content: Content, prompter: Prompter, echo: Callable[[str], None] = typer.echo
    ):
        self.content = content
        self.p = prompter
        self.echo = echo

    def run(self, kind: str | None = None) -> list[str]:
        """Ask, create, repeat while wanted. Returns what was done."""
        done: list[str] = []
        answers: Answers = {}
        while True:
            chosen = kind or self._pick_kind()
            form = FORMS[chosen]
            result = self._fill(form, answers)
            if result is BACK:
                kind, answers = None, {}
                continue
            done.append(result)
            self.echo(result)
            if not self.p.confirm(f"Add another {form.kind}?", default=False):
                return done
            kind = form.kind
            answers = {k: v for k, v in answers.items() if k in form.keep}

    def _pick_kind(self) -> str:
        options = [(f"{k:<12} {f.help}", k) for k, f in FORMS.items()]
        choice = self.p.select("What do you want to add?", [*options, ("✗ cancel", None)])
        if choice is None:
            raise Cancelled
        return choice

    def _fill(self, form: Form, answers: Answers) -> Any:
        """Ask until the item is created (returns the message) or the user
        backs out of the first question (returns BACK)."""
        missing = form.missing(answers)
        required = form.required(answers)
        i = required.index(missing[0]) if missing else len(required)
        while True:
            required = form.required(answers)
            if i < len(required):
                if self._ask(form, required[i], answers) is BACK:
                    if i == 0:
                        return BACK
                    i -= 1
                else:
                    i += 1
                continue
            missing = form.missing(answers)
            if missing:  # a change made another required field apply, or cleared it
                j = required.index(missing[0])
                if self._ask(form, missing[0], answers) is BACK:
                    i = max(j - 1, 0)  # walk the questions again from the one before
                else:
                    i = len(form.required(answers))
                continue

            action = self._review(form, answers)
            if action == "create":
                try:
                    message = form.create(self.content, form.values(answers))
                except TavlaError as e:
                    self.echo(typer.style(f"error: {e}", fg=typer.colors.RED))
                    continue
                self.content.refresh()
                return message
            if action == "back":
                i = len(required) - 1
            elif action == "change":
                fields = form.visible(answers)
                options = [(f.label, f) for f in fields]
                picked = self.p.select("Which field?", [*options, BACK_OPTION])
                if picked is not BACK:
                    self._ask(form, picked, answers)
                i = len(form.required(answers))  # review again (after anything now missing)
            else:
                raise Cancelled

    def _review(self, form: Form, answers: Answers) -> str:
        rows = form.summary(self.content, answers)
        width = max(len(label) for label, _, _ in rows)
        self.echo("")
        self.echo(typer.style(f"  New {form.kind}", bold=True))
        for label, value, is_default in rows:
            shown = typer.style(value, dim=True) if is_default else value
            self.echo(f"    {label.lower():<{width}}  {shown}")
        self.echo("")
        return self.p.select(
            "What next?",
            [
                ("Create it", "create"),
                ("Change a field…", "change"),
                ("← back", "back"),
                ("✗ cancel", "cancel"),
            ],
        )

    def _ask(self, form: Form, field: Field, answers: Answers) -> Any:
        """Ask one field and store the answer. Returns BACK if the user went back."""
        current = answers.get(field.key, UNSET)
        message = field.label if field.required else f"{field.label} (optional)"
        if field.kind == "text":
            return self._ask_text(form, field, answers, message, current)

        assert field.options is not None
        options = [(o.label, o.value) for o in field.options(self.content, answers)]
        if field.kind == "multi":
            if not options:
                self.echo(f"Nothing to choose from for {field.label.lower()}.")
                return BACK
            checked = [] if current is UNSET else current
            picked = self.p.checkbox(message, options, checked)
            form.set(answers, field.key, picked or UNSET)
            return None

        if not options:
            self.echo(f"There is nothing to pick for {field.label.lower()} yet; add one first.")
            return BACK
        if not field.required:
            default = field.default(self.content, answers) if field.default else "–"
            options.insert(0, (f"(default: {default})", UNSET))
        value = self.p.select(message, [*options, BACK_OPTION], default=current)
        if value is BACK:
            return BACK
        form.set(answers, field.key, value)
        return None

    def _ask_text(
        self, form: Form, field: Field, answers: Answers, message: str, current: Any
    ) -> Any:
        assert field.parse is not None
        parse = field.parse

        def validate(raw: str) -> str | None:
            if raw.strip() == BACK_TEXT or (not raw.strip() and not field.required):
                return None
            try:
                parse(self.content, answers, raw)
            except ValidationError as e:
                return str(e)
            return None

        if not field.required and field.default:
            message = f"{message}, blank for {field.default(self.content, answers)}"
        elif not field.required:
            message = f"{message}, blank for none"
        default = "" if current is UNSET else field.show(current)
        while True:
            raw = self.p.text(message, default, validate)
            if raw.strip() == BACK_TEXT:
                return BACK
            if not raw.strip() and not field.required:
                form.set(answers, field.key, UNSET)
                return None
            error = validate(raw)
            if error is None:
                form.set(answers, field.key, parse(self.content, answers, raw))
                return None
            self.echo(typer.style(f"error: {error}", fg=typer.colors.RED))


KINDS_HELP = ", ".join(FORMS)


def _complete_kind(incomplete: str) -> list[str]:
    return [k for k in FORMS if k.startswith(incomplete)]


@handles_errors
def add(
    ctx: typer.Context,
    kind: Annotated[
        str | None,
        typer.Argument(
            metavar="[KIND]",
            help=f"What to add: {KINDS_HELP}. Asked if left out.",
            autocompletion=_complete_kind,
        ),
    ] = None,
    content_dir: ContentDirOpt = None,
) -> None:
    """Add a project, subproject, goal, task, subtask, idea or deliverable by answering questions.

    Required fields are asked one by one (choose ← back, or type <, to go back).
    A review then shows every field, optional ones at their defaults; change
    any of them, then create. Ctrl-C cancels without adding anything.
    """
    if kind is not None and kind not in FORMS:
        typer.secho(f"error: unknown kind '{kind}' (choose from {KINDS_HELP})", fg="red", err=True)
        raise typer.Exit(EXIT_INVALID)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        example = f"tv {kind or 'goal'} add --help"
        typer.secho(
            f"error: tv add asks questions and needs a terminal; in scripts use e.g. `{example}`",
            fg="red",
            err=True,
        )
        raise typer.Exit(EXIT_INVALID)
    content = state(ctx, content_dir=content_dir).content()
    try:
        Wizard(content, QuestionaryPrompter()).run(kind)
    except Cancelled:
        typer.echo("Cancelled.")
