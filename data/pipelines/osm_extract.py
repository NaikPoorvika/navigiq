"""NQ-011 - Extract candidate POIs from the Bengaluru OSM extract to staging JSONL.

Emits exactly: osm_type, osm_id, source_ref, lat, lon, tags.
Normalization, categories, dedup and scoring are NQ-013.

pyosmium 4.x: Area has no .envelope; centroids come from outer_rings().
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

import osmium

POI_KEYS = ("amenity", "tourism", "leisure", "historic", "shop", "craft")

NARROW_KEYS = {
    "natural": {"water", "peak", "spring", "bare_rock", "beach", "cave_entrance"},
    "man_made": {"tower", "lighthouse", "obelisk", "bridge", "pier", "observatory"},
}

SPOT_CHECKS = (
    ("Lalbagh Botanical Gardens", 12.9489, 77.5867),
    ("Cubbon Park", 12.9742, 77.5934),
    ("Bangalore Palace", 12.9986, 77.5920),
    ("Vidhana Soudha", 12.9797, 77.5906),
)


def matches_filter(tags: dict) -> bool:
    for key in POI_KEYS:
        if tags.get(key):
            return True
    for key, allowed in NARROW_KEYS.items():
        if tags.get(key) in allowed:
            return True
    return False


def bbox_centre(coords: list):
    if not coords:
        return None
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2


def area_coords(area) -> list:
    coords = []
    for ring in area.outer_rings():
        for node in ring:
            try:
                coords.append((node.lat, node.lon))
            except osmium.InvalidLocationError:
                continue
    return coords


class POIStagingHandler(osmium.SimpleHandler):
    def __init__(self, sink) -> None:
        super().__init__()
        self.sink = sink
        self.written = 0
        self.by_type = Counter()
        self.tag_combos = Counter()
        self.areas_without_location = 0

    def node(self, n) -> None:
        tags = {t.k: t.v for t in n.tags}
        if not matches_filter(tags):
            return
        self._write("node", n.id, n.location.lat, n.location.lon, tags)

    def area(self, a) -> None:
        tags = {t.k: t.v for t in a.tags}
        if not matches_filter(tags):
            return
        centre = bbox_centre(area_coords(a))
        if centre is None:
            self.areas_without_location += 1
            return
        osm_type = "way" if a.from_way() else "relation"
        self._write(osm_type, a.orig_id(), centre[0], centre[1], tags)

    def _write(self, osm_type, osm_id, lat, lon, tags) -> None:
        self.sink.write(json.dumps({
            "osm_type": osm_type,
            "osm_id": osm_id,
            "source_ref": f"{osm_type}/{osm_id}",
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "tags": tags,
        }, ensure_ascii=False) + "\n")
        self.written += 1
        self.by_type[osm_type] += 1
        for key in (*POI_KEYS, *NARROW_KEYS):
            val = tags.get(key)
            if val:
                self.tag_combos[f"{key}={val}"] += 1


def read_bbox(path: Path):
    reader = osmium.io.Reader(str(path))
    try:
        box = reader.header().box()
        return {
            "min_lat": box.bottom_left.lat, "min_lon": box.bottom_left.lon,
            "max_lat": box.top_right.lat, "max_lon": box.top_right.lon,
        }
    except osmium.InvalidLocationError:
        return None
    finally:
        reader.close()


def run(input_path: Path, out_path: Path, report_path: Path, manifest_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as sink:
        handler = POIStagingHandler(sink)
        handler.apply_file(str(input_path), locations=True, idx="flex_mem")

    with report_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["tag_combination", "count"])
        for combo, count in handler.tag_combos.most_common():
            writer.writerow([combo, count])

    manifest_path.write_text(json.dumps({
        "task": "NQ-011",
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file": str(input_path),
        "source_bytes": input_path.stat().st_size,
        "bbox": read_bbox(input_path),
        "pyosmium_version": pkg_version("osmium"),
        "poi_candidates": handler.written,
        "by_osm_type": dict(handler.by_type),
        "areas_without_location": handler.areas_without_location,
        "distinct_tag_combinations": len(handler.tag_combos),
        "license": "ODbL - (c) OpenStreetMap contributors",
    }, indent=2), encoding="utf-8")

    return handler


def spot_check(out_path: Path):
    found = {}
    with out_path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            name = rec["tags"].get("name")
            for target, _, _ in SPOT_CHECKS:
                if name == target and target not in found:
                    found[target] = (rec["lat"], rec["lon"])
    results = []
    for target, exp_lat, exp_lon in SPOT_CHECKS:
        if target not in found:
            results.append((target, False, "NOT FOUND"))
            continue
        lat, lon = found[target]
        ok = abs(lat - exp_lat) < 0.02 and abs(lon - exp_lon) < 0.02
        results.append((target, ok, f"{lat:.5f},{lon:.5f}"))
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="NQ-011 POI staging extraction")
    ap.add_argument("--input", default="infrastructure/osrm-data/map.osm.pbf")
    ap.add_argument("--out", default="data/artifacts/pois_staging.jsonl")
    ap.add_argument("--report", default="data/artifacts/unmapped_report.csv")
    ap.add_argument("--manifest", default="data/artifacts/extract_manifest.json")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"Input not found: {src}")

    out = Path(args.out)
    print(f"pyosmium {pkg_version('osmium')}")
    print(f"reading  {src} ({src.stat().st_size / 1e6:.1f} MB)")
    box = read_bbox(src)
    if box:
        print(f"bbox     lat {box['min_lat']:.4f}..{box['max_lat']:.4f}  "
              f"lon {box['min_lon']:.4f}..{box['max_lon']:.4f}")
    else:
        print("bbox     not declared in file header")

    h = run(src, out, Path(args.report), Path(args.manifest))

    print(f"\nwrote {h.written:,} POI candidates -> {out}")
    print(f"  by type: {dict(h.by_type)}")
    if h.areas_without_location:
        print(f"  areas skipped (no resolvable location): {h.areas_without_location:,}")
    print(f"  distinct tag combinations: {len(h.tag_combos):,}")

    print("\ntop 20 tag combinations:")
    for combo, count in h.tag_combos.most_common(20):
        print(f"  {count:>7,}  {combo}")

    print(f"\nreport   -> {args.report}")
    print(f"manifest -> {args.manifest}")

    print("\nspot check (3 of 4 are areas - failure means area assembly broke):")
    all_ok = True
    for name, ok, detail in spot_check(out):
        print(f"  [{'OK  ' if ok else 'FAIL'}] {name:<28} {detail}")
        all_ok &= ok
    if not all_ok:
        raise SystemExit("\nSPOT CHECK FAILED - do not proceed to NQ-013.")
    print("\nspot check passed.")


if __name__ == "__main__":
    main()
