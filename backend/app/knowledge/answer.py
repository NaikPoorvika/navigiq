"""Grounded answering (sections 51-52, 98-99).

    retrieve evidence -> authoritative fact block -> generate -> attach citations
      -> validate citations, numbers and coverage -> answer or honest refusal

Validation, not the prompt, is what keeps answers grounded:
  * every [n] marker must refer to a retrieved source (fabricated citations = 0)
  * every number must appear in a cited source or the fact block
    (numeric grounding failures = 0)
  * every sentence must carry a citation (citation coverage)
If the generated answer fails any check, or the model is unavailable, the
answer is EXTRACTIVE: verbatim sentences from the best sources, each cited.
If nothing relevant was retrieved, the answer is the fixed refusal
"I don't have reliable information for that yet." - never a guess.

Volatile facts (open today? rain today?) come from structured services via
the fact block and take priority over encyclopaedic text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.knowledge.retrieval import RetrievalResult, RetrievedChunk, STOPWORDS, retrieve
from app.llm.errors import LLMError
from app.llm.prompts import GROUNDED_ANSWER, untrusted

UNKNOWN = "I don't have reliable information for that yet."
MIN_DENSE_SIM = 0.58
_CITE_RE = re.compile(r"\[(\d{1,2})\]")
_NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_ABBREV = re.compile(r"\b(lit|St|Dr|Mr|Mrs|Ms|Sri|Smt|e\.g|i\.e|c|ca|approx|No|Nos|vs|etc|Jr|Sr|"
                     r"Rs|Govt|Dept|Mt|[A-Z])\.", re.UNICODE)
_SPLIT = re.compile(r"(?<=[.!?])(?:\s*\[\d{1,2}\])*\s+(?=[A-Z0-9\"“(])")
_PROTECT = "․"   # one-dot leader: stands in for protected full stops


def split_sentences(text: str) -> list[str]:
    """Sentence split that does not break on "St.", "lit.", initials, "e.g."."""
    protected = _ABBREV.sub(lambda m: m.group(0)[:-1] + _PROTECT, text.strip())
    parts, last = [], 0
    for m in _SPLIT.finditer(protected):
        parts.append(protected[last:m.start()] + protected[m.start():m.end()].rstrip())
        last = m.end()
    parts.append(protected[last:])
    return [p.replace(_PROTECT, ".").strip() for p in parts if p.strip()]


def attach_citations(text: str, chunks: list[RetrievedChunk]) -> tuple[str, int]:
    """Give every uncited sentence the retrieved source it overlaps most; drop
    sentences that no source supports. Returns (text, sentences_dropped)."""
    out, dropped = [], 0
    for s in split_sentences(text):
        if _CITE_RE.search(s):
            out.append(s)
            continue
        words = content_words(s)
        best, best_n = 0, None
        for n, c in enumerate(chunks, start=1):
            overlap = len(words & content_words(c.text))
            if overlap > best:
                best, best_n = overlap, n
        if best_n is not None and best >= max(2, int(0.3 * len(words))):
            out.append(f"{s.rstrip()} [{best_n}]")
        else:
            dropped += 1
    return " ".join(out), dropped


@dataclass
class GroundedAnswer:
    text: str
    sources: list[dict]
    answerable: bool
    method: str                    # llm | extractive | none
    validation: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"text": self.text, "sources": self.sources, "answerable": self.answerable,
                "method": self.method, "validation": self.validation, "notes": self.notes}


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in STOPWORDS and len(w) > 2}


def relevant(question: str, result: RetrievalResult) -> bool:
    if not result.chunks:
        return False
    q = content_words(question)
    top = result.chunks[:3]
    overlap = max(len(q & content_words(c.text)) for c in top) if q else 0
    sim = result.top_similarity
    if q and overlap == 0 and (sim is None or sim < MIN_DENSE_SIM + 0.1):
        return False
    if sim is not None and sim < MIN_DENSE_SIM and overlap < 2:
        return False
    return True


def _norm_num(n: str) -> str:
    return n.replace(",", "").rstrip(".")


def check_answer(text: str, chunks: list[RetrievedChunk], facts_text: str) -> dict:
    """Citation validity, coverage and numeric entailment for a generated answer."""
    cited = [int(n) for n in _CITE_RE.findall(text)]
    fabricated = sorted({n for n in cited if not 1 <= n <= len(chunks)})
    valid_cited = sorted({n for n in cited if 1 <= n <= len(chunks)})
    sentences = split_sentences(text)
    covered = sum(1 for s in sentences if _CITE_RE.search(s))
    coverage = covered / len(sentences) if sentences else 0.0
    evidence = " ".join(chunks[n - 1].text for n in valid_cited) + " " + facts_text
    evidence_nums = {_norm_num(n) for n in _NUM_RE.findall(evidence)}
    answer_nums = [_norm_num(n) for n in _NUM_RE.findall(_CITE_RE.sub("", text))]
    unsupported = sorted({n for n in answer_nums if n not in evidence_nums})
    return {"citations": valid_cited, "fabricated_citations": fabricated,
            "citation_coverage": round(coverage, 3), "unsupported_numbers": unsupported,
            "sentences": len(sentences)}


def extractive(question: str, chunks: list[RetrievedChunk], max_sentences: int = 2) -> tuple[str, list[int]]:
    q = content_words(question)
    scored = []
    for i, c in enumerate(chunks[:4], start=1):
        body = c.text.split(": ", 1)[-1]
        for s in split_sentences(body):
            s = s.strip()
            if 30 <= len(s) <= 400:
                scored.append((len(q & content_words(s)), -i, s, i))
    scored.sort(reverse=True)
    picked, used = [], []
    for overlap, _, s, i in scored:
        if overlap == 0 and picked:
            break
        if s not in picked:
            picked.append(f"{s} [{i}]")
            used.append(i)
        if len(picked) >= max_sentences:
            break
    return " ".join(picked), sorted(set(used))


async def answer_question(db, question: str, *, llm=None, gateway=None,
                          facts: dict | None = None, entity_poi_ids: list[int] | None = None,
                          recorder=None, k: int = 6) -> GroundedAnswer:
    result = await retrieve(db, question, k=k, gateway=gateway, entity_poi_ids=entity_poi_ids)
    notes = list(result.notes)
    facts_text = _facts_text(facts)
    if not relevant(question, result):
        if facts_text:
            return GroundedAnswer(facts_text, [], True, "facts", notes=notes)
        return GroundedAnswer(UNKNOWN, [], False, "none", notes=notes)
    chunks = result.chunks
    if llm is not None and llm.available:
        sources = "\n\n".join(
            f"[{i}] {c.title}:\n<data>{untrusted(c.text, 1400)}</data>"
            for i, c in enumerate(chunks, start=1))
        try:
            res = await llm.run(GROUNDED_ANSWER, recorder=recorder, facts=facts_text or "(none)",
                                sources=sources, question=untrusted(question, 500))
            parsed = res.parsed or {}
            text = str(parsed.get("answer", "")).strip()
            if parsed.get("answerable") is False or text == UNKNOWN or not text:
                return GroundedAnswer(UNKNOWN, [], False, "llm", notes=notes)
            text, dropped = attach_citations(text, chunks)
            if dropped:
                notes.append(f"{dropped} unsupported sentence(s) removed")
            check = check_answer(text, chunks, facts_text) if text else {
                "citations": [], "fabricated_citations": [], "citation_coverage": 0.0,
                "unsupported_numbers": [], "sentences": 0}
            if not check["fabricated_citations"] and not check["unsupported_numbers"] \
                    and check["citation_coverage"] >= 0.99 and check["citations"]:
                return GroundedAnswer(text, [chunks[n - 1].to_source(n) for n in check["citations"]],
                                      True, "llm", validation=check, notes=notes)
            notes.append(f"generated answer rejected by validation: {check}")
        except LLMError as exc:
            notes.append(f"language model unavailable ({exc.code})")
    text, used = extractive(question, chunks)
    if not text:
        return GroundedAnswer(UNKNOWN, [], False, "none", notes=notes)
    check = check_answer(text, chunks, facts_text)
    return GroundedAnswer(text, [chunks[n - 1].to_source(n) for n in used], True, "extractive",
                          validation=check, notes=notes)


def _facts_text(facts: dict | None) -> str:
    if not facts:
        return ""
    return "; ".join(f"{k}: {v}" for k, v in facts.items() if v not in (None, "", []))
