"""Reference resolution eval ("the second one", "that cafe", "it", "museum wala")
against shown results or the open plan's stops. Deterministic - no model.

Gate (section 105): target resolution >= 0.95. Ambiguous references must be
reported as ambiguous (the assistant then asks), never silently guessed.
"""
from __future__ import annotations

from app.assistant.references import resolve_reference
from app.assistant.state import ConversationState, LastPOI

from .common import SuiteResult, gate, load

RESULTS = [LastPOI(id=1, name="Quiet Cafe", category="cafe"),
           LastPOI(id=2, name="Test Museum", category="museum"),
           LastPOI(id=3, name="Corner Cafe", category="cafe"),
           LastPOI(id=4, name="Lake View Park", category="park")]
STOPS = [LastPOI(id=1, name="Lalbagh Botanical Garden", category="garden"),
         LastPOI(id=2, name="Government Museum", category="museum"),
         LastPOI(id=3, name="Brahmin's Coffee Bar", category="cafe"),
         LastPOI(id=4, name="Commercial Street", category="walking_area")]


async def run(db, *, llm=None, split: str = "test", config: str = "rules") -> SuiteResult:
    rows = load("references", split)
    ok = 0
    failures = []
    for r in rows:
        state = ConversationState(last_pois=list(RESULTS))
        if r.get("plan"):
            state.active_stops = list(STOPS)
        if r.get("focus"):
            state.last_focus_poi = next(p for p in RESULTS if p.id == r["focus"])
        ref = resolve_reference(r["text"], state, prefer_plan=bool(r.get("plan")))
        got = ref.poi.id if ref.status == "resolved" else ref.status
        good = got == r["expect"]
        ok += good
        if not good:
            failures.append({"id": r["id"], "text": r["text"], "expected": r["expect"], "got": got})
    acc = ok / len(rows)
    res = SuiteResult("references", config, split, len(rows), {"resolution_accuracy": round(acc, 4)},
                      failures=failures)
    gate(res, "target_resolution_accuracy", acc, ">=0.95")
    return res
