"""Hybrid retrieval: dense (pgvector) + sparse (Postgres FTS) + RRF (section 50).

  dense   cosine similarity of the query embedding against chunk embeddings
          (HNSW index); skipped - not faked - when embeddings are unavailable
  sparse  ts_rank_cd over the generated English tsvector (GIN index)
  fusion  Reciprocal Rank Fusion, k = 60, over the two ranked lists, plus an
          entity boost for chunks from documents about a place the question
          names (resolved deterministically by resolve_poi_name)

`mode` exists so the evaluation can measure dense-only, sparse-only and
hybrid on the same labelled questions (evals/rag).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.embedding import embed_query, vector_literal

RRF_K = 60
CANDIDATES = 30
ENTITY_BOOST = 0.02
STOPWORDS = {"what", "why", "who", "when", "where", "which", "how", "is", "are", "was", "were",
             "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "does", "do", "did",
             "tell", "me", "about", "it", "this", "that", "there", "famous", "known", "bangalore",
             "bengaluru", "place", "can", "i", "you", "be", "has", "have", "with", "at", "by"}

Mode = Literal["dense", "sparse", "hybrid"]


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    title: str
    source: str
    source_url: str | None
    license: str
    text: str
    section: str | None
    poi_id: int | None
    score: float
    dense_rank: int | None = None
    sparse_rank: int | None = None
    dense_sim: float | None = None

    def to_source(self, n: int) -> dict:
        return {"n": n, "title": self.title, "url": self.source_url, "license": self.license,
                "source": self.source, "section": self.section, "chunk_id": self.chunk_id,
                "document_id": self.document_id, "excerpt": self.text[:280]}


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    mode: str
    dense_available: bool
    notes: list[str] = field(default_factory=list)

    @property
    def top_similarity(self) -> float | None:
        sims = [c.dense_sim for c in self.chunks if c.dense_sim is not None]
        return max(sims) if sims else None


_DENSE_SQL = text("""
SELECT c.id, 1 - (c.embedding <=> CAST(:v AS vector)) AS sim
FROM knowledge_chunks c WHERE c.embedding IS NOT NULL
ORDER BY c.embedding <=> CAST(:v AS vector) LIMIT :k
""")

_SPARSE_SQL = text("""
SELECT c.id, ts_rank_cd(c.tsv, q) AS rank
FROM knowledge_chunks c, websearch_to_tsquery('english', :q) q
WHERE c.tsv @@ q ORDER BY rank DESC, c.id LIMIT :k
""")

_SPARSE_OR_SQL = text("""
SELECT c.id, ts_rank_cd(c.tsv, to_tsquery('english', :q)) AS rank
FROM knowledge_chunks c WHERE c.tsv @@ to_tsquery('english', :q)
ORDER BY rank DESC, c.id LIMIT :k
""")

_FETCH_SQL = text("""
SELECT c.id, c.document_id, c.chunk_text, c.metadata->>'section' AS section,
       d.title, d.source, d.source_url, d.license, d.poi_id
FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
WHERE c.id = ANY(CAST(:ids AS int[]))
""")


def keyword_query(question: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", question.lower())
             if w not in STOPWORDS and len(w) > 2]
    return " | ".join(dict.fromkeys(words))


async def retrieve(db: AsyncSession, question: str, *, k: int = 6, mode: Mode = "hybrid",
                   gateway=None, entity_poi_ids: list[int] | None = None) -> RetrievalResult:
    notes: list[str] = []
    dense: list[tuple[int, float]] = []
    dense_ok = False
    if mode in ("dense", "hybrid") and gateway is not None:
        try:
            v = await embed_query(gateway, question)
            dense = [(r.id, float(r.sim)) for r in (await db.execute(
                _DENSE_SQL, {"v": vector_literal(v), "k": CANDIDATES})).all()]
            dense_ok = True
        except Exception as exc:  # noqa: BLE001 - embedding failure degrades to sparse
            notes.append(f"dense retrieval unavailable ({type(exc).__name__})")
    elif mode in ("dense", "hybrid"):
        notes.append("dense retrieval unavailable (no embedding model)")
    sparse: list[int] = []
    if mode in ("sparse", "hybrid"):
        sparse = [r.id for r in (await db.execute(
            _SPARSE_SQL, {"q": question, "k": CANDIDATES})).all()]
        if len(sparse) < k:
            kq = keyword_query(question)
            if kq:
                extra = [r.id for r in (await db.execute(
                    _SPARSE_OR_SQL, {"q": kq, "k": CANDIDATES})).all()]
                sparse += [i for i in extra if i not in sparse]
    scores: dict[int, float] = {}
    dense_rank = {cid: i + 1 for i, (cid, _) in enumerate(dense)}
    dense_sim = dict(dense)
    sparse_rank = {cid: i + 1 for i, cid in enumerate(sparse)}
    for cid, r in dense_rank.items():
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + r)
    for cid, r in sparse_rank.items():
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + r)
    if not scores:
        return RetrievalResult([], mode, dense_ok, notes)
    rows = {r.id: r for r in (await db.execute(_FETCH_SQL, {"ids": list(scores)})).all()}
    entity = set(entity_poi_ids or [])
    out = []
    for cid, s in scores.items():
        r = rows.get(cid)
        if r is None:
            continue
        if entity and r.poi_id in entity:
            s += ENTITY_BOOST
        out.append(RetrievedChunk(cid, r.document_id, r.title, r.source, r.source_url, r.license,
                                  r.chunk_text, r.section, r.poi_id, s, dense_rank.get(cid),
                                  sparse_rank.get(cid), dense_sim.get(cid)))
    out.sort(key=lambda c: (-c.score, c.chunk_id))
    # At most two chunks per document so one long article cannot crowd out the rest.
    per_doc: dict[int, int] = {}
    final = []
    for c in out:
        if per_doc.get(c.document_id, 0) >= 2:
            continue
        per_doc[c.document_id] = per_doc.get(c.document_id, 0) + 1
        final.append(c)
        if len(final) >= k:
            break
    return RetrievalResult(final, mode, dense_ok, notes)
