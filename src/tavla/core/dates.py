"""Lenient date parsing for CLI-supplied dates (``--due``, ``--deadline``)."""

from __future__ import annotations

import datetime as dt
import re

from tavla.core.errors import ValidationError


def local_today() -> dt.date:
    """Today's date in the user's local timezone (dates in content files are local)."""
    return dt.datetime.now().astimezone().date()


_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_RELATIVE_RE = re.compile(r"^\+(\d+)([dw])$")


def parse_date(value: str, today: dt.date | None = None) -> dt.date:
    """Accept ``YYYY-MM-DD``, ``today``, ``tomorrow``, ``+3d``, ``+2w`` or a
    weekday name (``fri``/``friday``, meaning the next one after today)."""
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
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise ValidationError(
            f"invalid date '{value}' (use YYYY-MM-DD, today, tomorrow, +Nd, +Nw or a weekday)"
        ) from None
