"""Build the Bengaluru knowledge corpus and POI embeddings (section 49).

    python -m app.knowledge.ingest              # documents + chunks + embeddings
    python -m app.knowledge.ingest --no-embed   # text only (sparse retrieval still works)

Sources, each stored with URL, licence, retrieval time and content hash:
  * Wikipedia (CC BY-SA 4.0): articles linked from POIs, plus a fixed list of
    Bengaluru-region topics (TOPICS below)
  * POI records (ODbL / CC BY-SA text): one short document per recommendable
    POI that has a description, so place-specific questions retrieve it
  * NavigIQ guides (data/curated/guides/*.md): how NavigIQ works and its limits

Idempotent: a document whose content hash is unchanged is skipped; changed
documents have their chunks replaced; chunks missing an embedding (or embedded
by another model) are embedded. A second identical run writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys

import psycopg

from app.config import settings
from app.core.paths import data_dir
from app.ingestion.http import CachedClient, FetchError
from app.ingestion.load import sync_dsn
from app.ingestion.wiki import WIKIPEDIA_LICENSE, fetch_wikipedia_article
from app.knowledge.chunking import chunk_text
from app.knowledge.embedding import embed_documents, vector_literal

TOPICS = [
    "Bangalore", "History of Bangalore", "Culture of Bangalore", "Kempe Gowda I",
    "Bangalore Karaga", "Lakes in Bangalore", "Economy of Bangalore", "Kadalekai Parishe",
    "Bangalore Urban district", "Bangalore Rural district", "Ramanagara district",
    "Chikkaballapur district", "Kolar district", "Tumkur district", "Krishnagiri district",
    "Kannada", "Cuisine of Karnataka", "Karnataka", "Lalbagh", "Cubbon Park", "Bangalore Palace",
    "Vidhana Soudha", "Tipu Sultan's Summer Palace", "Bangalore Fort", "Bull Temple",
    "ISKCON Temple Bangalore", "Nandi Hills, India", "Bannerghatta National Park",
    "Bannerghatta Biological Park", "Ulsoor Lake", "Sankey Tank", "Hebbal Lake",
    "Visvesvaraya Industrial and Technological Museum", "HAL Heritage Centre and Aerospace Museum",
    "National Gallery of Modern Art, Bangalore", "Commercial Street, Bangalore", "Brigade Road",
    "Church Street, Bangalore", "Mahatma Gandhi Road, Bangalore", "Malleshwaram", "Basavanagudi",
    "Jayanagar", "Indiranagar", "Koramangala", "Frazer Town", "Shivajinagar", "Chickpet",
    "Savandurga", "Skandagiri", "Shivagange", "Devarayanadurga", "Channapatna",
    "Channapatna toys", "Hesaraghatta", "Dodda Alada Mara", "Wonderla", "Janapada Loka",
    "Manchanabele Dam", "Muthyala Maduvu", "Anthargange", "Kaiwara", "Chikkaballapur",
    "Adiyogi Shiva statue", "Art of Living International Center",
    "Gavi Gangadhareshwara Temple", "Venkatappa Art Gallery", "Jawaharlal Nehru Planetarium",
    "Ranga Shankara", "Karnataka Chitrakala Parishath", "St. Mary's Basilica, Bangalore",
    "Ramanagara", "Kanakapura", "Hosur", "Doddaballapura", "Magadi", "Kolar",
    "Kolar Gold Fields", "Hoskote", "Nelamangala", "Kengeri", "Yelahanka", "Whitefield, Bangalore",
    "Electronic City", "Bangalore International Centre", "Sampige Road", "Gandhi Bazaar",
    "KR Market", "Russell Market", "Mavalli Tiffin Rooms", "Vidyarthi Bhavan",
    "Masala dosa", "Filter coffee", "Bisi bele bath", "Ragi mudde", "Mysore pak",
    "Bangalore Metro", "Kempegowda International Airport", "Garden City",
]
POI_ARTICLE_LIMIT = 700


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_document(cur, *, source: str, external_id: str, title: str, url: str | None,
                    license: str, doc_type: str, poi_id: int | None, text: str,
                    metadata: dict) -> tuple[int, bool]:
    h = _hash(text)
    cur.execute("SELECT id, content_hash FROM knowledge_documents WHERE source=%s AND "
                "external_id=%s", (source, external_id))
    row = cur.fetchone()
    if row and row[1] == h:
        return row[0], False
    if row:
        doc_id = row[0]
        cur.execute("""UPDATE knowledge_documents SET title=%s, source_url=%s, license=%s,
                       doc_type=%s, poi_id=%s, content_hash=%s, metadata=%s, retrieved_at=now()
                       WHERE id=%s""", (title, url, license, doc_type, poi_id, h,
                                        json.dumps(metadata), doc_id))
        cur.execute("DELETE FROM knowledge_chunks WHERE document_id=%s", (doc_id,))
    else:
        cur.execute("""INSERT INTO knowledge_documents (source, external_id, title, source_url,
                       license, doc_type, poi_id, content_hash, metadata)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (source, external_id, title, url, license, doc_type, poi_id, h,
                     json.dumps(metadata)))
        doc_id = cur.fetchone()[0]
    for c in chunk_text(text, title):
        cur.execute("""INSERT INTO knowledge_chunks (document_id, chunk_index, chunk_text,
                       content_hash, metadata) VALUES (%s,%s,%s,%s,%s)""",
                    (doc_id, c.index, c.text, c.content_hash, json.dumps({"section": c.section})))
    return doc_id, True


def build_documents(dsn: str, *, refresh: bool = False) -> dict:
    stats = {"wikipedia_new_or_changed": 0, "wikipedia_unchanged": 0, "wikipedia_missing": 0,
             "poi_docs_new_or_changed": 0, "guides": 0}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, wikipedia_title FROM pois WHERE active AND wikipedia_title
                       IS NOT NULL ORDER BY prominence DESC, id LIMIT %s""", (POI_ARTICLE_LIMIT,))
        linked = cur.fetchall()
        titles: dict[str, int | None] = {t: None for t in TOPICS}
        for poi_id, title in linked:
            titles[title] = poi_id
        with CachedClient("wikimedia", min_interval_s=0.3, timeout_s=60, retries=3,
                          refresh=refresh) as client:
            for title, poi_id in titles.items():
                try:
                    art = fetch_wikipedia_article(client, title)
                except FetchError:
                    # A network failure for one article must not abort the build;
                    # the next run fetches it (everything else is cached).
                    stats["wikipedia_fetch_failed"] = stats.get("wikipedia_fetch_failed", 0) + 1
                    continue
                if art is None:
                    stats["wikipedia_missing"] += 1
                    continue
                if poi_id is None:
                    cur.execute("SELECT id FROM pois WHERE active AND wikipedia_title=%s LIMIT 1",
                                (art.title,))
                    r = cur.fetchone()
                    poi_id = r[0] if r else None
                _, changed = upsert_document(
                    cur, source="wikipedia", external_id=art.title, title=art.title,
                    url=art.url, license=WIKIPEDIA_LICENSE, doc_type="article", poi_id=poi_id,
                    text=art.extract, metadata={"pageid": art.pageid})
                stats["wikipedia_new_or_changed" if changed else "wikipedia_unchanged"] += 1
        cur.execute("""
            SELECT p.id, p.name, c.display_name, p.locality, p.district, p.short_description,
                   p.description, p.description_source, p.source_license, p.source_urls,
                   p.experience_tags
            FROM pois p JOIN poi_categories c ON c.id = p.primary_category
            WHERE p.active AND p.recommendable
              AND coalesce(p.short_description, p.description) IS NOT NULL
            ORDER BY p.id""")
        for (pid, name, cat, loc, dist, short, desc, dsrc, lic, urls, tags) in cur.fetchall():
            where = ", ".join(x for x in (loc, dist) if x)
            body = desc if dsrc == "wikipedia" and desc else (short or desc)
            text = (f"{name} is listed by NavigIQ as a {cat.lower()}"
                    + (f" in {where}" if where else "") + f". {body}")
            if tags:
                text += " Experience tags: " + ", ".join(t.replace('_', ' ') for t in tags) + "."
            _, changed = upsert_document(
                cur, source="poi", external_id=str(pid), title=name,
                url=(urls or [None])[-1], license=lic, doc_type="poi", poi_id=pid, text=text,
                metadata={"description_source": dsrc})
            stats["poi_docs_new_or_changed"] += int(changed)
        guides = sorted((data_dir() / "curated" / "guides").glob("*.md"))
        for g in guides:
            body = g.read_text(encoding="utf-8")
            title = body.splitlines()[0].lstrip("# ").strip() if body else g.stem
            upsert_document(cur, source="navigiq_guide", external_id=g.stem, title=title,
                            url=None, license="NavigIQ editorial", doc_type="guide",
                            poi_id=None, text=body, metadata={"file": g.name})
            stats["guides"] += 1
        conn.commit()
    return stats


async def embed_missing(dsn: str) -> dict:
    from app.llm.factory import build_llm_gateway
    gateway = build_llm_gateway(settings)
    model = settings.OLLAMA_EMBED_MODEL
    stats = {"chunks_embedded": 0, "pois_embedded": 0}
    try:
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, chunk_text FROM knowledge_chunks
                           WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s
                           ORDER BY id""", (model,))
            rows = cur.fetchall()
            for i in range(0, len(rows), 64):
                batch = rows[i:i + 64]
                vecs = await embed_documents(gateway, [r[1] for r in batch])
                for (cid, _), v in zip(batch, vecs):
                    cur.execute("UPDATE knowledge_chunks SET embedding=%s::vector, "
                                "embedding_model=%s WHERE id=%s", (vector_literal(v), model, cid))
                conn.commit()
                stats["chunks_embedded"] += len(batch)
            cur.execute("""
                SELECT p.id, p.name, c.display_name, coalesce(p.locality, ''),
                       coalesce(p.short_description, ''), p.experience_tags, p.mood_tags
                FROM pois p JOIN poi_categories c ON c.id = p.primary_category
                WHERE p.active AND p.recommendable ORDER BY p.id""")
            pois = []
            for pid, name, cat, loc, short, tags, moods in cur.fetchall():
                text = (f"{name}. {cat}. {loc}. {short} Tags: {', '.join(tags or [])}. "
                        f"Moods: {', '.join(moods or [])}.")
                pois.append((pid, text, _hash(model + text)))
            cur.execute("SELECT poi_id, content_hash FROM poi_embeddings")
            have = dict(cur.fetchall())
            todo = [p for p in pois if have.get(p[0]) != p[2]]
            for i in range(0, len(todo), 64):
                batch = todo[i:i + 64]
                vecs = await embed_documents(gateway, [p[1] for p in batch])
                for (pid, _, h), v in zip(batch, vecs):
                    cur.execute("""INSERT INTO poi_embeddings (poi_id, embedding, model, content_hash)
                                   VALUES (%s, %s::vector, %s, %s)
                                   ON CONFLICT (poi_id) DO UPDATE SET embedding=EXCLUDED.embedding,
                                   model=EXCLUDED.model, content_hash=EXCLUDED.content_hash,
                                   created_at=now()""", (pid, vector_literal(v), model, h))
                conn.commit()
                stats["pois_embedded"] += len(batch)
    finally:
        await gateway.aclose()
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NavigIQ knowledge corpus")
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    dsn = sync_dsn(settings.DATABASE_URL)
    print("documents:", build_documents(dsn, refresh=args.refresh), flush=True)
    if not args.no_embed:
        print("embeddings:", asyncio.run(embed_missing(dsn)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
