"""The eight NQ-027 task classes.

Each class pairs a prompt with the checks that decide whether a response was
usable. Two things are kept strictly apart:

  validity  - could the deterministic layer consume this at all?
  accuracy  - did it say the right thing?

They are not the same measurement and conflating them is how a model that
reliably emits well-formed nonsense looks good. A 1b model was observed
during design emitting a schema-valid TripSpec that had quietly dropped
party_size; it would have scored 100% on validity alone.

GROUNDING RULE (ADR-002). No prompt asks a model to supply a coordinate from
memory. Coordinates arrive in the prompt as a gazetteer block and the model
must copy the right one. The product will work the same way: the LLM is not
authoritative for anything numeric, so a benchmark that rewards it for
recalling coordinates would be measuring a capability the architecture
forbids using.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schemas import (
    TOOL_REGISTRY,
    Category,
    ClarifyQuestion,
    IntentClassification,
    ToolCall,
    TripSpec,
    tripspec_schema,
)
from .validity import Judgement, ungrounded_numbers

CASES_DIR = Path(__file__).parent / "cases"

CATEGORY_VALUES = sorted(c.value for c in Category)

# Fixed so relative dates ("this Saturday") resolve identically on every run.
# A benchmark whose gold answers move with the calendar is not reproducible.
REFERENCE_DATE = "2026-10-01"
REFERENCE_WEEKDAY = "Thursday"


# --- task definition ------------------------------------------------------

@dataclass(frozen=True)
class TaskClass:
    id: str
    description: str
    expects_json: bool
    num_predict: int
    latency_budget_ms: int | None
    build_messages: Callable[[dict], list[dict]]
    schema: dict | None = None
    schema_validator: Callable[[Any], None] | None = None
    task_check: Callable[[str, Any], tuple[bool, str]] | None = None
    score: Callable[[dict, Judgement], tuple[float, dict]] | None = None
    # Prompt variant used when structured output is switched off, so the
    # schema-vs-no-schema comparison changes one variable, not two.
    build_messages_unconstrained: Callable[[dict], list[dict]] | None = None

    def messages_for(self, case: dict, *, constrained: bool) -> list[dict]:
        if not constrained and self.build_messages_unconstrained is not None:
            return self.build_messages_unconstrained(case)
        return self.build_messages(case)


def load_cases(name: str) -> list[dict]:
    with (CASES_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# --- shared helpers -------------------------------------------------------

def _gazetteer_block(case: dict) -> str:
    """Coordinates the model may use. Copying, not recall."""
    lines = [f"  {p['name']}: lat={p['lat']}, lon={p['lon']}"
             for p in case.get("gazetteer", [])]
    return "\n".join(lines) if lines else "  (none supplied)"


def _facts_block(case: dict) -> str:
    return json.dumps(case["facts"], indent=2, ensure_ascii=False)


def _grounded_text_check(min_chars: int, max_chars: int,
                         facts_key: str = "facts",
                         allow_key: str = "allowed_numbers"):
    """Build a task_check for a free-text class.

    Free text has no schema to fail, so without a check of its own every
    non-empty string would count as a success - which is precisely how a
    free-text task class becomes meaningless. Three things are required:
    a plausible length, no refusal, and no invented numbers.
    """
    def check_factory(case: dict):
        def check(text: str, _payload) -> tuple[bool, str]:
            n = len(text)
            if n < min_chars:
                return False, f"too short: {n} chars < {min_chars}"
            if n > max_chars:
                return False, f"too long: {n} chars > {max_chars}"

            lowered = text.lower()
            for refusal in ("i cannot", "i can't", "i am unable",
                            "as an ai", "i do not have access"):
                if refusal in lowered:
                    return False, f"refusal: {refusal!r}"

            source = case.get(facts_key)
            if source is None:
                raise KeyError(
                    f"case {case.get('id')!r} has no {facts_key!r} to ground "
                    f"against; the check would reject every number in the "
                    f"answer")
            facts = json.dumps(source, ensure_ascii=False)
            allow = set(case.get(allow_key, []))
            invented = ungrounded_numbers(text, facts, allow=allow)
            if invented:
                return False, ("ungrounded numbers (ADR-002): "
                               + ", ".join(sorted(invented)))
            return True, ""
        return check
    return check_factory


def _mention_score(case: dict, judgement: Judgement) -> tuple[float, dict]:
    """Fraction of the required facts the answer actually restates."""
    must = case["gold"].get("must_mention", [])
    if not must:
        return 1.0, {"note": "no required mentions"}
    text = judgement.cleaned_text.lower()
    hits = [m for m in must if str(m).lower() in text]
    return len(hits) / len(must), {
        "matched": hits,
        "missed": [m for m in must if m not in hits],
    }


# --- 1. intent_classify ---------------------------------------------------

_INTENT_SYS = (
    "You classify a NavigIQ user message into exactly one intent.\n"
    "Intents:\n"
    "  plan_trip        - wants a new itinerary built\n"
    "  modify_trip      - wants an existing itinerary changed\n"
    "  explain_itinerary- asks why the plan is the way it is\n"
    "  reroute          - something went wrong en route; wants a new route\n"
    "  poi_question     - a factual question about a place\n"
    "  out_of_scope     - anything NavigIQ does not do (flights, hotels, "
    "bus routes, live traffic, anything outside trip planning)\n"
    "Reply with JSON only: {\"intent\": ..., \"confidence\": 0.0-1.0}"
)


def _intent_messages(case: dict) -> list[dict]:
    return [{"role": "system", "content": _INTENT_SYS},
            {"role": "user", "content": case["utterance"]}]


def _intent_score(case: dict, judgement: Judgement) -> tuple[float, dict]:
    got = (judgement.payload or {}).get("intent")
    want = case["gold"]["intent"]
    return (1.0 if got == want else 0.0), {"got": got, "want": want}


INTENT_CLASSIFY = TaskClass(
    id="intent_classify",
    description="Route a user message to a handler.",
    expects_json=True,
    num_predict=200,
    latency_budget_ms=2000,
    build_messages=_intent_messages,
    schema=IntentClassification.model_json_schema(),
    schema_validator=IntentClassification.model_validate,
    score=_intent_score,
)


# --- 2. tripspec_extract --------------------------------------------------

_EXTRACT_RULES = f"""You convert a travel request into a TripSpec JSON object.

HARD RULES
1. Coordinates: use ONLY the coordinates listed under KNOWN LOCATIONS, copied
   exactly. Never write a coordinate that is not listed there.
2. Categories: use ONLY these values: {", ".join(CATEGORY_VALUES)}.
   A wish that fits none of them goes in free_text_interests verbatim.
3. Times are 24-hour "HH:MM". date is "YYYY-MM-DD".
4. Do not invent a budget, party size or constraint the user did not state.
   Leave it out and the system will apply its own default.
5. priority: "must" only when the user insists on it, otherwise "should".

Today is {REFERENCE_DATE} ({REFERENCE_WEEKDAY}), Asia/Kolkata."""

_EXTRACT_SHAPE = """
Return a JSON object of this shape (omit anything not stated):
{
  "origin": {"name": str, "lat": float, "lon": float},
  "date": "YYYY-MM-DD",
  "start_time_local": "HH:MM",
  "end_time_local": "HH:MM",
  "budget_inr": int,
  "party_size": int,
  "interests": [{"category": str, "count": int, "priority": "must|should|nice_to_have"}],
  "free_text_interests": [str],
  "transport": ["walking"|"auto"|"cab"|"own_car"|"bike"],
  "constraints": {"vegetarian": bool, "max_stops": int, "max_walking_km": float}
}
Reply with the JSON object only, no prose and no code fence."""


def _extract_user_block(case: dict) -> str:
    return (f"KNOWN LOCATIONS\n{_gazetteer_block(case)}\n\n"
            f"REQUEST\n{case['utterance']}")


def _extract_messages(case: dict) -> list[dict]:
    return [{"role": "system", "content": _EXTRACT_RULES},
            {"role": "user", "content": _extract_user_block(case)}]


def _extract_messages_unconstrained(case: dict) -> list[dict]:
    return [{"role": "system", "content": _EXTRACT_RULES + _EXTRACT_SHAPE},
            {"role": "user", "content": _extract_user_block(case)}]


# Fields that change the resulting itinerary. Accuracy is measured over these
# only, and only over the ones the utterance actually determines - crediting a
# model for a default it never had to infer would inflate every score.
CRITICAL_FIELDS = (
    "origin", "date", "start_time_local", "end_time_local",
    "budget_inr", "party_size", "categories", "transport",
    "vegetarian", "max_stops",
)


def _extracted_value(spec: dict, field_name: str):
    constraints = spec.get("constraints") or {}
    match field_name:
        case "origin":
            o = spec.get("origin") or {}
            return (o.get("lat"), o.get("lon"))
        case "categories":
            items = spec.get("interests") or []
            return sorted(str(i.get("category")) for i in items
                          if isinstance(i, dict))
        case "transport":
            return sorted(str(t) for t in (spec.get("transport") or []))
        case "vegetarian":
            return constraints.get("vegetarian")
        case "max_stops":
            return constraints.get("max_stops")
        case _:
            return spec.get(field_name)


def _field_matches(field_name: str, got, want) -> bool:
    if field_name == "origin":
        if not isinstance(got, tuple) or got[0] is None or got[1] is None:
            return False
        return (abs(float(got[0]) - float(want[0])) < 1e-3
                and abs(float(got[1]) - float(want[1])) < 1e-3)
    if field_name in ("categories", "transport"):
        return sorted(got or []) == sorted(want or [])
    if field_name in ("budget_inr", "party_size", "max_stops"):
        try:
            return got is not None and int(got) == int(want)
        except (TypeError, ValueError):
            return False
    return got == want


def _tripspec_score(case: dict, judgement: Judgement) -> tuple[float, dict]:
    """Critical-field accuracy: matched / stated, per case."""
    gold = case["gold"]
    spec = judgement.payload or {}
    checked, matched, misses = 0, 0, {}

    for name in CRITICAL_FIELDS:
        if name not in gold:
            continue                     # the utterance did not state it
        checked += 1
        got = _extracted_value(spec, name)
        want = tuple(gold[name]) if name == "origin" else gold[name]
        if _field_matches(name, got, want):
            matched += 1
        else:
            misses[name] = {"got": list(got) if isinstance(got, tuple) else got,
                            "want": gold[name]}

    return (matched / checked if checked else 1.0), {
        "checked": checked, "matched": matched, "misses": misses,
    }


def _tripspec_grounding_check(case: dict):
    """Reject a spec whose origin was not copied from the gazetteer.

    A hallucinated coordinate is unusable output, not a wrong answer: it
    would send the planner somewhere the user never named. Scored as a
    failed run rather than a low accuracy score.
    """
    allowed = {(round(float(p["lat"]), 4), round(float(p["lon"]), 4))
               for p in case.get("gazetteer", [])}

    def check(_text: str, payload) -> tuple[bool, str]:
        if not isinstance(payload, dict):
            return False, "payload is not an object"
        origin = payload.get("origin") or {}
        try:
            point = (round(float(origin["lat"]), 4),
                     round(float(origin["lon"]), 4))
        except (KeyError, TypeError, ValueError):
            return False, "origin missing or non-numeric coordinates"
        if point not in allowed:
            return False, (f"origin {point} is not in the supplied gazetteer "
                           f"(ADR-002: coordinates may not be invented)")
        return True, ""
    return check


TRIPSPEC_EXTRACT = TaskClass(
    id="tripspec_extract",
    description="Natural language to TripSpec. The decisive class for NQ-029.",
    expects_json=True,
    num_predict=900,
    latency_budget_ms=8000,
    build_messages=_extract_messages,
    build_messages_unconstrained=_extract_messages_unconstrained,
    schema=tripspec_schema(),
    schema_validator=TripSpec.model_validate,
    score=_tripspec_score,
)


# --- 3. tripspec_modify ---------------------------------------------------

_MODIFY_RULES = f"""You apply one change to an existing TripSpec.

Return the COMPLETE updated TripSpec, not a patch.
Change ONLY what the user asked for; copy every other field through exactly.
Coordinates: only those already in the spec or under KNOWN LOCATIONS.
Categories: {", ".join(CATEGORY_VALUES)}.
Today is {REFERENCE_DATE} ({REFERENCE_WEEKDAY}), Asia/Kolkata."""


def _modify_user_block(case: dict) -> str:
    return (f"CURRENT TRIPSPEC\n"
            f"{json.dumps(case['current_spec'], indent=2)}\n\n"
            f"KNOWN LOCATIONS\n{_gazetteer_block(case)}\n\n"
            f"CHANGE REQUESTED\n{case['utterance']}")


def _modify_messages(case: dict) -> list[dict]:
    return [{"role": "system", "content": _MODIFY_RULES},
            {"role": "user", "content": _modify_user_block(case)}]


def _modify_messages_unconstrained(case: dict) -> list[dict]:
    return [{"role": "system", "content": _MODIFY_RULES + _EXTRACT_SHAPE},
            {"role": "user", "content": _modify_user_block(case)}]


def _modify_score(case: dict, judgement: Judgement) -> tuple[float, dict]:
    """Half the credit for making the change, half for touching nothing else.

    Both halves matter. A model that rewrites the whole spec to satisfy one
    request is as unusable as one that ignores the request.
    """
    gold = case["gold"]
    spec = judgement.payload or {}
    changed_ok, changed_bad = [], {}
    for name, want in (gold.get("changed") or {}).items():
        got = _extracted_value(spec, name)
        want_v = tuple(want) if name == "origin" else want
        if _field_matches(name, got, want_v):
            changed_ok.append(name)
        else:
            changed_bad[name] = {
                "got": list(got) if isinstance(got, tuple) else got,
                "want": want}

    preserved_ok, preserved_bad = [], {}
    original = case["current_spec"]
    for name in (gold.get("preserved") or []):
        got, want = _extracted_value(spec, name), _extracted_value(original, name)
        if _field_matches(name, got, want):
            preserved_ok.append(name)
        else:
            preserved_bad[name] = {
                "got": list(got) if isinstance(got, tuple) else got,
                "want": list(want) if isinstance(want, tuple) else want}

    n_changed = len(gold.get("changed") or {})
    n_preserved = len(gold.get("preserved") or [])
    change_score = len(changed_ok) / n_changed if n_changed else 1.0
    preserve_score = len(preserved_ok) / n_preserved if n_preserved else 1.0

    return (0.5 * change_score + 0.5 * preserve_score), {
        "change_score": round(change_score, 3),
        "preserve_score": round(preserve_score, 3),
        "wrong_changes": changed_bad,
        "clobbered": preserved_bad,
    }


TRIPSPEC_MODIFY = TaskClass(
    id="tripspec_modify",
    description="Apply one modification to a spec without clobbering the rest.",
    expects_json=True,
    num_predict=900,
    latency_budget_ms=8000,
    build_messages=_modify_messages,
    build_messages_unconstrained=_modify_messages_unconstrained,
    schema=tripspec_schema(),
    schema_validator=TripSpec.model_validate,
    score=_modify_score,
)


# --- 4. tool_select -------------------------------------------------------

_TOOL_SYS = (
    "You choose ONE tool from the NavigIQ registry to serve the user request.\n"
    "You may only name a tool from the registry. You never answer from your "
    "own knowledge: distances, travel times, opening hours, costs and place "
    "facts come from tools.\n\n"
    "REGISTRY\n" + json.dumps(TOOL_REGISTRY, indent=2) + "\n\n"
    "Reply with JSON only: "
    "{\"tool\": ..., \"arguments\": {...}, \"reason\": \"one short sentence\"}"
)


def _tool_messages(case: dict) -> list[dict]:
    user = case["utterance"]
    if case.get("context"):
        user = (f"CONTEXT\n{json.dumps(case['context'], indent=2)}\n\n"
                f"REQUEST\n{user}")
    return [{"role": "system", "content": _TOOL_SYS},
            {"role": "user", "content": user}]


def _tool_score(case: dict, judgement: Judgement) -> tuple[float, dict]:
    """0.7 for the right tool, 0.3 for the arguments it cannot run without."""
    payload = judgement.payload or {}
    gold = case["gold"]
    tool_ok = payload.get("tool") == gold["tool"]

    required = gold.get("required_arguments") or {}
    args = payload.get("arguments") or {}
    arg_hits = []
    for key, want in required.items():
        got = args.get(key)
        if want is None:
            ok = key in args and got is not None
        elif isinstance(want, (int, float)) and isinstance(got, (int, float)):
            ok = abs(float(got) - float(want)) < 1e-3
        elif isinstance(want, list):
            ok = isinstance(got, list) and sorted(map(str, got)) == sorted(map(str, want))
        else:
            ok = str(got) == str(want)
        if ok:
            arg_hits.append(key)

    arg_score = len(arg_hits) / len(required) if required else 1.0
    return (0.7 * (1.0 if tool_ok else 0.0) + 0.3 * arg_score), {
        "tool_got": payload.get("tool"), "tool_want": gold["tool"],
        "arg_score": round(arg_score, 3),
        "args_missing": [k for k in required if k not in arg_hits],
    }


TOOL_SELECT = TaskClass(
    id="tool_select",
    description="Bounded tool choice from the ADR-004 registry.",
    expects_json=True,
    num_predict=400,
    latency_budget_ms=4000,
    build_messages=_tool_messages,
    schema=ToolCall.model_json_schema(),
    schema_validator=ToolCall.model_validate,
    score=_tool_score,
)


# --- 5. explain_itinerary -------------------------------------------------

_EXPLAIN_SYS = (
    "You explain a NavigIQ itinerary to the traveller in 2-4 sentences.\n"
    "Use ONLY the figures in ITINERARY FACTS. Never state a distance, "
    "duration, cost or time that is not there. Do not add places that are "
    "not listed. Plain prose, no markdown, no bullet points."
)


def _explain_messages(case: dict) -> list[dict]:
    return [{"role": "system", "content": _EXPLAIN_SYS},
            {"role": "user", "content": f"ITINERARY FACTS\n{_facts_block(case)}\n\n"
                                        f"{case['utterance']}"}]


EXPLAIN_ITINERARY = TaskClass(
    id="explain_itinerary",
    description="Grounded natural-language explanation of a computed plan.",
    expects_json=False,
    num_predict=600,
    latency_budget_ms=9000,
    build_messages=_explain_messages,
    task_check=None,     # bound per case by the runner
    score=_mention_score,
)


# --- 6. rag_answer --------------------------------------------------------

_RAG_SYS = (
    "Answer the question using ONLY the passages provided.\n"
    "If the passages do not contain the answer, say so plainly - that is a "
    "correct response, not a failure. Never supplement them from your own "
    "knowledge. Two or three sentences."
)


def _rag_messages(case: dict) -> list[dict]:
    passages = "\n\n".join(f"[{i + 1}] {p}"
                           for i, p in enumerate(case["passages"]))
    return [{"role": "system", "content": _RAG_SYS},
            {"role": "user", "content": f"PASSAGES\n{passages}\n\n"
                                        f"QUESTION\n{case['utterance']}"}]


RAG_ANSWER = TaskClass(
    id="rag_answer",
    description="Answer strictly from retrieved passages (NQ-034 shape).",
    expects_json=False,
    num_predict=600,
    latency_budget_ms=9000,
    build_messages=_rag_messages,
    score=_mention_score,
)


# --- 7. reroute_message ---------------------------------------------------

_REROUTE_SYS = (
    "Tell the traveller, in 1-3 sentences, that their route changed and what "
    "it means for them.\n"
    "Use ONLY the figures in REROUTE FACTS. Never invent a delay, distance or "
    "arrival time. Calm and direct; no apology longer than a clause."
)


def _reroute_messages(case: dict) -> list[dict]:
    return [{"role": "system", "content": _REROUTE_SYS},
            {"role": "user", "content": f"REROUTE FACTS\n{_facts_block(case)}"}]


REROUTE_MESSAGE = TaskClass(
    id="reroute_message",
    description="Short grounded notification for a mid-trip reroute.",
    expects_json=False,
    num_predict=400,
    latency_budget_ms=6000,
    build_messages=_reroute_messages,
    score=_mention_score,
)


# --- 8. clarify_question --------------------------------------------------

_CLARIFY_SYS = (
    "A travel request is missing information the planner requires.\n"
    "Ask ONE short question that recovers the most important missing piece, "
    "and list the field names that are missing.\n"
    "Field names must come from: origin, date, start_time_local, "
    "end_time_local, interests, budget_inr, party_size, transport.\n"
    "Ask one question only. Do not guess the answer yourself.\n"
    "Reply with JSON only: "
    "{\"question\": str, \"missing_fields\": [str]}"
)


def _clarify_messages(case: dict) -> list[dict]:
    return [{"role": "system", "content": _CLARIFY_SYS},
            {"role": "user", "content": case["utterance"]}]


def _clarify_score(case: dict, judgement: Judgement) -> tuple[float, dict]:
    """Did it ask about the field that is actually missing?"""
    payload = judgement.payload or {}
    got = {str(f) for f in (payload.get("missing_fields") or [])}
    want = set(case["gold"]["missing_fields"])

    hit = len(got & want) / len(want) if want else 1.0
    # Naming fields that are present is noise in the UI, so it costs.
    noise = len(got - want) / max(len(got), 1)
    question = str(payload.get("question", ""))
    asks_one = question.count("?") <= 1 and len(question) >= 5

    return max(0.0, 0.7 * hit + 0.2 * (1 - noise) + 0.1 * asks_one), {
        "matched_fields": sorted(got & want),
        "spurious_fields": sorted(got - want),
        "question_marks": question.count("?"),
    }


CLARIFY_QUESTION = TaskClass(
    id="clarify_question",
    description="One targeted question when the spec is underdetermined.",
    expects_json=True,
    num_predict=300,
    latency_budget_ms=4000,
    build_messages=_clarify_messages,
    schema=ClarifyQuestion.model_json_schema(),
    schema_validator=ClarifyQuestion.model_validate,
    score=_clarify_score,
)


# --- registry -------------------------------------------------------------

TASK_CLASSES: dict[str, TaskClass] = {
    t.id: t for t in (
        INTENT_CLASSIFY,
        TRIPSPEC_EXTRACT,
        TRIPSPEC_MODIFY,
        TOOL_SELECT,
        EXPLAIN_ITINERARY,
        RAG_ANSWER,
        REROUTE_MESSAGE,
        CLARIFY_QUESTION,
    )
}

TASK_IDS = tuple(TASK_CLASSES)

# Per-class case files.
CASE_FILES = {
    "intent_classify": "intent_classify.json",
    "tripspec_extract": "tripspec_extract.json",
    "tripspec_modify": "tripspec_modify.json",
    "tool_select": "tool_select.json",
    "explain_itinerary": "explain_itinerary.json",
    "rag_answer": "rag_answer.json",
    "reroute_message": "reroute_message.json",
    "clarify_question": "clarify_question.json",
}

# Free-text classes need their check bound to the case being run.
_TEXT_CHECK_FACTORIES = {
    # The lower bounds catch non-answers ("Sure!", a single clause), not
    # concision. A correct two-sentence explanation can be short, and failing
    # it for that would measure verbosity rather than usefulness.
    "explain_itinerary": _grounded_text_check(80, 1200),
    # A RAG answer is grounded in its retrieved passages, not in a facts
    # block - grounding it against the wrong field would treat every figure
    # in the passages as invented.
    "rag_answer": _grounded_text_check(40, 1200, facts_key="passages"),
    "reroute_message": _grounded_text_check(40, 700),
}


def task_check_for(task: TaskClass, case: dict):
    """The per-case check, or None when the class does not need one."""
    if task.id in _TEXT_CHECK_FACTORIES:
        return _TEXT_CHECK_FACTORIES[task.id](case)
    if task.id in ("tripspec_extract", "tripspec_modify"):
        return _tripspec_grounding_check(case)
    return None


def cases_for(task_id: str) -> list[dict]:
    return load_cases(CASE_FILES[task_id])


def validate_case_file(task_id: str) -> list[str]:
    """Structural problems in a case file, as a list of messages.

    Gold answers are checked against the real TripSpec where the class
    produces one: a case whose own gold answer is not a legal spec would
    penalise every model for the benchmark author's mistake.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for i, case in enumerate(cases_for(task_id)):
        cid = case.get("id") or f"<index {i}>"
        if cid in seen:
            problems.append(f"{task_id}: duplicate case id {cid!r}")
        seen.add(cid)
        if "gold" not in case:
            problems.append(f"{task_id}/{cid}: no gold block")
        if task_id in ("tripspec_extract", "tripspec_modify"):
            gaz = {(round(float(p["lat"]), 4), round(float(p["lon"]), 4))
                   for p in case.get("gazetteer", [])}
            gold = case.get("gold", {})
            origin = (gold.get("origin")
                      or (gold.get("changed") or {}).get("origin"))
            if origin and (round(float(origin[0]), 4),
                           round(float(origin[1]), 4)) not in gaz:
                problems.append(
                    f"{task_id}/{cid}: gold origin is not in the gazetteer")
        if task_id == "tripspec_modify":
            try:
                TripSpec.model_validate(case["current_spec"])
            except ValidationError as exc:
                problems.append(
                    f"{task_id}/{cid}: current_spec is not a valid TripSpec: "
                    f"{str(exc)[:200]}")
    return problems
