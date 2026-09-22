"""Regression tests for the misses found by the held-out TripSpec splits v4 and
v5 (docs/reports/evaluation_history.md). Each case is a phrasing a user wrote
that the extractor got wrong before the fix."""
from __future__ import annotations

from datetime import date

import pytest

from app.assistant.extraction import extract_must_names
from app.nlu.lexicon import parse_interests
from app.nlu.quantities import parse_budget
from app.nlu.timeparse import resolve_date, resolve_date_range, resolve_time_window

MON = date(2026, 9, 21)


@pytest.mark.parametrize("text,start,end", [
    ("parso subah 6 baje Nandi Hills jaana hai", 6 * 60, 12 * 60),
    ("morning at 7", 7 * 60, 12 * 60),
    ("7 in the morning", 7 * 60, 12 * 60),
    ("evening 5", 17 * 60, 21 * 60),
])
def test_clock_time_with_a_day_part_is_the_start(text, start, end):
    tw = resolve_time_window(text)
    assert (tw.start_min, tw.end_min) == (start, end)


def test_day_part_alone_keeps_its_window():
    assert resolve_time_window("sunday morning coffee").start_min == 8 * 60


def test_ampersand_weekend():
    r = resolve_date_range("weekend trip - sat & sun - trekking", MON)
    assert (r.start, r.end) == (date(2026, 9, 26), date(2026, 9, 27))


@pytest.mark.parametrize("text", ["monday to wednesday next week", "next week monday to wednesday"])
def test_weekday_range_next_week(text):
    r = resolve_date_range(text, MON)
    assert (r.start, r.end) == (date(2026, 9, 28), date(2026, 9, 30))


def test_kannada_weekday():
    assert resolve_date("ee shanivara Cubbon Park", MON).value == date(2026, 9, 26)


@pytest.mark.parametrize("text,amount", [
    ("3 days, 20000 for a family of 4", 20000),
    ("a 5 day holiday from saturday, 25k", 25000),
    ("this saturday evening, rooftop dinner, 2 people, 4000", 4000),
])
def test_budgets_without_a_currency_word(text, amount):
    b = parse_budget(text)
    assert b is not None and b.amount == amount and not b.per_person


@pytest.mark.parametrize("text", ["oct 2, 2026, parks", "10 to 12, museums", "we are 150, cafe",
                                  "leaving at 6, back by 4"])
def test_numbers_that_are_not_money(text):
    assert parse_budget(text) is None


def test_negation_of_places_does_not_reach_past_the_comma():
    p = parse_interests("avoid Majestic and Shivajinagar, markets tomorrow")
    assert p.interests == ["market"] and p.avoid_interests == []
    # a list right after the negator is still one negated list
    assert parse_interests("no malls, temples").avoid_interests == ["mall", "temple"]


@pytest.mark.parametrize("text,name", [
    ("kal subah Lalbagh jaana hai, uske baad breakfast", "lalbagh"),
    ("naale beligge Cubbon Park hogona", "cubbon park"),
    ("from 12 oct to 14 oct, Nandi Hills at sunrise", "nandi hills"),
])
def test_required_place_before_a_verb_of_going(text, name):
    assert name in extract_must_names(text)


def test_a_kind_of_place_is_not_a_required_place():
    assert extract_must_names("a lake at sunset") == []
    assert extract_must_names("dosto ke saath mall jaana hai") == []


def test_heritage_and_adventure_are_categories():
    assert "heritage" in parse_interests("heritage sites and forts").interests
    assert "adventure" in parse_interests("adventure activities").interests


def test_morning_settles_the_meridiem_of_a_bare_range():
    tw = resolve_time_window("thursday morning 6 to 9, cycling around a lake")
    assert (tw.start_min, tw.end_min) == (6 * 60, 9 * 60)
    # without a day part the convention stands: 1-6 is afternoon
    assert resolve_time_window("today 2 to 7").start_min == 14 * 60


def test_kannada_night_and_hindi_saturday_spelling():
    assert resolve_time_window("ivattu raatri dinner").start_min == 18 * 60 + 30
    assert resolve_date("is shanivaar ko", MON).value == date(2026, 9, 26)


def test_friends_and_me_in_hindi():
    from app.nlu.quantities import parse_party
    assert parse_party("do dost aur main, bowling").size == 3


async def test_the_model_cannot_flip_a_wanted_interest_into_an_avoided_one():
    from app.assistant.extraction import merge_llm
    fields = {"interests": ["park", "cafe"], "avoid_interests": []}
    merge_llm(fields, {"avoid_interests": ["park", "cafe"], "interests": ["quiet"]},
              "stay away from MG Road, parks and a quiet cafe", MON, {})
    assert {"park", "cafe"} <= set(fields["interests"])
    assert fields["avoid_interests"] == []


def test_the_weekend_after_this_one():
    r = resolve_date_range("the weekend after this one, both days, heritage", MON)
    assert (r.start, r.end) == (date(2026, 10, 3), date(2026, 10, 4))
    assert resolve_date("the weekend after this one", MON).value == date(2026, 10, 3)
    # this weekend, both days, is still this weekend
    r = resolve_date_range("this weekend, both days", MON)
    assert (r.start, r.end) == (date(2026, 9, 26), date(2026, 9, 27))


def test_morning_with_only_an_end_time_starts_in_the_morning():
    tw = resolve_time_window("tomorrow morning, a walk in a big park, back home by 11")
    assert (tw.start_min, tw.end_min) == (8 * 60, 11 * 60)


def test_hindi_breakfast_word():
    from app.assistant.extraction import rule_fields
    f, _ = rule_fields("is ravivaar subah, mandir aur nashta", MON, 10 * 60)
    assert f["meal_preferences"] == ["breakfast"]


def test_a_time_range_after_a_date_is_not_a_date_range():
    # Regression (v8): "oct 9 to 6" was read as a span rolled into next year,
    # producing a 7-day trip from 9 October.
    from app.assistant.extraction import rule_fields
    f, _ = rule_fields("plan 1st oct 9 to 6, a waterfall, vegetarian food", MON, 10 * 60)
    assert f["date"] == date(2026, 10, 1) and "end_date" not in f
    assert (f["start_time"], f["end_time"]) == ("09:00", "18:00")
    assert resolve_date_range("oct 9 to 6", MON) is None
    r = resolve_date_range("oct 30 to nov 2", MON)
    assert (r.start, r.end) == (date(2026, 10, 30), date(2026, 11, 2))


def test_hindi_weekday_w_spelling():
    assert resolve_date("is shaniwar ko mandir", MON).value == date(2026, 9, 26)


def test_amount_before_max_and_party_before_a_place():
    from app.nlu.quantities import parse_party
    assert parse_budget("dinner for two in Indiranagar, 5000 max").amount == 5000
    assert parse_budget("3 stops max") is None
    assert parse_party("dinner for two in Indiranagar").size == 2
    assert parse_party("4 kids and 2 adults").size == 6
