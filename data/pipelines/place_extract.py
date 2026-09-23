"""NQ-011b - Extract named places for the gazetteer.

A gap NQ-029 exposed: the LLM must never produce coordinates (ADR-002), so
"from Indiranagar" needs a place-name lookup. Nothing did that.

POIs are not places. Searching pois for 'Indiranagar' returns a library, a
plaque and a bar - none of which is the neighbourhood. Suburbs, towns and
localities are tagged place=* and were never captured by the NQ-011 filter.

Emits data/artifacts/places_staging.jsonl.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import osmium

# Ordered by how specific they are - a suburb beats a city when both match.
PLACE_KINDS = (
    "neighbourhood", "quarter", "suburb", "borough",
    "village", "town", "city", "locality", "hamlet",
)


class PlaceHandler(osmium.SimpleHandler):
    def __init__(self, sink) -> None:
        super().__init__()
        self.sink = sink
        self.written = 0
        self.by_kind = Counter()

    def node(self, n) -> None:
        self._maybe_write(n.tags, "node", n.id, n.location.lat, n.location.lon)

    def area(self, a) -> None:
        tags = {t.k: t.v for t in a.tags}
        if tags.get("place") not in PLACE_KINDS:
            return
        coords = []
        for ring in a.outer_rings():
            for node in ring:
                try:
                    coords.append((node.lat, node.lon))
                except osmium.InvalidLocationError:
                    continue
        if not coords:
            return
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        self._maybe_write(
            a.tags, "relation" if not a.from_way() else "way", a.orig_id(),
            (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)

    def _maybe_write(self, tags, osm_type, osm_id, lat, lon) -> None:
        t = {k.k: k.v for k in tags} if not isinstance(tags, dict) else tags
        kind = t.get("place")
        name = t.get("name") or t.get("name:en")
        if kind not in PLACE_KINDS or not name:
            return
        self.sink.write(json.dumps({
            "osm_type": osm_type, "osm_id": osm_id,
            "source_ref": f"{osm_type}/{osm_id}",
            "name": name, "kind": kind,
            "lat": round(lat, 7), "lon": round(lon, 7),
            "population": t.get("population"),
            "wikidata": t.get("wikidata"),
        }, ensure_ascii=False) + "\n")
        self.written += 1
        self.by_kind[kind] += 1


def main() -> None:
    ap = argparse.ArgumentParser(description="NQ-011b place extraction")
    ap.add_argument("--input", default="infrastructure/osrm-data/map.osm.pbf")
    ap.add_argument("--out", default="data/artifacts/places_staging.jsonl")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"Input not found: {src}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"reading {src} ({src.stat().st_size / 1e6:.1f} MB)")
    with out.open("w", encoding="utf-8") as sink:
        h = PlaceHandler(sink)
        h.apply_file(str(src), locations=True, idx="flex_mem")

    print(f"\nwrote {h.written:,} places -> {out}")
    for kind, n in h.by_kind.most_common():
        print(f"  {n:>6,}  {kind}")

    print("\nspot check:")
    text = out.read_text(encoding="utf-8")
    for target in ("Indiranagar", "Koramangala", "Jayanagar",
                   "Malleshwaram", "Whitefield", "Nandi"):
        hits = sum(1 for line in text.splitlines()
                   if json.loads(line)["name"].startswith(target))
        print(f"  [{'OK  ' if hits else 'MISS'}] {target:<16} {hits}")


if __name__ == "__main__":
    main()