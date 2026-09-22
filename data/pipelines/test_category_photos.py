"""Offline tests for deriving category photos from photographed POIs."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from category_photos import Photographed, choose  # noqa: E402


def row(cat, poi_id, links):
    return Photographed(cat, poi_id, f"Place {poi_id}", f"https://x/{poi_id}.jpg",
                        "Author", "CC BY-SA 4.0", "https://src", links)


def test_picks_most_notable_place_in_each_category():
    chosen = choose([row("lake", 1, 5), row("lake", 2, 40)])
    assert chosen["lake"].poi_id == 2


def test_never_reuses_a_place():
    chosen = choose([row("park", 1, 50), row("landmark", 1, 50), row("landmark", 2, 10)])
    ids = [r.poi_id for r in chosen.values()]
    assert len(ids) == len(set(ids))


def test_scarce_category_chooses_first():
    """Place 1 is the only lake. 'landmark' has others, so it must not take it."""
    rows = [row("lake", 1, 30), row("landmark", 1, 30), row("landmark", 2, 99)]
    chosen = choose(rows)
    assert chosen["lake"].poi_id == 1
    assert chosen["landmark"].poi_id == 2


def test_category_without_photos_is_absent():
    assert "cafe" not in choose([row("lake", 1, 5)])
