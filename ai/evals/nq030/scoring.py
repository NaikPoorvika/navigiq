"""NQ-030 scoring - measures extraction in BOTH directions.

NQ-029's scorer was built around one question - did the model invent
fields? - and was nearly blind to the other: did it drop what the user
actually said? This one scores both, per field, deterministically:

  stated field       (expected, non-empty)  -> correct | missing | wrong
  restraint field    (every other field not in `allow`)
                                            -> empty, or UNREQUESTED

and classifies every unrequested value by what it would DO downstream, read
off draft_builder.py's actual defaults rather than by intuition:

  benign          equals what draft_builder uses when the field is absent
                  (vegetarian false, mode balanced, days 1, party_size 1,
                  max_walking_km 3.0, transport walking+auto), or is a
                  field nothing downstream consumes yet (free_text_interests)
  clarifying      a date_phrase resolve_date_phrase() cannot parse - it
                  becomes a question, not a wrong plan
  plan_altering   everything else: an invented budget, party size, mode,
                  transport, date, time, place or interest changes the trip

A WRONG value for a stated field (bus -> auto, 3 people -> 4) is also plan
altering: it is a substitution, not an omission. NQ-029's scorer filed the
bus -> auto case under "missed field", which kept the single most dangerous
answer out of its hallucination number.

Judgement calls, stated once:
  places        case-insensitive, superset accepted, a list = accepted
                spellings ("Koramangala" / "kormangala")
  date phrases  compared by what they resolve to on a fixed Monday
  interests     exact set of categories - an extra one is wrong, not free
  failures      a failed extraction scores every stated field as missing
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

REFERENCE_DATE = date(2026, 9, 21)  # a Monday

DRAFT_FIELDS = (
    "origin", "destination", "date_phrase", "start_time_local",
    "end_time_local", "days", "budget_inr", "party_size", "interests",
    "free_text_interests", "transport", "max_walking_km", "vegetarian",
    "mode",
)

# What draft_builder.build_tripspec() uses when a field is absent. An
# invented value equal to one of these changes nothing downstream.
DOWNSTREAM_DEFAULTS: dict[str, Any] = {
    "vegetarian": False,
    "mode": "balanced",
    "days": 1,
    "party_size": 1,
    "max_walking_km": 3.0,
    "transport": {"walking", "auto"},
}
# Passed into TripSpec but read by no planner code (verified: grep
# free_text_interests in app/ shows only draft_builder passing it on).
UNCONSUMED_FIELDS = {"free_text_interests"}

PLACE_FIELDS = {"origin", "destination"}
PLACE_INTEREST_FIELDS = {"origin", "destination", "place_any", "interests",
                         "free_text_contains"}

STRICT_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
COORDINATE_KEYS = {"lat", "lon", "lng", "latitude", "longitude",
                   "coordinates", "coords", "geo", "point", "geometry"}
COORDINATE_NUMBER = re.compile(r"\b(1[0-4]|7[5-9])\.\d{3,}\b")

BENIGN, CLARIFYING, PLAN_ALTERING = "benign", "clarifying", "plan_altering"


@dataclass
class FieldCheck:
    field: str
    status: str          # correct | missing | wrong
    got: str


@dataclass
class Unrequested:
    field: str
    severity: str        # benign | clarifying | plan_altering
    value: str


@dataclass
class CaseScore:
    case_id: str
    category: str
    ok: bool
    failure_reason: str | None
    raw_text: str | None
    latency_ms: float
    stated: list[FieldCheck] = field(default_factory=list)
    unrequested: list[Unrequested] = field(default_factory=list)
    restraint_opportunities: int = 0
    coordinate_leak: bool = False
    malformed_times: list[str] = field(default_factory=list)
    had_time_in_raw: bool = False
    had_date_phrase_in_raw: bool = False
    unsupported_date_phrase: str | None = None

    @property
    def plan_altering(self) -> list[str]:
        out = [u.field for u in self.unrequested if u.severity == PLAN_ALTERING]
        out += [f"{c.field} (wrong)" for c in self.stated if c.status == "wrong"]
        return out

    @property
    def clean(self) -> bool:
        """Valid, every stated field right, nothing non-benign invented."""
        return (self.ok and all(c.status == "correct" for c in self.stated)
                and not any(u.severity != BENIGN for u in self.unrequested))

    @property
    def place_interest_correct(self) -> bool:
        if not self.ok:
            return False
        checks = [c for c in self.stated if c.field in PLACE_INTEREST_FIELDS]
        misplaced = [u for u in self.unrequested
                     if u.field in PLACE_FIELDS | {"interests"}]
        return all(c.status == "correct" for c in checks) and not misplaced


# --- helpers -------------------------------------------------------------------

def _norm(value: Any) -> str:
    return str(value).strip().lower()


def _resolve(phrase: str | None):
    if phrase is None:
        return None
    from app.services.planning.draft_builder import resolve_date_phrase
    return resolve_date_phrase(phrase, REFERENCE_DATE)


def _is_empty_expectation(value: Any) -> bool:
    return value is None or value == [] or value == ()


def _is_set(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict, str)):
        return len(value) > 0
    return True


def _place_matches(expected: Any, got: str | None) -> bool:
    if not got:
        return False
    options = expected if isinstance(expected, (list, tuple)) else [expected]
    g = _norm(got)
    return any(_norm(e) == g or _norm(e) in g or g in _norm(e) for e in options)


def restraint_fields(expected: dict, allow: tuple | list) -> list[str]:
    """Every field that must stay empty: not stated, not allowed."""
    stated = {k for k, v in expected.items() if not _is_empty_expectation(v)}
    if "place_any" in stated:
        stated |= PLACE_FIELDS
    if "free_text_contains" in stated:
        stated.add("free_text_interests")
    return [f for f in DRAFT_FIELDS if f not in stated and f not in allow]


def classify(field_name: str, value: Any) -> str:
    """Severity of an unrequested value, from draft_builder's defaults."""
    if field_name in UNCONSUMED_FIELDS:
        return BENIGN
    if field_name == "date_phrase":
        return CLARIFYING if _resolve(value) is None else PLAN_ALTERING
    if field_name in DOWNSTREAM_DEFAULTS:
        default = DOWNSTREAM_DEFAULTS[field_name]
        if field_name == "transport":
            return BENIGN if set(value) == default else PLAN_ALTERING
        if isinstance(default, float):
            return (BENIGN if value is not None
                    and abs(float(value) - default) < 1e-9 else PLAN_ALTERING)
        return BENIGN if value == default else PLAN_ALTERING
    return PLAN_ALTERING


def check_stated(name: str, expected: Any, draft: dict | None) -> FieldCheck:
    if draft is None:
        return FieldCheck(name, "missing", "no draft")

    if name == "place_any":
        got = [(draft.get(f) or {}).get("name") for f in ("origin", "destination")]
        if not any(got):
            return FieldCheck(name, "missing", "None")
        ok = any(_place_matches(expected, g) for g in got)
        return FieldCheck(name, "correct" if ok else "wrong", f"{got}")

    if name in PLACE_FIELDS:
        got = (draft.get(name) or {}).get("name")
        if not got:
            return FieldCheck(name, "missing", "None")
        return FieldCheck(name, "correct" if _place_matches(expected, got)
                          else "wrong", repr(got))

    if name == "date_phrase":
        got = draft.get("date_phrase")
        if not got:
            return FieldCheck(name, "missing", "None")
        want, have = _resolve(expected), _resolve(got)
        ok = want is not None and want == have
        return FieldCheck(name, "correct" if ok else "wrong", f"{got!r} -> {have}")

    if name == "interests":
        got = {i["category"] for i in draft.get("interests") or []}
        if not got:
            return FieldCheck(name, "missing", "[]")
        return FieldCheck(name, "correct" if got == set(expected) else "wrong",
                          f"{sorted(got)}")

    if name == "transport":
        got = set(draft.get("transport") or [])
        if not got:
            return FieldCheck(name, "missing", "[]")
        return FieldCheck(name, "correct" if got == set(expected) else "wrong",
                          f"{sorted(got)}")

    if name == "free_text_contains":
        items = draft.get("free_text_interests") or []
        if not items:
            return FieldCheck(name, "missing", "[]")
        blob = " | ".join(items).lower()
        ok = all(p.lower() in blob for p in expected)
        return FieldCheck(name, "correct" if ok else "wrong", f"{items}")

    got = draft.get(name)
    if got is None:
        return FieldCheck(name, "missing", "None")
    if isinstance(expected, float) or isinstance(got, float):
        ok = abs(float(got) - float(expected)) < 1e-9
    else:
        ok = got == expected
    return FieldCheck(name, "correct" if ok else "wrong", repr(got))


# --- scoring -------------------------------------------------------------------

def score_case(case: dict, *, draft: dict | None, raw_text: str | None,
               failure_reason: str | None, latency_ms: float) -> CaseScore:
    expected = case.get("expected", {})
    allow = case.get("allow", [])
    result = CaseScore(case_id=case["id"], category=case["category"],
                       ok=draft is not None, failure_reason=failure_reason,
                       raw_text=raw_text, latency_ms=latency_ms)

    for name, value in expected.items():
        if not _is_empty_expectation(value):
            result.stated.append(check_stated(name, value, draft))

    forbidden = restraint_fields(expected, allow)
    result.restraint_opportunities = len(forbidden)
    if draft is not None:
        for name in forbidden:
            value = draft.get(name)
            if _is_set(value):
                shown = value
                if name in ("interests",):
                    shown = sorted(i["category"] for i in value)
                result.unrequested.append(
                    Unrequested(name, classify(name, _plain(name, value)),
                                json.dumps(shown, ensure_ascii=False)))

    _score_raw(result, raw_text)
    return result


def _plain(name: str, value: Any) -> Any:
    if name == "transport":
        return list(value)
    return value


def _score_raw(result: CaseScore, raw_text: str | None) -> None:
    """Measured on the raw response: TripDraft would hide these."""
    if not raw_text:
        return
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        result.coordinate_leak = bool(COORDINATE_NUMBER.search(raw_text))
        return
    if not isinstance(payload, dict):
        return
    result.coordinate_leak = _has_coordinate(payload)
    for name in ("start_time_local", "end_time_local"):
        value = payload.get(name)
        if value is None:
            continue
        result.had_time_in_raw = True
        if not (isinstance(value, str) and STRICT_HHMM.match(value)):
            result.malformed_times.append(f"{name}={value!r}")
    phrase = payload.get("date_phrase")
    if isinstance(phrase, str) and phrase.strip():
        result.had_date_phrase_in_raw = True
        if _resolve(phrase) is None:
            result.unsupported_date_phrase = phrase


def _has_coordinate(node: Any) -> bool:
    if isinstance(node, dict):
        return any((_norm(k) in COORDINATE_KEYS and v not in (None, "", [], {}))
                   or _has_coordinate(v) for k, v in node.items())
    if isinstance(node, list):
        return any(_has_coordinate(v) for v in node)
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return bool(COORDINATE_NUMBER.match(f"{float(node):.6f}"))
    if isinstance(node, str):
        return bool(COORDINATE_NUMBER.search(node))
    return False


def _rate(n: int, d: int) -> float | None:
    """None when nothing was measured - never a flattering 0%."""
    return None if d == 0 else n / d


def summarise(scores: list[CaseScore]) -> dict:
    n = len(scores)
    valid = [s for s in scores if s.ok]
    raw = [s for s in scores if s.raw_text]
    stated = [c for s in scores for c in s.stated]
    correct = sum(c.status == "correct" for c in stated)
    missing = sum(c.status == "missing" for c in stated)
    wrong = sum(c.status == "wrong" for c in stated)
    unreq = [u for s in valid for u in s.unrequested]
    opportunities = sum(s.restraint_opportunities for s in valid)
    timed = [s for s in raw if s.had_time_in_raw]
    dated = [s for s in raw if s.had_date_phrase_in_raw]
    pi = [s for s in scores if s.category == "place_interest"]
    latencies = sorted(s.latency_ms for s in scores)

    by_severity = {sev: sum(u.severity == sev for u in unreq)
                   for sev in (BENIGN, CLARIFYING, PLAN_ALTERING)}
    categories: dict[str, dict] = {}
    for s in scores:
        c = categories.setdefault(s.category, {"cases": 0, "clean": 0})
        c["cases"] += 1
        c["clean"] += s.clean

    return {
        "cases": n,
        "clean_cases": sum(s.clean for s in scores),
        "clean_rate": _rate(sum(s.clean for s in scores), n),
        "schema_valid": len(valid),
        "schema_validity_rate": _rate(len(valid), n),
        "stated_checks": len(stated),
        "stated_correct": correct,
        "explicit_extraction_accuracy": _rate(correct, len(stated)),
        "stated_missing": missing,
        "under_extraction_rate": _rate(missing, len(stated)),
        "stated_wrong": wrong,
        "wrong_value_rate": _rate(wrong, len(stated)),
        "unrequested_cases": sum(bool(s.unrequested) for s in valid),
        "unrequested_case_rate": _rate(sum(bool(s.unrequested) for s in valid),
                                       len(valid)),
        "unrequested_fields": len(unreq),
        "restraint_opportunities": opportunities,
        "unrequested_field_rate": _rate(len(unreq), opportunities),
        "unrequested_by_severity": by_severity,
        "plan_altering_cases": sum(bool(s.plan_altering) for s in valid),
        "plan_altering_rate": _rate(sum(bool(s.plan_altering) for s in valid),
                                    len(valid)),
        "coordinate_leak_cases": sum(s.coordinate_leak for s in raw),
        "coordinate_leakage_rate": _rate(sum(s.coordinate_leak for s in raw),
                                         len(raw)),
        "responses_with_a_time": len(timed),
        "malformed_time_rate": _rate(sum(bool(s.malformed_times) for s in timed),
                                     len(timed)),
        "responses_with_a_date_phrase": len(dated),
        "unsupported_date_cases": sum(bool(s.unsupported_date_phrase)
                                      for s in dated),
        "unsupported_date_rate": _rate(sum(bool(s.unsupported_date_phrase)
                                           for s in dated), len(dated)),
        "place_interest_cases": len(pi),
        "place_interest_correct": sum(s.place_interest_correct for s in pi),
        "place_interest_accuracy": _rate(sum(s.place_interest_correct
                                             for s in pi), len(pi)),
        "latency_ms_mean": sum(latencies) / n if n else None,
        "latency_ms_p50": latencies[n // 2] if n else None,
        "latency_ms_max": latencies[-1] if n else None,
        "failures_by_reason": _count(s.failure_reason for s in scores
                                     if s.failure_reason),
        "by_category": categories,
    }


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out
