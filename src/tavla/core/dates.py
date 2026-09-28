"""Lenient date parsing for CLI-supplied dates (``--due``, ``--deadline``)."""

from __future__ import annotations

import datetime as dt
import re

from tavla.core.errors import ValidationError


def local_today() -> dt.date:
    """Today's date in the user's local timezone (dates in content files are local)."""
    return dt.datetime.now().astimezone().date()


def local_now() -> dt.datetime:
    """Current local time, minute precision, without tzinfo (as written to log.md)."""
    return dt.datetime.now().astimezone().replace(second=0, microsecond=0, tzinfo=None)


_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_RELATIVE_RE = re.compile(r"^\+(\d+)([dw])$")
# Day-first numeric dates: DD-MM-YYYY, DD/MM/YY, DD.MM.YYYY, ... (year optional).
_DMY_RE = re.compile(r"^(\d{1,2})([-/.])(\d{1,2})(?:\2(\d{2}|\d{4}))?$")
DMY_WITH_YEAR_RE = re.compile(r"^\d{1,2}([-/.])\d{1,2}\1(\d{2}|\d{4})$")
_DATE_HELP = (
    "YYYY-MM-DD, DD.MM.YYYY (or with - or /, 2-digit year, or no year), "
    "today, tomorrow, +Nd, +Nw or a weekday"
)


def parse_dmy(text: str, today: dt.date | None = None) -> dt.date | None:
    """Parse a day-first date (``31.12.2026``, ``31/12/26``, ``31-12``).

    Two-digit years mean 20YY. Without a year, the next occurrence on or after
    today is used. Returns None if ``text`` isn't in this shape; raises
    ValidationError if it is but names no real date.
    """
    m = _DMY_RE.match(text.strip())
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(3)), m.group(4)
    try:
        if year is not None:
            return dt.date(int(year) + (2000 if len(year) == 2 else 0), month, day)
        today = today or local_today()
        candidate = dt.date(today.year, month, day)
        return candidate if candidate >= today else dt.date(today.year + 1, month, day)
    except ValueError:
        raise ValidationError(f"invalid date '{text}' (no such day)") from None


def parse_date(value: str, today: dt.date | None = None) -> dt.date:
    """Accept ``YYYY-MM-DD``, a day-first date (``31.12.2026``, ``31/12/26``,
    ``31-12``; see :func:`parse_dmy`), ``today``, ``tomorrow``, ``+3d``, ``+2w``
    or a weekday name (``fri``/``friday``, meaning the next one after today)."""
    today = today or local_today()
    text = value.strip().lower()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + dt.timedelta(days=1)
    m = _RELATIVE_RE.match(text)
    if m:
        n = int(m.group(1))
        return today + dt.timedelta(days=n if m.group(2) == "d" else 7 * n)
    for i, day in enumerate(_WEEKDAYS):
        if len(text) >= 3 and (day.startswith(text) or text.startswith(day)):
            ahead = (i - today.weekday() - 1) % 7 + 1
            return today + dt.timedelta(days=ahead)
    dmy = parse_dmy(text, today)
    if dmy is not None:
        return dmy
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise ValidationError(f"invalid date '{value}' (use {_DATE_HELP})") from None
