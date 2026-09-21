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
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s)\]>\"']+", re.I)
# Passages that read like instructions to a model are withheld from generation
# and from extractive answers. Prompts already mark retrieved text as data and
# no tool is reachable from here; this is defence in depth (section 77).
_INSTRUCTION_LIKE = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|rules|prompts?)\b"
    r"|\bsystem prompt\b"
    r"|\b(call|invoke|run|execute|use)\b.{0,30}\b(tool|function|shell|command)\b"
    r"|\brm\s+-rf\b|\bdrop\s+table\b", re.I | re.S)


def instruction_like(text: str) -> bool:
    return bool(_INSTRUCTION_LIKE.search(text or ""))


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
    known_urls = {c.source_url.rstrip("/.,") for c in chunks if c.source_url}
    known_urls |= {u.rstrip("/.,") for u in _URL_RE.findall(evidence)}
    fabricated_urls = sorted({u.rstrip("/.,") for u in _URL_RE.findall(text)} - known_urls)
    return {"citations": valid_cited, "fabricated_citations": fabricated,
            "citation_coverage": round(coverage, 3), "unsupported_numbers": unsupported,
            "fabricated_urls": fabricated_urls, "instruction_like": instruction_like(text),
            "sentences": len(sentences)}


def passes(check: dict) -> bool:
    return (not check["fabricated_citations"] and not check["unsupported_numbers"]
            and not check["fabricated_urls"] and not check["instruction_like"]
            and check["citation_coverage"] >= 0.99 and bool(check["citations"]))


# Question shapes and the kind of sentence that answers them.
_UNIT = r"\d[\d,.]*\s*-?\s*(?:km|kilomet|kilom|metres?|meters?|miles?|mi\b|acres?|hectares?|ha\b|" \
        r"feet|ft\b|m\b|sq|square)"
_ANSWER_TYPES = [
    (re.compile(r"\b(when|what year|which year|since when|how old)\b"),
     re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b|\b\d+\s*(?:-\s*)?(?:years?|centur)")),
    (re.compile(r"\bhow (?:far|long|big|large|high|tall|wide|deep)\b|"
                r"\bwhat (?:area|size|length|height)\b"), re.compile(_UNIT, re.I)),
    (re.compile(r"\bhow (?:much|many)\b"), re.compile(r"\d")),
    (re.compile(r"\b(famous|known|special|notable|popular) (for|about)\b|\bwhat is .* known\b"),
     re.compile(r"\b(famous|known|notable|popular|renowned|celebrated)\b", re.I)),
    (re.compile(r"\bwho\b"), re.compile(r"\b(?:by|founded|built|designed|named after|"
                                        r"commissioned|established|started)\b")),
    (re.compile(r"\bwhere\b"), re.compile(r"\b(?:located|situated|lies|near)\b")),
]
_TEMPLATE_SENTENCE = re.compile(r"\blisted by NavigIQ\b", re.I)
# Question words and the stems that answer them in encyclopaedic prose.
_SYNONYMS = {
    "mean": ("mean", "translat", "literal", "lit", "refer", "named"),
    "founded": ("found", "establish", "built", "start", "set up"),
    "built": ("built", "construct", "establish", "commission", "erect"),
    "show": ("show", "display", "exhibit", "house", "collection"),
    "originate": ("origin", "source", "creat", "rise", "begin"),
    "become": ("former", "earlier", "was the", "previous", "originally"),
    "became": ("former", "earlier", "was the", "previous", "originally"),
    "called": ("known", "name", "called", "also"),
}


def _stem_match(qw: str, words: set[str]) -> bool:
    stems = _SYNONYMS.get(qw, (qw,))
    for sw in words:
        for st in stems:
            if (len(st) >= 4 and sw.startswith(st)) or sw == st or \
                    (len(sw) >= 5 and st.startswith(sw)):
                return True
    return False


def _overlap(qwords: set[str], words: set[str]) -> int:
    return sum(1 for w in qwords if _stem_match(w, words))


def extractive(question: str, chunks: list[RetrievedChunk],
               max_sentences: int = 2) -> tuple[str, list[int]]:
    """Quote the sentences that answer the question, or nothing.

    The question's words that are not the place's own name ("password",
    "founded", "rivers") must appear in the chosen sentence, or the sentence
    must have the shape the question asks for (a year for "when", a quantity
    for "how far"). Otherwise the caller refuses rather than quoting an
    unrelated sentence about the right place - found by the answer evals."""
    q = content_words(question)
    entity: set[str] = set()
    for c in chunks[:4]:
        entity |= content_words(c.title)
    focus = q - entity
    ql = question.lower()
    types = [ans for ask, ans in _ANSWER_TYPES if ask.search(ql)]
    scored = []
    for i, c in enumerate(chunks[:4], start=1):
        body = c.text.split(": ", 1)[-1]
        # a chunk about the place the question names outranks a neighbour's
        about = _overlap(q, content_words(c.title))
        for j, s in enumerate(split_sentences(body)):
            s = s.strip()
            if not 30 <= len(s) <= 400 or _TEMPLATE_SENTENCE.search(s):
                continue
            words = content_words(s) | content_words(c.title)
            f = _overlap(focus, content_words(s))
            e = _overlap(q & entity, words)
            typed = any(p.search(s) for p in types)
            score = 2.0 * f + 0.5 * e + 1.0 * about + (1.5 if typed else 0.0) + \
                (0.3 if j == 0 else 0.0) - 0.1 * i
            scored.append((score, f, typed, e, s, i))
    if not scored:
        return "", []
    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    if focus and best[1] == 0 and not best[2]:
        return "", []
    if not focus and best[3] == 0:
        return "", []
    picked, used = [], []
    for _score, f, typed, e, s, i in scored:
        # a second sentence must also answer the question, from the same source
        # unless it shares the question's own words
        if picked and f == 0 and not (typed and i == used[0]):
            break
        if s not in [p.rsplit(" [", 1)[0] for p in picked]:
            picked.append(f"{s} [{i}]")
            used.append(i)
        if len(picked) >= max_sentences:
            break
    return " ".join(picked), sorted(set(used))


# Facts that change (prices, today's hours, "right now") are never answered
# from encyclopaedic text, which may be years old: only from the live fact
# block the caller supplies (section 51, static vs volatile facts).
VOLATILE = re.compile(r"\b(today'?s?|tonight|right now|currently|at the moment|this week|"
                      r"open now|still open|entry fee|ticket price|tickets? cost|price|prices|"
                      r"charges?|how much (?:is|are|does|do)|timings?|opening hours|"
                      r"closing time|open today|closed today)\b", re.I)


async def answer_question(db, question: str, *, llm=None, gateway=None,
                          facts: dict | None = None, entity_poi_ids: list[int] | None = None,
                          recorder=None, k: int = 6) -> GroundedAnswer:
    facts_text = _facts_text(facts)
    if VOLATILE.search(question):
        if facts_text:
            return GroundedAnswer(facts_text, [], True, "facts",
                                  notes=["volatile fact: answered from live data only"])
        return GroundedAnswer(UNKNOWN, [], False, "none",
                              notes=["volatile fact: not answered from encyclopaedic text"])
    result = await retrieve(db, question, k=k, gateway=gateway, entity_poi_ids=entity_poi_ids)
    notes = list(result.notes)
    if not relevant(question, result):
        if facts_text:
            return GroundedAnswer(facts_text, [], True, "facts", notes=notes)
        return GroundedAnswer(UNKNOWN, [], False, "none", notes=notes)
    chunks = [c for c in result.chunks if not instruction_like(c.text)]
    if len(chunks) < len(result.chunks):
        notes.append(f"{len(result.chunks) - len(chunks)} passage(s) withheld: "
                     "instruction-like text")
    if not chunks:
        if facts_text:
            return GroundedAnswer(facts_text, [], True, "facts", notes=notes)
        return GroundedAnswer(UNKNOWN, [], False, "none", notes=notes)
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
            check = check_answer(text, chunks, facts_text)
            if passes(check):
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
