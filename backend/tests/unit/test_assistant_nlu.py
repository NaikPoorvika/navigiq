"""Assistant NLU: intent rules on the spec's example requests (section 4),
reference resolution (104), modification parsing (58) and TripSpec
extraction with LLM-output grounding guards (39)."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from app.assistant.extraction import extract_trip_spec, extract_areas, merge_llm
from app.assistant.intents import Intent, IntentContext, classify_rules
from app.assistant.modparse import parse_modifications
from app.assistant.references import resolve_reference
from app.assistant.state import ConversationState, LastPOI
from app.llm import FakeLLM
from app.llm.service import LLMService
from app.nlu.timeparse import IST

PLAN = IntentContext(has_plan=True, has_results=True)
FRESH = IntentContext()

SPEC_EXAMPLES = [
    ("I'm bored.", Intent.MOOD_DISCOVERY), ("Surprise me.", Intent.SURPRISE_ME),
    ("Suggest something interesting.", Intent.DISCOVER),
    ("What should I do today?", Intent.DISCOVER), ("Anything fun tonight?", Intent.DISCOVER),
    ("Show me something different.", Intent.SHOW_DIFFERENT),
    ("I want to go somewhere peaceful.", Intent.DISCOVER),
    ("Something adventurous.", Intent.DISCOVER), ("Somewhere romantic.", Intent.DISCOVER),
    ("Any hidden gems?", Intent.DISCOVER), ("Something under ₹500.", Intent.DISCOVER),
    ("Cheap things to do.", Intent.DISCOVER), ("Things four college friends can do.", Intent.DISCOVER),
    ("Places to go with my parents.", Intent.DISCOVER),
    ("Where should I go with my girlfriend?", Intent.DISCOVER),
    ("Something good for photography.", Intent.DISCOVER), ("Best places for sunset.", Intent.DISCOVER),
    ("Any sunrise locations?", Intent.DISCOVER), ("Good cafes for working.", Intent.DISCOVER),
    ("Coffee around Jayanagar.", Intent.PLACE_SEARCH),
    ("Interesting places near Indiranagar.", Intent.PLACE_SEARCH),
    ("Good food around Basavanagudi.", Intent.PLACE_SEARCH),
    ("Nature places outside Bengaluru.", Intent.DISCOVER),
    ("Weekend escapes from Bengaluru.", Intent.DISCOVER),
    ("Short trips around Bangalore.", Intent.DISCOVER),
    ("Places within 90 km of Bengaluru.", Intent.DISCOVER),
    ("Something outside the city.", Intent.DISCOVER),
    ("Heritage places around Bengaluru.", Intent.DISCOVER),
    ("Temples around Bengaluru.", Intent.DISCOVER),
    ("Something indoors because it may rain.", Intent.DISCOVER),
    ("What can I do for three hours?", Intent.DISCOVER),
    ("Plan tomorrow for me.", Intent.CREATE_ITINERARY),
    ("Plan a relaxed Sunday.", Intent.CREATE_ITINERARY),
    ("I have ₹1500 and six hours.", Intent.CREATE_ITINERARY),
    ("Plan something from 10 AM to 7 PM.", Intent.CREATE_ITINERARY),
    ("Plan a date under ₹1800.", Intent.CREATE_ITINERARY),
    ("I like nature, cafes and photography.", Intent.DISCOVER),
    ("I don't want malls.", Intent.DISCOVER), ("I don't like crowded places.", Intent.DISCOVER),
    ("Tell me about Bangalore Palace.", Intent.PLACE_DETAILS),
    ("Why is Lalbagh famous?", Intent.LOCAL_KNOWLEDGE),
    ("Lalbagh vs Cubbon Park for photography.", Intent.COMPARE_PLACES),
    ("Is this place worth visiting?", Intent.PLACE_DETAILS),
    ("Show me places like this.", Intent.SHOW_SIMILAR),
    ("Give me something completely different.", Intent.SHOW_DIFFERENT),
    ("Remove the second stop.", Intent.MODIFY_ITINERARY),
    ("Replace the museum.", Intent.MODIFY_ITINERARY), ("Make this cheaper.", Intent.MODIFY_ITINERARY),
    ("Make this more romantic.", Intent.MODIFY_ITINERARY),
    ("Add somewhere for dinner.", Intent.MODIFY_ITINERARY),
    ("I'm tired, reduce the plan.", Intent.MODIFY_ITINERARY),
    ("What if my budget were ₹800?", Intent.WHAT_IF_ITINERARY),
    ("What if we start three hours later?", Intent.WHAT_IF_ITINERARY),
]


@pytest.mark.parametrize("text,intent", SPEC_EXAMPLES, ids=[t for t, _ in SPEC_EXAMPLES])
def test_spec_examples_route_correctly(text, intent):
    assert classify_rules(text, PLAN).intent == intent


def test_plan_intents_need_an_active_plan():
    assert classify_rules("Remove the second stop.", FRESH).intent != Intent.MODIFY_ITINERARY
    assert classify_rules("What if my budget were 800?", FRESH).intent != Intent.WHAT_IF_ITINERARY


def test_pending_clarification_answers():
    ctx = IntentContext(pending_clarification=True)
    for t in ("10 to 6", "you decide", "evening", "tomorrow", "₹1500"):
        assert classify_rules(t, ctx).intent == Intent.CLARIFICATION_RESPONSE


def test_greeting_and_out_of_scope():
    assert classify_rules("hi", FRESH).intent == Intent.MOOD_DISCOVERY
    assert classify_rules("write me a poem", FRESH).intent == Intent.OUT_OF_SCOPE
    assert classify_rules("best biryani in Mumbai", FRESH).intent == Intent.OUT_OF_SCOPE


def test_planetarium_is_not_a_plan():
    assert classify_rules("is the planetarium open today", FRESH).intent != Intent.CREATE_ITINERARY


# --- references --------------------------------------------------------------------------------

def _state():
    s = ConversationState()
    s.last_pois = [LastPOI(id=1, name="Quiet Cafe", category="cafe"),
                   LastPOI(id=2, name="Test Museum", category="museum"),
                   LastPOI(id=3, name="Corner Cafe", category="cafe")]
    s.active_stops = [LastPOI(id=10, name="Garden", category="garden"),
                      LastPOI(id=11, name="Museum Two", category="museum"),
                      LastPOI(id=12, name="Late Cafe", category="cafe")]
    return s


@pytest.mark.parametrize("text,poi_id", [
    ("tell me more about the second one", 2), ("the first one", 1), ("the last one", 3),
    ("what about the museum", 2), ("tell me about Corner Cafe", 3), ("option 2", 2),
])
def test_references_against_results(text, poi_id):
    r = resolve_reference(text, _state())
    assert r.status == "resolved" and r.poi.id == poi_id


def test_ambiguous_reference_asks():
    r = resolve_reference("tell me more about that cafe", _state())
    assert r.status == "ambiguous" and len(r.candidates) == 2


def test_references_against_plan_stops():
    r = resolve_reference("remove the second stop", _state(), prefer_plan=True)
    assert r.poi.id == 11 and r.seq == 2
    assert resolve_reference("replace the museum", _state(), prefer_plan=True).poi.id == 11


def test_it_uses_focus():
    s = _state()
    s.focus(LastPOI(id=2, name="Test Museum", category="museum"))
    assert resolve_reference("save it", s).poi.id == 2


def test_state_is_bounded():
    s = ConversationState()
    for i in range(500):
        s.remember_results([LastPOI(id=i, name=str(i), category="cafe")], {"x": i})
        s.note_turn("DISCOVER")
    assert len(s.shown_history) <= 80 and len(s.recent_intents) <= 8


# --- modification parsing -------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Remove the second stop.", [{"op": "remove_stop", "target_seq": 2}]),
    ("Replace the museum.", [{"op": "replace_stop", "target_seq": 2}]),
    ("replace the museum with a gallery", [{"op": "replace_stop", "target_seq": 2,
                                           "category": "gallery"}]),
    ("Make this cheaper.", [{"op": "set_budget", "amount": 450}]),
    ("What if my budget were ₹800?", [{"op": "set_budget", "amount": 800}]),
    ("Make this more romantic.", [{"op": "add_interest", "interest": "romantic"}]),
    ("Add somewhere for dinner.", [{"op": "add_meal", "meal": "dinner"}]),
    ("What if we start three hours later?", [{"op": "shift_time", "minutes": 180}]),
    ("start at 11 am", [{"op": "set_start_time", "time": "11:00"}]),
    ("end by 6 pm", [{"op": "set_end_time", "time": "18:00"}]),
    ("no more museums", [{"op": "avoid_category", "category": "museum"}]),
    ("make it indoors", [{"op": "set_indoor_preference", "preference": "indoor"}]),
])
def test_modification_parsing(text, expected):
    s = _state()
    pm = parse_modifications(text, s, current_cost=600)
    assert pm.operations[:len(expected)] == expected


def test_tired_reduces_and_relaxes():
    ops = parse_modifications("I'm tired, reduce the plan", _state()).operations
    assert {"op": "set_stop_count", "count": 2} in ops and {"op": "set_pace", "pace": "relaxed"} in ops


def test_ambiguous_stop_is_flagged():
    s = _state()
    s.active_stops.append(LastPOI(id=13, name="Other Cafe", category="cafe"))
    pm = parse_modifications("remove the cafe", s)
    assert pm.needs_target and len(pm.ambiguous_candidates) == 2 and not pm.operations


def test_all_parsed_operations_validate_against_closed_model():
    from app.services.planning.modify import Modification
    for text, _ in [("Remove the second stop.", 0), ("Make this cheaper.", 0),
                    ("Add somewhere for dinner.", 0), ("I'm tired, reduce the plan", 0),
                    ("start three hours later", 0), ("no more museums", 0)]:
        for op in parse_modifications(text, _state(), current_cost=600).operations:
            Modification.model_validate(op)


# --- extraction ------------------------------------------------------------------------------------

NOW = datetime(2026, 9, 21, 11, 5, tzinfo=IST)


async def test_rule_extraction_of_the_spec_sentence():
    ex = await extract_trip_spec(
        "Tomorrow I'm free from around 11 to 8, me and my girlfriend want something relaxed, "
        "maybe nature and a nice cafe, budget about ₹1800, preferably not malls.",
        now=NOW, use_llm=False)
    s = ex.spec
    assert s.date == date(2026, 9, 22) and (s.start_time, s.end_time) == ("11:00", "20:00")
    assert s.party_size == 2 and s.party_type.value == "couple" and s.budget_total == 1800
    assert {"nature", "cafe"} <= set(s.interests) and s.avoid_interests == ["mall"]
    assert s.pace.value == "relaxed" and s.romantic is True


def test_areas_are_names_never_coordinates():
    assert extract_areas("quiet cafe near Jayanagar") == ["jayanagar"]
    assert extract_areas("dinner in the evening") == []
    assert extract_areas("nature places near lakes") == []


def test_llm_cannot_introduce_ungrounded_numbers_or_dates():
    fields = {"interests": ["cafe"], "avoid_interests": []}
    llm = {"date_phrase": "25 December", "start_time": "09:00", "end_time": "21:00",
           "budget_amount": 5000, "party_size": 7, "interests": ["cafe", "flying_carpets", "lake"],
           "avoid_interests": ["lake"]}
    merge_llm(fields, llm, "a cafe tomorrow please", NOW.date(), {})
    assert "date" not in fields and "start_time" not in fields
    assert "budget_total" not in fields and "party_size" not in fields
    assert "flying_carpets" not in fields["interests"]
    assert "lake" not in fields["interests"]


def test_llm_grounded_values_are_accepted():
    fields = {"interests": [], "avoid_interests": []}
    llm = {"budget_amount": 1200, "party_size": 3, "start_time": "16:00"}
    merge_llm(fields, llm, "three of us, around 4, 1200 total", NOW.date(), {})
    assert fields["budget_total"] == 1200 and fields["party_size"] == 3
    assert fields["start_time"] == "16:00"


async def test_extraction_with_fake_llm_merges_and_never_breaks_on_garbage():
    svc = LLMService(FakeLLM(responses=["not json at all"]), cache_ttl_s=0)
    ex = await extract_trip_spec("plan a cafe afternoon", now=NOW, llm=svc)
    assert ex.llm_error == "LLM_MALFORMED_RESPONSE" and "cafe" in ex.spec.interests
    svc2 = LLMService(FakeLLM(responses=[json.dumps({
        "interests": ["photography", "unknown_x"], "avoid_interests": [], "areas": ["Mars Colony"],
        "must_include_names": ["Atlantis"], "party_type": "friends"})]), cache_ttl_s=0)
    ex2 = await extract_trip_spec("photography walk with friends", now=NOW, llm=svc2)
    assert "photography" in ex2.spec.interests and "unknown_x" not in ex2.spec.interests
    assert ex2.area_names == [] and ex2.must_include_names == []   # not in the user's words
    assert ex2.spec.party_type.value == "friends"
