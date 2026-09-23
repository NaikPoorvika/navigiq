"""One candidate per POI, however many categories it matches.

From a real failure: St Mary's Basilica matched both 'temple' and
'historical', entered the candidate list twice, and the optimizer scheduled
it twice. The validator rejected the plan (EXCLUSION_VIOLATED) - correctly,
but the user just saw an error.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.planning.orchestrator import _unique_candidates  # noqa: E402


@dataclass
class Row:
    id: int
    name: str
    matched_category: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "matched_category": self.matched_category}


def test_a_poi_matching_two_categories_appears_once():
    out = _unique_candidates({
        "temple": [Row(1, "St Mary's Basilica", "temple"), Row(2, "Other temple", "temple")],
        "historical": [Row(1, "St Mary's Basilica", "historical")],
    })
    ids = [d["id"] for d in out]
    assert ids.count(1) == 1
    assert sorted(ids) == [1, 2]


def test_the_scarcer_category_keeps_the_shared_poi():
    """'historical' has only this one candidate; 'temple' has three."""
    out = _unique_candidates({
        "temple": [Row(1, "X", "temple"), Row(2, "B", "temple"), Row(3, "C", "temple")],
        "historical": [Row(1, "X", "historical")],
    })
    kept = next(d for d in out if d["id"] == 1)
    assert kept["matched_category"] == "historical"


def test_nothing_is_lost_when_there_are_no_duplicates():
    out = _unique_candidates({
        "cafe": [Row(1, "A", "cafe"), Row(2, "B", "cafe")],
        "park": [Row(3, "C", "park")],
    })
    assert sorted(d["id"] for d in out) == [1, 2, 3]