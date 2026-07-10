"""Wall-clock helpers pinned to the school's timezone.

A session's ``session_date``, ``start_time`` and ``end_time`` are *wall-clock* values — what a
teacher reads off a timetable — not instants. They must therefore all be derived from one clock.

They previously were not. ``start_workflow_session`` used ``datetime.now()`` (machine-local) while
``end_workflow_session`` used a UTC clock, so on any host ahead of UTC an empty-payload close
produced ``end_time < start_time``. The close path clamped that back to ``start_time``, silently
recording **zero-duration sessions** instead of raising. Reading "today" from the machine clock had
the same class of problem: a server running in UTC flips date at a different moment than the school.

Audit rows, ``created_at``/``updated_at`` and ``closed_at`` are instants, not wall-clock, and
correctly stay UTC. Do not route those through here.

The timezone is read from config on every call so tests can monkeypatch it.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import config as app_config

_UTC = ZoneInfo("UTC")


def school_zone() -> ZoneInfo:
    """The configured school timezone, falling back to UTC if it is missing or misspelled."""
    name = str(getattr(app_config, "SCHOOL_TIMEZONE", "") or "").strip()
    if not name:
        return _UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # A bad TZ name must not take the app down; UTC keeps start/end mutually consistent.
        return _UTC


def school_now() -> datetime:
    """Current wall-clock time at the school, naive so it matches the stored columns."""
    return datetime.now(school_zone()).replace(tzinfo=None)


def school_today() -> date:
    """Today's date at the school, which is not necessarily the server's date."""
    return school_now().date()
