"""Grounded-answer eval: the full answer path (retrieve -> generate or extract
-> validate) on the RAG questions.

Every final answer is re-checked here INDEPENDENTLY of the answer module:
its citation markers must point at the returned sources, every number in it
must occur in the cited chunks' full text (fetched from the database), every
URL must be a source URL, and every sentence must carry a citation.

  answer_rate            answerable questions that got an answer
  key_term_recall        answers containing all of the question's key terms
  refusal_rate           unanswerable questions that got the fixed refusal
  citation_coverage      mean share of cited sentences over given answers
Gates (section 105): citation coverage >= 0.98; numeric grounding failures,
fabricated citations and fabricated URLs all == 0.
"""
from __future__ import annotations

import re

from sqlalchemy import text

from app.knowledge.answer import UNKNOWN, answer_question, split_sentences

from .common import SuiteResult, gate, load
from .rag import embedding_gateway

CITE = re.compile(r"\[(\d{1,2})\]")
NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
URL = re.compile(r"(?:https?://|www\.)[^\s)\]>\"']+", re.I)


def _norm(n: str) -> str:
    return n.replace(",", "").rstrip(".")


async def audit(db, ans) -> dict:
    cited = [int(n) for n in CITE.findall(ans.text)]
    by_n = {s["n"]: s for s in ans.sources}
    fabricated_citations = sorted({n for n in cited if n not in by_n})
    ids = [by_n[n]["chunk_id"] for n in set(cited) if n in by_n]
    evidence = " ".join((await db.execute(text(
        "SELECT chunk_text FROM knowledge_chunks WHERE id = ANY(:i)"), {"i": ids})).scalars())
    evidence_nums = {_norm(n) for n in NUM.findall(evidence)}
    unsupported = sorted({_norm(n) for n in NUM.findall(CITE.sub("", ans.text))} - evidence_nums)
    urls = {s.get("url") for s in ans.sources if s.get("url")}
    fabricated_urls = [u for u in URL.findall(ans.text) if u.rstrip("/.,") not in
                       {x.rstrip("/.,") for x in urls}]
    sentences = split_sentences(ans.text)
    coverage = sum(1 for s in sentences if CITE.search(s)) / len(sentences) if sentences else 0.0
    return {"fabricated_citations": fabricated_citations, "unsupported_numbers": unsupported,
            "fabricated_urls": fabricated_urls, "coverage": coverage}


async def run(db, *, llm=None, split: str = "test", config: str = "rules") -> SuiteResult:
    rows = load("rag", split)
    gateway = (llm.gateway if llm is not None else None) or await embedding_gateway()
    answerable = [r for r in rows if r["gold"]]
    unanswerable = [r for r in rows if not r["gold"]]
    answered = term_hits = 0
    coverages: list[float] = []
    fab_cites = fab_urls = num_fail = 0
    methods: dict[str, int] = {}
    failures = []
    for r in answerable:
        ans = await answer_question(db, r["q"], llm=llm, gateway=gateway)
        methods[ans.method] = methods.get(ans.method, 0) + 1
        if not ans.answerable or ans.text == UNKNOWN:
            failures.append({"id": r["id"], "q": r["q"], "problem": "refused"})
            continue
        answered += 1
        a = await audit(db, ans)
        coverages.append(a["coverage"])
        fab_cites += bool(a["fabricated_citations"])
        fab_urls += bool(a["fabricated_urls"])
        num_fail += bool(a["unsupported_numbers"])
        if a["fabricated_citations"] or a["fabricated_urls"] or a["unsupported_numbers"]:
            failures.append({"id": r["id"], "q": r["q"], "problem": "grounding", **a,
                             "text": ans.text[:300]})
        low = ans.text.lower()
        if all(t.lower() in low for t in r["terms"]):
            term_hits += 1
        else:
            failures.append({"id": r["id"], "q": r["q"], "problem": "missing key terms",
                             "terms": r["terms"], "method": ans.method, "text": ans.text[:300]})
    refused = 0
    for r in unanswerable:
        ans = await answer_question(db, r["q"], llm=llm, gateway=gateway)
        ok = (not ans.answerable) or ans.text == UNKNOWN
        refused += ok
        if not ok:
            failures.append({"id": r["id"], "q": r["q"], "problem": "answered an unanswerable "
                             "question", "method": ans.method, "text": ans.text[:300]})
    n = len(answerable) or 1
    metrics = {
        "answer_rate": round(answered / n, 4),
        "key_term_recall": round(term_hits / n, 4),
        "refusal_rate": round(refused / len(unanswerable), 4) if unanswerable else 1.0,
        "citation_coverage": round(sum(coverages) / len(coverages), 4) if coverages else 0.0,
        "numeric_grounding_failures": num_fail,
        "fabricated_citations": fab_cites,
        "fabricated_urls": fab_urls,
    }
    res = SuiteResult("answers", config, split, len(rows), metrics, failures=failures,
                      breakdown={"methods": methods})
    gate(res, "citation_coverage", metrics["citation_coverage"], ">=0.98")
    gate(res, "numeric_grounding_failures", num_fail, "==0")
    gate(res, "fabricated_citations", fab_cites, "==0")
    gate(res, "fabricated_urls", fab_urls, "==0")
    return res
