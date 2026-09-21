"""Retrieval eval over the real knowledge corpus (development database).

Each answerable question lists the gold document title(s) and key terms that
the gold document must contain (the dataset is checked against the corpus
first, so a label that the corpus cannot support is reported, not scored).

  recall@6  a gold document appears among the 6 retrieved chunks
  MRR       1 / rank of the first gold chunk (0 when absent)
for dense-only, sparse-only and hybrid (RRF) retrieval. Unanswerable
questions measure whether the relevance check refuses them.

Gate (section 105): hybrid recall@6 >= 0.85.
"""
from __future__ import annotations

from sqlalchemy import text

from app.knowledge.answer import relevant
from app.knowledge.retrieval import retrieve

from .common import SuiteResult, gate, load

K = 6


async def embedding_gateway():
    """The configured embedding model, or None when Ollama is unreachable."""
    from app.config import settings
    from app.llm.factory import build_llm_gateway
    try:
        gw = build_llm_gateway(settings)
        await gw.embed(["ping"])
        return gw
    except Exception:  # noqa: BLE001
        return None


async def label_check(db, rows: list[dict]) -> list[str]:
    bad = []
    for r in rows:
        if not r["gold"]:
            continue
        body = (await db.execute(text("""
            SELECT string_agg(c.chunk_text, ' ') FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id WHERE d.title = ANY(:t)"""),
            {"t": r["gold"]})).scalar() or ""
        if not all(term.lower() in body.lower() for term in r["terms"]):
            bad.append(r["id"])
    return bad


async def run(db, *, llm=None, split: str = "test", config: str = "rules") -> SuiteResult:
    rows = load("rag", split)
    gateway = (llm.gateway if llm is not None else None) or await embedding_gateway()
    bad_labels = await label_check(db, rows)
    answerable = [r for r in rows if r["gold"] and r["id"] not in bad_labels]
    unanswerable = [r for r in rows if not r["gold"]]
    modes = ["sparse"] + (["dense", "hybrid"] if gateway is not None else ["hybrid"])
    metrics: dict[str, float] = {}
    failures = []
    for mode in modes:
        hits = 0
        lenient = 0
        rr = 0.0
        for r in answerable:
            res = await retrieve(db, r["q"], k=K, mode=mode, gateway=gateway)
            titles = [c.title for c in res.chunks[:K]]
            rank = next((i + 1 for i, t in enumerate(titles) if t in r["gold"]), None)
            hits += rank is not None
            rr += 1.0 / rank if rank else 0.0
            # lenient: any retrieved chunk that contains every key term, whatever
            # document it came from (a POI page quoting the same article)
            lenient += rank is not None or any(
                all(term.lower() in c.text.lower() for term in r["terms"])
                for c in res.chunks[:K])
            if mode == "hybrid" and rank is None:
                failures.append({"id": r["id"], "q": r["q"], "gold": r["gold"],
                                 "got": titles[:4]})
        n = len(answerable) or 1
        metrics[f"{mode}_recall@{K}"] = round(hits / n, 4)
        metrics[f"{mode}_mrr"] = round(rr / n, 4)
        metrics[f"{mode}_answer_bearing@{K}"] = round(lenient / n, 4)
    refused = 0
    for r in unanswerable:
        res = await retrieve(db, r["q"], k=K, mode="hybrid", gateway=gateway)
        refused += not relevant(r["q"], res)
    metrics["unanswerable_refusal_rate"] = round(refused / len(unanswerable), 4) \
        if unanswerable else 1.0
    cfg = config + ("" if gateway is not None else " (no embedding model: dense skipped)")
    res = SuiteResult("rag", cfg, split, len(rows), metrics, failures=failures,
                      breakdown={"answerable": len(answerable), "unanswerable": len(unanswerable),
                                 "labels_not_supported_by_corpus": bad_labels,
                                 "embedding_model": getattr(gateway, "embedding_model", None)})
    gate(res, "hybrid_recall@6", metrics[f"hybrid_recall@{K}"], ">=0.85")
    return res
