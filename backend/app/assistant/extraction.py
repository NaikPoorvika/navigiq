"""Natural language -> TripSpec (section 39).

Two passes, deterministic post-processing always last:
  1. Rules (app.nlu) read dates, time windows, budgets, party, interests,
     exclusions, pace, meals, dietary needs and area phrases directly.
  2. The LLM (optional) proposes the same fields under a JSON schema whose
     interests are an enum of the controlled vocabulary.

Merge policy - the rules win wherever they found something, and the model is
never allowed to introduce a number or date the user did not say:
  * dates: the model may only supply a date PHRASE, which Python resolves;
  * times / budget / party size from the model are accepted only when the
    same number appears in the user's text (numeric grounding);
  * interests from the model must be in the vocabulary and must not
    contradict an avoided interest;
  * areas and must-include places stay NAMES here - coordinates and POI ids
    are resolved later from the database, never by the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.taxonomy import PartyType, is_valid_category
from app.llm.errors import LLMError
from app.llm.prompts import TRIPSPEC, VOCABULARY, untrusted
from app.nlu.lexicon import parse_interests
from app.nlu.quantities import parse_budget, parse_party, parse_radius_km, parse_stop_count
from app.nlu.text import WORD_NUMBERS, normalize_utterance
from app.nlu.timeparse import (
    minute_of_day, resolve_date, resolve_duration, resolve_time_window, round_up_to_quarter,
)
from app.schemas.tripspec import TripSpec, is_controlled_interest, minutes_to_hhmm

AREA_RE = re.compile(
    r"\b(?:near|around|in|at|close to|nearby|next to|from|hatthira|ke paas|side of)\s+"
    r"([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,3})")
AREA_STOP = {"the", "a", "an", "morning", "evening", "afternoon", "night", "tonight", "today",
             "tomorrow", "bengaluru", "bangalore", "city", "the city", "town", "weekend",
             "noon", "rs", "budget", "mind", "general", "total", "time", "all", "my", "our",
             "front", "person", "advance", "case", "which", "that", "this", "it", "there",
             "about", "least", "most", "rain", "peace", "search", "place", "places",
             "around", "outskirts", "nature", "view", "stock", "hand", "detail", "search of"}
AREA_TRIM = re.compile(r"\s+(for|with|and|but|or|to|under|below|within|by|at|on|from|in|"
                       r"tomorrow|today|tonight|please|this|next|between|budget|rs|around|"
                       r"after|before|till|until|me|us|we|i|if|because|that|which)\b.*$")
MUST_RE = re.compile(r"\b(?:must (?:visit|see|include|go to)|definitely (?:visit|include|go to)|"
                     r"include|have to (?:visit|see|go to)|make sure (?:we|i) (?:visit|see)|"
                     r"start (?:at|with|from)|end (?:at|with))\s+"
                     r"([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,4})")


@dataclass
class Extraction:
    spec: TripSpec
    area_names: list[str] = field(default_factory=list)
    avoid_area_names: list[str] = field(default_factory=list)
    must_include_names: list[str] = field(default_factory=list)
    duration_min: int | None = None
    has_time_info: bool = False
    has_budget: bool = False
    scope: str | None = None
    field_sources: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None


def extract_areas(text: str) -> list[str]:
    t = normalize_utterance(text)
    out = []
    for m in AREA_RE.finditer(t):
        name = AREA_TRIM.sub("", m.group(1)).strip(" .'-")
        name = re.sub(r"^(the|a|an)\s+", "", name)
        if not name or name in AREA_STOP or len(name) < 3:
            continue
        if parse_interests(name).interests and len(name.split()) <= 2 and not re.search(
                r"(nagar|layout|palya|halli|pura|pet|road|circle|park|block|stage|city)$", name):
            continue                      # "in nature", "near lakes" are interests, not areas
        if re.match(r"^\d", name):
            continue
        out.append(name)
    return list(dict.fromkeys(out))[:3]


def extract_must_names(text: str) -> list[str]:
    t = normalize_utterance(text)
    names = []
    for m in MUST_RE.finditer(t):
        name = AREA_TRIM.sub("", m.group(1)).strip(" .'-")
        if name and name not in AREA_STOP and len(name) >= 4:
            names.append(name)
    return list(dict.fromkeys(names))[:4]


def infer_scope(text: str, interests: list[str]) -> str | None:
    t = normalize_utterance(text)
    if re.search(r"\b(outside (the )?(city|bengaluru|bangalore)|out of (the )?(city|town)|"
                 r"escapes?|getaways?|day trips?|short trips?|weekend trips?|road trips?|"
                 r"outskirts|nearby towns?|around (bengaluru|bangalore)|from (bengaluru|bangalore)|"
                 r"near (bengaluru|bangalore)|within \d+ ?km)\b", t):
        return "regional"
    if re.search(r"\b(in|within|inside) (the )?(city|bengaluru|bangalore)\b", t):
        return "city"
    return None


def _numbers_in(text: str) -> set[int]:
    t = normalize_utterance(text)
    nums = {int(float(n.replace(",", ""))) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)}
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*k\b", t):
        nums.add(int(float(m[1]) * 1000))
    for word, value in WORD_NUMBERS.items():
        if isinstance(value, int) and re.search(rf"\b{re.escape(word)}\b", t):
            nums.add(value)
    return nums


def rule_fields(text: str, today: date, now_min: int) -> tuple[dict, dict]:
    t = normalize_utterance(text)
    f: dict = {}
    extra: dict = {}
    d = resolve_date(text, today)
    if d:
        f["date"] = d.value
    tw = resolve_time_window(text)
    if tw:
        extra["has_time_info"] = True
        if tw.start_min is not None:
            f["start_time"] = minutes_to_hhmm(tw.start_min)
        if tw.end_min is not None:
            f["end_time"] = minutes_to_hhmm(tw.end_min)
        if tw.duration_min and tw.start_min is None and tw.end_min is None:
            extra["duration_min"] = tw.duration_min
            day = f.get("date") or today
            start = max(round_up_to_quarter(now_min + 15), 7 * 60) if day == today else 10 * 60
            if day == today and start + 60 > 23 * 60:
                start = 10 * 60
                f["date"] = date.fromordinal(today.toordinal() + 1)
            f["start_time"] = minutes_to_hhmm(start)
            f["end_time"] = minutes_to_hhmm(min(start + tw.duration_min, 23 * 60 + 30))
    b = parse_budget(text)
    if b:
        extra["has_budget"] = True
        if b.per_person:
            f["budget_per_person"] = b.amount
        else:
            f["budget_total"] = b.amount
    p = parse_party(text)
    if p:
        if p.size:
            f["party_size"] = p.size
        if p.party_type:
            f["party_type"] = p.party_type
    ip = parse_interests(text)
    f["interests"] = [i for i in ip.interests if is_controlled_interest(i)][:12]
    f["avoid_interests"] = [i for i in ip.avoid_interests if is_controlled_interest(i)][:12]
    if ip.crowd_averse:
        f["quiet_preference"] = True
        f["crowd_sensitivity"] = "high"
    if "quiet" in ip.moods:
        f["quiet_preference"] = True
    if "romantic" in ip.moods or (p and p.party_type == PartyType.COUPLE):
        f["romantic"] = True
    if re.search(r"\b(relaxed|relaxing|chill|slow|leisurely|not rushed|easy going|easy-going|"
                 r"laid back|lazy|aram se)\b", t):
        f["pace"] = "relaxed"
    elif re.search(r"\b(packed|as many as possible|quick|fast|hectic|lots of places|"
                   r"cover a lot)\b", t):
        f["pace"] = "quick"
    n = parse_stop_count(text)
    if n:
        f["desired_stop_count"] = n
    if re.search(r"\b(indoors?|inside)\b", t):
        f["indoor_preference"] = "indoor"
    elif re.search(r"\boutdoors?\b", t):
        f["indoor_preference"] = "outdoor"
    if re.search(r"\b(rain|raining|rainy|monsoon|baarish)\b", t):
        f["weather_sensitive"] = True
    meals = [m for m in ("breakfast", "lunch", "dinner") if re.search(rf"\b{m}\b", t)]
    if re.search(r"\bbrunch\b", t):
        meals.append("lunch")
    f["meal_preferences"] = list(dict.fromkeys(meals))
    diet = []
    if re.search(r"\b(pure veg|pure vegetarian|jain food)\b", t):
        diet.append("pure_vegetarian")
    elif re.search(r"\b(veg|vegetarian|veggie)\b", t):
        diet.append("vegetarian")
    if re.search(r"\bvegan\b", t):
        diet.append("vegan")
    if re.search(r"\bhalal\b", t):
        diet.append("halal")
    f["dietary_preferences"] = diet
    fam = []
    if re.search(r"\b(kids|children|toddler|my son|my daughter|bachche|makkalu)\b", t):
        fam.append("kids_friendly")
    if re.search(r"\b(parents|elderly|grandparents|seniors|amma appa)\b", t):
        fam.append("senior_friendly")
    f["family_requirements"] = fam
    if re.search(r"\b(wheelchair|accessible|disabled access)\b", t):
        f["accessibility_requirements"] = ["wheelchair_accessible"]
    r = parse_radius_km(text)
    if r:
        f["exploration_radius_km"] = min(90.0, r)
    extra["scope"] = infer_scope(text, f["interests"])
    return f, extra


def merge_llm(fields: dict, llm: dict, text: str, today: date, sources: dict) -> None:
    grounded = _numbers_in(text)
    if "date" not in fields and llm.get("date_phrase"):
        d = resolve_date(str(llm["date_phrase"]), today)
        if d and normalize_utterance(d.phrase) in normalize_utterance(text):
            fields["date"] = d.value
            sources["date"] = "llm_phrase"
    for key in ("start_time", "end_time"):
        v = llm.get(key)
        if key not in fields and isinstance(v, str) and re.fullmatch(r"\d{1,2}:\d{2}", v):
            hour = int(v.split(":")[0])
            if hour in grounded or (hour - 12) in grounded:
                fields[key] = f"{hour:02d}:{v.split(':')[1]}"
                sources[key] = "llm"
    amount = llm.get("budget_amount")
    if "budget_total" not in fields and "budget_per_person" not in fields and \
            isinstance(amount, int) and amount in grounded and amount >= 20:
        fields["budget_per_person" if llm.get("budget_per_person") else "budget_total"] = amount
        sources["budget"] = "llm"
    size = llm.get("party_size")
    if "party_size" not in fields and isinstance(size, int) and 1 <= size <= 20 and \
            size in grounded:
        fields["party_size"] = size
        sources["party_size"] = "llm"
    pt = llm.get("party_type")
    if "party_type" not in fields and pt in {p.value for p in PartyType}:
        fields["party_type"] = PartyType(pt)
        sources["party_type"] = "llm"
    avoid = set(fields.get("avoid_interests", []))
    for key in ("interests", "avoid_interests"):
        extra = [i for i in (llm.get(key) or []) if isinstance(i, str) and i in VOCABULARY]
        if key == "interests":
            extra = [i for i in extra if i not in avoid]
        merged = list(dict.fromkeys(fields.get(key, []) + extra))[:12]
        if len(merged) > len(fields.get(key, [])):
            sources[key] = "rules+llm"
        fields[key] = merged
    fields["interests"] = [i for i in fields["interests"] if i not in set(fields["avoid_interests"])]
    for key in ("pace", "indoor_preference"):
        v = llm.get(key)
        if key not in fields and v in (("quick", "balanced", "relaxed") if key == "pace"
                                       else ("indoor", "outdoor", "any")):
            fields[key] = v
    for key in ("meal_preferences", "dietary_preferences"):
        vals = [v for v in (llm.get(key) or []) if isinstance(v, str)]
        fields[key] = list(dict.fromkeys(fields.get(key, []) + vals))[:5]
    for flag, target in (("quiet", "quiet_preference"), ("romantic", "romantic")):
        if llm.get(flag) is True and target not in fields:
            fields[target] = True
    if llm.get("kids") is True and "kids_friendly" not in fields.get("family_requirements", []):
        fields["family_requirements"] = fields.get("family_requirements", []) + ["kids_friendly"]
    if llm.get("wheelchair") is True:
        fields["accessibility_requirements"] = ["wheelchair_accessible"]
    free = [str(x)[:80] for x in (llm.get("free_text_interests") or []) if isinstance(x, str)]
    fields["free_text_interests"] = free[:10]


def _clean_names(values, text: str) -> list[str]:
    t = normalize_utterance(text)
    out = []
    for v in values or []:
        if not isinstance(v, str):
            continue
        name = normalize_utterance(v).strip(" .")
        # Only names the user actually wrote survive - no invented places.
        if 3 <= len(name) <= 80 and name in t:
            out.append(name)
    return out


async def extract_trip_spec(text: str, *, now: datetime, llm=None, use_llm: bool = True,
                            recorder=None, base: TripSpec | None = None) -> Extraction:
    today, now_min = now.date(), minute_of_day(now)
    fields, extra = rule_fields(text, today, now_min)
    sources = {k: "rules" for k in fields}
    areas = extract_areas(text)
    must = extract_must_names(text)
    avoid_areas: list[str] = []
    ex = Extraction(spec=TripSpec(), duration_min=extra.get("duration_min"),
                    has_time_info=bool(extra.get("has_time_info")),
                    has_budget=bool(extra.get("has_budget")), scope=extra.get("scope"))
    if use_llm and llm is not None and llm.available:
        try:
            res = await llm.run(TRIPSPEC, recorder=recorder, message=untrusted(text, 1500),
                                vocabulary=", ".join(VOCABULARY))
            merge_llm(fields, res.parsed or {}, text, today, sources)
            areas = list(dict.fromkeys(areas + _clean_names(res.parsed.get("areas"), text)))[:3]
            avoid_areas = _clean_names(res.parsed.get("avoid_areas"), text)[:3]
            must = list(dict.fromkeys(must + _clean_names(
                res.parsed.get("must_include_names"), text)))[:4]
            ex.llm_used = True
        except LLMError as exc:
            ex.llm_error = exc.code
            ex.notes.append("Language model unavailable - used rule-based understanding")
    data = base.model_dump() if base is not None else {}
    for k, v in fields.items():
        if v in (None, [], ""):
            continue
        data[k] = v.value if hasattr(v, "value") else v
    data["source_utterance"] = text[:2000]
    data["source"] = "llm" if ex.llm_used else data.get("source", "form")
    if data.get("interests"):
        data["interests"] = [i for i in data["interests"]
                             if i not in set(data.get("avoid_interests", []))]
    data["avoid_areas"] = list(dict.fromkeys(data.get("avoid_areas", []) + avoid_areas))[:5]
    ex.spec = _safe_spec(data, ex)
    ex.area_names = [a for a in areas if a not in avoid_areas]
    ex.avoid_area_names = avoid_areas
    ex.must_include_names = must
    ex.field_sources = sources
    return ex


def _safe_spec(data: dict, ex: Extraction) -> TripSpec:
    """Build the spec; drop any single field that fails validation rather than
    losing the whole extraction, and say so."""
    try:
        return TripSpec.model_validate(data)
    except Exception:  # noqa: BLE001
        pass
    for key in ("end_time", "start_time", "desired_stop_count", "max_stop_count",
                "budget_total", "budget_per_person", "date"):
        if key in data:
            trial = {k: v for k, v in data.items() if k != key}
            try:
                spec = TripSpec.model_validate(trial)
                ex.notes.append(f"Ignored an inconsistent {key.replace('_', ' ')}")
                return spec
            except Exception:  # noqa: BLE001
                data = trial
    return TripSpec(source_utterance=data.get("source_utterance", ""))


def categories_of(spec: TripSpec) -> list[str]:
    return [i for i in spec.interests if is_valid_category(i)]
