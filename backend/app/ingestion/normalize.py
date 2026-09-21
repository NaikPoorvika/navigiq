"""Stage 3 - NORMALIZE: names, slugs, aliases, chain detection keys.

The same normalisation is used by search at query time (app.services.poi.
text), so "Malleshwaram" typed by a user and stored by the pipeline compare
equal after both pass through `normalize_name`.
"""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_PUNCT = re.compile(r"[^\w\s&'-]", re.UNICODE)

# Spelling variants that are the same place. Applied to both stored names
# and queries, so every variant finds every other.
VARIANT_FOLDS = (
    (re.compile(r"\bbangalore\b"), "bengaluru"),
    (re.compile(r"\bmalleswaram\b"), "malleshwaram"),
    (re.compile(r"\bm\.?\s*g\.?\s+road\b"), "mahatma gandhi road"),
    (re.compile(r"\bmg road\b"), "mahatma gandhi road"),
    (re.compile(r"\blal\s*bagh\b"), "lalbagh"),
    (re.compile(r"\bulsoor\b"), "halasuru"),
    (re.compile(r"\bbasavangudi\b"), "basavanagudi"),
    (re.compile(r"\byeshwantpur\b"), "yeshwanthpur"),
    (re.compile(r"\bkoramangla\b"), "koramangala"),
    (re.compile(r"\bindira\s+nagar\b"), "indiranagar"),
    (re.compile(r"\bjaya\s+nagar\b"), "jayanagar"),
    (re.compile(r"\bj\.?\s*p\.?\s+nagar\b"), "jp nagar"),
    (re.compile(r"\bh\.?\s*s\.?\s*r\.?\s+layout\b"), "hsr layout"),
    (re.compile(r"\bst\.?\s+"), "saint "),
    (re.compile(r"&"), " and "),
)

GENERIC_NAMES = frozenset({
    "cafe", "restaurant", "temple", "park", "lake", "garden", "church", "mosque",
    "hotel", "bakery", "shop", "store", "tea stall", "juice center", "juice shop",
    "masjid", "mandir", "kere", "bar", "pub", "viewpoint", "kids park", "children park",
    "childrens park", "children's park", "bbmp park", "public park", "mini park", "tot lot",
    "playground", "park area", "open space", "tea shop", "hotel", "canteen", "darshini",
    "fast food", "juice", "bakery and sweets", "condiments", "ice cream", "coffee",
})


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Lowercase, accent-free, punctuation-light, variant-folded."""
    s = strip_accents(name).lower().replace("’", "'").replace("`", "'")
    s = _PUNCT.sub(" ", s)
    for pattern, repl in VARIANT_FOLDS:
        s = pattern.sub(repl, s)
    return _WS.sub(" ", s).strip()


def slugify(name: str, suffix: str) -> str:
    base = _NON_SLUG.sub("-", strip_accents(name).lower()).strip("-")[:120] or "place"
    return f"{base}-{suffix}"


def clean_display_name(name: str) -> str:
    return _WS.sub(" ", name).strip()


def is_generic_name(name: str) -> bool:
    return normalize_name(name) in GENERIC_NAMES


def chain_key(tags: dict, name: str) -> str | None:
    """A stable key for brand/franchise branches, or None.

    brand:wikidata is the strongest signal, then brand, then the name itself
    (the dedupe stage counts name frequency and promotes frequent names).
    """
    if tags.get("brand:wikidata"):
        return f"wd:{tags['brand:wikidata']}"
    if tags.get("brand"):
        return f"brand:{normalize_name(tags['brand'])}"[:80]
    return None


def alias_candidates(tags: dict, name: str) -> list[str]:
    """Alternative names already present in the source tags."""
    out = []
    for key in ("name:en", "alt_name", "old_name", "official_name", "short_name",
                "loc_name", "name:kn"):
        value = tags.get(key)
        if not value:
            continue
        for part in str(value).split(";"):
            part = clean_display_name(part)
            if part and normalize_name(part) != normalize_name(name) and len(part) <= 120:
                out.append(part)
    return out
