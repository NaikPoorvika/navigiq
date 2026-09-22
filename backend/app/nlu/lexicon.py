"""Deterministic interest / mood / exclusion parsing over the controlled lexicon.

Longest phrases match first and consume their span, so "street food" is not
also counted as "food". Negation is scoped: a negator applies to the first
interest after it (within six tokens and the same clause) and to any further
interests joined to that one by a bare list connector ("no malls or temples",
"no malls, temples"). "no crowds and a nice cafe" negates crowds only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from app.core.paths import config_path
from app.domain.taxonomy import is_valid_category, is_valid_mood, is_valid_tag
from app.nlu.text import normalize_utterance, phrase_pattern

# Positive verbs end a negation's reach: "no crowds, I like cafes".
CLAUSE_BREAK = re.compile(r"[.;!?]|\b(?:but|however|instead|just|only|prefer|like|love|want|"
                          r"enjoy|need|looking for|interested in)\b")
CONNECTORS = {"or", "and", "nor", ",", "/", "&"}
LOCATIVE = re.compile(r"\s+(?:near|in|around|at|close to|next to|from|towards)\b")
NEGATION_WINDOW_TOKENS = 6


@dataclass
class LexEntry:
    phrase: str
    pattern: re.Pattern
    categories: tuple[str, ...]
    tags: tuple[str, ...]
    moods: tuple[str, ...]


@dataclass
class InterestParse:
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    avoid_categories: list[str] = field(default_factory=list)
    avoid_tags: list[str] = field(default_factory=list)
    avoid_moods: list[str] = field(default_factory=list)
    crowd_averse: bool = False
    matched_phrases: list[str] = field(default_factory=list)

    @property
    def interests(self) -> list[str]:
        """Categories, tags and moods as one controlled list (TripSpec.interests)."""
        return list(dict.fromkeys(self.categories + self.tags + self.moods))

    @property
    def avoid_interests(self) -> list[str]:
        return list(dict.fromkeys(self.avoid_categories + self.avoid_tags + self.avoid_moods))

    @property
    def empty(self) -> bool:
        return not (self.categories or self.tags or self.moods or self.avoid_categories
                    or self.avoid_tags or self.crowd_averse)


@dataclass(frozen=True)
class Lexicon:
    entries: tuple[LexEntry, ...]
    negators: tuple[re.Pattern, ...]
    postfix_negators: tuple[re.Pattern, ...]
    crowd: tuple[re.Pattern, ...]


@lru_cache(maxsize=1)
def lexicon() -> Lexicon:
    raw = yaml.safe_load(config_path("lexicon.yaml").read_text(encoding="utf-8"))
    entries = []
    for e in raw["entries"]:
        cats = tuple(e.get("categories", []))
        tags = tuple(e.get("tags", []))
        moods = tuple(e.get("moods", []))
        for c in cats:
            if not is_valid_category(c):
                raise ValueError(f"lexicon: unknown category {c!r}")
        for t in tags:
            if not is_valid_tag(t):
                raise ValueError(f"lexicon: unknown tag {t!r}")
        for m in moods:
            if not is_valid_mood(m):
                raise ValueError(f"lexicon: unknown mood {m!r}")
        for phrase in e["phrases"]:
            p = normalize_utterance(str(phrase))
            entries.append(LexEntry(p, phrase_pattern(p, plural=True), cats, tags, moods))
    entries.sort(key=lambda x: (-len(x.phrase), x.phrase))
    negators = tuple(phrase_pattern(normalize_utterance(n))
                     for n in sorted(raw["negators"], key=len, reverse=True))
    postfix = tuple(phrase_pattern(normalize_utterance(n))
                    for n in sorted(raw.get("postfix_negators", []), key=len, reverse=True))
    crowd = tuple(phrase_pattern(normalize_utterance(c)) for c in raw["crowd_phrases"])
    return Lexicon(tuple(entries), negators, postfix, crowd)


def _tokens_between(text: str, a: int, b: int) -> list[str]:
    return re.findall(r"[\w']+|,|/|&", text[a:b])


def parse_interests(utterance: str) -> InterestParse:
    lex = lexicon()
    text = normalize_utterance(utterance)
    taken = [False] * len(text)
    matches: list[tuple[int, int, LexEntry]] = []
    for entry in lex.entries:
        for m in entry.pattern.finditer(text):
            if any(taken[m.start():m.end()]):
                continue
            for i in range(m.start(), m.end()):
                taken[i] = True
            matches.append((m.start(), m.end(), entry))
    matches.sort(key=lambda x: x[0])

    negator_spans = []
    for pat in lex.negators:
        for m in pat.finditer(text):
            # "not near Majestic, street food": the negation is about a place.
            if LOCATIVE.match(text, m.end()):
                continue
            if not any(taken[m.start():m.end()]):
                negator_spans.append((m.start(), m.end()))
    negator_spans.sort()
    # Hindi/Kannada negate after the object: "mall nahi", "mall beda".
    postfix_spans = []
    for pat in lex.postfix_negators:
        for m in pat.finditer(text):
            if not any(taken[m.start():m.end()]):
                postfix_spans.append((m.start(), m.end()))

    # Crowd phrases are not interests, but they block a negation from
    # reaching past them, and a negated one means "avoid crowds".
    crowd_spans = []
    for pat in lex.crowd:
        for m in pat.finditer(text):
            if not any(taken[m.start():m.end()]):
                crowd_spans.append((m.start(), m.end()))

    def governed(start: int, window: int) -> bool:
        for ns, ne in negator_spans:
            if ne > start:
                break
            if CLAUSE_BREAK.search(text[ne:start]):
                continue
            # A comma between the negator and the interest means the negator
            # had another object ("avoid Majestic and Shivajinagar, markets
            # tomorrow"); lists that start right after it ("no malls,
            # temples") are handled by the connector rule below.
            if "," in text[ne:start]:
                continue
            if len(_tokens_between(text, ne, start)) > window:
                continue
            blockers = [ms for ms, _, _ in matches] + [cs for cs, _ in crowd_spans]
            if any(ne <= b < start for b in blockers):
                continue
            return True
        return False

    def post_negated(end: int) -> bool:
        return any(ps >= end and len(_tokens_between(text, end, ps)) <= 2
                   and not CLAUSE_BREAK.search(text[end:ps]) for ps, _ in postfix_spans)

    out = InterestParse()
    prev_negated_end: int | None = None
    for start, end, entry in matches:
        negated = governed(start, NEGATION_WINDOW_TOKENS) or post_negated(end)
        if not negated and prev_negated_end is not None:
            gap = _tokens_between(text, prev_negated_end, start)
            negated = bool(gap) and len(gap) <= 2 and all(t in CONNECTORS for t in gap)
        if negated:
            prev_negated_end = end
            # "no temples" avoids the category, not every spiritual place.
            if entry.categories:
                out.avoid_categories += list(entry.categories)
            else:
                out.avoid_tags += list(entry.tags)
                out.avoid_moods += list(entry.moods)
        else:
            prev_negated_end = None
            out.categories += list(entry.categories)
            out.tags += list(entry.tags)
            out.moods += list(entry.moods)
        out.matched_phrases.append(("-" if negated else "+") + entry.phrase)

    for cs, _ in crowd_spans:
        if governed(cs, 4):
            out.crowd_averse = True
    if any(p.startswith("+") and "crowd" in p for p in out.matched_phrases):
        out.crowd_averse = True           # "no crowds", "less crowded" are quiet-mood phrases
    if out.crowd_averse and "quiet" not in out.moods:
        out.moods.append("quiet")

    def dedupe(xs: list[str]) -> list[str]:
        return list(dict.fromkeys(xs))

    out.categories = dedupe(out.categories)
    out.tags = dedupe(out.tags)
    out.moods = dedupe(out.moods)
    # Something both wanted and avoided in one utterance: avoidance wins.
    out.avoid_categories = dedupe(out.avoid_categories)
    out.avoid_tags = dedupe(out.avoid_tags)
    out.avoid_moods = dedupe(out.avoid_moods)
    out.categories = [c for c in out.categories if c not in out.avoid_categories]
    out.tags = [t for t in out.tags if t not in out.avoid_tags]
    out.moods = [m for m in out.moods if m not in out.avoid_moods]
    return out


def controlled_interest(value: str) -> str | None:
    """Accept an interest only if it is in the controlled vocabulary, either
    directly or via a lexicon phrase. Used to sanitise LLM output."""
    v = normalize_utterance(value).replace(" ", "_")
    if is_valid_category(v) or is_valid_tag(v) or is_valid_mood(v):
        return v
    parsed = parse_interests(value)
    vals = parsed.interests
    return vals[0] if vals else None
