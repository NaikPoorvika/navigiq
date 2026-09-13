"""Run classification. The reason this package exists.

A previous NQ-027 harness recorded capped generations as successes and then
reported their latency as if it described the task. It does not: it describes
the token cap. Every number it produced for those task classes was therefore
meaningless, and the ADR that would have cited them was blocked.

The fix is structural rather than a patch. A run is scored by a single ladder,
in a fixed order, and only the top rung counts:

    transport -> truncation -> emptiness -> JSON -> schema -> task check

Order is load-bearing. Truncation is checked BEFORE parsing, because a
response cut off at the cap can still be parseable - constrained decoding
emits a syntactically closed object, and a free-text answer is always
"parseable". Checking parse first is exactly how a capped run gets recorded
as a success.

Nothing outside this module decides whether a run succeeded. metrics.py
aggregates only runs whose outcome is VALID.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

from .client import GenResult

# Reasoning models emit <think>...</think>. Ollama usually splits it into a
# separate field, but not every model/template does. Stripped before the
# emptiness and JSON checks so a response that is *only* reasoning is
# correctly scored EMPTY rather than accidentally passing on its think text.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)

# Models often wrap JSON in a markdown fence despite instructions.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class Outcome(str, Enum):
    """Mutually exclusive run outcomes.

    VALID is the ONLY success. Everything else is a failure and is excluded
    from every performance statistic.
    """
    VALID = "valid"

    TRANSPORT_ERROR = "transport_error"   # no complete response arrived
    TIMEOUT = "timeout"                   # client-side deadline exceeded
    TRUNCATED = "truncated"               # hit the token cap; answer incomplete
    EMPTY = "empty"                       # nothing usable after stripping
    INVALID_JSON = "invalid_json"         # JSON expected, did not parse
    SCHEMA_INVALID = "schema_invalid"     # parsed, violated the contract
    TASK_CHECK_FAILED = "task_check_failed"  # unusable for the task itself

    @property
    def is_success(self) -> bool:
        return self is Outcome.VALID


# Every non-VALID member, named explicitly. Used by the tests to assert that
# adding a new outcome cannot silently become a success.
FAILURE_OUTCOMES = frozenset(o for o in Outcome if o is not Outcome.VALID)


def strip_reasoning(text: str) -> str:
    """Remove <think> blocks, including one left unclosed by a cap."""
    cleaned = _THINK_BLOCK.sub("", text)
    cleaned = _UNCLOSED_THINK.sub("", cleaned)
    return cleaned.strip()


def strip_fence(text: str) -> str:
    """Unwrap a markdown code fence if the whole response is one."""
    m = _FENCE.match(text)
    return m.group(1).strip() if m else text.strip()


def looks_truncated(gen: GenResult) -> bool:
    """Was this generation cut off rather than finished?

    Two independent signals, either sufficient:

    1. done_reason == "length". Authoritative - the server says it stopped
       because it hit num_predict. Note that done is still True in this case,
       which is the trap the old harness fell into.
    2. eval_count >= num_predict. Defensive: covers a server build that omits
       or renames done_reason. Cannot produce a false positive, because a
       model that stops of its own accord emits its stop token before
       reaching the cap.
    """
    if gen.done_reason == "length":
        return True
    if (gen.num_predict and gen.eval_count
            and gen.num_predict > 0 and gen.eval_count >= gen.num_predict):
        return True
    return False


@dataclass
class Judgement:
    """The verdict on one run, plus everything needed to audit it."""
    outcome: Outcome
    detail: str = ""
    payload: dict | list | None = None      # parsed JSON, when the task wants JSON
    cleaned_text: str = ""                  # reasoning and fences removed
    accuracy: float | None = None           # task-specific, VALID runs only
    accuracy_detail: dict = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.outcome.is_success

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "detail": self.detail,
            "accuracy": self.accuracy,
            "accuracy_detail": self.accuracy_detail,
        }


def judge(
    gen: GenResult,
    *,
    expects_json: bool,
    schema_validator=None,
    task_check=None,
) -> Judgement:
    """Classify one generation. The ladder, in order.

    schema_validator: callable(obj) -> None, raising on violation. For
        structured tasks this is the real Pydantic model, so the benchmark
        validates against the product contract rather than a copy of it.
    task_check: callable(cleaned_text, payload) -> (ok: bool, detail: str).
        The last rung: output that parses and validates but is still unusable
        for the task - a fabricated number, a refusal, an empty answer field.
    """
    # 1. transport ------------------------------------------------------
    if not gen.transport_ok:
        err = gen.error or "unknown transport failure"
        outcome = (Outcome.TIMEOUT if "timeout" in err.lower()
                   else Outcome.TRANSPORT_ERROR)
        return Judgement(outcome=outcome, detail=err)

    # 2. truncation - BEFORE any parsing, deliberately -------------------
    if looks_truncated(gen):
        return Judgement(
            outcome=Outcome.TRUNCATED,
            detail=(f"done_reason={gen.done_reason!r} "
                    f"eval_count={gen.eval_count} cap={gen.num_predict}"),
        )

    cleaned = strip_fence(strip_reasoning(gen.text))

    # 3. emptiness -------------------------------------------------------
    if not cleaned:
        thought = len(gen.thinking) + len(gen.text)
        return Judgement(
            outcome=Outcome.EMPTY,
            detail=(f"no content after stripping reasoning "
                    f"(raw chars={thought})"),
            cleaned_text="",
        )

    if not expects_json:
        if task_check is not None:
            ok, detail = task_check(cleaned, None)
            if not ok:
                return Judgement(outcome=Outcome.TASK_CHECK_FAILED,
                                 detail=detail, cleaned_text=cleaned)
        return Judgement(outcome=Outcome.VALID, cleaned_text=cleaned)

    # 4. JSON ------------------------------------------------------------
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return Judgement(
            outcome=Outcome.INVALID_JSON,
            detail=f"{exc.msg} at pos {exc.pos}",
            cleaned_text=cleaned,
        )

    # 5. schema ----------------------------------------------------------
    if schema_validator is not None:
        try:
            schema_validator(payload)
        except Exception as exc:                    # noqa: BLE001
            return Judgement(
                outcome=Outcome.SCHEMA_INVALID,
                detail=_short(exc),
                payload=payload,
                cleaned_text=cleaned,
            )

    # 6. task check ------------------------------------------------------
    if task_check is not None:
        ok, detail = task_check(cleaned, payload)
        if not ok:
            return Judgement(outcome=Outcome.TASK_CHECK_FAILED, detail=detail,
                             payload=payload, cleaned_text=cleaned)

    return Judgement(outcome=Outcome.VALID, payload=payload, cleaned_text=cleaned)


def _short(exc: Exception, limit: int = 300) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\n", " ")
    return text[:limit]


# --- grounding -----------------------------------------------------------

# Numbers as a model writes them: 1,500 / 1500 / 1500.5 / 12:30 handled apart.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[str]:
    """Normalised numeric tokens appearing in a string.

    Thousands separators are removed and trailing zeros normalised so that
    "1,500" in the facts matches "1500" in the answer. Matching is on value,
    not on spelling.
    """
    found = set()
    for raw in _NUMBER.findall(text):
        token = raw.replace(",", "")
        try:
            value = float(token)
        except ValueError:
            continue
        found.add(_canon(value))
    return found


def _canon(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def ungrounded_numbers(answer: str, facts: str,
                       allow: set[str] | None = None) -> set[str]:
    """Numbers asserted in `answer` that do not appear in `facts`.

    ADR-002 makes the LLM non-authoritative for anything numeric. A grounded
    explanation may only restate figures the deterministic layer supplied. A
    number that appears from nowhere is a fabrication, and a fabrication is
    not a successful run however fluent the sentence around it.

    Small integers 0-12 are allowed by default: they are ordinals and counts
    ("your 3 stops", "first", "2 hours" derived from a stated range) and
    flagging them produces noise rather than signal.
    """
    # The allow list is authored as numbers (22, 5.5) but numbers_in yields
    # canonical strings, so "22" would never match the integer 22. Everything
    # is put through the same canonicalisation before comparison.
    allowed = {str(n) for n in range(13)}
    for entry in (allow or set()):
        try:
            allowed.add(_canon(float(str(entry).replace(",", ""))))
        except (TypeError, ValueError):
            allowed.add(str(entry))
    return numbers_in(answer) - numbers_in(facts) - allowed
