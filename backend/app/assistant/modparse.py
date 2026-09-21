"""Rule-based parsing of plan changes into closed Modification operations.

Covers the common phrasings deterministically; anything these rules do not
recognise goes to the LLM (MODIFY prompt), whose output is validated against
the same closed Modification model. Stop references ("the museum", "the
second one") are resolved by app.assistant.references, never by the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.assistant.references import resolve_reference
from app.assistant.state import ConversationState
from app.nlu.lexicon import parse_interests
from app.nlu.quantities import parse_budget
from app.nlu.text import normalize_utterance
from app.nlu.timeparse import resolve_duration, resolve_time_window


@dataclass
class ParsedMods:
    operations: list[dict] = field(default_factory=list)
    needs_target: bool = False
    ambiguous_candidates: list = field(default_factory=list)
    add_poi_name: str | None = None
    area_name: str | None = None
    matched: bool = False


def _target(message: str, state: ConversationState, pm: ParsedMods) -> int | None:
    ref = resolve_reference(message, state, prefer_plan=True)
    if ref.status == "resolved" and ref.source in ("stops", "focus"):
        if ref.source == "focus":
            seq = next((s_i + 1 for s_i, s in enumerate(state.active_stops)
                        if s.id == ref.poi.id), None)
            return seq
        return ref.seq
    if ref.status == "ambiguous":
        pm.ambiguous_candidates = ref.candidates or []
    pm.needs_target = True
    return None


REMOVE_RE = re.compile(r"\b(remove|delete|drop|skip|cut|take out|get rid of|lose|ditch|"
                       r"can go|has to go|have to go|don'?t want|do not want|not interested in|"
                       r"hata do|hatao|hata|nikal do|nikaal do|tegedu haaki|beda)\b")
REPLACE_RE = re.compile(r"\b(replace|swap|switch|substitute|change|badal do|badlo)\b")
_NAME_STOP = {"a", "an", "the", "some", "visit", "to", "in", "on", "at", "of", "stop", "place",
              "please", "also", "too", "plan", "day", "itinerary", "my", "our", "one", "more"}


def _targets(message: str, state: ConversationState, pm: ParsedMods) -> list[int]:
    """Every stop a removal names: "remove the first and the last" -> [1, 4]."""
    t = normalize_utterance(message)
    parts = [p for p in re.split(r"\band\b|,|&", t) if p.strip()]
    seqs: list[int] = []
    if len(parts) > 1:
        for part in parts:
            probe = ParsedMods()
            seq = _target(part, state, probe)
            if seq and seq not in seqs:
                seqs.append(seq)
    if len(seqs) >= 2:
        return seqs
    seq = _target(message, state, pm)
    return [seq] if seq else []


def _new_category(t: str) -> str | None:
    """The category a replacement asks for: "with a gallery", "for a lake", "to a temple"."""
    m = re.search(r"\b(?:with|for|to|into) (?:a |an |some )?(.+)$", t)
    if m:
        cats = parse_interests(m.group(1)).categories
        if cats:
            return cats[0]
    return None


def _poi_name(phrase: str) -> str | None:
    """A named place ("Cubbon Park", "Bangalore Palace") rather than a kind of place
    ("a park"): words remain after removing interest vocabulary and filler."""
    words = [w for w in re.findall(r"[a-z0-9'.&-]+", phrase)]
    covered = {w for p in parse_interests(phrase).matched_phrases
               for w in p.lstrip("+-").split()}
    leftover = [w for w in words if w not in _NAME_STOP and not any(
        w.startswith(c) or c.startswith(w) for c in covered)]
    return phrase.strip(" .") if leftover else None


def parse_modifications(message: str, state: ConversationState, *,
                        current_cost: int | None = None) -> ParsedMods:
    t = normalize_utterance(message)
    pm = ParsedMods()
    ops = pm.operations
    n_stops = len(state.active_stops)

    replace = REPLACE_RE.search(t) and not re.search(r"\b(start|end|time|budget|pace|area)\b", t)
    if REMOVE_RE.search(t) and not replace:
        for seq in _targets(message, state, pm):
            ops.append({"op": "remove_stop", "target_seq": seq})
    elif replace:
        seq = _target(message, state, pm)
        if seq:
            op = {"op": "replace_stop", "target_seq": seq}
            head = t[:REPLACE_RE.search(t).end()]
            cat = _new_category(t[len(head):]) if len(t) > len(head) else None
            # "swap the museum for a lake": the category after the target
            if cat and cat != state.active_stops[seq - 1].category:
                op["category"] = cat
            ops.append(op)

    meal = re.search(r"\badd (?:a |an |some )?(?:somewhere |some place |a place |a spot |a stop )?"
                     r"(?:for )?(dinner|lunch|breakfast|coffee|snacks?|brunch)\b", t) or \
        re.search(r"\b(dinner|lunch|breakfast|coffee|snacks?) (?:stop|break)\b", t)
    if meal:
        value = meal.group(1)
        value = "snacks" if value.startswith("snack") else ("lunch" if value == "brunch" else value)
        ops.append({"op": "add_meal", "meal": value})
    elif re.search(r"\badd\b", t) and not re.search(r"\badd (more|another|one more) stop", t):
        m = re.search(r"\badd (?:a visit to |in |on )?(.+?)(?: to (?:the |my )?(?:plan|day|"
                      r"itinerary))?(?: somewhere| at the (?:end|start)| in between| too| also)?$", t)
        if m:
            phrase = re.sub(r"^(?:a|an|the|some)\s+", "", m.group(1).strip(" ."))
            name = _poi_name(phrase)
            cats = parse_interests(phrase).categories
            if name:
                pm.add_poi_name = name[:80]
            elif cats:
                ops.append({"op": "prefer_category", "category": cats[0]})

    budget = parse_budget(t)
    bare = re.search(r"\b(?:budget|have only|only have|have|spend|afford|limit)\b[^\d]{0,15}"
                     r"(\d{3,6})\b", t)
    if budget and re.search(r"\b(budget|under|below|within|cheaper|spend|max|rs|have|limit)\b", t):
        ops.append({"op": "set_budget", "amount": budget.amount})
    elif bare and not re.search(r"\b\d{3,6}\s*(?:km|steps|meters|m)\b", t):
        ops.append({"op": "set_budget", "amount": int(bare.group(1))})
    elif re.search(r"\bcheaper\b|\bless expensive\b|\bspend less\b|\btoo expensive\b|\bpricey\b|"
                   r"\bover (?:our|my|the) budget\b|\bsasta\b|\bsaste\b|\bsasti\b|\bkam kharch", t):
        if current_cost and current_cost > 0:
            target = max(0, int(current_cost * 0.75) // 50 * 50)
            ops.append({"op": "set_budget", "amount": target})
        else:
            ops.append({"op": "add_interest", "interest": "budget"})

    shift = re.search(r"\b(start|begin|leave|push|shuru)\b.*\b(later|earlier|baad|pehle)\b|"
                      r"\b(later|earlier) start\b|\b(push|move) (?:everything|it|the plan|the start)"
                      r"(?: back)? by\b|\b\S+ ghante? (baad|pehle)\b", t)
    minutes = resolve_duration(t) or (60 if re.search(r"\ban hour\b", t) else None)
    tw = resolve_time_window(t)
    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if shift and minutes:
        later = bool(re.search(r"\b(later|baad|push|back)\b", shift.group(0)))
        ops.append({"op": "shift_time", "minutes": minutes if later else -minutes})
    elif shift and clock:
        # "start later, around 1 pm": a new start time, not a shift
        h = int(clock.group(1)) % 12 + (12 if clock.group(3) == "pm" else 0)
        ops.append({"op": "set_start_time", "time": f"{h:02d}:{int(clock.group(2) or 0):02d}"})
    else:
        if re.search(r"\b(start|begin|from|leave|leaving|head out|shuru)\b", t) and tw and \
                tw.start_min is not None:
            ops.append({"op": "set_start_time",
                        "time": f"{tw.start_min // 60:02d}:{tw.start_min % 60:02d}"})
        if re.search(r"\b(end|finish|wrap up|be back|back|done|till|until|by)\b", t) and tw and \
                tw.end_min is not None:
            ops.append({"op": "set_end_time",
                        "time": f"{tw.end_min // 60:02d}:{tw.end_min % 60:02d}"})

    if re.search(r"\b(i'?m (so )?tired|we'?re (so )?(tired|exhausted)|exhausted|reduce|"
                 r"fewer stops|fewer places|less packed|too many|shorter|cut down|lighter|"
                 r"take it easy)\b", t) and n_stops > 1 and not any(
            o["op"] in ("remove_stop",) for o in ops):
        m = re.search(r"\b(\d) (?:stops|places)\b", t)
        ops.append({"op": "set_stop_count", "count": int(m.group(1)) if m else n_stops - 1})
        if re.search(r"\btired|exhausted|take it easy|lighter|slower\b", t):
            ops.append({"op": "set_pace", "pace": "relaxed"})
    elif re.search(r"\b(one more stop|more stops|add (another|one more) stop|another stop)\b", t):
        ops.append({"op": "set_stop_count", "count": min(8, n_stops + 1)})
    m = re.search(r"\b(\d|two|three|four|five) (?:stops|places)\b", t)
    if m and not any(o["op"] == "set_stop_count" for o in ops):
        word = {"two": 2, "three": 3, "four": 4, "five": 5}
        ops.append({"op": "set_stop_count", "count": word.get(m.group(1)) or int(m.group(1))})

    if re.search(r"\b(more relaxed|slower|relaxed pace|less rushed|less walking|walk less|"
                 r"not so rushed)\b", t) and not any(o["op"] == "set_pace" for o in ops):
        ops.append({"op": "set_pace", "pace": "relaxed"})
    elif re.search(r"\b(faster|quicker|packed|pack more|more efficient)\b", t) and not any(
            o["op"] == "set_pace" for o in ops):
        ops.append({"op": "set_pace", "pace": "quick"})

    if re.search(r"\b(indoors?|inside)\b", t):
        ops.append({"op": "set_indoor_preference", "preference": "indoor"})
    elif re.search(r"\boutdoors?\b", t):
        ops.append({"op": "set_indoor_preference", "preference": "outdoor"})

    m = re.search(r"\b(?:no more|avoid|without|skip all|no)\s+(museums?|temples?|malls?|cafes?|"
                  r"restaurants?|parks?|lakes?|markets?|churches|bars?|pubs?|galleries|shopping)\b",
                  t)
    if m and not any(o["op"] in ("remove_stop", "replace_stop") for o in ops):
        cats = parse_interests(m.group(1)).categories
        if cats:
            ops.append({"op": "avoid_category", "category": cats[0]})

    m = re.search(r"\bmore (romantic|peaceful|quiet|adventurous|cultural|scenic|relaxing|"
                  r"budget|nature|food|foodie|photogenic|social|kid friendly|kid-friendly|"
                  r"family friendly|kids)\b|\bmake (?:it|this|the plan) (?:more )?"
                  r"(romantic|peaceful|quiet|adventurous|cultural|scenic|relaxing)\b", t)
    if m:
        word = m.group(1) or m.group(2)
        interest = {"food": "foodie", "photogenic": "photography", "kid friendly": "kids",
                    "kid-friendly": "kids", "family friendly": "family"}.get(word, word)
        ops.append({"op": "add_interest", "interest": interest})

    m = re.search(r"\b(?:around|near|in|(?:move|shift) (?:it|the plan|everything) to)\s+"
                  r"([a-z][a-z .'-]{2,40}?)(?:\s+instead)?$", t)
    if m and re.search(r"\b(move|shift|instead|change the area|somewhere around|plan it around)\b",
                       t):
        pm.area_name = m.group(1).strip()
        ops.append({"op": "set_area", "area": pm.area_name})

    m = re.search(r"\b(\d{1,2})[- ]?min(?:ute)?s? (?:transition|buffer|gap)", t)
    if m:
        ops.append({"op": "set_transition_buffer", "minutes": int(m.group(1))})

    # De-duplicate, keeping the first occurrence; several removals of different
    # stops are distinct operations. The closed model caps at 3.
    seen: set = set()
    deduped = []
    for o in ops:
        key = (o["op"], o.get("target_seq")) if o["op"] == "remove_stop" else o["op"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(o)
    pm.operations = deduped[:3]
    pm.matched = bool(pm.operations or pm.add_poi_name or pm.needs_target)
    return pm
