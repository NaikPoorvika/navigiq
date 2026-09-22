"""NQ-029 - natural language -> TripDraft extraction.

Every test here runs against FakeLLM: no GPU, no Ollama, no network, no
database. The real-model measurements live in ai/evals/nq029/ and are a
separate, explicitly-run job - a unit suite that needed a 14B model would
just stop being run.

What is being pinned, in order:
  1. the request actually sent to the gateway (schema-constrained, t=0)
  2. what gets extracted from a well-formed answer
  3. what CANNOT get through: coordinates, unknown fields, invented enums
  4. what is refused rather than repaired: fences, prose, arrays, bad fields
  5. that every gateway failure mode reaches the caller as itself
  6. that the prompt and the code cannot silently drift apart
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from app.llm import (  # noqa: E402
    FakeLLM,
    LLMEmptyResponse,
    LLMMalformedResponse,
    LLMRequestRejected,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
)
from app.llm.extraction import (  # noqa: E402
    EXTRACTION_MAX_TOKENS,
    MAX_USER_REQUEST_CHARS,
    REASON_INVALID_JSON,
    REASON_NOT_AN_OBJECT,
    REASON_SCHEMA_INVALID,
    TripDraftExtractionFailed,
    draft_json_schema,
    extract_trip_draft,
    render_prompt,
)
from app.schemas.tripspec import Category, PlanningMode, TransportMode  # noqa: E402

# asyncio_mode = auto (pytest.ini) collects the async tests; a module-level
# asyncio mark would also be applied to the sync prompt tests below.

REQUEST = "cafe and a park near Koramangala tomorrow"


def _llm(payload) -> FakeLLM:
    """A gateway scripted to answer once with `payload`."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return FakeLLM(responses=[text])


async def _extract(payload, request: str = REQUEST):
    return await extract_trip_draft(request, gateway=_llm(payload))


# --- 1. what we ask the model for ------------------------------------------

async def test_the_call_is_schema_constrained_with_tripdrafts_own_schema():
    """Constrained decoding is the primary defence against malformed output;
    if the schema stopped being sent, everything would still pass except
    this."""
    gateway = _llm({"destination": {"name": "Mysore"}})
    await extract_trip_draft(REQUEST, gateway=gateway)

    call = gateway.generate_calls[0]
    assert call.json_schema == draft_json_schema()
    assert "properties" in call.json_schema


async def test_the_schema_sent_to_the_model_has_no_coordinate_fields():
    """The model is never even shown a place to put a lat/lon."""
    assert "lat" not in json.dumps(draft_json_schema())
    assert "lon" not in json.dumps(draft_json_schema())


async def test_extraction_is_deterministic_by_construction():
    gateway = _llm({"destination": {"name": "Mysore"}})
    await extract_trip_draft(REQUEST, gateway=gateway)

    call = gateway.generate_calls[0]
    assert call.temperature == 0.0
    assert call.seed is not None
    assert call.max_tokens == EXTRACTION_MAX_TOKENS


async def test_identical_requests_produce_identical_calls():
    calls = []
    for _ in range(2):
        gateway = _llm({"destination": {"name": "Mysore"}})
        await extract_trip_draft(REQUEST, gateway=gateway)
        calls.append(gateway.generate_calls[0])
    assert calls[0] == calls[1]


async def test_the_user_text_is_sent_as_a_user_message_not_spliced_in():
    """Keeping the request out of the system prompt is what stops a user
    sentence from being read as instructions."""
    gateway = _llm({"destination": {"name": "Mysore"}})
    await extract_trip_draft(REQUEST, gateway=gateway)

    roles = [m.role for m in gateway.generate_calls[0].messages]
    assert roles == ["system", "user"]
    assert gateway.generate_calls[0].messages[1].content == REQUEST
    assert REQUEST not in gateway.generate_calls[0].messages[0].content


# --- 2. extraction from a well-formed answer --------------------------------

async def test_a_full_request_is_extracted():
    result = await _extract({
        "origin": {"name": "Indiranagar"},
        "destination": {"name": "Jayanagar"},
        "date_phrase": "Saturday",
        "start_time_local": "09:00",
        "end_time_local": "20:00",
        "party_size": 2,
        "budget_inr": 1500,
        "interests": [{"category": "cafe"}, {"category": "park"}],
        "free_text_interests": ["street photography"],
        "transport": ["auto"],
        "vegetarian": True,
        "max_walking_km": 5,
        "days": 2,
        "mode": "relaxed",
    })
    draft = result.draft
    assert draft.origin.name == "Indiranagar"
    assert draft.destination.name == "Jayanagar"
    assert draft.date_phrase == "Saturday"
    assert draft.start_time_local == "09:00"
    assert draft.party_size == 2
    assert draft.budget_inr == 1500
    assert [i.category for i in draft.interests] == [
        Category.CAFE, Category.PARK]
    assert draft.free_text_interests == ["street photography"]
    assert draft.transport == [TransportMode.AUTO]
    assert draft.vegetarian is True
    assert draft.mode is PlanningMode.RELAXED


async def test_a_sparse_request_stays_sparse():
    """Omission is the correct answer to silence. Nothing may be filled in
    on the way through - a guessed field is a question the user never got
    asked."""
    result = await _extract({"destination": {"name": "Mysore"}})
    draft = result.draft
    assert draft.destination.name == "Mysore"
    assert draft.origin is None
    assert draft.date_phrase is None
    assert draft.start_time_local is None
    assert draft.end_time_local is None
    assert draft.party_size is None
    assert draft.budget_inr is None
    assert draft.vegetarian is None
    assert draft.mode is None
    assert draft.interests == []
    assert draft.free_text_interests == []
    assert draft.transport == []


async def test_an_empty_object_is_a_valid_extraction_not_an_error():
    """"hello" is a real thing a user types. An empty draft is the honest
    result; draft_builder turns it into clarifying questions."""
    result = await _extract({}, request="hello")
    assert result.draft.origin is None
    assert result.draft.interests == []


async def test_provenance_is_reported():
    result = await _extract({"destination": {"name": "Mysore"}})
    assert result.model == "fake-generation"
    assert result.prompt_version == "v1"
    assert result.attempts == 1
    assert result.completion_tokens > 0


# --- 3. what cannot get through ---------------------------------------------

async def test_hallucinated_coordinates_never_survive():
    """ADR-002. The model inventing 12.97/77.64 must not reach planning."""
    result = await _extract({
        "origin": {"name": "Koramangala", "lat": 12.9352, "lon": 77.6245},
    })
    assert result.draft.origin.name == "Koramangala"
    assert not hasattr(result.draft.origin, "lat")
    assert result.draft.origin.model_dump() == {"name": "Koramangala"}


async def test_a_resolved_date_is_not_a_field_the_model_can_set():
    """The model answering "2026-09-23" for "tomorrow" must not become a
    date on the draft - date resolution stays in resolve_date_phrase()."""
    result = await _extract({
        "date_phrase": "tomorrow", "date": "2026-09-23"})
    assert result.draft.date_phrase == "tomorrow"
    assert "date" not in result.draft.model_dump()


async def test_invented_fields_are_dropped():
    result = await _extract({
        "destination": {"name": "Mysore"},
        "rating": 5, "confidence": 0.9, "reasoning": "the user wants a trip",
    })
    dumped = result.draft.model_dump()
    assert "rating" not in dumped
    assert "confidence" not in dumped
    assert "reasoning" not in dumped


@pytest.mark.parametrize("payload,field", [
    ({"interests": [{"category": "rooftop_hookah_lounge"}]}, "interests"),
    ({"transport": ["helicopter"]}, "transport"),
    ({"mode": "leisurely"}, "mode"),
])
async def test_invented_enum_values_are_refused_not_coerced(payload, field):
    """The Category enum is closed on purpose (tripspec.py). A near-miss
    must fail loudly, not be snapped to the nearest real value."""
    with pytest.raises(TripDraftExtractionFailed) as exc_info:
        await _extract(payload)
    assert exc_info.value.reason == REASON_SCHEMA_INVALID
    assert any(d.startswith(field) for d in exc_info.value.details)


@pytest.mark.parametrize("bad_time", ["9:00", "9am", "09:00:00", "25:00",
                                      "09:60", "morning"])
async def test_malformed_times_are_refused(bad_time):
    """ADR-015's strict HH:MM. A loose time here would fail later and more
    confusingly, inside TripSpec construction."""
    with pytest.raises(TripDraftExtractionFailed) as exc_info:
        await _extract({"start_time_local": bad_time})
    assert exc_info.value.reason == REASON_SCHEMA_INVALID
    assert any(d.startswith("start_time_local")
               for d in exc_info.value.details)


async def test_out_of_range_values_are_refused():
    with pytest.raises(TripDraftExtractionFailed) as exc_info:
        await _extract({"party_size": 400})
    assert exc_info.value.reason == REASON_SCHEMA_INVALID


async def test_free_text_overflow_is_refused():
    """ADR-015 bounds this to 10 entries. A model dumping everything here
    instead of mapping categories is doing the task wrong, and that must be
    visible rather than silently truncated."""
    with pytest.raises(TripDraftExtractionFailed) as exc_info:
        await _extract({"free_text_interests": [f"thing {i}" for i in range(11)]})
    assert exc_info.value.reason == REASON_SCHEMA_INVALID


# --- 4. refused, not repaired ------------------------------------------------

@pytest.mark.parametrize("text,reason", [
    ('```json\n{"destination": {"name": "Mysore"}}\n```', REASON_INVALID_JSON),
    ('Sure! Here is the draft:\n{"destination": {"name": "Mysore"}}',
     REASON_INVALID_JSON),
    ('{"destination": {"name": "Mysore"}', REASON_INVALID_JSON),
    ("not json at all", REASON_INVALID_JSON),
    ('[{"destination": {"name": "Mysore"}}]', REASON_NOT_AN_OBJECT),
    ('"a string"', REASON_NOT_AN_OBJECT),
    ("42", REASON_NOT_AN_OBJECT),
])
async def test_unusable_answers_are_refused_with_a_reason(text, reason):
    """Deliberately NO fence-stripping and no brace-hunting. Repairing here
    would hide a prompt regression behind a passing test; the eval counts
    these instead."""
    with pytest.raises(TripDraftExtractionFailed) as exc_info:
        await _extract(text)
    assert exc_info.value.reason == reason


async def test_failures_never_echo_model_or_user_text():
    """The message and details are logged and returned over HTTP, so they
    must not carry the user's sentence or the model's prose back out."""
    secret = "Ravi Kumar, 9876543210, Flat 4B"
    with pytest.raises(TripDraftExtractionFailed) as exc_info:
        await extract_trip_draft(
            f"plan something for {secret}",
            gateway=_llm(f"I cannot help with {secret}"))

    blob = " ".join([exc_info.value.message, *exc_info.value.details])
    assert "Ravi" not in blob
    assert "9876543210" not in blob


async def test_extraction_failure_is_an_llm_error_with_a_stable_code():
    from app.llm import LLMError
    with pytest.raises(LLMError) as exc_info:
        await _extract("not json")
    assert exc_info.value.code == "TRIPDRAFT_EXTRACTION_FAILED"
    assert exc_info.value.retryable is False


# --- 5. gateway failures reach the caller as themselves ---------------------

@pytest.mark.parametrize("error", [
    LLMUnavailable("ollama is down"),
    LLMTimeout("took too long"),
    LLMRequestRejected("bad request", status_code=400),
    LLMMalformedResponse("no message.content"),
    LLMEmptyResponse("empty"),
    LLMTruncated("hit the cap"),
])
async def test_gateway_failures_are_not_swallowed_or_rewrapped(error):
    """A truncated or empty response must never be parsed as a draft, and
    must not arrive as a generic error either - the caller branches on the
    specific type."""
    gateway = FakeLLM(responses=[error])
    with pytest.raises(type(error)):
        await extract_trip_draft(REQUEST, gateway=gateway)


async def test_a_truncated_answer_is_never_partially_parsed():
    """Real truncation produces JSON that is valid up to the cut. The
    gateway raises before this module ever sees it (NQ-028); nothing here
    may reconstruct the rest."""
    gateway = FakeLLM(responses=[LLMTruncated("hit the cap")])
    with pytest.raises(LLMTruncated):
        await extract_trip_draft(REQUEST, gateway=gateway)


# --- input guards -------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "   ", "\n\t "])
async def test_empty_requests_are_rejected_before_the_model_is_called(bad):
    gateway = _llm({})
    with pytest.raises(ValueError):
        await extract_trip_draft(bad, gateway=gateway)
    assert gateway.generate_calls == [], "no model call may have been made"


async def test_oversized_requests_are_rejected_before_the_model_is_called():
    gateway = _llm({})
    with pytest.raises(ValueError):
        await extract_trip_draft("x" * (MAX_USER_REQUEST_CHARS + 1),
                                 gateway=gateway)
    assert gateway.generate_calls == []


async def test_non_string_requests_are_a_type_error():
    with pytest.raises(TypeError):
        await extract_trip_draft({"text": "hi"}, gateway=_llm({}))


# --- 6. the prompt and the code cannot drift apart ---------------------------

def test_every_category_value_is_offered_to_the_model():
    """A category added to the enum without the prompt being updated is a
    value the model is never told about. Injection makes that impossible;
    this proves the injection happened."""
    prompt = render_prompt()
    for category in Category:
        assert category.value in prompt, category.value


def test_every_transport_and_planning_value_is_offered_to_the_model():
    prompt = render_prompt()
    for mode in TransportMode:
        assert mode.value in prompt, mode.value
    for mode in PlanningMode:
        assert mode.value in prompt, mode.value


def test_the_prompt_has_no_unrendered_placeholders():
    prompt = render_prompt()
    assert "{categories}" not in prompt
    assert "{transport_modes}" not in prompt
    assert "{planning_modes}" not in prompt


def test_the_prompt_never_shows_the_model_a_coordinate():
    """A latitude anywhere in the prompt - even in a counter-example - is a
    coordinate the model has seen in context and may echo."""
    prompt = render_prompt()
    assert not re.search(r"\b1[23]\.\d{3,}\b", prompt), \
        "the prompt contains something shaped like a Bengaluru latitude"


# Every date phrase the prompt tells the model is understood. If
# resolve_date_phrase() ever stops accepting one of these, the prompt is
# advertising a phrase that will become a clarifying question instead of a
# date - silent drift between the prompt and the resolver, which is exactly
# what ADR-015 pinned for the schema docstring.
PROMPT_ADVERTISED_PHRASES = [
    "today", "tonight", "tomorrow", "day after tomorrow",
    "weekend", "this weekend",
    "Monday", "next Saturday", "coming Friday", "sat",
    "2026-10-01",
]


@pytest.mark.parametrize("phrase", PROMPT_ADVERTISED_PHRASES)
def test_prompt_date_vocabulary_matches_the_resolver(phrase):
    from datetime import date

    from app.services.planning.draft_builder import resolve_date_phrase
    assert resolve_date_phrase(phrase, date(2026, 9, 21)) is not None, (
        f"the extraction prompt tells the model {phrase!r} is understood, "
        f"but resolve_date_phrase() returns None for it")


@pytest.mark.parametrize("phrase", PROMPT_ADVERTISED_PHRASES)
def test_the_prompt_actually_names_each_phrase_it_is_credited_with(phrase):
    """Guards the other direction: this list must describe the real prompt,
    not a prompt someone remembers writing. An ISO date is advertised as a
    form rather than as a literal example, so it matches on the form."""
    prompt = render_prompt().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", phrase):
        assert "yyyy-mm-dd" in prompt
    else:
        assert phrase.lower() in prompt, phrase
