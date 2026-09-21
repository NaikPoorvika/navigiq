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
        rf"{_NUM}(?=\s*(?:per person|per head|each|pp|a head|per pax|per banda|per bande|"
        rf"har ek|a person))",
        rf"{_NUM}(?=\s*(?:total|in total|overall|altogether|all in|all-in|for all of us|"
        rf"for everyone|for the group)\b)",
        # "4000 for both of us", "2500 for two": a sum for the party
        rf"(?<![\d:]){_NUM}(?=\s*for (?:both of us|the two of us|two of us|us two|both|the two|"
        rf"two|three|four|five|us|all|\d+(?: people| of us)?)\b)(?!\s*for \d+\s*(?:hours|hrs|"
        rf"days|mins|minutes))",
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


_KIDS = r"(?:kids?|children|child|toddlers?|babies|baby|infants?|sons?|daughters?)"
_COUNT = rf"(\d+|{_NUMWORD})"


def _party_size(t: str) -> tuple[int | None, str]:
    """How many people, from explicit counts only. Composite counts add up
    ("2 adults and a toddler" = 3); "with 4 friends" includes the speaker."""
    m = re.search(rf"{_COUNT} adults?(?:,|\s+and|\s*&|\s+with|\s+plus)?\s+"
                  rf"(?:{_COUNT}|an?)\s+{_KIDS}\b", t)
    if m and _n(m[1]):
        kids = _n(m[2]) if m[2] else 1
        return _n(m[1]) + (kids or 0), m[0]
    m = re.search(rf"family of {_COUNT}\b", t)
    if m and _n(m[1]):
        return _n(m[1]), m[0]
    m = re.search(rf"{_COUNT} couples\b", t)
    if m and _n(m[1]):
        return 2 * _n(m[1]), m[0]
    m = re.search(rf"{_COUNT} (?:\w+ )?(?:friends|buddies|colleagues|mates|cousins|others) "
                  rf"(?:and|&|plus) (?:me|myself|i)\b", t)
    if m and _n(m[1]):
        return _n(m[1]) + 1, m[0]
    m = re.search(rf"(?:\b(?:me|myself|i)\s+)?(?:and|&|with|plus) (?:my )?{_COUNT} (?:\w+ )?"
                  rf"(?:friends|buddies|colleagues|mates|others|people|cousins)\b", t)
    if m and _n(m[1]):
        return _n(m[1]) + 1, m[0]
    m = re.search(rf"{_COUNT} (?:\w+ )?(?:friends|buddies|mates|colleagues)\b", t)
    if m and _n(m[1]):
        return _n(m[1]), m[0]
    m = re.search(rf"(?:we are|we're|group of|party of|there are|there will be) {_COUNT}"
                  rf"(?![\w:])", t)
    if m and _n(m[1]):
        return _n(m[1]), m[0]
    m = re.search(rf"{_COUNT} (?:of us|people|persons|adults|pax|log|jan|janaru|members)\b", t)
    if m and _n(m[1]):
        return _n(m[1]), m[0]
    m = re.search(rf"\bfor {_COUNT}(?:\s+(?:people|persons|adults|of us))?(?=\s*(?:[,.;!?]|$|"
                  rf"on\b|this\b|tomorrow|today|tonight|next\b|at\b|from\b|with\b|and\b))", t)
    if m and _n(m[1]) and 1 <= _n(m[1]) <= 20:
        return _n(m[1]), m[0]
    m = re.search(r"\b(?:both of us|the two of us|two of us|us two)\b", t)
    if m:
        return 2, m[0]
    m = re.search(r"\b(?:just me|only me|just myself|by myself|on my own|alone|solo|"
                  r"i'?m alone)\b", t)
    if m:
        return 1, m[0]
    return None, ""


def _party_type(t: str) -> PartyType | None:
    # "kid friendly places" describes places, not who is coming
    who = re.sub(r"\b(?:kids?|child)[- ]friendly\b", " ", t)
    if re.search(rf"\b(?:{_KIDS}|toddler|bachche|bacche|makkalu)\b", who):
        return PartyType.FAMILY_WITH_KIDS
    if re.search(r"(?:my )?(?:girlfriend|boyfriend|wife|husband|partner|fiance|fiancee|gf|bf)\b|"
                 r"\bcouple\b|\bdate night\b|\b(?:a|dinner|lunch|coffee|first|romantic|movie) date\b|"
                 r"\bfor a date\b|\bon a date\b|\bplan a date\b|\banniversary\b|\bhoneymoon\b", t):
        return PartyType.COUPLE
    if re.search(r"\bcolleagues|team outing|office (?:team|group)\b", t):
        return PartyType.COLLEAGUES
    if re.search(r"\b(?:friends|buddies|gang|dosto|dost|the boys|the girls|mates|college group)\b",
                 t):
        return PartyType.FRIENDS
    if re.search(r"\b(?:my parents|with parents|mom and dad|amma appa|with my mom|with my dad|"
                 r"grandparents|grandma|grandpa|elderly)\b", t):
        return PartyType.PARENTS
    if re.search(r"\b(?:family|parivar)\b", t):
        return PartyType.FAMILY
    if re.search(r"\b(?:solo|alone|by myself|on my own|just me|only me)\b", t):
        return PartyType.SOLO
    return None


def parse_party(utterance: str) -> Party | None:
    t = normalize_utterance(utterance)
    size, phrase = _party_size(t)
    kind = _party_type(t)
    if size is None and kind == PartyType.COUPLE:
        size = 2
    if size == 1 and kind is None:
        kind = PartyType.SOLO
    if size is None and kind is None:
        return None
    return Party(size, kind, phrase or (kind.value if kind else ""))


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
