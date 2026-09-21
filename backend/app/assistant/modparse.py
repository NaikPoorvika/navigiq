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


def parse_modifications(message: str, state: ConversationState, *,
                        current_cost: int | None = None) -> ParsedMods:
    t = normalize_utterance(message)
    pm = ParsedMods()
    ops = pm.operations
    n_stops = len(state.active_stops)

    if re.search(r"\b(remove|delete|drop|skip|cut|take out|get rid of)\b", t):
        seq = _target(message, state, pm)
        if seq:
            ops.append({"op": "remove_stop", "target_seq": seq})
    elif re.search(r"\b(replace|swap|switch|substitute|change)\b", t) and not re.search(
            r"\b(start|end|time|budget|pace|area)\b", t):
        seq = _target(message, state, pm)
        if seq:
            op = {"op": "replace_stop", "target_seq": seq}
            m = re.search(r"\bwith (?:a |an |some )?(.+)$", t)
            if m:
                cats = parse_interests(m.group(1)).categories
                if cats:
                    op["category"] = cats[0]
            ops.append(op)

    meal = re.search(r"\badd (?:somewhere |some place |a place |a spot )?(?:for )?"
                     r"(dinner|lunch|breakfast|coffee|snacks?)\b", t)
    if meal:
        value = meal.group(1)
        ops.append({"op": "add_meal", "meal": "snacks" if value.startswith("snack") else value})
    elif re.search(r"\badd\b", t) and not re.search(r"\badd (more|another|one more) stop", t):
        m = re.search(r"\badd (?:a visit to |in |on )?(.+?)(?: to (?:the |my )?(?:plan|day|"
                      r"itinerary))?$", t)
        if m and not parse_interests(m.group(1)).categories:
            pm.add_poi_name = m.group(1).strip(" .")[:80]
        elif m:
            cats = parse_interests(m.group(1)).categories
            if cats:
                ops.append({"op": "prefer_category", "category": cats[0]})

    budget = parse_budget(t)
    if budget and re.search(r"\b(budget|under|below|within|cheaper|spend|max|rs)\b", t):
        ops.append({"op": "set_budget", "amount": budget.amount})
    elif re.search(r"\bcheaper\b|\bless expensive\b|\bspend less\b|\btoo expensive\b", t):
        if current_cost and current_cost > 0:
            target = max(0, int(current_cost * 0.75) // 50 * 50)
            ops.append({"op": "set_budget", "amount": target})
        else:
            ops.append({"op": "add_interest", "interest": "budget"})

    shift = re.search(r"\b(start|begin|leave)\b.*\b(later|earlier)\b|\b(later|earlier) start\b", t)
    if shift:
        minutes = resolve_duration(t) or (60 if re.search(r"\ban hour\b", t) else None)
        if minutes:
            ops.append({"op": "shift_time",
                        "minutes": minutes if "later" in shift.group(0) else -minutes})
    else:
        tw = resolve_time_window(t)
        if re.search(r"\b(start|begin|from)\b", t) and tw and tw.start_min is not None:
            ops.append({"op": "set_start_time",
                        "time": f"{tw.start_min // 60:02d}:{tw.start_min % 60:02d}"})
        if re.search(r"\b(end|finish|wrap up|be back|till|until|by)\b", t) and tw and \
                tw.end_min is not None:
            ops.append({"op": "set_end_time",
                        "time": f"{tw.end_min // 60:02d}:{tw.end_min % 60:02d}"})

    if re.search(r"\b(i'?m (so )?tired|reduce|fewer stops|less packed|too many|shorter|"
                 r"cut down|lighter|take it easy)\b", t) and n_stops > 1 and not any(
            o["op"] in ("remove_stop",) for o in ops):
        ops.append({"op": "set_stop_count", "count": n_stops - 1})
        if re.search(r"\btired|take it easy|lighter\b", t):
            ops.append({"op": "set_pace", "pace": "relaxed"})
    elif re.search(r"\b(one more stop|more stops|add (another|one more) stop|another stop)\b", t):
        ops.append({"op": "set_stop_count", "count": min(8, n_stops + 1)})
    m = re.search(r"\b(\d) stops\b", t)
    if m and not any(o["op"] == "set_stop_count" for o in ops):
        ops.append({"op": "set_stop_count", "count": int(m.group(1))})

    if re.search(r"\b(more relaxed|slower|relaxed pace|less rushed)\b", t) and not any(
            o["op"] == "set_pace" for o in ops):
        ops.append({"op": "set_pace", "pace": "relaxed"})
    elif re.search(r"\b(faster|quicker|packed|pack more|more efficient)\b", t):
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
                  r"budget|nature|food|foodie|photogenic|social)\b|\bmake (?:it|this|the plan) "
                  r"(?:more )?(romantic|peaceful|quiet|adventurous|cultural|scenic|relaxing)\b", t)
    if m:
        word = m.group(1) or m.group(2)
        interest = {"food": "foodie", "photogenic": "photography"}.get(word, word)
        ops.append({"op": "add_interest", "interest": interest})

    m = re.search(r"\b(?:around|near|in|move (?:it|the plan) to)\s+([a-z][a-z .'-]{2,40})$", t)
    if m and re.search(r"\b(move|shift|instead|change the area|somewhere around|plan it around)\b",
                       t):
        pm.area_name = m.group(1).strip()
        ops.append({"op": "set_area", "area": pm.area_name})

    m = re.search(r"\b(\d{1,2})[- ]?min(?:ute)?s? (?:transition|buffer|gap)", t)
    if m:
        ops.append({"op": "set_transition_buffer", "minutes": int(m.group(1))})

    # De-duplicate by op, keeping the first occurrence; the closed model caps at 3.
    seen: set[str] = set()
    deduped = []
    for o in ops:
        if o["op"] in seen:
            continue
        seen.add(o["op"])
        deduped.append(o)
    pm.operations = deduped[:3]
    pm.matched = bool(pm.operations or pm.add_poi_name or pm.needs_target)
    return pm
