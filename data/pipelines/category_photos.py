"""Category photos, derived from the data - no hand-written mapping.

Run AFTER wikidata_enrich.py. Once real photos are attached to POIs, each
category's photo is simply the photo of its MOST NOTABLE photographed place:
the one with the most Wikipedia language editions (wikidata_sitelinks).
Nothing is chosen by hand, and adding data changes the result automatically.

Each photo keeps its real subject, so the app captions it truthfully
("Ulsoor Lake - Photo: <author>, CC BY-SA 4.0"). A category with no
photographed place gets no photo, and the app shows its icon.

Writes frontend/public/images/categories/<category>.jpg, categories.json
(subject, author, licence, source) and CREDITS.md.

    python data/pipelines/category_photos.py --dry-run
    python data/pipelines/category_photos.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from wikidata_enrich import USER_AGENT  # noqa: E402

DSN = os.environ.get(
    "PG_DSN", "postgresql://navigiq:navigiq_local_dev@localhost:5433/navigiq")
OUT_DIR = Path("frontend/public/images/categories")


@dataclass
class Photographed:
    category: str
    poi_id: int
    name: str
    image_url: str
    credit: str | None
    license: str | None
    source: str | None
    sitelinks: int


def choose(rows: list[Photographed]) -> dict[str, Photographed]:
    """Most notable photographed place per category, never reusing a place.

    Categories with the FEWEST candidates choose first, so a place that fits
    several categories isn't taken by a well-supplied one and leave a scarce
    one with nothing.
    """
    by_cat: dict[str, list[Photographed]] = {}
    for r in rows:
        by_cat.setdefault(r.category, []).append(r)
    for group in by_cat.values():
        group.sort(key=lambda r: (-r.sitelinks, r.poi_id))

    chosen: dict[str, Photographed] = {}
    used: set[int] = set()
    for category in sorted(by_cat, key=lambda c: (len(by_cat[c]), c)):
        pick = next((r for r in by_cat[category] if r.poi_id not in used), None)
        if pick:
            chosen[category] = pick
            used.add(pick.poi_id)
    return chosen


def load_rows() -> list[Photographed]:
    import psycopg

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        # Read the link table's column name instead of assuming it.
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_name = 'poi_category_links'""")
        cols = {r[0] for r in cur.fetchall()}
        cat_col = next((c for c in ("category_key", "category", "category_id") if c in cols), None)
        if cat_col is None:
            raise SystemExit(f"poi_category_links has no category column: {sorted(cols)}")

        cur.execute(f"""
            SELECT l.{cat_col}, p.id, p.name, p.image_url, p.image_credit,
                   p.image_license, p.image_source_url, COALESCE(p.wikidata_sitelinks, 0)
            FROM pois p
            JOIN poi_category_links l ON l.poi_id = p.id
            WHERE p.active AND p.image_url IS NOT NULL
        """)
        return [Photographed(*r) for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Category photos from photographed POIs")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)

    rows = load_rows()
    if not rows:
        raise SystemExit("No POI has a photo yet - run wikidata_enrich.py first.")
    chosen = choose(rows)
    print(f"{len(rows):,} photographed category links; photos for {len(chosen)} categories:")
    for category, r in sorted(chosen.items()):
        print(f"  {category:<14} {r.name[:44]:<46} {r.sitelinks:>3} links")
    if args.dry_run:
        print("\n--dry-run: nothing downloaded")
        return

    import httpx

    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("*.jpg"), *out.glob("*.png")]:
        old.unlink()

    manifest: dict[str, dict] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0,
                      follow_redirects=True) as client:
        for category, r in chosen.items():
            ext = ".png" if r.image_url.lower().endswith(".png") else ".jpg"
            resp = client.get(r.image_url)
            if resp.status_code != 200:
                print(f"  {category}: download failed ({resp.status_code}), skipped")
                continue
            file = f"{category}{ext}"
            (out / file).write_bytes(resp.content)
            manifest[category] = {
                "file": file, "subject": r.name, "poi_id": r.poi_id,
                "credit": r.credit or "Wikimedia Commons",
                "license": r.license or "see source", "source": r.source,
            }

    (out / "categories.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    rows_md = "\n".join(
        f"| {k} | {m['subject']} | {m['credit']} | {m['license']} | {m['source']} |"
        for k, m in sorted(manifest.items()))
    (out / "CREDITS.md").write_text(
        "# Category photos\n\nGenerated by `data/pipelines/category_photos.py`: each is "
        "the real photo of that category's most notable photographed place, from "
        "Wikimedia Commons. Captioned in the app with its real subject.\n\n"
        "| Category | Shows | Author | Licence | Source |\n|---|---|---|---|---|\n"
        f"{rows_md}\n", encoding="utf-8")
    print(f"\nsaved {len(manifest)} photos to {out}")


if __name__ == "__main__":
    main()
