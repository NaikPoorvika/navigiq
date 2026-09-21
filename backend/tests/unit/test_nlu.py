"""Deterministic NLU: relative dates (Python, never the LLM), time windows,
budgets, party, radius and interest/negation parsing - English, Hinglish,
romanized Kannada and Kannada script."""
from __future__ import annotations

from datetime import date

import pytest

from app.nlu.lexicon import controlled_interest, parse_interests
from app.nlu.quantities import parse_budget, parse_party, parse_radius_km, parse_stop_count
from app.nlu.timeparse import (
    next_weekday, resolve_date, resolve_duration, resolve_time_window, this_weekday,
)
from app.domain.taxonomy import PartyType

MON = date(2026, 9, 21)      # a Monday
SAT = date(2026, 9, 26)
SUN = date(2026, 9, 27)


@pytest.mark.parametrize("text,today,expected", [
    ("today", MON, MON), ("tonight", MON, MON), ("this evening", MON, MON),
    ("tomorrow", MON, date(2026, 9, 22)), ("tmrw", MON, date(2026, 9, 22)),
    ("day after tomorrow", MON, date(2026, 9, 23)), ("parso", MON, date(2026, 9, 23)),
    ("this saturday", MON, SAT), ("saturday", MON, SAT), ("on sunday", MON, SUN),
    ("next saturday", MON, date(2026, 10, 3)), ("this weekend", MON, SAT),
    ("weekend", MON, SAT), ("next weekend", MON, date(2026, 10, 3)),
    ("this weekend", SAT, SAT), ("this weekend", SUN, SUN),
    ("next saturday", SAT, date(2026, 10, 3)), ("in 3 days", MON, date(2026, 9, 24)),
    ("25 sept", MON, date(2026, 9, 25)), ("sept 25", MON, date(2026, 9, 25)),
    ("5 jan", MON, date(2027, 1, 5)), ("25/09", MON, date(2026, 9, 25)),
    ("2026-10-02", MON, date(2026, 10, 2)), ("25/12/2026", MON, date(2026, 12, 25)),
    ("aaj", MON, MON), ("kal chalte hain", MON, date(2026, 9, 22)),
    ("naale", MON, date(2026, 9, 22)), ("ivattu", MON, MON),
    ("ನಾಳೆ", MON, date(2026, 9, 22)), ("ಇವತ್ತು", MON, MON), ("ನಾಡಿದ್ದು", MON, date(2026, 9, 23)),
])
def test_relative_dates(text, today, expected):
    r = resolve_date(text, today)
    assert r is not None and r.value == expected


def test_this_and_next_weekday_rules():
    assert this_weekday(MON, 0) == MON
    assert next_weekday(MON, 0) == date(2026, 9, 28)
    assert next_weekday(SUN, 5) == date(2026, 10, 3)


@pytest.mark.parametrize("text", ["what should I do", "saturdays are fun", "plan something"])
def test_no_date_when_none_given(text):
    assert resolve_date(text, MON) is None


@pytest.mark.parametrize("text,start,end", [
    ("from 10 am to 7 pm", 600, 1140), ("10am-7pm", 600, 1140), ("10 to 6", 600, 1080),
    ("from around 11 to 8", 660, 1200), ("between 4 and 9", 960, 1260), ("4pm to 9pm", 960, 1260),
    ("10 to 7 pm", 600, 1140), ("7 to 11 at night", 1140, 1380), ("10:30 to 13:15", 630, 795),
    ("morning", 480, 720), ("evening", 990, 1260), ("tonight", 1110, 1380),
    ("full day", 540, 1140), ("kal shaam", 990, 1260), ("ಸಂಜೆ", 990, 1260),
])
def test_time_windows(text, start, end):
    tw = resolve_time_window(text)
    assert tw is not None and (tw.start_min, tw.end_min) == (start, end)


def test_date_digits_are_not_times():
    tw = resolve_time_window("2026-10-02 4pm to 9pm")
    assert (tw.start_min, tw.end_min) == (960, 1260)


def test_money_ranges_are_not_times():
    assert resolve_time_window("budget rs 500 to 800") is None


@pytest.mark.parametrize("text,minutes", [
    ("three hours", 180), ("for 3 hrs", 180), ("six hours", 360), ("half a day", 240),
    ("a couple of hours", 120), ("90 minutes", 90), ("2 ghante", 120),
])
def test_durations(text, minutes):
    assert resolve_duration(text) == minutes


@pytest.mark.parametrize("text,amount,pp", [
    ("under ₹500", 500, False), ("₹1,500", 1500, False), ("Rs. 800", 800, False),
    ("budget about 1800", 1800, False), ("1.5k budget", 1500, False), ("budget 2k", 2000, False),
    ("800 per person", 800, True), ("₹300 each", 300, True), ("1500 ka budget", 1500, False),
    ("within 1000 rupees", 1000, False),
])
def test_budgets(text, amount, pp):
    b = parse_budget(text)
    assert b is not None and b.amount == amount and b.per_person is pp


@pytest.mark.parametrize("text", ["within 90 km", "10 to 6", "four friends", "3 hours",
                                  "under 5 stops", "2 people"])
def test_non_budgets_are_not_budgets(text):
    assert parse_budget(text) is None


@pytest.mark.parametrize("text,size,ptype", [
    ("me and my girlfriend", 2, PartyType.COUPLE), ("with my wife", 2, PartyType.COUPLE),
    ("four college friends", 4, PartyType.FRIENDS), ("me and 3 friends", 4, PartyType.FRIENDS),
    ("we are 5", 5, None), ("6 people", 6, None), ("with my parents", None, PartyType.PARENTS),
    ("with kids", None, PartyType.FAMILY_WITH_KIDS), ("solo trip", 1, PartyType.SOLO),
    ("a date night", 2, PartyType.COUPLE),
])
def test_party(text, size, ptype):
    p = parse_party(text)
    assert p is not None and p.size == size and p.party_type == ptype


def test_radius_and_stop_count():
    assert parse_radius_km("places within 90 km of bengaluru") == 90.0
    assert parse_stop_count("plan 4 stops") == 4
    assert parse_stop_count("nothing") is None


@pytest.mark.parametrize("text,want,avoid", [
    ("I like nature, cafes and photography. I don't want malls.",
     {"nature", "cafe", "photography"}, {"mall"}),
    ("no malls or temples please", set(), {"mall", "temple"}),
    ("anything but temples", set(), {"temple"}),
    ("I don't want malls, just nature", {"nature"}, {"mall"}),
    ("no malls. I like temples", {"temple"}, {"mall"}),
    ("mujhe mall nahi jaana, kuch peaceful batao", {"peaceful"}, {"mall"}),
    ("mall beda, kere hatthira", {"lake"}, {"mall"}),
    ("ನಾಳೆ ಕೆರೆ ಹತ್ತಿರ ಕಾಫಿ", {"lake", "cafe"}, set()),
    ("street food in VV Puram", {"street_food"}, set()),
])
def test_interest_parsing_and_negation(text, want, avoid):
    p = parse_interests(text)
    assert want <= set(p.interests), p.matched_phrases
    assert avoid <= set(p.avoid_interests), p.matched_phrases
    assert not (set(p.interests) & set(p.avoid_interests))


def test_crowd_aversion_is_a_preference_not_an_avoided_interest():
    p = parse_interests("I don't like crowded places")
    assert p.crowd_averse and "quiet" in p.moods and not p.avoid_interests


def test_negation_does_not_leak_past_a_positive_clause():
    p = parse_interests("no crowds, I like cafes")
    assert "cafe" in p.categories and p.crowd_averse


def test_free_as_in_available_is_not_budget():
    assert "budget" not in parse_interests("Tomorrow I'm free from around 11 to 8").interests
    assert "budget" in parse_interests("free things to do").interests


def test_budget_word_with_amount_is_not_a_cheap_mood():
    assert "budget" not in parse_interests("budget about 1800").interests


@pytest.mark.parametrize("value,expected", [("cafe", "cafe"), ("Cafes", "cafe"),
                                             ("sunset", "sunset"), ("romantic", "romantic"),
                                             ("quantum physics", None)])
def test_controlled_interest(value, expected):
    assert controlled_interest(value) == expected
