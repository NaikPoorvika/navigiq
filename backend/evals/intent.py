"""Intent classification eval: the agent's real classifier (rules, the
bare-name POI lookup, and the LLM for low-confidence messages when one is
configured) over data/evals/intent.jsonl.

Gate (section 105): accuracy >= 0.95.
"""
from __future__ import annotations

from app.assistant.agent import Agent
from app.assistant.state import ConversationState, LastPOI, PendingClarification
from app.assistant.tools import Role
from app.services.planning.store import Owner

from .common import NOW, SuiteResult, by_group, confusion, gate, load, per_label

RESULTS = [LastPOI(id=1, name="Cubbon Park", category="park"),
           LastPOI(id=2, name="Lalbagh Botanical Garden", category="garden"),
           LastPOI(id=3, name="Third Wave Coffee", category="cafe")]


def state_for(ctx: str | None) -> ConversationState:
    s = ConversationState()
    if ctx in ("results", "plan"):
        s.last_pois = list(RESULTS)
    if ctx == "plan":
        s.active_itinerary_id = 1
        s.active_version_no = 1
        s.active_stops = list(RESULTS)
    if ctx == "pending":
        s.pending_clarification = PendingClarification(
            kind="time_budget", question="Roughly what time window and budget should I plan "
                                         "around?", options=[])
    return s


async def run(db, *, llm=None, split: str = "test", config: str = "rules") -> SuiteResult:
    rows = load("intent", split)
    pairs, correct, failures, sources = [], [], [], {}
    for r in rows:
        agent = Agent(db=db, owner=Owner(None, "eval-intent-000001"), role=Role.ANONYMOUS,
                      state=state_for(r.get("ctx")), conversation_id="eval", llm=llm,
                      gateway=llm.gateway if llm else None, now=NOW)
        guess = await agent.classify(r["text"])
        got = guess.intent.value
        ok = got == r["intent"] or got in r.get("also", [])
        pairs.append((r["intent"], got if not ok else r["intent"]))
        correct.append(ok)
        sources[guess.source] = sources.get(guess.source, 0) + 1
        if not ok:
            failures.append({"id": r["id"], "text": r["text"], "expected": r["intent"],
                             "got": got, "source": guess.source, "rule": guess.rule,
                             "confidence": round(guess.confidence, 2)})
    acc = sum(correct) / len(rows) if rows else 0.0
    res = SuiteResult("intent", config, split, len(rows), {"accuracy": round(acc, 4)},
                      failures=failures,
                      breakdown={"by_language": by_group(rows, "lang", correct),
                                 "decided_by": sources, "per_intent": per_label(pairs),
                                 "top_confusions": confusion(pairs)})
    gate(res, "intent_accuracy", acc, ">=0.95")
    return res
