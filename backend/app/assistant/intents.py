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
# Catch-all rules fire on weak evidence (an interest word, an area, "what is").
# On held-out data they were right far less often than the specific patterns
# (docs/reports/evaluation_history.md), so when a model is available it makes
# the call; without one they are still the fallback.
WEAK_RULES = frozenset({"discover", "area_search", "what_is", "default", "question_fallback",
                        "bare_name"})
SEARCH_FAMILY = frozenset({Intent.DISCOVER, Intent.PLACE_SEARCH})


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
             r"imagine if|kya ho agar|agar)\b|\bwhat if\b|"
             r"\bwhat would (it|the plan|this|the day) (look like|change|be)\b")
MODIFY = _r(
    r"\b(remove|delete|drop|skip|cut|take out|get rid of|replace|swap|switch|substitute)\b|"
    r"\bmake (this|it|the plan|the day|that|my plan)?\s*(cheaper|shorter|longer|more|less|"
    r"quieter|relaxed|romantic|faster|slower|budget|lighter|easier|indoor)|"
    r"\b(cheaper|shorter|less packed|more relaxed|fewer stops|more stops|one more stop|"
    r"less walking)\b|\badd (somewhere|a |an |another|one more|dinner|lunch|breakfast|coffee|"
    r"a stop|something)|\b(start|begin|leave) (later|earlier|at|by|after)\b|"
    r"\b(start|begin|leave|end|finish)\b.{0,20}\b(later|earlier)\b|"
    r"\b(sasta|saste|sasti|hata do|hatao|nikal do|badal do|kam kar do|chhota kar do|"
    r"kadime maadi|tegedu haaki|bere haaki)\b|"
    r"\b(end|finish|wrap up|be back) (earlier|later|by|at|before)\b|\bi'?m (so )?tired\b|"
    r"\btoo (long|many|much|expensive|packed|tiring|far)\b|\breduce\b|\bshorten\b|\bextend\b|"
    r"\bmove (the|it|that)\b|\binstead of\b|\bno (more )?(museums?|temples?|malls?|cafes?)\b"
    r"(?=.*\b(plan|it|this)\b)|\bchange (the|my|this)\b|\bupdate (the|my) plan\b|"
    r"\bundo\b|\brestore\b|\bgo back to (version|the (previous|original|last))\b")
EXPLAIN_PLAN = _r(r"\bwhy (did you|this|these|the plan|is (the|this) .* (first|last|in)|that order|"
                  r"this order|so early|so late|pick|choose|chose|include)\b|"
                  r"\bexplain (the|this|my) (plan|itinerary|order|schedule)\b|"
                  r"\bhow did you (plan|pick|choose)\b|\bwhy (you|did you) (chose|choose|picked|"
                  r"pick|put|include|included|order)\b|\bwalk me through\b|"
                  r"\bwhy is there (a |so much |such a )?(gap|break|wait|free time)\b|"
                  r"\bhow did you (decide|arrive|come up)\b")
CREATE = _r(r"\b(plan|itinerary|schedule|organi[sz]e|map out|chalk out)\b|ಪ್ಲಾನ್|ಯೋಜನೆ|"
            r"\bmake (me )?a (day|plan|schedule|itinerary)\b|\bday out\b|\bfull day\b")
COMPARE = _r(r"\b(vs\.?|versus|compare|comparison|compared to|better than|which is better|"
             r"difference between|or .{2,40} (for|which is better|better)\b|"
             r"\bthe (first|second|third|last)( one)? or the (first|second|third|last)\b|"
             r"\bwhich (one|of them|of these|of the two) is (better|closer|cheaper|nearer|"
             r"bigger|quieter|calmer|nicer))")
SAVE = _r(r"\b(save|bookmark|favourite|favorite|add (.{1,50} )?"
          r"to (my )?(saved|favourites|favorites|list|saved list|wishlist)|remember (this|that|it)|keep (this|that) (place|one))\b")
SIMILAR = _r(r"\b(similar|like this|like that|places like|more like|same vibe|such places|"
             r"something like|alternatives? to|like the (first|second|third|last) one|"
             r"more of (these|those|this|that))\b")
DIFFERENT = _r(r"\b(something (else|different|new|other)|show me (something )?different|"
               r"anything else|other options|different ones|not these|none of these|"
               r"another (one|option|idea|suggestion)|more options|different options|"
               r"other (ideas|places|suggestions|options|spots)|"
               r"completely different|kuch aur|kuch alag|bere enadru|"
               r"(don'?t|do not) like (any of )?(these|them|those))\b")
SURPRISE = _r(r"\bsurprise\b|\brandom\b|\bpick (something|anything|one) for me\b|"
              r"\bdecide for me\b|(?<!did )(?<!do )(?<!how )(?<!why )\byou (decide|choose|pick)\b|\bdealer'?s choice\b|\bfeeling lucky\b|"
              r"\broll the dice\b|\bspin the wheel\b|\bsurprise (me|us)\b")
BORED = _r(r"\bbored\b|\bboring day\b|\bbore ho\b|\bbejaar\b|\bbejar\b|ಬೇಜಾರು|\bnothing to do\b|"
           r"\bkuch karne ko nahi\b|\b(i'?m|i am|feeling|feel) (so |kinda |a bit )?(low|sad|"
           r"restless|stuck|lazy|meh|down)\b")
GREETING = _r(r"^\s*(hi|hello|hey|hii+|namaste|namaskara|yo|good (morning|evening|afternoon)|"
              r"howdy)( there| navigiq| again| all| everyone| friend)?\b[\s!.?]*$")
KNOWLEDGE = _r(r"\b(why is|why was|why are|who built|who made|who designed|when was|when were|"
               r"history (of|behind)|story (of|behind)|origin of|significance of|famous for|known for|"
               r"what is special|built by|built in|how old|founded|established|legend|"
               r"meaning of|named after)\b")
DETAILS = _r(r"\b(tell me (more )?about|tell me more|more about|info(rmation)? "
             r"(on|about)|details (of|about|on)|opening hours|timings?|open (today|now|on|at)|"
             r"is .{1,40} open|entry fee|ticket|how much (is|does|for)|"
             r"(when|what time) does .{1,40} (open|close)|(opening|closing|visiting) (time|hours)|"
             r"\bdoes .{1,40} (open|close)|wheelchair|accessible|"
             r"kab (khulta|khulti|khulega|band)|khula hai|entry free|"
             r"yaavaga (open|tegeyutte)|when does .{1,40} "
             r"(open|close)|is (it|this|that|.{1,40}) (worth|good for|family|kid|free|crowded|"
             r"safe|nice|suitable))\b")
WHAT_IS = _r(r"^(what is|what's|whats|what are)\b")
GENERAL = _r(r"\b(bengaluru|bangalore|namma bengaluru|the city)\b.*\b(weather|climate|culture|"
             r"language|kannada|food|cuisine|traffic|best time|known for|famous for|safe|"
             r"festival|festivals|people|nickname|garden city|silicon valley)\b|"
             r"\b(weather|climate|best time (of (the )?year )?to visit|culture|cuisine|"
             r"traffic|nickname)\b.*\b(bengaluru|bangalore|the city)\b|"
             r"\b(will it rain|is it raining|(going to|gonna|likely to) rain|"
             r"weather (today|tomorrow|this weekend)|"
             r"how hot|temperature (today|now))\b|\bwhat language\b|\bkaraga\b|\bkannada\b")
AREA = _r(r"\b(near|around|in|at|close to|nearby|next to|walking distance from|side|"
          r"hatthira|paas|ke paas)\s+([a-z][a-z .'-]{2,40})|"
          r"\b([a-z][a-z'-]{3,30})\s+(mein|alli|nalli|hatthira|ke paas)\b")
DISCOVER = _r(r"\b(suggest|recommend|recommendation|ideas?|things to do|places to (go|visit|eat|"
              r"see)|where (should|can|do) (i|we)|what (can|should|to) (i |we )?do|anything fun|"
              r"something (fun|interesting|good|nice|peaceful|adventurous|romantic|cheap|"
              r"indoors?|outdoors?|to do)|hidden gems?|escapes?|getaways?|day trips?|"
              r"short trips?|trips? (around|from|near)|weekend|outside (bengaluru|bangalore|"
              r"the city)|within \d+ ?km|best places|"
              r"good places|nice places|spots|show me|any (good|nice)|options for|looking for|"
              r"want to go|wanna go|go out|outing|hang ?out|explore|what'?s (fun|good|happening|on)|"
              r"somewhere (to|for|with|quiet|nice|fun|good|new)|where'?s (good|nice|best|a good)|"
              r"kahan (milega|milta|milti)|"
              r"(yelli|elli|ellige) (hog|hogona|hogbahudu|hogodu)\w*|(yenu|enu) maad\w*|"
              r"kahan (jaaye|jaayein|jaa sakte|chale|ghoom\w*)|kya (karein|kare|karu)|"
              r"ghoomne|kuch (acha|accha|chill|mast|fun))\b")
OUT_OF_SCOPE = _r(r"\b(write (me )?(a|an) (poem|essay|story|code|song)|python|javascript|"
                  r"stock|crypto|bitcoin|election|politic|homework|solve|equation|"
                  r"translate|recipe for|diagnose|medicine|lawyer|legal advice)\b")
# A destination outside the 90 km envelope, used as a place to go ("trip to
# Goa", "things to do in Ooty") - not as an adjective ("Mumbai vada pav") or a
# Bengaluru street named after a city ("Mysore Road", "Hosur Road").
ELSEWHERE = _r(r"\b(in|to|at|near|around|visit|visiting|from|of|for)\s+(mumbai|delhi|chennai|"
               r"hyderabad|goa|pune|kolkata|manali|ooty|coorg|kodaikanal|munnar|kerala|mysore|"
               r"mysuru|hampi|gokarna|chikmagalur|wayanad|pondicherry|puducherry|london|dubai|"
               r"paris|singapore|bangkok|new york|tokyo)\b"
               r"(?!\s+(road|rd|bank|pak|circle|layout|colony|street|junction|cross|gate|"
               r"highway|expressway|palace road))")
QUESTION = _r(r"^(who|what|when|where|why|how|is|are|does|do|did|can|could|will|would|should|"
              r"which|whom)\b")
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
                or resolve_duration(t) or re.search(r"\b\d{2,6}\b", t)
                or re.search(r"^(the )?(first|second|third|last|other)( one)?$", t))):
        return g(Intent.CLARIFICATION_RESPONSE, 0.9, "pending_clarification")
    if GREETING.search(t):
        return g(Intent.MOOD_DISCOVERY, 0.9, "greeting")
    if ctx.has_plan and WHAT_IF.search(t):
        return g(Intent.WHAT_IF_ITINERARY, 0.95, "what_if")
    if ctx.has_plan and EXPLAIN_PLAN.search(t):
        return g(Intent.PLAN_EXPLANATION, 0.9, "explain_plan")
    refers_to_plan = re.search(r"\b(the|this|my|current|our)( (original|previous|last|old|"
                               r"first|earlier|current))? (plan|itinerary|day|schedule)\b", t)
    if ctx.has_plan and MODIFY.search(t) and (not CREATE.search(t) or refers_to_plan) \
            or ctx.has_plan and re.search(r"^(undo|restore)", t):
        return g(Intent.MODIFY_ITINERARY, 0.9, "modify")
    if ELSEWHERE.search(t) and not re.search(r"\b(bengaluru|bangalore)\b", t):
        return g(Intent.OUT_OF_SCOPE, 0.85, "elsewhere")
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
    city_subject = re.search(r"\b(bengaluru|bangalore|namma bengaluru|the city)\b", t)
    if GENERAL.search(t) and city_subject:
        return g(Intent.GENERAL_BENGALURU, 0.86, "general")
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
    question = bool(QUESTION.search(t) or message.strip().endswith("?"))
    generic_places = re.search(r"\b(places?|things|stuff|spots?|interesting|what'?s there|"
                               r"what to do|to do|to see|options)\b", t)
    if area and (not interests.empty or generic_places) and not re.search(
            r"\b(near|around|in|at)\s+(\d|the (morning|evening|afternoon)|morning|evening|"
            r"night|bengaluru|bangalore|the city|city|town)\b", t):
        # A question that merely contains an area and an interest word ("what are
        # the visiting hours at the museum?") is not reliably a search: below the
        # accept threshold, so the model decides when it is available.
        return g(Intent.PLACE_SEARCH, 0.72 if question else 0.86, "area_search")
    if DISCOVER.search(t):
        return g(Intent.DISCOVER, 0.85, "discover")
    if not interests.empty or budget:
        # Interest words alone are weak evidence: "does Cubbon Park close at
        # night?" mentions a park and the night but asks for details.
        return g(Intent.DISCOVER, 0.7 if question else 0.85, "discover")
    if WHAT_IS.search(t) and len(t.split()) <= 7:
        return g(Intent.PLACE_DETAILS, 0.75, "what_is")
    if re.search(r"\?$", message.strip()) and len(t.split()) >= 4:
        return g(Intent.GENERAL_BENGALURU, 0.55, "question_fallback")
    if len(t.split()) <= 5:
        # A bare name is most likely "tell me about <place>"; the orchestrator
        # confirms it with a POI lookup before trusting this.
        return g(Intent.PLACE_DETAILS, 0.6, "bare_name")
    return g(Intent.DISCOVER, 0.5, "default")


_NAME_STOP = {"the", "a", "an", "and", "of", "in", "at", "to", "for", "near", "some", "any",
              "good", "best", "nice", "me", "my", "please", "i", "we", "want", "show"}


def looks_like_name(message: str) -> bool:
    """A short message whose words are not all interest/mood vocabulary - "Nandi
    Hills", "bannerghatta national park" - may be a place name. The caller
    confirms with a POI lookup before treating it as one."""
    t = normalize_utterance(message)
    words = re.findall(r"[a-z']+", t)
    if not words or len(words) > 4 or DISCOVER.search(t) or AREA.search(t):
        return False
    covered = [w for p in parse_interests(t).matched_phrases for w in p.lstrip("+-").split()]
    leftover = [w for w in words if w not in _NAME_STOP and not any(
        w.startswith(c) or c.startswith(w) for c in covered)]
    return bool(leftover)


def _today():
    from app.nlu.timeparse import today_ist
    return today_ist()
