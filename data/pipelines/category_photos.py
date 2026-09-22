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
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from wikidata_enrich import COMMONS_API, USER_AGENT, get_with_retry, strip_html  # noqa: E402

DSN = os.environ.get(
    "PG_DSN", "postgresql://navigiq:navigiq_local_dev@localhost:5433/navigiq")
OUT_DIR = Path("frontend/public/images/categories")
PHOTO_WIDTH = 1200


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


# Titles with these words are rarely a photo of the place itself.
NOT_A_PHOTO = ("logo", "map", "chart", "diagram", "icon", "flag", "graph", "plan", "sign")
FREE_LICENCES = ("cc0", "cc by", "cc-by", "public domain", "pd")


# Everyday synonyms to SEARCH with - vocabulary, not chosen photos. The
# category's own display name is always tried first.
SEARCH_SYNONYMS: dict[str, list[str]] = {
    "bookstore": ["bookshop", "book store"],
    "bar": ["pub", "brewery"],
    "nightlife": ["night"],
    "cafe": ["coffee"],
    "dessert": ["sweets", "ice cream"],
}


def title_words(title: str) -> set[str]:
    words = set()
    for w in re.findall(r"[a-z0-9]+", title.lower()):
        words.add(w)
        if len(w) > 3 and w.endswith("s"):
            words.add(w[:-1])                 # "bookshops" also counts as "bookshop"
    return words


def names_the_subject(title: str, term: str) -> bool:
    """Every word of the search term appears as a WHOLE word in the title -
    so 'BarCamp' is not a bar, and a market is not a bookstore."""
    return set(re.findall(r"[a-z0-9]+", term.lower())) <= title_words(title)


def pick_search_result(candidates: list[dict], term: str | None = None) -> dict | None:
    """First search result that is a real, free, reasonably large photo -
    and, if a term is given, whose title actually names that subject.

    Each candidate: {title, url, width, mime, license, credit, source}.
    """
    for c in candidates:
        title = c.get("title", "").lower()
        if term and not names_the_subject(title, term):
            continue
        if any(w in title for w in NOT_A_PHOTO):
            continue
        if c.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if (c.get("width") or 0) < 600:
            continue
        if not any(l in (c.get("license") or "").lower() for l in FREE_LICENCES):
            continue
        return c
    return None


def photo_subject(title: str) -> str:
    """'File:Cafe_in_Indiranagar_2019.jpg' -> 'Cafe in Indiranagar 2019'."""
    name = title.removeprefix("File:").rsplit(".", 1)[0]
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip()


def search_commons(client, display_name: str, key: str | None = None) -> dict | None:
    """A real photo of this kind of place in Bengaluru, found by search and
    captioned in the app with what the file actually shows. Tries the display
    name, then everyday synonyms, until a title actually names the subject."""
    terms = [display_name, *SEARCH_SYNONYMS.get(key or "", [])]
    for term in terms:
        r = get_with_retry(client, COMMONS_API, {
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{term} Bangalore filetype:bitmap",
            "gsrnamespace": "6", "gsrlimit": "20",
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": str(PHOTO_WIDTH),
            "iiextmetadatafilter": "Artist|LicenseShortName",
        })
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(),
                       key=lambda p: p.get("index", 99))
        candidates = []
        for page in pages:
            info = (page.get("imageinfo") or [None])[0]
            if not info:
                continue
            meta = info.get("extmetadata", {})
            candidates.append({
                "title": page["title"],
                "url": info.get("thumburl") or info.get("url"),
                "width": info.get("width"), "mime": info.get("mime"),
                "license": strip_html(meta.get("LicenseShortName", {}).get("value", ""), 40),
                "credit": strip_html(meta.get("Artist", {}).get("value", "")) or "Wikimedia Commons",
                "source": info.get("descriptionurl"),
            })
        pick = pick_search_result(candidates, term)
        if pick:
            return pick
    return None


def search_missing(client, missing: list[str], names: dict[str, str],
                   search=None) -> dict[str, dict]:
    """Search for each missing category. A failure leaves that category on
    its icon; a refusal (403) stops searching rather than retrying into it."""
    search = search or search_commons
    found: dict[str, dict] = {}
    for key in missing:
        try:
            hit = search(client, names[key], key)
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            print(f"  {key:<14} search failed ({status or type(exc).__name__}) - icon stays")
            if status == 403:
                print("  Wikimedia refused the request - set WIKIMEDIA_CONTACT and retry later;"
                      " stopping the search")
                break
            continue
        if hit:
            found[key] = hit
            print(f"  {key:<14} {photo_subject(hit['title'])[:60]}")
        else:
            print(f"  {key:<14} (nothing suitable - icon stays)")
    return found


INTEGER_TYPES = {"integer", "bigint", "smallint"}


def category_sql(link_cols: dict[str, str], category_cols: set[str]) -> tuple[str, str]:
    """(select expression, join clause) that yields each link's category KEY.

    The link table may store the key itself ('park') or the category's numeric
    id - read the schema instead of assuming, since a numeric id would
    otherwise be saved as the key ("12" instead of "viewpoint").
    """
    cat_col = next((c for c in ("category_key", "category", "category_id") if c in link_cols), None)
    if cat_col is None:
        raise SystemExit(f"poi_category_links has no category column: {sorted(link_cols)}")
    if link_cols[cat_col] not in INTEGER_TYPES:
        return f"l.{cat_col}", ""
    key_col = next((c for c in ("key", "slug", "code") if c in category_cols), None)
    if key_col is None or "id" not in category_cols:
        raise SystemExit(f"poi_categories has no id/key columns: {sorted(category_cols)}")
    return f"c.{key_col}", f"JOIN poi_categories c ON c.id = l.{cat_col}"


def load_rows() -> list[Photographed]:
    import psycopg

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_name = 'poi_category_links'""")
        link_cols = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_name = 'poi_categories'""")
        category_cols = {r[0] for r in cur.fetchall()}
        select_cat, join_cat = category_sql(link_cols, category_cols)

        cur.execute(f"""
            SELECT {select_cat}, p.id, p.name, p.image_url, p.image_credit,
                   p.image_license, p.image_source_url, COALESCE(p.wikidata_sitelinks, 0)
            FROM pois p
            JOIN poi_category_links l ON l.poi_id = p.id
            {join_cat}
            WHERE p.active AND p.image_url IS NOT NULL
        """)
        return [Photographed(*r) for r in cur.fetchall()]


def load_category_names() -> dict[str, str]:
    """key -> display name, for every category, from poi_categories."""
    import psycopg

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_name = 'poi_categories'""")
        cols = {r[0] for r in cur.fetchall()}
        key_col = next(c for c in ("key", "slug", "code") if c in cols)
        name_col = next((c for c in ("display_name", "name", "label") if c in cols), key_col)
        cur.execute(f"SELECT {key_col}, {name_col} FROM poi_categories")
        return {k: n for k, n in cur.fetchall()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Category photos from photographed POIs")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-search", action="store_true",
                    help="only use photographed places; don't search Commons")
    args = ap.parse_args()
    out = Path(args.out)

    rows = load_rows()
    if not rows:
        raise SystemExit("No POI has a photo yet - run wikidata_enrich.py first.")
    chosen = choose(rows)
    print(f"photographed places give photos for {len(chosen)} categories:")
    for category, r in sorted(chosen.items()):
        print(f"  {category:<14} {r.name[:44]:<46} {r.sitelinks:>3} links")

    import httpx

    names = load_category_names()
    missing = sorted(set(names) - set(chosen))
    found: dict[str, dict] = {}
    if missing and not args.no_search:
        print(f"\nsearching Commons for the {len(missing)} still missing:")
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
            found = search_missing(client, missing, names)

    if args.dry_run:
        print("\n--dry-run: nothing downloaded")
        return

    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("*.jpg"), *out.glob("*.png")]:
        old.unlink()

    manifest: dict[str, dict] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0,
                      follow_redirects=True) as client:
        downloads = [(k, r.image_url, {"subject": r.name, "poi_id": r.poi_id,
                                       "credit": r.credit or "Wikimedia Commons",
                                       "license": r.license or "see source",
                                       "source": r.source})
                     for k, r in chosen.items()]
        downloads += [(k, h["url"], {"subject": photo_subject(h["title"]),
                                     "credit": h["credit"], "license": h["license"],
                                     "source": h["source"], "found_by": "search"})
                      for k, h in found.items()]
        for category, url, meta in downloads:
            resp = client.get(url)
            if resp.status_code != 200:
                print(f"  {category}: download failed ({resp.status_code}), skipped")
                continue
            ext = ".png" if url.lower().endswith(".png") else ".jpg"
            file = f"{category}{ext}"
            (out / file).write_bytes(resp.content)
            manifest[category] = {"file": file, **meta}

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
