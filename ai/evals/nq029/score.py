"""NQ-029 extraction scoring.

Two layers are scored on purpose:

  the RAW model response   what the model actually emitted
  the VALIDATED draft      what survived TripDraft

Coordinate leakage and malformed times are measured on the RAW layer. The
TripDraft schema drops unknown fields and rejects bad times, so a model that
emitted `"lat": 12.9352` on every single call would score a perfect 0%
leakage if only the validated draft were inspected. That would be measuring
our own schema, not the model.

The scoring rules that are judgement calls, stated once here:

  places        matched case-insensitively, and a superset is accepted
                ("Koramangala, Bengaluru" counts as "Koramangala") because
                the gazetteer resolves the name later anyway
  date phrases  compared by what they RESOLVE to, against a fixed reference
                Monday - "Saturday" and "this Saturday" are the same answer
  interests     exact set equality, so a spurious extra category is a miss,
                not a free pass
  failures      a case whose extraction failed scores 0 for every field it
                was expected to produce. Failing must never look better
                than answering wrongly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# A fixed Monday, so "coming Sunday" resolves identically whenever the eval
# is run. Nothing here depends on today's date.
REFERENCE_DATE = date(2026, 9, 21)

STRICT_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Keys a model reaches for when it decides to be helpful about location.
COORDINATE_KEYS = {
    "lat", "lon", "lng", "latitude", "longitude", "coordinates", "coords",
    "geo", "location", "point", "position", "geometry",
}

# A Bengaluru-region latitude or longitude written out, in case the model
# puts one in a string rather than a dedicated key.
COORDINATE_NUMBER = re.compile(r"\b(1[0-4]|7[5-9])\.\d{3,}\b")

TIME_FIELDS = ("start_time_local", "end_time_local")


@dataclass
class CaseResult:
    case_id: str
    case_class: str
    ok: bool                      # produced a validated TripDraft
    failure_reason: str | None = None
    raw_text: str | None = None
    draft: dict | None = None
    latency_ms: float = 0.0

    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    hallucinated: list[str] = field(default_factory=list)
    coordinate_leak: bool = False
    malformed_times: list[str] = field(default_factory=list)
    unsupported_date_phrase: str | None = None
    had_time_in_raw: bool = False
    had_date_phrase_in_raw: bool = False

    @property
    def correct(self) -> int:
        return sum(1 for _, ok, _ in self.checks if ok)

    @property
    def total(self) -> int:
        return len(self.checks)


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def _place_matches(expected: str, got: str | None) -> bool:
    if not got:
        return False
    e, g = _norm(expected), _norm(got)
    return e == g or e in g or g in e


def _resolve(phrase: str | None):
    """resolve_date_phrase(), imported lazily so scoring can be unit-tested
    without the backend package on the path."""
    if phrase is None:
        return None
    from app.services.planning.draft_builder import resolve_date_phrase
    return resolve_date_phrase(phrase, REFERENCE_DATE)


def _field_is_set(draft: dict, name: str) -> bool:
    value = draft.get(name)
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, str, dict)):
        return len(value) > 0
    return True


def score_case(case, *, draft: dict | None, raw_text: str | None,
               failure_reason: str | None, latency_ms: float) -> CaseResult:
    """Score one case. `draft` is model_dump(mode="json") or None."""
    result = CaseResult(
        case_id=case.id, case_class=case.case_class,
        ok=draft is not None, failure_reason=failure_reason,
        raw_text=raw_text, draft=draft, latency_ms=latency_ms,
    )

    _score_raw(result, raw_text)

    for name, expected in case.expect.items():
        ok, detail = _check(name, expected, draft)
        result.checks.append((name, ok, detail))

    if draft is not None:
        result.hallucinated = [f for f in case.forbid if _field_is_set(draft, f)]

    return result


def _check(name: str, expected: Any, draft: dict | None) -> tuple[bool, str]:
    """A failed extraction scores every expectation as a miss."""
    if draft is None:
        return False, "no draft"

    if name == "place_any":
        got = [(draft.get("origin") or {}).get("name"),
               (draft.get("destination") or {}).get("name")]
        ok = any(_place_matches(expected, g) for g in got)
        return ok, f"origin/destination={got}"

    if name in ("origin", "destination"):
        got = (draft.get(name) or {}).get("name")
        return _place_matches(expected, got), f"{got!r}"

    if name == "date_phrase":
        got = draft.get("date_phrase")
        if got is None:
            return False, "None"
        want, have = _resolve(expected), _resolve(got)
        return (want is not None and want == have), f"{got!r} -> {have}"

    if name == "interests":
        got = {i["category"] for i in draft.get("interests") or []}
        return got == set(expected), f"{sorted(got)}"

    if name == "transport":
        got = set(draft.get("transport") or [])
        return got == set(expected), f"{sorted(got)}"

    if name == "free_text_contains":
        blob = " | ".join(draft.get("free_text_interests") or []).lower()
        missing = [p for p in expected if p.lower() not in blob]
        return not missing, f"{draft.get('free_text_interests')}"

    got = draft.get(name)
    if isinstance(expected, float) or isinstance(got, float):
        ok = got is not None and abs(float(got) - float(expected)) < 1e-6
    else:
        ok = got == expected
    return ok, f"{got!r}"


def _score_raw(result: CaseResult, raw_text: str | None) -> None:
    """Coordinate leakage, malformed times and unsupported date phrases, as
    the model emitted them - before TripDraft cleaned anything up."""
    if not raw_text:
        return

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        result.coordinate_leak = _has_coordinate(payload)
        for name in TIME_FIELDS:
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
    else:
        # Unparseable output can still be inspected for coordinates.
        result.coordinate_leak = bool(COORDINATE_NUMBER.search(raw_text))


def _has_coordinate(node: Any) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if _norm(key) in COORDINATE_KEYS and value not in (None, "", [], {}):
                return True
            if _has_coordinate(value):
                return True
        return False
    if isinstance(node, list):
        return any(_has_coordinate(v) for v in node)
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return bool(COORDINATE_NUMBER.match(f"{float(node):.6f}"))
    if isinstance(node, str):
        return bool(COORDINATE_NUMBER.search(node))
    return False


def _rate(numerator: int, denominator: int) -> float | None:
    """None, not 0.0, when nothing was measured. A rate over an empty
    denominator is not 'perfect', it is unmeasured - and printing 0.0% for
    it would be the exact kind of manufactured good result NQ-029 forbids."""
    if denominator == 0:
        return None
    return numerator / denominator


def summarise(results: list[CaseResult]) -> dict:
    n = len(results)
    with_draft = [r for r in results if r.ok]
    with_raw = [r for r in results if r.raw_text]

    checks_total = sum(r.total for r in results)
    checks_ok = sum(r.correct for r in results)

    timed = [r for r in with_raw if r.had_time_in_raw]
    dated = [r for r in with_raw if r.had_date_phrase_in_raw]

    failures: dict[str, int] = {}
    for r in results:
        if r.failure_reason:
            failures[r.failure_reason] = failures.get(r.failure_reason, 0) + 1

    return {
        "cases": n,
        "schema_valid": len(with_draft),
        "schema_validity_rate": _rate(len(with_draft), n),
        "critical_field_checks": checks_total,
        "critical_field_correct": checks_ok,
        "critical_field_accuracy": _rate(checks_ok, checks_total),
        "hallucination_cases": sum(1 for r in with_draft if r.hallucinated),
        "hallucination_rate": _rate(
            sum(1 for r in with_draft if r.hallucinated), len(with_draft)),
        "coordinate_leak_cases": sum(1 for r in with_raw if r.coordinate_leak),
        "coordinate_leakage_rate": _rate(
            sum(1 for r in with_raw if r.coordinate_leak), len(with_raw)),
        "responses_with_a_time": len(timed),
        "malformed_time_cases": sum(1 for r in timed if r.malformed_times),
        "malformed_time_rate": _rate(
            sum(1 for r in timed if r.malformed_times), len(timed)),
        "responses_with_a_date_phrase": len(dated),
        "unsupported_date_phrase_cases": sum(
            1 for r in dated if r.unsupported_date_phrase),
        "unsupported_date_phrase_rate": _rate(
            sum(1 for r in dated if r.unsupported_date_phrase), len(dated)),
        "failures_by_reason": failures,
        "latency_ms_mean": (
            sum(r.latency_ms for r in results) / n if n else None),
    }
