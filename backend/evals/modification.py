"""Plan-modification eval: a message against an open plan -> closed operations.

Mirrors the agent's policy: deterministic parsing first; the model (when
configured) only when the rules found nothing and did not ask which stop.
Model operations must validate against the closed Modification model;
`add_poi` is compared by the place NAME the parser or model produced
(resolving it to an id is a separate, database-backed step).

Scores
  operation accuracy   the produced operation set equals the expected set
                       (each expected op matched on every field it states)
  target resolution    among expected ops that name a stop, the right stop
  clarification        ambiguous references ask instead of guessing

Gates (section 105): modification operation >= 0.95, target resolution >= 0.95.
"""
from __future__ import annotations

from app.assistant.modparse import parse_modifications
from app.assistant.state import ConversationState, LastPOI
from app.llm.errors import LLMError
from app.llm.prompts import MODIFY, VOCABULARY, untrusted

from .common import SuiteResult, gate, load

CURRENT_COST = 1200
CONTEXTS = {
    "default": [("Lalbagh Botanical Garden", "garden"), ("Government Museum", "museum"),
                ("Brahmin's Coffee Bar", "cafe"), ("Commercial Street", "walking_area")],
    "two_cafes": [("Lalbagh Botanical Garden", "garden"), ("Brahmin's Coffee Bar", "cafe"),
                  ("Government Museum", "museum"), ("Third Wave Coffee", "cafe")],
    "with_mall": [("Lalbagh Botanical Garden", "garden"), ("Government Museum", "museum"),
                  ("Brahmin's Coffee Bar", "cafe"), ("Orion Mall", "mall")],
}


def state_for(ctx: str) -> ConversationState:
    stops = [LastPOI(id=100 + i, name=n, category=c)
             for i, (n, c) in enumerate(CONTEXTS[ctx], start=1)]
    return ConversationState(active_itinerary_id=1, active_version_no=1, active_stops=stops,
                             last_pois=list(stops))


async def produce(text: str, state: ConversationState, llm) -> tuple[list[dict], bool, str]:
    pm = parse_modifications(text, state, current_cost=CURRENT_COST)
    ops = list(pm.operations)
    if pm.add_poi_name:
        ops.append({"op": "add_poi", "poi_name": pm.add_poi_name})
    if pm.needs_target and not ops and pm.ambiguous_candidates:
        return [], True, "rules"
    if ops or llm is None:
        return ops, False, "rules"
    from app.services.planning.modify import Modification
    stops = "\n".join(f"{i + 1}. {s.name} ({s.category})" for i, s in enumerate(state.active_stops))
    try:
        res = await llm.run(MODIFY, stops=stops, budget=1500, vocabulary=", ".join(VOCABULARY),
                            message=untrusted(text, 800))
    except LLMError:
        return [], False, "llm_error"
    parsed = res.parsed or {}
    out = []
    for o in (parsed.get("operations") or [])[:3]:
        if not isinstance(o, dict):
            continue
        o = {k: v for k, v in o.items() if v is not None}
        if o.get("op") == "add_poi":
            if o.get("poi_name"):
                out.append({"op": "add_poi", "poi_name": str(o["poi_name"])})
            continue
        o.pop("poi_name", None)
        try:
            Modification.model_validate(o)
        except Exception:  # noqa: BLE001 - invalid model output is dropped, as in the agent
            continue
        out.append(o)
    return out, bool(parsed.get("needs_clarification")) and not out, "llm"


def matches(want: dict, got: dict) -> bool:
    for k, v in want.items():
        g = got.get(k)
        if isinstance(v, str) and isinstance(g, str):
            if k == "poi_name":
                if not (v.lower() in g.lower() or g.lower() in v.lower()):
                    return False
            elif v.lower() != g.lower():
                return False
        elif v != g:
            return False
    return True


def same_ops(expected: list[dict], produced: list[dict]) -> bool:
    if len(expected) != len(produced):
        return False
    remaining = list(produced)
    for want in expected:
        hit = next((g for g in remaining if matches(want, g)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


async def run(db, *, llm=None, split: str = "test", config: str = "rules") -> SuiteResult:
    rows = load("modification", split)
    ok_ops = 0
    tgt_ok = tgt_n = 0
    clar_ok = clar_n = 0
    failures = []
    sources: dict[str, int] = {}
    for r in rows:
        produced, clarified, source = await produce(r["text"], state_for(r.get("ctx", "default")),
                                                    llm)
        sources[source] = sources.get(source, 0) + 1
        if r.get("clarify"):
            clar_n += 1
            good = clarified and not produced
            clar_ok += good
            ok_ops += good
            if not good:
                failures.append({"id": r["id"], "text": r["text"], "expected": "clarification",
                                 "got": produced, "source": source})
            continue
        good = same_ops(r["expect"], produced)
        ok_ops += good
        for want in r["expect"]:
            if "target_seq" in want:
                tgt_n += 1
                tgt_ok += any(g.get("op") == want["op"] and g.get("target_seq") == want["target_seq"]
                              for g in produced)
        if not good:
            failures.append({"id": r["id"], "text": r["text"], "expected": r["expect"],
                             "got": produced, "source": source})
    n = len(rows)
    metrics = {"operation_accuracy": round(ok_ops / n, 4),
               "target_resolution_accuracy": round(tgt_ok / tgt_n, 4) if tgt_n else 1.0,
               "clarification_accuracy": round(clar_ok / clar_n, 4) if clar_n else 1.0}
    res = SuiteResult("modification", config, split, n, metrics, failures=failures,
                      breakdown={"decided_by": sources, "target_examples": tgt_n})
    gate(res, "modification_operation_accuracy", metrics["operation_accuracy"], ">=0.95")
    gate(res, "target_resolution_accuracy", metrics["target_resolution_accuracy"], ">=0.95")
    return res
