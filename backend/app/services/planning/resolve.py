"""Complete a partial TripSpec for planning, recording every assumption.

A conversation can leave date or times unstated ("plan something relaxed").
Planning needs them, so defaults are applied HERE, deterministically, and
each one is returned as a human-readable assumption the UI shows as an
editable chip. Nothing is silently invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.nlu.timeparse import minute_of_day, round_up_to_quarter
from app.schemas.tripspec import TripSpec, minutes_to_hhmm

DEFAULT_START = 10 * 60
DEFAULT_END = 18 * 60
DEFAULT_SPAN = 6 * 60
LATEST_START_TODAY = 20 * 60
LATEST_END = 22 * 60 + 30
EARLIEST_START = 7 * 60


@dataclass
class Resolution:
    spec: TripSpec
    assumptions: list[str] = field(default_factory=list)


def resolve_for_planning(spec: TripSpec, now: datetime) -> Resolution:
    data = spec.model_dump()
    assumptions: list[str] = []
    today = now.date()
    now_min = minute_of_day(now)

    if spec.date is None:
        if now_min < 16 * 60:
            data["date"] = today
            assumptions.append("Planned for today")
        else:
            data["date"] = today + timedelta(days=1)
            assumptions.append("Planned for tomorrow")
    day = data["date"]
    earliest = EARLIEST_START
    if day == today:
        earliest = max(EARLIEST_START, round_up_to_quarter(now_min + 30))

    start, end = spec.start_minute, spec.end_minute
    if start is None and end is None:
        start = max(DEFAULT_START, earliest) if day != today or earliest <= DEFAULT_START \
            else earliest
        end = min(start + DEFAULT_SPAN, LATEST_END) if start > DEFAULT_START else DEFAULT_END
        if day == today and start > LATEST_START_TODAY:
            data["date"] = day = today + timedelta(days=1)
            start, end = DEFAULT_START, DEFAULT_END
            assumptions.append("It's late today, so this is planned for tomorrow")
        assumptions.append(f"Time window {minutes_to_hhmm(start)}–{minutes_to_hhmm(end)}")
    elif start is None:
        start = max(earliest if day == today else EARLIEST_START, end - DEFAULT_SPAN)
        assumptions.append(f"Starting at {minutes_to_hhmm(start)}")
    elif end is None:
        end = min(start + DEFAULT_SPAN, LATEST_END)
        assumptions.append(f"Ending around {minutes_to_hhmm(end)}")
    if end - start < 60:
        end = min(start + 60, 23 * 60 + 59)
    data["start_time"] = minutes_to_hhmm(start)
    data["end_time"] = minutes_to_hhmm(end)
    if spec.party_size is None and spec.party_type is None:
        assumptions.append("Planned for one person")
    return Resolution(TripSpec.model_validate(data), assumptions)
