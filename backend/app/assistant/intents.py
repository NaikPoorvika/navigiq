"""Intent classification (section 18): rules first, LLM for the ambiguous rest.

Rules handle the obvious cases in microseconds with no model. Each rule
carries a confidence; below ACCEPT_THRESHOLD the LLM is consulted (if it is
available), and its answer is itself validated against the closed enum. If
neither is confident and the choice changes the workflow, the assistant asks
one short clarification instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.nlu.lexicon import parse_interests
from app.nlu.quantities import parse_budget
from app.nlu.text import normalize_utterance
from app.nlu.timeparse import resolve_date, resolve_duration, resolve_time_window


class Intent(str, Enum):
    DISCOVER = "DISCOVER"
    SURPRISE_ME = "SURPRISE_ME"
    MOOD_DISCOVERY = "MOOD_DISCOVERY"
    PLACE_SEARCH = "PLACE_SEARCH"
    PLACE_DETAILS = "PLACE_DETAILS"
    SHOW_SIMILAR = "SHOW_SIMILAR"
    SHOW_DIFFERENT = "SHOW_DIFFERENT"
    SAVE_PLACE = "SAVE_PLACE"
    LOCAL_KNOWLEDGE = "LOCAL_KNOWLEDGE"
    COMPARE_PLACES = "COMPARE_PLACES"
    GENERAL_BENGALURU = "GENERAL_BENGALURU"
    CREATE_ITINERARY = "CREATE_ITINERARY"
    MODIFY_ITINERARY = "MODIFY_ITINERARY"
    WHAT_IF_ITINERARY = "WHAT_IF_ITINERARY"
    PLAN_EXPLANATION = "PLAN_EXPLANATION"
    CLARIFICATION_RESPONSE = "CLARIFICATION_RESPONSE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


ACCEPT_THRESHOLD = 0.8


@dataclass
class IntentGuess:
    intent: Intent
    confidence: float
    source: str                   # rules | llm | fallback
    rule: str | None = None
    alternatives: list[tuple[Intent, float]] = field(default_factory=list)


@dataclass
class IntentContext:
    has_plan: bool = False
    has_results: bool = False
    pending_clarification: bool = False
    last_poi_names: list[str] = field(default_factory=list)


def _r(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


WHAT_IF = _r(r"^\s*(what if|what about if|what would happen if|suppose|supposing|hypothetically|"
             r"imagine if|kya ho agar|agar)\b|\bwhat if\b")
MODIFY = _r(
    r"\b(remove|delete|drop|skip|cut|take out|get rid of|replace|swap|switch|substitute)\b|"
    r"\bmake (this|it|the plan|the day|that|my plan)?\s*(cheaper|shorter|longer|more|less|"
    r"quieter|relaxed|romantic|faster|slower|budget|lighter|easier|indoor)|"
    r"\b(cheaper|shorter|less packed|more relaxed|fewer stops|more stops|one more stop|"
    r"less walking)\b|\badd (somewhere|a |an |another|one more|dinner|lunch|breakfast|coffee|"
    r"a stop|something)|\b(start|begin|leave) (later|earlier|at|by|after)\b|"
    r"\b(end|finish|wrap up|be back) (earlier|later|by|at|before)\b|\bi'?m (so )?tired\b|"
    r"\btoo (long|many|much|expensive|packed|tiring|far)\b|\breduce\b|\bshorten\b|\bextend\b|"
    r"\bmove (the|it|that)\b|\binstead of\b|\bno (more )?(museums?|temples?|malls?|cafes?)\b"
    r"(?=.*\b(plan|it|this)\b)|\bchange (the|my|this)\b|\bupdate (the|my) plan\b|"
    r"\bundo\b|\brestore\b|\bgo back to (version|the (previous|original|last))\b")
EXPLAIN_PLAN = _r(r"\bwhy (did you|this|these|the plan|is (the|this) .* (first|last|in)|that order|"
                  r"this order|so early|so late|pick|choose|chose|include)\b|"
                  r"\bexplain (the|this|my) (plan|itinerary|order|schedule)\b|"
                  r"\bhow did you (plan|pick|choose)\b")
CREATE = _r(r"\b(plan|itinerary|schedule|organi[sz]e|map out|chalk out)\b|"
            r"\bmake (me )?a (day|plan|schedule|itinerary)\b|\bday out\b|\bfull day\b")
COMPARE = _r(r"\b(vs\.?|versus|compare|comparison|compared to|better than|which is better|"
             r"difference between|or .{2,40} (for|which is better|better)\b)")
SAVE = _r(r"\b(save|bookmark|favourite|favorite|add to (my )?(saved|favourites|favorites|list|"
          r"wishlist)|remember (this|that|it)|keep (this|that) (place|one))\b")
SIMILAR = _r(r"\b(similar|like this|like that|places like|more like|same vibe|such places|"
             r"something like|alternatives? to|like the (first|second|third|last) one|"
             r"more of (these|those|this|that))\b")
DIFFERENT = _r(r"\b(something (else|different|new|other)|show me (something )?different|"
               r"anything else|other options|different ones|not these|none of these|"
               r"another (one|option|idea|suggestion)|more options|different options|"
               r"completely different|kuch aur|kuch alag|bere enadru)\b")
SURPRISE = _r(r"\bsurprise\b|\brandom\b|\bpick (something|anything|one) for me\b|"
              r"\bdecide for me\b|\byou (decide|choose|pick)\b|\bdealer'?s choice\b|\bfeeling lucky\b")
BORED = _r(r"\bbored\b|\bboring day\b|\bbore ho\b|\bbejaar\b|\bbejar\b|ಬೇಜಾರು|\bnothing to do\b|"
           r"\bkuch karne ko nahi\b|\b(i'?m|i am|feeling|feel) (so |kinda |a bit )?(low|sad|"
           r"restless|stuck|lazy|meh|down)\b")
GREETING = _r(r"^\s*(hi|hello|hey|hii+|namaste|namaskara|yo|good (morning|evening|afternoon)|"
              r"howdy)\b[\s!.?]*$")
KNOWLEDGE = _r(r"\b(why is|why was|why are|who built|who made|who designed|when was|when were|"
               r"history of|story (of|behind)|origin of|significance of|famous for|known for|"
               r"what is special|built by|built in|how old|founded|established|legend|"
               r"meaning of|named after)\b")
DETAILS = _r(r"\b(tell me (more )?about|tell me more|more about|what is|what's|info(rmation)? "
             r"(on|about)|details (of|about|on)|opening hours|timings?|open (today|now|on|at)|"
             r"is .{1,40} open|entry fee|ticket|how much (is|does|for)|when does .{1,40} "
             r"(open|close)|is (it|this|that|.{1,40}) (worth|good for|family|kid|free|crowded|"
             r"safe|nice|suitable))\b")
GENERAL = _r(r"\b(bengaluru|bangalore|namma bengaluru|the city)\b.*\b(weather|climate|culture|"
             r"language|kannada|food|cuisine|traffic|best time|known for|famous for|safe|"
             r"festival|festivals|people|nickname|garden city|silicon valley)\b|"
             r"\b(will it rain|is it raining|weather (today|tomorrow|this weekend)|"
             r"how hot|temperature (today|now))\b|\bwhat language\b|\bkaraga\b|\bkannada\b")
AREA = _r(r"\b(near|around|in|at|close to|nearby|next to|walking distance from|side|"
          r"hatthira|paas|ke paas)\s+([a-z][a-z .'-]{2,40})")
DISCOVER = _r(r"\b(suggest|recommend|recommendation|ideas?|things to do|places to (go|visit|eat|"
              r"see)|where (should|can|do) (i|we)|what (can|should|to) (i |we )?do|anything fun|"
              r"something (fun|interesting|good|nice|peaceful|adventurous|romantic|cheap|"
              r"indoors?|outdoors?|to do)|hidden gems?|escapes?|getaways?|day trips?|"
              r"short trips?|trips? (around|from|near)|weekend|outside (bengaluru|bangalore|"
              r"the city)|within \d+ ?km|best places|"
              r"good places|nice places|spots|show me|any (good|nice)|options for|looking for|"
              r"want to go|wanna go|go out|outing|hang ?out|explore)\b")
OUT_OF_SCOPE = _r(r"\b(write (me )?(a|an) (poem|essay|story|code|song)|python|javascript|"
                  r"stock|crypto|bitcoin|election|politic|mumbai|delhi|chennai|hyderabad|goa|"
                  r"pune|kolkata|manali|ooty|coorg|london|dubai|paris|homework|solve|equation|"
                  r"translate|recipe for|diagnose|medicine|lawyer|legal advice)\b")
CLARIFY_ANSWER = _r(r"^\s*(yes|yeah|yep|sure|ok|okay|no|nope|either|any|anything|whatever|"
                    r"you (decide|choose|pick)|doesn'?t matter|up to you|sounds good|fine)\b")


def classify_rules(message: str, ctx: IntentContext) -> IntentGuess:
    t = normalize_utterance(message)

    def g(intent: Intent, conf: float, rule: str) -> IntentGuess:
        return IntentGuess(intent, conf, "rules", rule)

    if not t:
        return g(Intent.OUT_OF_SCOPE, 0.5, "empty")
    if ctx.pending_clarification and (
            CLARIFY_ANSWER.search(t) or len(t.split()) <= 6 and (
                resolve_time_window(t) or parse_budget(t) or resolve_date(t, _today())
                or resolve_duration(t))):
        return g(Intent.CLARIFICATION_RESPONSE, 0.9, "pending_clarification")
    if GREETING.search(t):
        return g(Intent.MOOD_DISCOVERY, 0.9, "greeting")
    if ctx.has_plan and WHAT_IF.search(t):
        return g(Intent.WHAT_IF_ITINERARY, 0.95, "what_if")
    if ctx.has_plan and EXPLAIN_PLAN.search(t):
        return g(Intent.PLAN_EXPLANATION, 0.9, "explain_plan")
    refers_to_plan = re.search(r"\b(the|this|my|current|our) (plan|itinerary|day|schedule)\b", t)
    if ctx.has_plan and MODIFY.search(t) and (not CREATE.search(t) or refers_to_plan) \
            or ctx.has_plan and re.search(r"^(undo|restore)", t):
        return g(Intent.MODIFY_ITINERARY, 0.9, "modify")
    if COMPARE.search(t) and not CREATE.search(t):
        return g(Intent.COMPARE_PLACES, 0.9, "compare")
    if SAVE.search(t) and not CREATE.search(t):
        return g(Intent.SAVE_PLACE, 0.9, "save")
    if SIMILAR.search(t):
        return g(Intent.SHOW_SIMILAR, 0.88, "similar")
    if DIFFERENT.search(t) and (ctx.has_results or re.search(r"\bshow\b|\bgive\b", t)):
        return g(Intent.SHOW_DIFFERENT, 0.9, "different")
    if SURPRISE.search(t) and not CREATE.search(t):
        return g(Intent.SURPRISE_ME, 0.92, "surprise")
    if CREATE.search(t) and not re.search(r"\bplanetarium\b", t):
        return g(Intent.CREATE_ITINERARY, 0.93, "create")
    if OUT_OF_SCOPE.search(t) and not re.search(r"\b(bengaluru|bangalore)\b", t):
        return g(Intent.OUT_OF_SCOPE, 0.85, "out_of_scope")
    if BORED.search(t):
        return g(Intent.MOOD_DISCOVERY, 0.9, "bored")
    if KNOWLEDGE.search(t):
        return g(Intent.LOCAL_KNOWLEDGE, 0.88, "knowledge")
    if GENERAL.search(t):
        return g(Intent.GENERAL_BENGALURU, 0.86, "general")
    if DETAILS.search(t):
        return g(Intent.PLACE_DETAILS, 0.85, "details")
    budget = parse_budget(t)
    duration = resolve_duration(t)
    if budget and duration and re.search(r"\bi (have|got)\b", t):
        return g(Intent.CREATE_ITINERARY, 0.8, "budget_and_time")
    interests = parse_interests(t)
    area = AREA.search(t)
    generic_places = re.search(r"\b(places?|things|stuff|spots?|interesting|what'?s there|"
                               r"what to do|to do|to see|options)\b", t)
    if area and (not interests.empty or generic_places) and not re.search(
            r"\b(near|around|in|at)\s+(\d|the (morning|evening|afternoon)|morning|evening|"
            r"night|bengaluru|bangalore|the city|city)", t):
        return g(Intent.PLACE_SEARCH, 0.86, "area_search")
    if DISCOVER.search(t) or not interests.empty or budget:
        return g(Intent.DISCOVER, 0.85, "discover")
    if re.search(r"\?$", message.strip()) and len(t.split()) >= 4:
        return g(Intent.GENERAL_BENGALURU, 0.55, "question_fallback")
    if len(t.split()) <= 5:
        # A bare name is most likely "tell me about <place>"; the orchestrator
        # confirms it with a POI lookup before trusting this.
        return g(Intent.PLACE_DETAILS, 0.6, "bare_name")
    return g(Intent.DISCOVER, 0.5, "default")


def _today():
    from app.nlu.timeparse import today_ist
    return today_ist()
