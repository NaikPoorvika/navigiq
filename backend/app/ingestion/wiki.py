"""Stage 5 - ENRICH from Wikidata and Wikipedia (ADR-026).

Wikidata (CC0): English label, description, aliases, sitelink count and the
English Wikipedia title for every POI whose OSM record carries a wikidata id.

Wikipedia (CC BY-SA 4.0): the lead-section extract as the POI description,
always stored with its source URL and licence so it is attributed wherever it
is shown. Full article text feeds the knowledge corpus (stage 9).

Wikimedia Commons: a lead image is used ONLY when Commons reports a free
licence (CC0 / CC BY / CC BY-SA / public domain) and the artist, so it can
be displayed with correct attribution. Non-free (fair-use) images live on
en.wikipedia, not Commons, and are therefore never picked up.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from app.ingestion.http import CachedClient

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

WIKIPEDIA_LICENSE = "CC BY-SA 4.0"
FREE_LICENSE_RE = re.compile(r"^(cc0|cc[ -]by(-sa)?[ -]?\d(\.\d)?|public domain|pd\b|pd-)",
                             re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_QID_RE = re.compile(r"^Q\d{1,12}$")


@dataclass
class WikidataInfo:
    qid: str
    label: str | None
    description: str | None
    aliases: list[str]
    sitelinks: int
    enwiki_title: str | None


@dataclass
class WikipediaInfo:
    title: str
    extract: str
    url: str
    image_file: str | None
    pageid: int


@dataclass
class ImageInfo:
    file: str
    thumb_url: str
    license: str
    artist: str
    description_url: str


def valid_qid(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().split(";")[0].strip()
    return value if _QID_RE.match(value) else None


def fetch_wikidata(client: CachedClient, qids: list[str]) -> dict[str, WikidataInfo]:
    out: dict[str, WikidataInfo] = {}
    unique = sorted({q for q in qids if valid_qid(q)})
    for i in range(0, len(unique), 50):
        batch = unique[i:i + 50]
        body = client.fetch_json(WIKIDATA_API, params={
            "action": "wbgetentities", "ids": "|".join(batch), "format": "json",
            "props": "labels|descriptions|aliases|sitelinks", "languages": "en",
        })
        for qid, ent in (body.get("entities") or {}).items():
            if "missing" in ent:
                continue
            sitelinks = ent.get("sitelinks") or {}
            out[qid] = WikidataInfo(
                qid=qid,
                label=(ent.get("labels") or {}).get("en", {}).get("value"),
                description=(ent.get("descriptions") or {}).get("en", {}).get("value"),
                aliases=[a["value"] for a in (ent.get("aliases") or {}).get("en", [])][:10],
                sitelinks=len(sitelinks),
                enwiki_title=(sitelinks.get("enwiki") or {}).get("title"),
            )
    return out


def fetch_wikipedia_intros(client: CachedClient, titles: list[str]) -> dict[str, WikipediaInfo]:
    """Lead-section extracts, keyed by the REQUESTED title (redirects followed)."""
    out: dict[str, WikipediaInfo] = {}
    unique = sorted(set(t for t in titles if t))
    for i in range(0, len(unique), 20):
        batch = unique[i:i + 20]
        body = client.fetch_json(WIKIPEDIA_API, params={
            "action": "query", "format": "json", "formatversion": "2",
            "prop": "extracts|pageimages|info", "exintro": "1", "explaintext": "1",
            "exlimit": "20", "piprop": "name", "inprop": "url", "redirects": "1",
            "titles": "|".join(batch),
        })
        query = body.get("query") or {}
        resolved = {t: t for t in batch}
        for n in query.get("normalized", []) + query.get("redirects", []):
            for original, target in list(resolved.items()):
                if target == n["from"]:
                    resolved[original] = n["to"]
        pages = {p["title"]: p for p in query.get("pages", []) if not p.get("missing")}
        for original, final in resolved.items():
            page = pages.get(final)
            if not page or not page.get("extract"):
                continue
            out[original] = WikipediaInfo(
                title=page["title"], extract=clean_extract(page["extract"]),
                url=page.get("fullurl") or f"https://en.wikipedia.org/wiki/{final.replace(' ', '_')}",
                image_file=page.get("pageimage"), pageid=page.get("pageid", 0),
            )
    return out


def fetch_wikipedia_article(client: CachedClient, title: str) -> WikipediaInfo | None:
    body = client.fetch_json(WIKIPEDIA_API, params={
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "extracts|info", "explaintext": "1", "inprop": "url",
        "redirects": "1", "titles": title,
    })
    pages = (body.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing") or not pages[0].get("extract"):
        return None
    p = pages[0]
    return WikipediaInfo(title=p["title"], extract=p["extract"], url=p.get("fullurl", ""),
                         image_file=None, pageid=p.get("pageid", 0))


def fetch_commons_images(client: CachedClient, files: list[str]) -> dict[str, ImageInfo]:
    out: dict[str, ImageInfo] = {}
    unique = sorted(set(f for f in files if f))
    for i in range(0, len(unique), 40):
        batch = unique[i:i + 40]
        body = client.fetch_json(COMMONS_API, params={
            "action": "query", "format": "json", "formatversion": "2",
            "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "640",
            "titles": "|".join(f"File:{f}" for f in batch),
        })
        for page in (body.get("query") or {}).get("pages", []):
            info = (page.get("imageinfo") or [None])[0]
            if page.get("missing") or not info:
                continue
            meta = info.get("extmetadata") or {}
            license_name = (meta.get("LicenseShortName") or {}).get("value", "")
            artist = _strip_html((meta.get("Artist") or {}).get("value", ""))
            if not FREE_LICENSE_RE.match(license_name.strip()) or not artist:
                continue
            name = page["title"].removeprefix("File:")
            out[name] = ImageInfo(
                file=name, thumb_url=info.get("thumburl") or info.get("url"),
                license=license_name, artist=artist[:200],
                description_url=info.get("descriptionurl", ""),
            )
    return out


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", value))).strip()


def clean_extract(text: str) -> str:
    text = re.sub(r"\(\s*[;,]?\s*\)", "", text)          # empty parentheses left by templates
    text = re.sub(r"\s+\n", "\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def first_sentences(text: str, max_chars: int = 240) -> str:
    """A short description: whole sentences up to max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out = ""
    for s in sentences:
        if len(out) + len(s) + 1 > max_chars:
            break
        out = f"{out} {s}".strip()
    return out or text[:max_chars].rsplit(" ", 1)[0] + "…"
