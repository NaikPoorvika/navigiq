"""Turn an LLM-produced TripDraft into a validated TripSpec.

Deterministic. No model is called here. This is the boundary where words
become facts:
  place names   -> gazetteer (places + pois), never the model
  date phrases  -> Python, never the model
  missing info  -> a clarifying question, never a guess

At most MAX_CLARIFICATIONS questions are returned, most important first, so
the user is not interrogated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.trip_draft import TripDraft
from app.schemas.tripspec import TripSpec
from app.services.places.resolver import resolve_place

IST = ZoneInfo("Asia/Kolkata")
MAX_CLARIFICATIONS = 2
DEFAULT_TRIP_HOURS = 5
LATEST_END = "22:00"
DEFAULT_TRANSPORT = ["walking", "auto"]

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}


@dataclass
class Clarification:
    field: str
    question: str
    options: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"field": self.field, "question": self.question,
                "options": self.options}


@dataclass
class BuildResult:
    tripspec: TripSpec | None
    clarifications: list[Clarification] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
        # What was resolved before any question stopped the build: dates,
    # times, party size. A UI showing the draft for correction needs these
    # even when the draft is incomplete, or it has to re-resolve them
    # itself and the two answers drift apart.
    resolved: dict = field(default_factory=dict)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarifications)

    def to_dict(self) -> dict:
        return {
            "needs_clarification": self.needs_clarification,
            "clarifications": [c.to_dict()
                               for c in self.clarifications[:MAX_CLARIFICATIONS]],
            "assumptions": self.assumptions,
            "resolved": self.resolved,
            "tripspec": (self.tripspec.model_dump(mode="json")
                         if self.tripspec else None),
        }


def resolve_date_phrase(phrase: str, today: date) -> date | None:
    """Relative dates are resolved HERE, never by the model.

    'saturday' / 'this saturday'  -> the coming Saturday, today if it is one
    'next saturday'               -> the coming Saturday, never today
    """
    p = phrase.strip().lower()
    if p in ("today", "tonight"):
        return today
    if p == "tomorrow":
        return today + timedelta(days=1)
    if p in ("day after tomorrow", "day after"):
        return today + timedelta(days=2)
    if p in ("this weekend", "weekend"):
        p = "saturday"

    skip_today = p.startswith("next ")
    for prefix in ("this ", "next ", "coming "):
        if p.startswith(prefix):
            p = p[len(prefix):]

    if p in WEEKDAYS:
        ahead = (WEEKDAYS[p] - today.weekday()) % 7
        if ahead == 0 and skip_today:
            ahead = 7
        return today + timedelta(days=ahead)

    try:
        return date.fromisoformat(p)
    except ValueError:
        return None


def _hhmm_to_min(v: str) -> int:
    h, m = v.split(":")
    return int(h) * 60 + int(m)


def _min_to_hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


async def _resolve(db, ref, field_name, result, required):
    """Resolve a place name, recording a question or an assumption."""
    if ref is None:
        if required:
            result.clarifications.append(Clarification(
                field_name, "Where will you be starting from?"))
        return None

    r = await resolve_place(db, ref.name)
    if r.match is None:
        result.clarifications.append(Clarification(
            field_name, f"I couldn't find '{ref.name}'. Could you give a "
                        f"nearby landmark or neighbourhood?"))
        return None

    if r.needs_clarification:
        options = [r.match.to_dict()] + [a.to_dict() for a in r.alternatives[:3]]
        result.clarifications.append(Clarification(
            field_name, f"There's more than one '{ref.name}'. Which one?",
            options))
        return None

    if r.confidence == "medium":
        result.assumptions.append(
            f"Took '{ref.name}' to mean {r.match.name} ({r.match.kind}).")

    return {"name": r.match.name, "lat": r.match.lat, "lon": r.match.lon}


async def build_tripspec(
    db: AsyncSession, draft: TripDraft, now: datetime | None = None,
) -> BuildResult:
    now = now or datetime.now(IST)
    today = now.date()
    result = BuildResult(tripspec=None)

    # --- places: most important question first -------------------------
    origin = await _resolve(db, draft.origin, "origin", result, required=True)
    destination = await _resolve(db, draft.destination, "destination",
                                 result, required=False)

    # --- interests: no sane default ---------------------------------------
    if not draft.interests:
        result.clarifications.append(Clarification(
            "interests", "What would you like to do - food, sightseeing, "
                         "parks, shopping?"))

    # --- date ---------------------------------------------------------------
    if draft.date_phrase:
        trip_date = resolve_date_phrase(draft.date_phrase, today)
        if trip_date is None:
            result.clarifications.append(Clarification(
                "date", f"Which day did you mean by '{draft.date_phrase}'?"))
        elif trip_date < today:
            result.clarifications.append(Clarification(
                "date", f"{trip_date} has already passed. Which day?"))
    else:
        # Today if at least two hours remain before 22:00, otherwise tomorrow.
        minutes_now = now.hour * 60 + now.minute
        trip_date = (today if _hhmm_to_min(LATEST_END) - minutes_now >= 120
                     else today + timedelta(days=1))
        result.assumptions.append(f"Planning for {trip_date.isoformat()}.")

    # --- times --------------------------------------------------------------
    if draft.start_time_local:
        start = draft.start_time_local
    elif trip_date == today:
        rounded = ((now.hour * 60 + now.minute) // 30 + 1) * 30
        start = _min_to_hhmm(min(rounded, _hhmm_to_min(LATEST_END) - 60))
        result.assumptions.append(f"Starting at {start}.")
    else:
        start = "10:00"
        result.assumptions.append("Starting at 10:00.")

    if draft.end_time_local:
        end = draft.end_time_local
    else:
        end_min = min(_hhmm_to_min(start) + DEFAULT_TRIP_HOURS * 60,
                      _hhmm_to_min(LATEST_END))
        end = _min_to_hhmm(end_min)
        result.assumptions.append(f"Ending by {end}.")

    result.resolved = {
        "origin": origin,
        "destination": destination,
        "date": trip_date.isoformat() if trip_date else None,
        "start_time_local": start,
        "end_time_local": end,
        "party_size": draft.party_size or 1,
        "budget_inr": draft.budget_inr,
        "vegetarian": bool(draft.vegetarian),
    }

    if result.clarifications:
        return result

    # --- assemble and validate ---------------------------------------------
    try:
        result.tripspec = TripSpec(
            origin=origin,
            destination=destination,
            date=trip_date,
            start_time_local=start,
            end_time_local=end,
            days=draft.days or 1,
            budget_inr=draft.budget_inr,
            party_size=draft.party_size or 1,
            interests=[i.model_dump() for i in draft.interests],
            free_text_interests=draft.free_text_interests,
            transport=draft.transport or DEFAULT_TRANSPORT,
            constraints={
                "max_walking_km": (draft.max_walking_km
                                   if draft.max_walking_km is not None else 3.0),
                "vegetarian": bool(draft.vegetarian),
            },
            mode=draft.mode or "balanced",
            source="llm",
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        result.clarifications.append(Clarification(
            ".".join(str(p) for p in first["loc"]) or "request",
            f"Something doesn't fit: {first['msg']}"))

    return result