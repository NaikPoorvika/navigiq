"""Multi-day trips (ADR-031): date spans, splitting, trip-level checks, day
scoping of changes. Pure functions only; the DB-backed flow is in
tests/integration/test_trips_api.py."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.assistant.extraction import rule_fields
from app.assistant.modparse import day_scope, parse_modifications
from app.assistant.state import ConversationState, LastPOI
from app.nlu.timeparse import resolve_date_range, resolve_time_window
from app.schemas.tripspec import MAX_TRIP_DAYS, TripSpec
from app.services.planning.modify import Modification, ModificationError
from app.services.planning.trips import (
    _scope, check_trip, compare_days, day_spec_for, is_trip_itinerary, split_budget,
    stops_of_day,
)

MON = date(2026, 9, 21)   # the evaluation's fixed "today" is a Monday


# --- date spans ------------------------------------------------------------------------------

@pytest.mark.parametrize("text,start,end,days", [
    ("plan a 3 day trip", None, None, 3),
    ("3-day itinerary with nature", None, None, 3),
    ("for three days", None, None, 3),
    ("do din ka plan", None, None, 2),
    ("next 3 days", MON, date(2026, 9, 23), 3),
    ("friday to sunday", date(2026, 9, 25), date(2026, 9, 27), 3),
    ("fri-sun", date(2026, 9, 25), date(2026, 9, 27), 3),
    ("sunday to tuesday", date(2026, 9, 27), date(2026, 9, 29), 3),
    ("saturday and sunday", date(2026, 9, 26), date(2026, 9, 27), 2),
    ("the whole weekend", date(2026, 9, 26), date(2026, 9, 27), 2),
    ("both days this weekend", date(2026, 9, 26), date(2026, 9, 27), 2),
    ("10 to 12 october", date(2026, 10, 10), date(2026, 10, 12), 3),
    ("oct 10 - oct 12", date(2026, 10, 10), date(2026, 10, 12), 3),
    ("Oct 30 to Nov 2", date(2026, 10, 30), date(2026, 11, 2), 4),
    ("30 oct to 2 nov", date(2026, 10, 30), date(2026, 11, 2), 4),
])
def test_date_spans(text, start, end, days):
    r = resolve_date_range(text, MON)
    assert r is not None, text
    assert (r.start, r.end, r.days) == (start, end, days)


@pytest.mark.parametrize("text", [
    "in 3 days",                        # a single date
    "3 days from now",
    "two days ago",
    "this weekend",                     # stays one day (Saturday)
    "next weekend",
    "monday and friday",                # two separate days, not a span
    "things to do day after tomorrow",  # "do" is not the Hindi "two" here
    "open 7 days a week",
    "10 to 12",                         # a time window, not dates
    "plan a day with a garden",
])
def test_not_date_spans(text):
    assert resolve_date_range(text, MON) is None


def test_whole_weekend_on_sunday_is_not_a_span():
    assert resolve_date_range("the whole weekend", date(2026, 9, 27)) is None


def test_unit_after_a_range_is_not_a_time_window():
    # regression: a stray control character made this guard never match
    assert resolve_time_window("4 to 6 people") is None
    assert resolve_time_window("10 to 12 friends") is None
    assert resolve_time_window("4 to 6 pm").start_min == 16 * 60


def test_extraction_sets_trip_dates_and_full_days():
    f, extra = rule_fields("plan a 3 day trip with gardens and museums", MON, 10 * 60)
    assert f["date"] == MON and f["end_date"] == date(2026, 9, 23)
    assert extra["has_time_info"] is True
    assert "start_time" not in f and "end_time" not in f


def test_extraction_late_in_the_day_starts_tomorrow():
    f, _ = rule_fields("a 2 day trip", MON, 17 * 60)
    assert f["date"] == date(2026, 9, 22) and f["end_date"] == date(2026, 9, 23)


def test_extraction_date_range_is_not_read_as_hours():
    f, _ = rule_fields("plan 10 to 12 october, from 9 am to 5 pm", MON, 10 * 60)
    assert (f["date"], f["end_date"]) == (date(2026, 10, 10), date(2026, 10, 12))
    assert (f["start_time"], f["end_time"]) == ("09:00", "17:00")


def test_extraction_explicit_start_and_length():
    f, _ = rule_fields("3 days starting saturday", MON, 10 * 60)
    assert (f["date"], f["end_date"]) == (date(2026, 9, 26), date(2026, 9, 28))


def test_extraction_caps_trip_length():
    f, extra = rule_fields("a 10 day holiday", MON, 10 * 60)
    assert (f["end_date"] - f["date"]).days + 1 == MAX_TRIP_DAYS
    f, extra = rule_fields("from 1 to 12 november", MON, 10 * 60)
    assert (f["end_date"] - f["date"]).days + 1 == MAX_TRIP_DAYS
    assert "limited to 7 days" in extra["notes"][0]


# --- TripSpec -------------------------------------------------------------------------------------

def test_tripspec_end_date_rules():
    s = TripSpec(date=MON, end_date=date(2026, 9, 23))
    assert s.is_trip and s.day_count == 3
    assert s.trip_dates() == [MON, date(2026, 9, 22), date(2026, 9, 23)]
    assert TripSpec(date=MON, end_date=MON).end_date is None   # one day is not a trip
    with pytest.raises(ValidationError):
        TripSpec(end_date=MON)                                  # no start
    with pytest.raises(ValidationError):
        TripSpec(date=MON, end_date=date(2026, 9, 20))          # before the start
    with pytest.raises(ValidationError):
        TripSpec(date=MON, end_date=date(2026, 9, 28))          # 8 days
    assert TripSpec(date=MON, end_date=date(2026, 9, 27)).day_count == MAX_TRIP_DAYS


def test_budget_split_never_exceeds_total():
    s = TripSpec(date=MON, end_date=date(2026, 9, 23), budget_total=1000)
    assert split_budget(s, 3) == {"budget_total": 333, "budget_per_person": None}
    s = TripSpec(date=MON, end_date=date(2026, 9, 22), budget_per_person=901)
    assert split_budget(s, 2)["budget_per_person"] == 450


def test_day_specs_spread_required_places_and_drop_end_date():
    s = TripSpec(date=MON, end_date=date(2026, 9, 22), must_include_poi_ids=[1, 2, 3],
                 budget_total=4000, must_include_names=["Somewhere"])
    d1 = day_spec_for(s, MON, 0, 2)
    d2 = day_spec_for(s, date(2026, 9, 22), 1, 2)
    assert (d1.must_include_poi_ids, d2.must_include_poi_ids) == ([1, 3], [2])
    assert d1.end_date is None and d1.budget_total == 2000 and d1.must_include_names == []
    assert d2.date == date(2026, 9, 22)


# --- trip structure ------------------------------------------------------------------------------

def stop(seq, day, day_seq, pid, name, cat="park", cost=100, arrive="10:00", depart="11:00"):
    return {"seq": seq, "day": day, "day_seq": day_seq, "arrive": arrive, "depart": depart,
            "poi": {"id": pid, "name": name, "category": cat},
            "estimated_cost": {"typical": cost}}


def trip(stops, days=2):
    return {"kind": "trip", "stops": stops,
            "days": [{"day": d, "validator": {"valid": True, "rules_run": ["X"], "findings": []}}
                     for d in range(1, days + 1)]}


STOPS = [stop(1, 1, 1, 10, "Garden"), stop(2, 1, 2, 11, "Museum", "museum"),
         stop(3, 2, 1, 12, "Lake", "lake"), stop(4, 2, 2, 13, "Cafe", "cafe"),
         stop(5, 2, 3, 14, "Temple", "temple")]


def test_is_trip_and_stops_of_day():
    it = trip(STOPS)
    assert is_trip_itinerary(it) and not is_trip_itinerary({"stops": []})
    assert [s["seq"] for s in stops_of_day(it, 2)] == [1, 2, 3]
    assert [s["poi"]["name"] for s in stops_of_day(it, 2)] == ["Lake", "Cafe", "Temple"]


def test_check_trip_catches_repeats_and_budget():
    it = trip(STOPS)
    assert check_trip(it["days"], STOPS, budget=500)["valid"]
    dup = STOPS + [stop(6, 2, 4, 10, "Garden")]
    rep = check_trip(it["days"], dup, budget=None)
    assert not rep["valid"] and rep["findings"][0]["rule"] == "DUPLICATE_ACROSS_DAYS"
    over = check_trip(it["days"], STOPS, budget=499)
    assert not over["valid"] and over["findings"][0]["rule"] == "TRIP_BUDGET_EXCEEDED"
    bad_day = trip(STOPS)
    bad_day["days"][1]["validator"] = {"valid": False, "findings": [{"rule": "VENUE_CLOSED"}]}
    rep = check_trip(bad_day["days"], STOPS, budget=None)
    assert not rep["valid"] and rep["findings"][0]["day"] == 2


def test_scope_maps_trip_wide_and_day_local_stops():
    it = trip(STOPS)
    (d, m), = _scope([Modification(op="remove_stop", target_seq=4)], it)
    assert (d, m.target_seq, m.day) == (2, 2, None)
    (d, m), = _scope([Modification(op="remove_stop", target_seq=1, day=2)], it)
    assert (d, m.target_seq) == (2, 1)
    (d, m), = _scope([Modification(op="set_pace", pace="relaxed")], it)
    assert d is None
    (d, m), = _scope([Modification(op="set_budget", amount=300, day=1)], it)
    assert d == 1
    (d, m), = _scope([Modification(op="add_poi", poi_id=99)], it)
    assert d == 1                                    # the day with fewer stops


def test_scope_rejects_bad_targets():
    it = trip(STOPS)
    with pytest.raises(ModificationError, match="no day 3"):
        _scope([Modification(op="set_pace", pace="relaxed", day=3)], it)
    with pytest.raises(ModificationError, match="no stop 9"):
        _scope([Modification(op="remove_stop", target_seq=9)], it)
    with pytest.raises(ModificationError, match="already on day 2"):
        _scope([Modification(op="add_poi", poi_id=12, day=1)], it)


def test_compare_days_reports_only_changed_days():
    a = trip(STOPS)
    b = trip(STOPS[:2] + [stop(3, 2, 1, 12, "Lake", "lake", cost=0),
                          stop(4, 2, 2, 20, "Gallery", "gallery")])
    rows = compare_days(a, b)
    assert [r["changed"] for r in rows] == [False, True]
    assert rows[1]["added"] == ["Gallery"] and set(rows[1]["removed"]) == {"Cafe", "Temple"}
    assert rows[1]["estimated_cost"]["delta"] == 200 - 400


# --- conversational day scoping ----------------------------------------------------------------

def trip_state():
    names = [("Garden", "garden"), ("Museum", "museum"), ("Lake", "lake"), ("Cafe", "cafe"),
             ("Temple", "temple")]
    return ConversationState(
        active_itinerary_id=1, active_version_no=1,
        active_stops=[LastPOI(id=10 + i, name=n, category=c) for i, (n, c) in enumerate(names)],
        active_stop_days=[1, 1, 2, 2, 2])


@pytest.mark.parametrize("text,day", [
    ("make day 2 cheaper", 2), ("make the second day more relaxed", 2),
    ("make the last day more romantic", 2), ("on day one, start later", 1),
    ("make it cheaper", None),
])
def test_day_scope(text, day):
    assert day_scope(text, trip_state())[0] == day


def test_day_scope_ignored_for_single_day_plans():
    st = trip_state()
    st.active_stop_days = [1, 1, 1, 1, 1]
    assert day_scope("make day 2 cheaper", st)[0] is None


def test_day_scoped_changes_carry_the_day_and_use_that_days_cost():
    pm = parse_modifications("make day 2 cheaper", trip_state(), current_cost=4000,
                             day_costs={1: 1000, 2: 2000})
    assert pm.operations == [{"op": "set_budget", "amount": 1500, "day": 2}]
    pm = parse_modifications("make the last day more romantic", trip_state())
    assert pm.operations == [{"op": "add_interest", "interest": "romantic", "day": 2}]
    pm = parse_modifications("make day 1 more relaxed", trip_state())
    assert pm.operations == [{"op": "set_pace", "pace": "relaxed", "day": 1}]


def test_day_scoped_stop_references_become_trip_wide_numbers():
    pm = parse_modifications("remove the first stop on day 2", trip_state())
    assert pm.operations == [{"op": "remove_stop", "target_seq": 3}]
    pm = parse_modifications("remove the cafe on day 2", trip_state())
    assert pm.operations == [{"op": "remove_stop", "target_seq": 4}]


def test_whole_trip_change_counts_stops_per_day():
    pm = parse_modifications("fewer stops please", trip_state())
    assert pm.operations[0] == {"op": "set_stop_count", "count": 2}
