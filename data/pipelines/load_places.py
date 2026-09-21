"""NQ-011b - Load the place gazetteer.

Reads data/artifacts/places_staging.jsonl into the places table.
Idempotent: rerunning on unchanged input writes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from collections import Counter

import psycopg

DSN = os.environ.get(
    "PG_DSN", "postgresql://navigiq:navigiq_local_dev@localhost:5433/navigiq"
)


def normalize_name(name: str) -> str:
    """unaccent + lower + collapse whitespace, for trigram matching.
    Users type 'Malleshwaram'; OSM says 'Malleswaram'."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser(description="NQ-011b load places")
    ap.add_argument("--staging", default="data/artifacts/places_staging.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = []
    stats = Counter()
    with open(args.staging, encoding="utf-8") as fh:
        for line in fh:
            stats["read"] += 1
            r = json.loads(line)
            population = r.get("population")
            try:
                population = int(population) if population else None
            except (TypeError, ValueError):
                population = None
            rows.append((
                r["source_ref"], r["name"], normalize_name(r["name"]),
                r["kind"], r["lon"], r["lat"], population, r.get("wikidata"),
            ))
            stats[r["kind"]] += 1

    print(f"read {stats['read']:,} places")
    for kind, n in stats.most_common():
        if kind != "read":
            print(f"  {n:>6,}  {kind}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO places (source_ref, name, name_normalized, kind,
                                geom, population, wikidata_id)
            VALUES (%s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s)
            ON CONFLICT (source_ref) DO UPDATE SET
                name = EXCLUDED.name,
                name_normalized = EXCLUDED.name_normalized,
                kind = EXCLUDED.kind,
                geom = EXCLUDED.geom,
                population = EXCLUDED.population
            """,
            rows,
        )
        conn.commit()
        cur.execute("SELECT count(*) FROM places")
        print(f"\nplaces in database: {cur.fetchone()[0]:,}")


if __name__ == "__main__":
    main()
