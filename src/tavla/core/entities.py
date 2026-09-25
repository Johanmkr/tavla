"""Entity models mapping the content-directory file shapes (spec section 4).

Each entity keeps its full parsed metadata in ``meta`` so that later writes can
round-trip fields the model doesn't know about.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, TypeVar

from tavla.core import parsing
from tavla.core.errors import ValidationError


class Priority(StrEnum):
    HIGH = "high"
    MED = "med"
    LOW = "low"

    @property
    def rank(self) -> int:
        return _PRIORITY_RANK[self]


_PRIORITY_RANK = {Priority.HIGH: 0, Priority.MED: 1, Priority.LOW: 2}


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    BLOCKED = "blocked"
    DONE = "done"


class DeliverableKind(StrEnum):
    PAPER = "paper"
    SLIDES = "slides"
    DATASET = "dataset"
    CODE_RELEASE = "code-release"


class DeliverableStatus(StrEnum):
    DRAFTING = "drafting"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under-review"
    ACCEPTED = "accepted"
    PUBLISHED = "published"


class SourceStatus(StrEnum):
    TO_READ = "to-read"
    READING = "reading"
    READ = "read"
    SKIMMED = "skimmed"


# --- field coercion ---------------------------------------------------------

E = TypeVar("E", bound=StrEnum)


def _require_id(meta: dict[str, Any], path: Path) -> str:
    value = meta.get("id")
    if value is None or str(value).strip() == "":
        raise ValidationError(f"{path}: missing required field 'id'")
    return str(value).strip()


def _enum(cls: type[E], value: Any, name: str, path: Path, default: E | None) -> E | None:
    if value is None:
        return default
    try:
        return cls(str(value).strip().lower())
    except ValueError:
        allowed = " | ".join(m.value for m in cls)
        raise ValidationError(f"{path}: invalid {name} '{value}' (expected {allowed})") from None


def _date(value: Any, name: str, path: Path) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(
            f"{path}: invalid {name} date '{value}' (expected YYYY-MM-DD)"
        ) from None


def _str_list(value: Any, name: str, path: Path) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ValidationError(f"{path}: '{name}' must be a list")


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


# --- entities ---------------------------------------------------------------

PROJECT_FILE = "project.yaml"
TASKS_DIR = "tasks"
DELIVERABLES_DIR = "deliverables"
SUBPROJECTS_DIR = "subprojects"
LOG_FILE = "log.md"
IDEAS_FILE = "ideas.md"
REFERENCES_FILE = "references.yaml"


@dataclass
class Project:
    id: str
    title: str
    status: ProjectStatus
    priority: Priority
    path: Path  # project directory
    parent: str | None = None
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    repo_path: str | None = None
    created: dt.date | None = None
    meta: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_subproject(self) -> bool:
        return self.parent is not None

    @classmethod
    def load(cls, directory: Path, parent: str | None = None) -> Project:
        path = directory / PROJECT_FILE
        meta = parsing.read_yaml(path) or {}
        if not isinstance(meta, dict):
            raise ValidationError(f"{path}: expected a mapping")
        id_ = _require_id(meta, path)
        return cls(
            id=id_,
            title=str(meta.get("title") or id_),
            status=_enum(ProjectStatus, meta.get("status"), "status", path, ProjectStatus.ACTIVE),
            priority=_enum(Priority, meta.get("priority"), "priority", path, Priority.MED),
            path=directory,
            parent=parent,
            tags=_str_list(meta.get("tags"), "tags", path),
            related=_str_list(meta.get("related"), "related", path),
            repo_path=_opt_str(meta.get("repo_path")),
            created=_date(meta.get("created"), "created", path),
            meta=meta,
        )


@dataclass
class Task:
    id: str
    project: str
    title: str
    status: TaskStatus
    priority: Priority
    path: Path  # the .md file
    tags: list[str] = field(default_factory=list)
    created: dt.date | None = None
    updated: dt.date | None = None
    due: dt.date | None = None
    subtasks_done: int = 0
    subtasks_total: int = 0
    body: str = field(default="", repr=False)
    meta: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path, project: str) -> Task:
        """Load a task file. ``project`` is taken from the containing project
        directory, not the frontmatter, so moving the file never leaves the
        task pointing at a stale project."""
        meta, body = parsing.read_markdown(path)
        id_ = _require_id(meta, path)
        done, total = parsing.count_subtasks(body)
        return cls(
            id=id_,
            project=project,
            title=parsing.first_heading(body) or str(meta.get("title") or id_),
            status=_enum(TaskStatus, meta.get("status"), "status", path, TaskStatus.TODO),
            priority=_enum(Priority, meta.get("priority"), "priority", path, Priority.MED),
            path=path,
            tags=_str_list(meta.get("tags"), "tags", path),
            created=_date(meta.get("created"), "created", path),
            updated=_date(meta.get("updated"), "updated", path),
            due=_date(meta.get("due"), "due", path),
            subtasks_done=done,
            subtasks_total=total,
            body=body,
            meta=meta,
        )


@dataclass
class Deliverable:
    id: str
    project: str
    title: str
    kind: DeliverableKind
    status: DeliverableStatus
    path: Path
    venue: str | None = None
    deadline: dt.date | None = None
    coauthors: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path, project: str) -> Deliverable:
        meta = parsing.read_yaml(path) or {}
        if not isinstance(meta, dict):
            raise ValidationError(f"{path}: expected a mapping")
        id_ = _require_id(meta, path)
        return cls(
            id=id_,
            project=project,
            title=str(meta.get("title") or id_),
            kind=_enum(DeliverableKind, meta.get("kind"), "kind", path, DeliverableKind.PAPER),
            status=_enum(
                DeliverableStatus, meta.get("status"), "status", path, DeliverableStatus.DRAFTING
            ),
            path=path,
            venue=_opt_str(meta.get("venue")),
            deadline=_date(meta.get("deadline"), "deadline", path),
            coauthors=_str_list(meta.get("coauthors"), "coauthors", path),
            meta=meta,
        )


@dataclass
class Source:
    id: str  # Better BibTeX citekey
    title: str
    type: str
    status: SourceStatus
    path: Path
    zotero_key: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    tags: list[str] = field(default_factory=list)
    added: dt.date | None = None
    body: str = field(default="", repr=False)
    meta: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path) -> Source:
        meta, body = parsing.read_markdown(path)
        id_ = _require_id(meta, path)
        year = meta.get("year")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            raise ValidationError(f"{path}: invalid year '{year}'") from None
        return cls(
            id=id_,
            title=str(meta.get("title") or id_),
            type=str(meta.get("type") or "paper"),
            status=_enum(SourceStatus, meta.get("status"), "status", path, SourceStatus.TO_READ),
            path=path,
            zotero_key=_opt_str(meta.get("zotero_key")),
            authors=_str_list(meta.get("authors"), "authors", path),
            year=year,
            tags=_str_list(meta.get("tags"), "tags", path),
            added=_date(meta.get("added"), "added", path),
            body=body,
            meta=meta,
        )


@dataclass
class Reference:
    """An entry in a project's ``references.yaml``."""

    id: str
    why: str = ""


@dataclass
class LogEntry:
    date: dt.date
    text: str
    time: dt.time | None = None


@dataclass
class Idea:
    """One unstructured line from ``inbox.md`` or a project's ``ideas.md``."""

    text: str


# --- line-oriented files ----------------------------------------------------

_LOG_RE = re.compile(
    r"^\s*[-*+]\s+(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?\s*(?::|—|–|-)?\s*(.*)$"
)


def parse_log(text: str) -> list[LogEntry]:
    """Parse ``- YYYY-MM-DD[ HH:MM]: text`` lines; anything else is ignored."""
    entries = []
    for line in text.splitlines():
        m = _LOG_RE.match(line)
        if not m:
            continue
        try:
            date = dt.date.fromisoformat(m.group(1))
            time = dt.time.fromisoformat(m.group(2).zfill(5)) if m.group(2) else None
        except ValueError:
            continue
        entries.append(LogEntry(date=date, time=time, text=m.group(3).strip()))
    return entries


_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")


def parse_ideas(text: str) -> list[Idea]:
    """Each non-blank, non-heading line is one idea (leading bullet stripped)."""
    ideas = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ideas.append(Idea(_BULLET_RE.sub("", line).strip()))
    return ideas


def parse_references(data: Any, path: Path) -> list[Reference]:
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValidationError(f"{path}: expected a list of references")
    refs = []
    for item in data:
        if isinstance(item, str):
            refs.append(Reference(item))
        elif isinstance(item, dict) and item.get("id"):
            refs.append(Reference(str(item["id"]), str(item.get("why") or "")))
        else:
            raise ValidationError(f"{path}: each reference needs an 'id'")
    return refs


# --- serialisation ----------------------------------------------------------


def to_dict(obj: Any, root: Path | None = None, *, exclude: tuple[str, ...] = ("meta",)) -> Any:
    """JSON-friendly representation. Paths are made relative to ``root``."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_dict(getattr(obj, f.name), root, exclude=exclude)
            for f in dataclasses.fields(obj)
            if f.name not in exclude
        }
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (dt.date, dt.time)):
        return obj.isoformat()
    if isinstance(obj, Path):
        if root is not None:
            try:
                return str(obj.relative_to(root))
            except ValueError:
                pass
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_dict(v, root, exclude=exclude) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v, root, exclude=exclude) for v in obj]
    return obj
