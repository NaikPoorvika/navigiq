"""Deterministic budget, party and radius extraction.

Money is recognised only with a currency marker (₹, rs, inr, rupees, bucks)
or an explicit budget/limit word ("budget 1500", "under 500", "1500 tak"),
never from a bare number - "10 to 6" is a time and "four friends" a party.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.taxonomy import PartyType
from app.nlu.text import WORD_NUMBERS, normalize_utterance

_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k(?![a-z])|thousand|hazaar|hazar|lakh)?"
_NUMWORD = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a couple of|"
            "couple of|ek|do|teen|char|chaar|paanch|ondu|eradu|mooru|naalku|aidu")


@dataclass(frozen=True)
class Budget:
    amount: int
    per_person: bool
    phrase: str


@dataclass(frozen=True)
class Party:
    size: int | None
    party_type: PartyType | None
    phrase: str


def _amount(num: str, mult: str | None) -> int | None:
    try:
        value = float(num.replace(",", ""))
    except ValueError:
        return None
    factor = {"k": 1000, "thousand": 1000, "hazaar": 1000, "hazar": 1000,
              "lakh": 100_000}.get(mult or "", 1)
    amount = int(round(value * factor))
    return amount if 0 <= amount <= 1_000_000 else None


PER_PERSON = re.compile(r"^\s*(?:rs|inr|rupees)?\s*(?:per person|per head|each|pp|a head|"
                        r"per pax|/person|/head|per banda|har ek)")


def parse_budget(utterance: str) -> Budget | None:
    t = normalize_utterance(utterance)
    patterns = [
        rf"(?:rs\.?|inr)\s*{_NUM}",
        rf"{_NUM}\s*(?:rs|inr|rupees|bucks|rupaye|rupay)(?![\w])",
        rf"(?:budget|budjet)\s*(?:of|is|about|around|approx\.?|~|:|under|below|max|up to|upto)?"
        rf"\s*(?:rs\.?|inr)?\s*{_NUM}",
        rf"(?:under|below|less than|within|max|maximum|up to|upto|not more than|no more than)"
        rf"\s*(?:rs\.?|inr)?\s*{_NUM}(?!\s*(?:km|kms|kilomet|hours|hrs|mins|minutes|people|"
        rf"persons|stops|places|am|pm|:))",
        rf"{_NUM}\s*(?:ka budget|ke andar|tak|mein|budget)",
        rf"{_NUM}(?=\s*(?:per person|per head|each|pp|a head|per pax))",
    ]
    for pat in patterns:
        for m in re.finditer(pat, t):
            amount = _amount(m.group(1), m.group(2))
            if amount is None:
                continue
            if amount < 20 and not m.group(2):
                continue            # "under 5" is not a rupee budget
            per_person = bool(PER_PERSON.match(t[m.end():m.end() + 24]))
            return Budget(amount, per_person, m.group(0).strip())
    return None


def _n(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return WORD_NUMBERS.get(token)


def parse_party(utterance: str) -> Party | None:
    t = normalize_utterance(utterance)
    m = re.search(r"(?:me|myself|i) (?:and|&|with) (?:my )?(girlfriend|boyfriend|gf|bf|wife|"
                  r"husband|partner|fiance|fiancee|spouse|date)", t)
    if m:
        return Party(2, PartyType.COUPLE, m[0])
    m = re.search(rf"(?:me|myself|i) (?:and|&|with) (\d+|{_NUMWORD}) (?:\w+ )?(?:friends|buddies|"
                  rf"colleagues|mates|others|people)", t)
    if m and _n(m[1]):
        kind = PartyType.COLLEAGUES if "colleague" in m[0] else PartyType.FRIENDS
        return Party(_n(m[1]) + 1, kind, m[0])
    m = re.search(rf"(\d+|{_NUMWORD}) (?:\w+ )?(?:friends|buddies|mates)", t)
    if m and _n(m[1]):
        return Party(_n(m[1]), PartyType.FRIENDS, m[0])
    m = re.search(rf"(\d+|{_NUMWORD}) (?:\w+ )?colleagues", t)
    if m and _n(m[1]):
        return Party(_n(m[1]), PartyType.COLLEAGUES, m[0])
    m = re.search(rf"(?:we are|we're|group of|party of|for|there are|there will be) (\d+|{_NUMWORD})"
                  rf"(?: of us| people| persons| adults)?(?![\w:])", t)
    if m and _n(m[1]) and re.search(r"of us|people|persons|adults|group|party|we are|we're", m[0]):
        return Party(_n(m[1]), None, m[0])
    m = re.search(rf"(\d+|{_NUMWORD}) (?:of us|people|persons|adults)", t)
    if m and _n(m[1]):
        return Party(_n(m[1]), None, m[0])
    if re.search(r"(?:my )?(?:girlfriend|boyfriend|wife|husband|partner|gf|bf)\b|\bcouple\b|"
                 r"\bdate night\b|\ba date\b|\bfor a date\b|\bon a date\b", t):
        return Party(2, PartyType.COUPLE, "couple")
    if re.search(r"\b(?:kids|children|my son|my daughter|toddler|bachche|makkalu)\b", t):
        return Party(None, PartyType.FAMILY_WITH_KIDS, "kids")
    if re.search(r"\b(?:my parents|with parents|mom and dad|amma appa|with my mom|with my dad|"
                 r"grandparents|elderly)\b", t):
        return Party(None, PartyType.PARENTS, "parents")
    if re.search(r"\b(?:family|parivar)\b", t):
        return Party(None, PartyType.FAMILY, "family")
    if re.search(r"\b(?:friends|gang|dosto|the boys|the girls)\b", t):
        return Party(None, PartyType.FRIENDS, "friends")
    if re.search(r"\b(?:solo|alone|by myself|on my own)\b", t):
        return Party(1, PartyType.SOLO, "solo")
    return None


DEFAULT_PARTY_SIZE = {
    PartyType.SOLO: 1, PartyType.COUPLE: 2, PartyType.FRIENDS: 4, PartyType.FAMILY: 4,
    PartyType.FAMILY_WITH_KIDS: 4, PartyType.PARENTS: 3, PartyType.COLLEAGUES: 4,
}


def parse_radius_km(utterance: str) -> float | None:
    t = normalize_utterance(utterance)
    m = re.search(r"(?:within|under|less than|up to|upto|max|in)\s*(\d{1,3})\s*(?:km|kms|"
                  r"kilometers|kilometres)", t)
    if m and 0 < int(m[1]) <= 500:
        return float(m[1])
    return None


def parse_stop_count(utterance: str) -> int | None:
    t = normalize_utterance(utterance)
    m = re.search(rf"(\d+|{_NUMWORD}) (?:stops|places|spots|locations)", t)
    if m and _n(m[1]) and 1 <= _n(m[1]) <= 12:
        return _n(m[1])
    return None
