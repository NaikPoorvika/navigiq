"""Text normalisation shared by every deterministic NLU component."""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a couple of": 2,
    "couple of": 2, "a couple": 2, "a few": 3, "few": 3, "an": 1, "a": 1, "half a": 0.5,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "chhe": 6,
    "ondu": 1, "eradu": 2, "mooru": 3, "naalku": 4, "aidu": 5,
}


def normalize_utterance(text: str) -> str:
    """Lowercase, unify punctuation and currency so regexes stay simple.

    Kannada and Devanagari script are preserved (NFC), Latin accents folded.
    """
    s = unicodedata.normalize("NFC", text or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("₹", " rs ")
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not (unicodedata.combining(c) and ord(c) < 0x0900))
    s = unicodedata.normalize("NFC", s).lower()
    return _WS.sub(" ", s).strip()


def phrase_pattern(phrase: str, *, plural: bool = False) -> re.Pattern:
    """Whole-word(s) match that also works for non-Latin scripts. With
    `plural`, a Latin-script phrase also matches its regular plural
    ("bookshop" -> "bookshops", "church" -> "churches")."""
    escaped = r"\s+".join(re.escape(p) for p in phrase.split())
    last = phrase.split()[-1] if phrase.split() else ""
    if plural and re.fullmatch(r"[a-z]{3,}", last) and not last.endswith("s"):
        escaped += "(?:es|s)?"
    return re.compile(rf"(?<![\w]){escaped}(?![\w])", re.UNICODE)
