"""NQ-032 - the facts an explanation is allowed to use.

The model writes the sentences; every name, time, number and price in them
must already be here. A fact block is built from a plan that has been
through the optimizer AND the validator, so each value in it was checked
before it was allowed near the model (ADR-002).

Nothing else is passed to the model. There is no database handle, no search,
no "and here is the itinerary as JSON" - if a fact is not in the block, the
model has no way to state it, and the entailment check refuses any number
that isn't.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class StopFact:
    seq: int
    name: str
    category: str
    arrive: str
    depart: str
    visit_minutes: int
    cost_inr: int
    cost_is_estimate: bool
    hours_verified: bool | None
    travel_minutes_from_prev: int
    mode_from_prev: str | None


@dataclass(frozen=True)
class FactBlock:
    date: str
    origin: str
    start: str
    end: str
    party_size: int
    budget_inr: int | None
    stops: tuple[StopFact, ...]
    total_cost_inr: int
    total_duration_min: int
    total_walk_m: int
    weather: str | None
    temperature_c: int | None
    not_included: tuple[str, ...] = field(default_factory=tuple)

    def to_prompt(self) -> str:
        """The block as text, which is all the model ever sees of the plan."""
        lines = [
            f"DATE: {self.date}",
            f"START: {self.origin} at {self.start}",
            f"END BY: {self.end}",
            f"PEOPLE: {self.party_size}",
        ]
        if self.budget_inr is not None:
            lines.append(f"BUDGET: {self.budget_inr} rupees")
        if self.weather:
            temp = f", {self.temperature_c} degrees" if self.temperature_c is not None else ""
            lines.append(f"WEATHER: {self.weather}{temp}")

        lines.append("STOPS:")
        for s in self.stops:
            travel = (f"{s.travel_minutes_from_prev} min by {s.mode_from_prev}"
                      if s.mode_from_prev else "start")
            cost = ("free" if s.cost_inr == 0
                    else f"about {s.cost_inr} rupees (typical for the category)"
                    if s.cost_is_estimate else f"{s.cost_inr} rupees")
            hours = "" if s.hours_verified is not False else ", opening hours not confirmed"
            lines.append(
                f"  {s.seq}. {s.name} ({s.category}) - arrive {s.arrive}, leave {s.depart}, "
                f"{s.visit_minutes} min there, {travel}, {cost}{hours}")

        lines.append(f"TOTALS: {len(self.stops)} stops, {self.total_duration_min} minutes, "
                     f"about {self.total_cost_inr} rupees, {self.total_walk_m} m walking")
        if self.not_included:
            lines.append(f"ASKED FOR BUT NOT INCLUDED: {', '.join(self.not_included)}")
        return "\n".join(lines)

    def allowed_numbers(self) -> set[str]:
        """Every number the model may write. Anything else is refused."""
        allowed: set[str] = set()

        def add(value) -> None:
            allowed.add(str(value))

        add(self.party_size)
        add(len(self.stops))
        add(self.total_cost_inr)
        add(self.total_duration_min)
        add(self.total_walk_m)
        add(self.total_duration_min // 60)          # "about 2 hours"
        if self.budget_inr is not None:
            add(self.budget_inr)
        if self.temperature_c is not None:
            add(self.temperature_c)
        allowed.update({self.start, self.end})
        allowed.update({p for t in (self.start, self.end) for p in t.split(":")})

        for s in self.stops:
            add(s.seq)
            add(s.visit_minutes)
            add(s.cost_inr)
            add(s.travel_minutes_from_prev)
            allowed.update({s.arrive, s.depart})
            allowed.update({p for t in (s.arrive, s.depart) for p in t.split(":")})

        # Dates appear as written, and their parts.
        allowed.add(self.date)
        allowed.update(self.date.split("-"))
        return allowed


def build_facts(plan: dict, spec: dict) -> FactBlock:
    """A fact block from a planned trip. Values are copied, never recomputed:
    a number the model states must be one the validator already accepted."""
    it = plan["itinerary"]
    weather = plan.get("weather") or {}
    planned = {s["category"] for s in it["stops"]}

    return FactBlock(
        date=spec["date"],
        origin=it["origin"].get("name") or "your starting point",
        start=spec["start_time_local"],
        end=spec["end_time_local"],
        party_size=spec.get("party_size", 1),
        budget_inr=spec.get("budget_inr"),
        stops=tuple(
            StopFact(
                seq=s["seq"], name=s["name"], category=s["category"],
                arrive=hhmm(s["arrive_min"]), depart=hhmm(s["depart_min"]),
                visit_minutes=s["visit_minutes"], cost_inr=s["cost_inr"],
                cost_is_estimate=s.get("cost_basis") != "poi_specific",
                hours_verified=s.get("hours_verified"),
                travel_minutes_from_prev=s.get("travel_minutes_from_prev", 0),
                mode_from_prev=s.get("mode_from_prev"),
            )
            for s in it["stops"]
        ),
        total_cost_inr=it["total_cost_inr"],
        total_duration_min=it["total_duration_min"],
        total_walk_m=it["total_walk_m"],
        weather=weather.get("condition") if weather.get("available") else None,
        temperature_c=(round(weather["mean_temp_c"])
                       if weather.get("available") and weather.get("mean_temp_c") is not None
                       else None),
        not_included=tuple(i["category"] for i in spec.get("interests", [])
                           if i["category"] not in planned),
    )


def plain_summary(facts: FactBlock) -> str:
    """A true sentence built from the facts alone.

    Used when the model is unavailable, or says something the facts don't
    support. It is dull, and it is never wrong.
    """
    if not facts.stops:
        return "No stops fitted this trip."
    names = [s.name for s in facts.stops]
    listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    cost = ("nothing" if facts.total_cost_inr == 0
            else f"about {facts.total_cost_inr} rupees")
    return (f"{len(facts.stops)} stops from {facts.origin}, starting {facts.start}: "
            f"{listed}. About {facts.total_duration_min} minutes altogether, "
            f"{cost}, with {facts.total_walk_m} m of walking.")