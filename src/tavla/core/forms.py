"""What ``tv add`` asks for each kind of thing, independent of how it's asked.

A :class:`Form` lists its fields in the order they are asked. Required fields
are asked one by one; optional ones start at their defaults and are changed
from the review. Answers live in a plain dict keyed by field; a missing key
means "not set" (the default applies). Each field parses and validates its own
input, so a bad value is caught at its question, and :meth:`Form.create`
calls the same ``ops`` functions as the ``tv <kind> add`` commands.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tavla.core import ideas, ops
from tavla.core.dates import parse_date
from tavla.core.entities import DeliverableKind, GoalStatus, Priority, TaskStatus
from tavla.core.errors import ValidationError
from tavla.core.store import Content

Answers = dict[str, Any]


@dataclass(frozen=True)
class Option:
    value: Any
    label: str


def _plain(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, list):
        return ", ".join(value) or "–"
    return str(value)


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text | select | multi
    required: bool = False
    # select/multi: the choices, given the answers so far.
    options: Callable[[Content, Answers], list[Option]] | None = None
    # text: turn the typed text into a value; raises ValidationError. Blank
    # input on an optional field means "not set" and never reaches parse.
    parse: Callable[[Content, Answers, str], Any] | None = None
    # What applies when the field isn't set, for the review ("med", "from title").
    default: Callable[[Content, Answers], str] | None = None
    # Whether the field applies at all, given the other answers.
    shown: Callable[[Answers], bool] = lambda answers: True
    # Changing any of these fields clears this one (its choices depend on them).
    after: tuple[str, ...] = ()
    fmt: Callable[[Any], str] = _plain

    def show(self, value: Any) -> str:
        return self.fmt(value)


@dataclass
class Form:
    kind: str
    help: str
    fields: list[Field]
    create: Callable[[Content, Answers], str]  # returns what was done
    # Fields kept when adding another of the same kind (where it goes).
    keep: tuple[str, ...] = ()

    def visible(self, answers: Answers) -> list[Field]:
        return [f for f in self.fields if f.shown(answers)]

    def required(self, answers: Answers) -> list[Field]:
        return [f for f in self.visible(answers) if f.required]

    def missing(self, answers: Answers) -> list[Field]:
        return [f for f in self.required(answers) if f.key not in answers]

    def set(self, answers: Answers, key: str, value: Any) -> None:
        """Set (or with ``UNSET`` clear) a field, clearing fields that depend on it."""
        old = answers.get(key, UNSET)
        if value is UNSET:
            answers.pop(key, None)
        else:
            answers[key] = value
        if old != value:
            for f in self.fields:
                if key in f.after and f.key in answers:
                    self.set(answers, f.key, UNSET)

    def values(self, answers: Answers) -> Answers:
        """The answers that apply (fields hidden by other answers dropped)."""
        keys = {f.key for f in self.visible(answers)}
        return {k: v for k, v in answers.items() if k in keys}

    def summary(self, content: Content, answers: Answers) -> list[tuple[str, str, bool]]:
        """(label, shown value, is-default) for each field that applies."""
        rows = []
        for f in self.visible(answers):
            if f.key in answers:
                rows.append((f.label, f.show(answers[f.key]), False))
            else:
                rows.append((f.label, f.default(content, answers) if f.default else "–", True))
        return rows


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


# --- choices --------------------------------------------------------------------


def _project_options(content: Content, answers: Answers) -> list[Option]:
    depth: dict[str, int] = {}
    options = []
    for p in content.projects():
        depth[p.id] = 0 if p.parent is None else depth[p.parent] + 1
        options.append(Option(p.id, f"{'  ' * depth[p.id]}{p.id}  {p.title}"))
    return options


def _open_goals(content: Content) -> list[Option]:
    return [
        Option(g.id, f"{g.id}  {g.title}  ({g.project})")
        for g in content.goals()
        if g.status != GoalStatus.DONE
    ]


def _open_tasks(content: Content) -> list[Option]:
    return [
        Option(t.id, f"{t.id}  {t.title}  ({t.project})")
        for t in content.tasks()
        if t.status != TaskStatus.DONE
    ]


def _enum_options(enum: type) -> Callable[[Content, Answers], list[Option]]:
    return lambda content, answers: [Option(e, e.value) for e in enum]


def _idea_scopes(content: Content, answers: Answers) -> list[Option]:
    return [
        Option(ideas.INBOX, "inbox"),
        *(Option(o.value, f"project  {o.label.strip()}") for o in _project_options(content, {})),
        *(Option(o.value, f"goal     {o.label}") for o in _open_goals(content)),
        *(Option(o.value, f"task     {o.label}") for o in _open_tasks(content)),
    ]


# --- parsing ----------------------------------------------------------------------


def _title(content: Content, answers: Answers, raw: str) -> str:
    return ops.clean_title(raw)


def _text(what: str) -> Callable[[Content, Answers, str], str]:
    return lambda content, answers, raw: ops.one_line(raw, what)


def _id(content: Content, answers: Answers, raw: str) -> str:
    id_ = raw.strip()
    ops.validate_id(id_)
    taken = content.all_ids()
    if id_ in taken:
        raise ValidationError(f"id '{id_}' is already used by {taken[id_][0]}")
    return id_


def _date(content: Content, answers: Answers, raw: str) -> dt.date:
    return parse_date(raw)


def _list(content: Content, answers: Answers, raw: str) -> list[str]:
    return ops.parse_tags(raw)


def _stripped(content: Content, answers: Answers, raw: str) -> str:
    return " ".join(raw.split())


def _id_default(content: Content, answers: Answers) -> str:
    title = answers.get("title")
    if not title:
        return "from the title"
    try:
        return f"{ops.suggest_id(content, title)}  (from the title)"
    except ValidationError:
        return "from the title"


def _goal_of(content: Content, answers: Answers):
    goal_id = answers.get("goal")
    return next((g for g in content.goals() if g.id == goal_id), None) if goal_id else None


def _task_priority_default(content: Content, answers: Answers) -> str:
    goal = _goal_of(content, answers)
    return f"{goal.priority}  (the goal's)" if goal else Priority.MED.value


def _task_due_default(content: Content, answers: Answers) -> str:
    goal = _goal_of(content, answers)
    return f"{goal.due.isoformat()}  (the goal's)" if goal and goal.due else "–"


def _fixed(text: str) -> Callable[[Content, Answers], str]:
    return lambda content, answers: text


# --- fields shared between forms --------------------------------------------------


def _title_field(label: str = "Title") -> Field:
    return Field("title", label, required=True, parse=_title)


def _project_field(label: str = "Project", key: str = "project", **kw: Any) -> Field:
    return Field(key, label, "select", required=True, options=_project_options, **kw)


ID = Field("id", "Id", parse=_id, default=_id_default)
PRIORITY = Field(
    "priority", "Priority", "select", options=_enum_options(Priority), default=_fixed("med")
)
DUE = Field("due", "Due", parse=_date, fmt=lambda d: d.isoformat())
TAGS = Field("tags", "Tags", parse=_list)


# --- create -----------------------------------------------------------------------


def _create_project(content: Content, a: Answers) -> str:
    parent = content.project(a["parent"]) if "parent" in a else None
    project = ops.add_project(
        content,
        a["title"],
        id=a.get("id"),
        priority=a.get("priority", Priority.MED),
        tags=a.get("tags", []),
        parent=parent,
    )
    where = f" under {parent.id}" if parent else ""
    return f"Added project {project.id}{where}"


def _create_goal(content: Content, a: Answers) -> str:
    goal = ops.add_goal(
        content,
        a["title"],
        content.project(a["project"]),
        id=a.get("id"),
        priority=a.get("priority", Priority.MED),
        due=a.get("due"),
        tags=a.get("tags", []),
    )
    return f"Added goal {goal.id} to {goal.project}"


def _create_task(content: Content, a: Answers) -> str:
    goal = content.goal(a["goal"]) if a.get("goal") else None
    task = ops.add_task(
        content,
        a["title"],
        None if goal else content.project(a["project"]),
        goal=goal,
        id=a.get("id"),
        priority=a.get("priority"),
        due=a.get("due"),
        tags=a.get("tags", []),
        depends_on=a.get("depends_on", []),
    )
    where = f"under goal {task.goal}" if task.goal else f"to {task.project}"
    return f"Added task {task.id} {where}"


def _create_subtask(content: Content, a: Answers) -> str:
    task = ops.add_subtask(content, content.task(a["task"]), a["text"])
    return f"Added subtask {task.subtasks_total} to {task.id}"


def _create_idea(content: Content, a: Answers) -> str:
    scope = ideas.resolve_scope(content, a["where"])
    line = ideas.add(content, scope, a["text"])
    return f"Added to {scope.label}: {line}"


def _create_deliverable(content: Content, a: Answers) -> str:
    deliverable = ops.add_deliverable(
        content,
        a["title"],
        content.project(a["project"]),
        id=a.get("id"),
        kind=a.get("kind", DeliverableKind.PAPER),
        venue=a.get("venue"),
        deadline=a.get("deadline"),
        coauthors=a.get("coauthors", []),
    )
    return f"Added deliverable {deliverable.id} to {deliverable.project}"


# --- the forms --------------------------------------------------------------------


FORMS: dict[str, Form] = {
    f.kind: f
    for f in [
        Form(
            "project",
            "a top-level project",
            [_title_field(), ID, PRIORITY, TAGS],
            _create_project,
        ),
        Form(
            "subproject",
            "a project inside another project",
            [_project_field("Parent project", "parent"), _title_field(), ID, PRIORITY, TAGS],
            _create_project,
            keep=("parent",),
        ),
        Form(
            "goal",
            "an outcome in a project, reached through tasks",
            [_project_field(), _title_field(), ID, PRIORITY, DUE, TAGS],
            _create_goal,
            keep=("project",),
        ),
        Form(
            "task",
            "a unit of work, under a goal or loose in a project",
            [
                Field(
                    "goal",
                    "Goal",
                    "select",
                    required=True,
                    options=lambda content, answers: [
                        Option(None, "(no goal: a loose task in a project)"),
                        *_open_goals(content),
                    ],
                    fmt=lambda v: v or "– (loose task)",
                ),
                _project_field(shown=lambda answers: answers.get("goal") is None),
                _title_field(),
                ID,
                Field(
                    "priority",
                    "Priority",
                    "select",
                    options=_enum_options(Priority),
                    default=_task_priority_default,
                    after=("goal",),
                ),
                Field("due", "Due", parse=_date, default=_task_due_default, fmt=DUE.fmt),
                Field(
                    "depends_on",
                    "Depends on",
                    "multi",
                    options=lambda content, answers: _open_tasks(content),
                ),
                TAGS,
            ],
            _create_task,
            keep=("goal", "project"),
        ),
        Form(
            "subtask",
            "a checklist item in a task",
            [
                Field(
                    "task",
                    "Task",
                    "select",
                    required=True,
                    options=lambda content, answers: _open_tasks(content),
                ),
                Field("text", "Subtask", required=True, parse=_text("subtask")),
            ],
            _create_subtask,
            keep=("task",),
        ),
        Form(
            "idea",
            "a one-line idea, in the inbox or on a project, goal or task",
            [
                Field("where", "Where", "select", required=True, options=_idea_scopes),
                Field("text", "Idea (#words are tags)", required=True, parse=_text("idea")),
            ],
            _create_idea,
            keep=("where",),
        ),
        Form(
            "deliverable",
            "a paper, slides, dataset or code release",
            [
                _project_field(),
                _title_field(),
                Field(
                    "kind",
                    "Kind",
                    "select",
                    options=_enum_options(DeliverableKind),
                    default=_fixed("paper"),
                ),
                Field("venue", "Venue", parse=_stripped),
                Field("deadline", "Deadline", parse=_date, fmt=DUE.fmt),
                Field("coauthors", "Coauthors", parse=_list),
                ID,
            ],
            _create_deliverable,
            keep=("project",),
        ),
    ]
}
