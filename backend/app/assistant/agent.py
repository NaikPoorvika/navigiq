"""The bounded NavigIQ agent (sections 55-56).

A finite-state machine with an explicit transition table. Each intent maps
to a fixed workflow of states; every state change is checked against the
table and every tool call goes through the typed registry, and both are
counted against hard limits enforced in Python (app.assistant.trace). There
are no open-ended loops: the only model-driven step (read-only tool selection
for general questions) runs at most MAX_TOOL_SELECT_ROUNDS rounds.

The LLM understands (intent, extraction, modification ops) and communicates
(explanations, grounded answers). Everything it produces is validated; every
fact, ranking, schedule and check comes from deterministic services.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

import structlog

from app.assistant import intents as I
from app.assistant.extraction import extract_areas, extract_trip_spec, infer_scope
from app.assistant.modparse import parse_modifications
from app.assistant.references import resolve_reference
from app.assistant.response import (
    AFTER_RESULTS, ERROR_MESSAGES, MOOD_CHIPS, TIME_CHIPS, AssistantResponse, Suggestion,
)
from app.assistant.state import ConversationState, LastPOI, PendingClarification
from app.assistant.tools import REGISTRY, Role, ToolContext, ToolRegistry, ToolResult
from app.assistant.trace import MAX_CLARIFICATIONS, LimitExceeded, Trace
from app.domain.taxonomy import category_catalog, is_valid_category, is_valid_mood
from app.llm.errors import LLMError
from app.llm.prompts import EXPLAIN, INTENT, MODIFY, TOOL_SELECT, VOCABULARY, untrusted
from app.nlu.lexicon import parse_interests
from app.nlu.quantities import parse_budget, parse_party
from app.nlu.text import normalize_utterance
from app.nlu.timeparse import now_ist
from app.services.planning.store import Owner
from app.services.planning.validator.itinerary import unsupported_numbers
from app.services.recommendation.scoring import reason_text

logger = structlog.get_logger("app.assistant")

STATES = ("RECEIVE", "CLASSIFY", "CLARIFY", "DISCOVER", "SEARCH", "RETRIEVE", "EXTRACT", "PLAN",
          "VALIDATE", "MODIFY", "COMPARE", "ANSWER", "EXPLAIN", "COMPLETE", "FAIL")

TRANSITIONS: dict[str, frozenset[str]] = {
    "RECEIVE": frozenset({"CLASSIFY", "FAIL"}),
    "CLASSIFY": frozenset({"CLARIFY", "DISCOVER", "SEARCH", "RETRIEVE", "EXTRACT", "MODIFY",
                           "COMPARE", "ANSWER", "EXPLAIN", "COMPLETE", "FAIL"}),
    "CLARIFY": frozenset({"COMPLETE", "FAIL"}),
    "DISCOVER": frozenset({"EXPLAIN", "CLARIFY", "COMPLETE", "FAIL"}),
    "SEARCH": frozenset({"RETRIEVE", "EXPLAIN", "CLARIFY", "COMPLETE", "FAIL"}),
    "RETRIEVE": frozenset({"ANSWER", "COMPLETE", "FAIL"}),
    "EXTRACT": frozenset({"CLARIFY", "PLAN", "COMPLETE", "FAIL"}),
    "PLAN": frozenset({"VALIDATE", "COMPLETE", "FAIL"}),
    "VALIDATE": frozenset({"EXPLAIN", "COMPLETE", "FAIL"}),
    "MODIFY": frozenset({"VALIDATE", "CLARIFY", "COMPLETE", "FAIL"}),
    "COMPARE": frozenset({"EXPLAIN", "COMPLETE", "FAIL"}),
    "ANSWER": frozenset({"COMPLETE", "FAIL"}),
    "EXPLAIN": frozenset({"COMPLETE", "FAIL"}),
    "COMPLETE": frozenset(),
    "FAIL": frozenset(),
}

MAX_TOOL_SELECT_ROUNDS = 1
LLM_INTENT_MIN = 0.6


class IllegalTransition(RuntimeError):
    code = "ILLEGAL_TRANSITION"


class ToolFailure(RuntimeError):
    def __init__(self, result: ToolResult):
        super().__init__(result.message or result.error_code)
        self.result = result


def _poi_last(item: dict) -> LastPOI:
    return LastPOI(id=item["id"], name=item["name"], category=item["category"])


def _cat_name(key: str) -> str:
    info = category_catalog().get(key)
    return info.name.lower() if info else key.replace("_", " ")


class Agent:
    def __init__(self, *, db, owner: Owner, role: Role, state: ConversationState,
                 conversation_id: str, llm=None, gateway=None, now: datetime | None = None,
                 registry: ToolRegistry = REGISTRY) -> None:
        self.state = state
        self.conversation_id = conversation_id
        self.llm = llm
        self.gateway = gateway
        self.registry = registry
        self.now = now or now_ist()
        self.trace = Trace()
        self.current: str | None = None
        self.llm_used = False
        seed = int(hashlib.sha256(f"{owner.user_id or owner.session_id}:{self.now.date()}:"
                                  f"{state.turn_count}".encode()).hexdigest()[:8], 16)
        self.ctx = ToolContext(db=db, owner=owner, role=role, trace=self.trace, llm=llm,
                               gateway=gateway, now=self.now, extra={"seed": seed})

    # --- machinery ---------------------------------------------------------------------------

    def goto(self, state: str) -> None:
        if state not in TRANSITIONS:
            raise IllegalTransition(f"unknown state {state}")
        if self.current is not None and state not in TRANSITIONS[self.current]:
            raise IllegalTransition(f"{self.current} -> {state} is not allowed")
        self.trace.enter(state)
        self.current = state

    async def tool(self, name: str, **args: Any) -> Any:
        res = await self.registry.call(name, args, self.ctx)
        if not res.ok:
            raise ToolFailure(res)
        return res.data

    def record_llm(self, rec) -> None:
        self.trace.record_llm(rec)
        if rec.status == "ok":
            self.llm_used = True

    @property
    def llm_ok(self) -> bool:
        return self.llm is not None and self.llm.available and self.trace.llm_budget_left()

    def respond(self, intent: str, text: str, ui_type: str = "message", *, data=None,
                sources=None, warnings=None, suggestions=None, ui_extra=None) -> AssistantResponse:
        return AssistantResponse(
            conversation_id=self.conversation_id, intent=intent, text=text,
            data=data or {}, ui={"type": ui_type, **(ui_extra or {})}, sources=sources or [],
            warnings=list(dict.fromkeys(warnings or [])), suggestions=suggestions or [],
            trace_id=str(self.trace.trace_id), llm_used=self.llm_used,
            llm_available=bool(self.llm is not None and self.llm.available))

    # --- entry point ------------------------------------------------------------------------------

    async def run(self, message: str) -> AssistantResponse:
        message = (message or "").strip()[:2000]
        intent_name = "OUT_OF_SCOPE"
        try:
            self.goto("RECEIVE")
            self.goto("CLASSIFY")
            guess = await self.classify(message)
            intent_name = guess.intent.value
            self.trace.intent = intent_name
            self.trace.intent_confidence = guess.confidence
            self.trace.intent_source = guess.source
            resp = await self.dispatch(guess, message)
            if self.current not in ("COMPLETE", "FAIL"):
                self.goto("COMPLETE")
            self.trace.status = "complete" if self.current == "COMPLETE" else "failed"
        except LimitExceeded as exc:
            self._fail("AGENT_LIMIT")
            logger.warning("agent_limit", limit=exc.limit, trace_id=str(self.trace.trace_id))
            resp = self.respond(intent_name, ERROR_MESSAGES["AGENT_LIMIT"], "error",
                                data={"error": {"code": "AGENT_LIMIT", "limit": exc.limit}})
        except Exception as exc:  # noqa: BLE001 - never leak internals
            code = "DATABASE_UNAVAILABLE" if _is_db_error(exc) else "INTERNAL"
            self._fail(code)
            logger.exception("agent_failure", trace_id=str(self.trace.trace_id),
                             error=type(exc).__name__)
            try:
                await self.ctx.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            resp = self.respond(intent_name, ERROR_MESSAGES[code], "error",
                                data={"error": {"code": code}})
        self.state.note_turn(intent_name)
        return resp

    def _fail(self, code: str) -> None:
        self.trace.status = "failed"
        self.trace.error_code = code
        if self.current is not None and "FAIL" in TRANSITIONS.get(self.current, ()):
            try:
                self.trace.enter("FAIL")
            except LimitExceeded:
                pass
            self.current = "FAIL"

    # --- classification --------------------------------------------------------------------------

    async def classify(self, message: str) -> I.IntentGuess:
        ctx = I.IntentContext(has_plan=self.state.active_itinerary_id is not None,
                              has_results=bool(self.state.last_pois),
                              pending_clarification=self.state.pending_clarification is not None)
        guess = I.classify_rules(message, ctx)
        if guess.confidence >= I.ACCEPT_THRESHOLD:
            return guess
        if guess.rule == "bare_name":
            try:
                found = await self.tool("resolve_poi_name", name=message[:80])
                if found["resolved"]:
                    return I.IntentGuess(I.Intent.PLACE_DETAILS, 0.85, "rules", "bare_name_poi")
            except ToolFailure:
                pass
        if self.llm_ok:
            try:
                res = await self.llm.run(
                    INTENT, recorder=self.record_llm, message=untrusted(message, 1000),
                    pending_question=(self.state.pending_clarification.question
                                      if self.state.pending_clarification else "none"),
                    has_plan="yes" if ctx.has_plan else "no")
                p = res.parsed or {}
                value = p.get("intent")
                conf = p.get("confidence")
                if value in I.Intent._value2member_map_ and isinstance(conf, (int, float)):
                    llm_guess = I.Intent(value)
                    if llm_guess in (I.Intent.MODIFY_ITINERARY, I.Intent.WHAT_IF_ITINERARY,
                                     I.Intent.PLAN_EXPLANATION) and not ctx.has_plan:
                        llm_guess = I.Intent.CREATE_ITINERARY
                    if float(conf) >= LLM_INTENT_MIN:
                        return I.IntentGuess(llm_guess, float(conf), "llm", None,
                                             [(guess.intent, guess.confidence)])
            except LLMError:
                pass
        return I.IntentGuess(guess.intent, guess.confidence, "fallback", guess.rule)

    async def dispatch(self, guess: I.IntentGuess, message: str) -> AssistantResponse:
        it = guess.intent
        handlers = {
            I.Intent.DISCOVER: self.discover, I.Intent.PLACE_SEARCH: self.discover,
            I.Intent.MOOD_DISCOVERY: self.mood, I.Intent.SURPRISE_ME: self.surprise,
            I.Intent.SHOW_DIFFERENT: self.different, I.Intent.SHOW_SIMILAR: self.similar,
            I.Intent.PLACE_DETAILS: self.details, I.Intent.SAVE_PLACE: self.save,
            I.Intent.LOCAL_KNOWLEDGE: self.knowledge, I.Intent.GENERAL_BENGALURU: self.knowledge,
            I.Intent.COMPARE_PLACES: self.compare, I.Intent.CREATE_ITINERARY: self.create_plan,
            I.Intent.MODIFY_ITINERARY: self.modify, I.Intent.WHAT_IF_ITINERARY: self.what_if,
            I.Intent.PLAN_EXPLANATION: self.explain_plan,
            I.Intent.CLARIFICATION_RESPONSE: self.clarification_response,
            I.Intent.OUT_OF_SCOPE: self.out_of_scope,
        }
        self.trace.workflow = handlers[it].__name__
        if it != I.Intent.CLARIFICATION_RESPONSE:
            self.state.pending_clarification = None
        return await handlers[it](message, it.value)

    # --- discovery -------------------------------------------------------------------------------------

    def discovery_args(self, message: str) -> tuple[dict, dict]:
        t = normalize_utterance(message)
        ip = parse_interests(message)
        args: dict = {}
        info: dict = {"interests": ip.interests, "areas": extract_areas(message)}
        cats = [i for i in ip.categories]
        tags = [i for i in ip.tags if i not in ("food",) or not cats]
        args["interests"] = list(dict.fromkeys(cats + tags))[:12]
        args["moods"] = [m for m in ip.moods if is_valid_mood(m)][:8]
        args["avoid"] = ip.avoid_interests[:12]
        party = parse_party(message)
        if party and party.party_type:
            args["party_type"] = party.party_type
        budget = parse_budget(message)
        if budget:
            size = (party.size if party and party.size else 1)
            args["budget_per_person"] = budget.amount if budget.per_person else max(
                0, budget.amount // max(1, size))
            info["budget"] = budget.amount
        scope = infer_scope(message, ip.interests)
        if scope:
            args["scope"] = scope
        if re.search(r"\b(right now|now|at the moment|currently)\b", t):
            args["when"] = "now"
        elif re.search(r"\b(tonight|this evening|night out)\b", t):
            args["when"] = "tonight"
        elif re.search(r"\btoday\b", t):
            args["when"] = "today"
        elif re.search(r"\btomorrow\b", t):
            args["when"] = "tomorrow"
        elif re.search(r"\b(this )?weekend\b", t) and scope != "regional":
            args["when"] = "weekend"
        if ip.crowd_averse or "quiet" in ip.moods:
            args["quiet"] = True
        if "kids" in ip.tags:
            args["kids"] = True
        if re.search(r"\b(indoors?|inside)\b", t):
            args["indoor_preference"] = "indoor"
        diet = []
        if re.search(r"\b(pure veg|pure vegetarian)\b", t):
            diet.append("pure_vegetarian")
        elif re.search(r"\b(veg|vegetarian)\b", t):
            diet.append("vegetarian")
        if diet:
            args["dietary"] = diet
        return args, info

    async def _weather_flag(self, when: str | None, message: str) -> tuple[bool | None, list[str]]:
        t = normalize_utterance(message)
        if when not in ("now", "today", "tonight", "tomorrow") and not re.search(
                r"\b(rain|raining|rainy|weather|monsoon)\b", t):
            return None, []
        try:
            from datetime import timedelta
            on = self.now.date() + timedelta(days=1 if when == "tomorrow" else 0)
            w = await self.tool("get_weather", on=on.isoformat())
        except ToolFailure:
            return None, [ERROR_MESSAGES["WEATHER_UNAVAILABLE"]]
        if not w.get("available"):
            return None, [ERROR_MESSAGES["WEATHER_UNAVAILABLE"]]
        return bool(w.get("heavy_rain_expected") or w.get("rain_likely")), []

    async def discover(self, message: str, intent: str, *, mode: str = "discover",
                       override: dict | None = None) -> AssistantResponse:
        self.goto("DISCOVER" if intent != "PLACE_SEARCH" else "SEARCH")
        args, info = self.discovery_args(message)
        if override:
            args.update(override)
        if re.search(r"\bhidden gems?\b|\boffbeat\b|\bunderrated\b|\blesser[- ]known\b",
                     normalize_utterance(message)):
            mode = "hidden_gems"
        warnings: list[str] = []
        rain, w = await self._weather_flag(args.get("when"), message)
        warnings += w
        if rain is not None:
            args["rain_expected"] = rain
        area = info["areas"][0] if info["areas"] else None
        if area:
            args["area"] = area
            args.pop("scope", None)
        try:
            res = await self.tool("recommend_pois", mode=mode, limit=8, **args)
        except ToolFailure as f:
            if f.result.error_code == "AREA_NOT_FOUND" and area:
                args.pop("area", None)
                warnings.append(f"I couldn't find '{area}' on the map, so these are from across "
                                "the city.")
                res = await self.tool("recommend_pois", mode=mode, limit=8, **args)
                area = None
            else:
                raise
        items = res["items"]
        if not items:
            self.goto("COMPLETE")
            return self.respond(intent, ERROR_MESSAGES["NO_CANDIDATES"], "poi_list",
                                data={"items": [], "query": args, "meta": res["meta"]},
                                warnings=warnings,
                                suggestions=[Suggestion(label="Surprise me", message="Surprise me"),
                                             Suggestion(label="Anywhere in the city",
                                                        message="Show me popular places in the city")])
        self.state.remember_results([_poi_last(i) for i in items],
                                    {"args": {k: (v.value if hasattr(v, "value") else v)
                                              for k, v in args.items()}, "mode": mode})
        await self._record_shown([i["id"] for i in items], intent)
        for i in items:
            i["why"] = [reason_text(r) for r in i["reason_codes"][:3]]
        text = self.describe_results(items, args, area, mode, res["meta"])
        text = await self.explain_text(message, items, text)
        self.goto("EXPLAIN")
        return self.respond(intent, text, "poi_list" if intent == "PLACE_SEARCH" else "discovery",
                            data={"items": items, "query": args, "meta": res["meta"]},
                            warnings=warnings, suggestions=AFTER_RESULTS)

    def describe_results(self, items, args, area, mode, meta) -> str:
        bits = []
        if args.get("moods"):
            bits.append(" & ".join(m.replace("_", " ") for m in args["moods"][:2]))
        cats = [i for i in args.get("interests", []) if is_valid_category(i)]
        what = " and ".join(_cat_name(c) + ("s" if not _cat_name(c).endswith("s") else "")
                            for c in cats[:2]) if cats else "ideas"
        head = {"hidden_gems": "Some lesser-known finds", "surprise": "A surprise",
                "different": "Something different"}.get(mode, f"Here are {len(items)}")
        where = f" near {area.title()}" if area else {
            "regional": " outside the city", "anywhere": " around Bengaluru"}.get(
            meta.get("scope"), " in Bengaluru")
        mood = f" for something {bits[0]}" if bits else ""
        budget = f" under ₹{args['budget_per_person']} per person" if args.get(
            "budget_per_person") else ""
        return f"{head} {what}{mood}{where}{budget}.".replace("  ", " ")

    async def explain_text(self, request: str, items: list[dict], fallback: str) -> str:
        """Optional LLM phrasing over deterministic facts; rejected if it adds numbers."""
        if not self.llm_ok:
            return fallback
        facts = [{"name": i["name"], "category": i["category"], "locality": i.get("locality"),
                  "reasons": i["reason_codes"][:4]} for i in items[:5]]
        try:
            res = await self.llm.run(EXPLAIN, recorder=self.record_llm,
                                     request=untrusted(request, 500), facts=str(facts))
            text = str((res.parsed or {}).get("text", "")).strip()
        except LLMError:
            return fallback
        allowed = {str(len(items))} | set(re.findall(r"\d+", request)) | set(
            re.findall(r"\d+", fallback))
        if not text or unsupported_numbers(text, allowed) or len(text) > 600:
            return fallback
        names = {i["name"].lower() for i in items}
        quoted = re.findall(r"\*\*(.+?)\*\*", text)
        if any(q.lower() not in names for q in quoted):
            return fallback
        return text

    async def _record_shown(self, ids: list[int], surface: str) -> None:
        from app.services.interactions import record_shown
        try:
            await record_shown(self.ctx.db, self.ctx.owner, ids, surface)
        except Exception:  # noqa: BLE001 - novelty tracking must never break a response
            await self.ctx.db.rollback()

    async def mood(self, message: str, intent: str) -> AssistantResponse:
        ip = parse_interests(message)
        if not ip.empty:
            return await self.discover(message, "DISCOVER")
        self.goto("DISCOVER")
        res = await self.tool("recommend_pois", mode="surprise", limit=3)
        items = res["items"]
        for i in items:
            i["why"] = [reason_text(r) for r in i["reason_codes"][:3]]
        self.state.pending_clarification = PendingClarification(
            kind="mood", question="What mood are you in?",
            options=[c.label for c in MOOD_CHIPS])
        if items:
            self.state.remember_results([_poi_last(i) for i in items], {"args": {}, "mode": "surprise"})
        greeting = normalize_utterance(message) in ("hi", "hello", "hey", "namaste", "namaskara")
        text = ("Hi! What are you in the mood for?" if greeting else
                "Let's fix that. What mood are you in?") + (
            " Or start with one of these:" if items else "")
        self.goto("CLARIFY")
        return self.respond(intent, text, "discovery", data={"items": items, "mood_prompt": True},
                            suggestions=MOOD_CHIPS)

    async def surprise(self, message: str, intent: str) -> AssistantResponse:
        args, info = self.discovery_args(message)
        mood = next(iter(args.get("moods", [])), None)
        self.goto("DISCOVER")
        res = await self.tool("get_surprise_recommendations", mood=mood,
                              budget_per_person=args.get("budget_per_person"),
                              area=info["areas"][0] if info["areas"] else None, limit=3)
        items = res["items"]
        if not items:
            self.goto("COMPLETE")
            return self.respond(intent, ERROR_MESSAGES["NO_CANDIDATES"], "discovery",
                                data={"items": []}, suggestions=MOOD_CHIPS)
        for i in items:
            i["why"] = [reason_text(r) for r in i["reason_codes"][:3]]
        self.state.remember_results([_poi_last(i) for i in items],
                                    {"args": {"moods": [mood] if mood else []}, "mode": "surprise"})
        self.state.focus(_poi_last(items[0]))
        await self._record_shown([i["id"] for i in items], intent)
        hero = items[0]
        where = f" in {hero['locality']}" if hero.get("locality") else ""
        text = f"How about {hero['name']}{where}?"
        if hero.get("short_description"):
            text += f" {hero['short_description']}"
        self.goto("EXPLAIN")
        return self.respond(intent, text, "discovery",
                            data={"items": items, "hero_id": hero["id"], "meta": res["meta"]},
                            suggestions=[Suggestion(label="Another surprise", message="Surprise me again"),
                                         *AFTER_RESULTS[:2]])

    async def different(self, message: str, intent: str) -> AssistantResponse:
        last = self.state.last_request or {"args": {}, "mode": "discover"}
        previous = [p.id for p in self.state.last_pois]
        if not previous:
            return await self.surprise(message, "SURPRISE_ME")
        self.ctx.extra["previous_ids"] = previous
        override = dict(last.get("args") or {})
        override["exclude_ids"] = sorted(set(previous) | set(self.state.shown_history[-40:]))[:100]
        extra_args, _ = self.discovery_args(message)
        for k in ("moods", "interests", "budget_per_person", "area"):
            if extra_args.get(k):
                override[k] = extra_args[k]
        if re.search(r"\bcompletely different\b|\btotally different\b", normalize_utterance(message)):
            override["avoid"] = list(dict.fromkeys(list(override.get("avoid", [])) + [
                p.category for p in self.state.last_pois]))[:12]
            override.pop("interests", None)
            override.pop("moods", None)
        return await self.discover(message if override.get("area") else "", "SHOW_DIFFERENT",
                                   mode="different", override=override)

    # --- places --------------------------------------------------------------------------------------

    async def _find_poi(self, message: str, intent: str, *, strip: str) -> tuple[dict | None, AssistantResponse | None]:
        """Resolve which place the user means: a named place, else a reference."""
        name = re.sub(strip, " ", normalize_utterance(message))
        name = re.sub(r"[?!.,]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        generic = re.fullmatch(r"(it|this|that|this place|that place|this one|that one|"
                               r"the (first|second|third|last) one|there|)", name)
        if name and not generic and len(name) >= 3:
            found = await self.tool("resolve_poi_name", name=name[:80])
            if found["resolved"]:
                return {"id": found["poi_id"]}, None
            if found["candidates"] and len(name) >= 4 and found["candidates"][0]["similarity"] >= 0.45:
                options = found["candidates"][:3]
                self.state.pending_clarification = PendingClarification(
                    kind="which_place", question="Which place do you mean?",
                    options=[o["name"] for o in options],
                    context={"intent": intent, "ids": [o["poi_id"] for o in options]})
                self.goto("CLARIFY")
                return None, self.respond(intent, "Which place do you mean?", "clarification",
                                          data={"options": options},
                                          suggestions=[Suggestion(label=o["name"], message=o["name"])
                                                       for o in options])
        ref = resolve_reference(message, self.state)
        if ref.status == "resolved":
            return {"id": ref.poi.id}, None
        if ref.status == "ambiguous" and ref.candidates:
            options = [{"poi_id": c.id, "name": c.name} for c in ref.candidates[:4]]
            self.state.pending_clarification = PendingClarification(
                kind="which_place", question="Which one do you mean?",
                options=[o["name"] for o in options],
                context={"intent": intent, "ids": [o["poi_id"] for o in options]})
            self.goto("CLARIFY")
            return None, self.respond(intent, "Which one do you mean?", "clarification",
                                      data={"options": options},
                                      suggestions=[Suggestion(label=o["name"], message=o["name"])
                                                   for o in options])
        return None, None

    DETAILS_STRIP = (r"\b(tell me (more )?about|tell me more|more about|what is|what's|info(rmation)? "
                     r"(on|about)|details (of|about|on)|is|are|it|open|today|now|tomorrow|opening "
                     r"hours|timings?|hours|entry fee|ticket( price)?|how much|does|cost|costs|"
                     r"worth visiting|worth it|worth|good for|family friendly|kid friendly|free|"
                     r"crowded|safe|photography|the|a|visit|visiting|place|at|of|for|when|close|"
                     r"closes|opens|please|lalbagh's)\b")

    async def details(self, message: str, intent: str) -> AssistantResponse:
        self.goto("SEARCH")
        target, clarification = await self._find_poi(message, intent, strip=self.DETAILS_STRIP)
        if clarification is not None:
            return clarification
        if target is None:
            return await self.knowledge(message, "LOCAL_KNOWLEDGE", entered=True)
        detail = await self.tool("get_poi", poi_id=target["id"])
        self.state.focus(LastPOI(id=detail["id"], name=detail["name"], category=detail["category"]))
        t = normalize_utterance(message)
        facts: list[str] = []
        if re.search(r"\b(open|hours|timings?|close|closes|opens)\b", t):
            h = await self.tool("get_poi_opening_hours", poi_id=detail["id"],
                                on=self.now.date().isoformat())
            if not h["verified"]:
                facts.append("I don't have verified opening hours for it, so please check before "
                             "you go.")
            elif h["intervals"]:
                facts.append("Open today " + ", ".join(f"{i['open']}–{i['close']}"
                                                         for i in h["intervals"]) + ".")
            else:
                facts.append("Its listed hours say it's closed today.")
        if re.search(r"\b(cost|fee|ticket|price|how much|free)\b", t):
            c = detail["estimated_cost"]
            facts.append("Estimated cost: free." if c["max"] == 0 else
                         f"Estimated cost ₹{c['min']}–₹{c['max']} per person (an estimate).")
        tags = set(detail.get("experience_tags", []))
        if re.search(r"\bphotograph", t):
            facts.append("It's a photogenic spot." if "photogenic" in tags else
                         "It isn't tagged as a photography spot in my data.")
        if re.search(r"\b(family|kids?|children)\b", t):
            fam = detail["suitability"].get("family_friendly")
            facts.append({True: "It's marked family friendly.", False: "It isn't suited to families.",
                          None: "I don't have family-suitability information for it."}[fam])
        if re.search(r"\bworth\b", t):
            reasons = [r for r in ("photogenic", "historic", "scenic", "peaceful", "cultural")
                       if r in tags]
            facts.append(("People seek it out for being " + ", ".join(reasons) + "."
                          if reasons else "It's a local spot rather than a major landmark.")
                         if detail.get("curated") or reasons else
                         "I don't have enough information to say whether it's worth a special trip.")
        highlights, sources = await self._highlights(detail)
        text = detail["name"] + (f" — {detail['short_description']}" if detail.get(
            "short_description") else "")
        if facts:
            text += " " + " ".join(facts)
        self.goto("EXPLAIN")
        return self.respond(intent, text, "poi_details",
                            data={"poi": detail, "highlights": highlights}, sources=sources,
                            suggestions=[Suggestion(label="Show similar", message="Show me places like this"),
                                         Suggestion(label="Save", message="Save this place"),
                                         Suggestion(label="Plan around it",
                                                    message=f"Plan a day including {detail['name']}")])

    async def _highlights(self, detail: dict) -> tuple[list[dict], list[dict]]:
        if not detail.get("wikipedia_title") and not detail.get("description"):
            return [], []
        try:
            res = await self.tool("retrieve_bengaluru_knowledge",
                                  question=f"{detail['name']} history significance", k=4)
        except ToolFailure:
            return [], []
        mine = [c for c in res["chunks"] if detail["name"].lower()[:12] in c["title"].lower()
                or detail.get("wikipedia_title") == c["title"]][:2]
        sources = [{k: v for k, v in c.items() if k != "text"} | {"n": n}
                   for n, c in enumerate(mine, start=1)]
        return [{"text": c["text"][:500], "source_n": n} for n, c in enumerate(mine, start=1)], sources

    async def similar(self, message: str, intent: str) -> AssistantResponse:
        self.goto("SEARCH")
        target, clarification = await self._find_poi(
            message, intent, strip=r"\b(show me|show|places|place|like|similar|to|more|of|"
                                   r"something|same vibe|as|alternatives?|find|any|other|such)\b")
        if clarification is not None:
            return clarification
        if target is None and self.state.last_pois:
            target = {"id": self.state.last_pois[0].id}
        if target is None:
            self.goto("CLARIFY")
            return self.respond(intent, "Similar to which place? Tell me its name.", "clarification")
        res = await self.tool("get_similar_pois", poi_id=target["id"], limit=6)
        items = res["items"]
        ref = res["reference"]
        for i in items:
            i["why"] = [reason_text(r) for r in i["reason_codes"][:3]]
        self.state.remember_results([_poi_last(i) for i in items],
                                    {"args": {}, "mode": "similar", "reference": ref["id"]})
        await self._record_shown([i["id"] for i in items], intent)
        text = (f"Places with a similar feel to {ref['name']}." if items else
                f"I couldn't find places quite like {ref['name']}.")
        self.goto("EXPLAIN")
        return self.respond(intent, text, "poi_list", data={"items": items, "reference": ref},
                            suggestions=AFTER_RESULTS[:1])

    async def save(self, message: str, intent: str) -> AssistantResponse:
        self.goto("SEARCH")
        target, clarification = await self._find_poi(
            message, intent, strip=r"\b(save|bookmark|add|to|my|list|saved|favourites?|favorites?|"
                                   r"remember|keep|this|that|place|please|it|wishlist)\b")
        if clarification is not None:
            return clarification
        if target is None:
            self.goto("COMPLETE")
            return self.respond(intent, "Which place should I save?", "message")
        if self.ctx.role != Role.USER:
            self.goto("COMPLETE")
            return self.respond(intent, "Sign in to save places — it's free, and your saved places "
                                "follow you across devices.", "message",
                                data={"action": "login_required", "poi_id": target["id"]})
        await self.tool("save_poi", poi_id=target["id"])
        detail = await self.tool("get_poi", poi_id=target["id"])
        self.goto("COMPLETE")
        return self.respond(intent, f"Saved {detail['name']} to your places.", "message",
                            data={"saved_poi": detail["id"]})

    # --- knowledge ----------------------------------------------------------------------------------------

    async def knowledge(self, message: str, intent: str, *, entered: bool = False) -> AssistantResponse:
        if not entered:
            self.goto("RETRIEVE")
        elif self.current != "RETRIEVE":
            self.goto("RETRIEVE")
        t = normalize_utterance(message)
        facts: dict = {}
        entity_ids: list[int] = []
        if re.search(r"\b(rain|weather|temperature|hot|cold|forecast)\b", t) and not re.search(
                r"\b(history|built|famous)\b", t):
            on = self.now.date()
            if re.search(r"\btomorrow\b", t):
                from datetime import timedelta
                on = on + timedelta(days=1)
            try:
                w = await self.tool("get_weather", on=on.isoformat())
            except ToolFailure:
                w = {"available": False}
            self.goto("ANSWER")
            if not w.get("available"):
                return self.respond(intent, "I can't get a reliable forecast right now, so I won't "
                                    "guess the weather.", "knowledge_answer",
                                    warnings=[ERROR_MESSAGES["WEATHER_UNAVAILABLE"]])
            text = _weather_sentence(w)
            return self.respond(intent, text, "knowledge_answer", data={"weather": w},
                                sources=[{"n": 1, "title": "Open-Meteo forecast",
                                          "url": "https://open-meteo.com/", "license": "CC BY 4.0",
                                          "source": "open-meteo"}])
        name_phrase = re.sub(r"\b(why|is|was|who|built|build|when|what|the|history|of|famous|known|"
                             r"for|story|behind|tell|me|about|how|old|significance|origin|special)\b",
                             " ", t)
        name_phrase = re.sub(r"[?!.,]", " ", name_phrase).strip()
        if len(name_phrase) >= 4:
            try:
                found = await self.tool("resolve_poi_name", name=name_phrase[:80])
                if found["resolved"]:
                    entity_ids = [found["poi_id"]]
            except ToolFailure:
                pass
        if intent == "GENERAL_BENGALURU" and self.llm_ok:
            facts.update(await self.llm_tool_facts(message))
        self.ctx.extra["facts"] = facts
        self.ctx.extra["entity_poi_ids"] = entity_ids
        ans = await self.tool("answer_grounded_question", question=message[:500], k=6)
        if ans["method"] == "llm":
            self.llm_used = True
        self.goto("ANSWER")
        warnings = []
        if not ans["answerable"] and self.llm is not None and not self.llm.available:
            warnings.append(ERROR_MESSAGES["LLM_UNAVAILABLE"])
        return self.respond(intent, ans["text"], "knowledge_answer",
                            data={"answerable": ans["answerable"], "method": ans["method"],
                                  "validation": ans["validation"]},
                            sources=ans["sources"], warnings=warnings)

    async def llm_tool_facts(self, question: str) -> dict:
        """Bounded, read-only tool selection by the model (one round, <= 2 calls).
        Every call is authorised, validated and limited by the registry."""
        facts: dict = {}
        catalog = self.registry.llm_catalog(self.ctx.role)
        tools_text = "\n".join(f"{t['name']}: {t['description']}; args={list(t['args'].get('properties', {}))}"
                               for t in catalog)
        for _ in range(MAX_TOOL_SELECT_ROUNDS):
            try:
                res = await self.llm.run(TOOL_SELECT, recorder=self.record_llm, tools=tools_text,
                                         question=untrusted(question, 500))
            except LLMError:
                return facts
            calls = (res.parsed or {}).get("calls") or []
            if not isinstance(calls, list):
                return facts
            for call in calls[:2]:
                if not isinstance(call, dict):
                    continue
                r = await self.registry.call(str(call.get("tool", ""))[:60], call.get("args"),
                                             self.ctx, from_llm=True)
                if r.ok:
                    facts[r.tool] = _compact(r.data)
        return facts

    async def compare(self, message: str, intent: str) -> AssistantResponse:
        self.goto("COMPARE")
        t = normalize_utterance(message)
        aspect_m = re.search(r"\b(?:for|when it comes to|in terms of)\s+(.+)$", t)
        aspect = aspect_m.group(1) if aspect_m else ""
        body = t[:aspect_m.start()] if aspect_m else t
        body = re.sub(r"\b(compare|comparison|which is better|better|between|difference|with)\b", " ", body)
        parts = [p.strip(" ?.,") for p in re.split(r"\bvs\.?\b|\bversus\b|\bor\b|\band\b|,", body)
                 if p.strip(" ?.,")]
        if len(parts) < 2 and self.state.last_comparison_ids:
            ids = self.state.last_comparison_ids[:2]
        else:
            ids = []
            for p in parts[:3]:
                found = await self.tool("resolve_poi_name", name=p[:80])
                if found["resolved"]:
                    ids.append(found["poi_id"])
        ids = list(dict.fromkeys(ids))
        if len(ids) < 2:
            self.goto("COMPLETE")
            return self.respond(intent, "Which two places should I compare? For example: "
                                "“Lalbagh vs Cubbon Park for photography”.", "clarification")
        details = [await self.tool("get_poi", poi_id=i) for i in ids[:3]]
        ranked = await self.tool("rank_candidates", poi_ids=ids[:3],
                                 interests=parse_interests(aspect).interests[:12] if aspect else [])
        order = [r["id"] for r in ranked["items"]]
        self.state.last_comparison_ids = ids[:3]
        self.state.remember_results([_poi_last(d) for d in details], None)
        rows = _comparison_rows(details)
        winner = next((d for d in details if d["id"] == order[0]), details[0])
        text = (f"For {aspect}, {winner['name']} is the better match in my data."
                if aspect and len(order) > 1 and ranked["items"][0]["score"] > ranked["items"][1]["score"]
                else "Here's how they compare side by side.")
        self.goto("EXPLAIN")
        return self.respond(intent, text, "comparison",
                            data={"places": details, "rows": rows, "aspect": aspect or None,
                                  "ranking": [{"id": r["id"], "reason_codes": r["reason_codes"]}
                                              for r in ranked["items"]]})

    # --- planning ------------------------------------------------------------------------------------

    async def create_plan(self, message: str, intent: str, *, extracted=None,
                          skip_clarify: bool = False) -> AssistantResponse:
        self.goto("EXTRACT")
        warnings: list[str] = []
        if extracted is None:
            extracted = await extract_trip_spec(message, now=self.now, llm=self.llm if self.llm_ok else None,
                                                recorder=self.record_llm)
            if extracted.llm_used:
                self.llm_used = True
            warnings += extracted.notes
        spec = extracted.spec
        if self.state.last_pois and re.search(r"\b(around these|these places|those places|with these)\b",
                                              normalize_utterance(message)):
            spec = spec.model_copy(update={"must_include_poi_ids": [p.id for p in self.state.last_pois[:3]]})
        if not skip_clarify and not extracted.has_time_info and \
                self.state.clarification_count < MAX_CLARIFICATIONS:
            self.state.clarification_count += 1
            ask = ("Roughly what time window should I plan around? I can choose the rest."
                   if extracted.has_budget else
                   "Roughly what time window and budget should I plan around? I can choose the rest.")
            self.state.pending_clarification = PendingClarification(
                kind="time_budget", question=ask, options=[c.label for c in TIME_CHIPS],
                context={"spec": spec.model_dump(mode="json"), "areas": extracted.area_names,
                         "must": extracted.must_include_names, "scope": extracted.scope})
            self.goto("CLARIFY")
            return self.respond(intent, ask, "clarification",
                                data={"trip_spec": spec.model_dump(mode="json"), "missing": ["time_window"]},
                                suggestions=TIME_CHIPS)
        from app.services.plans import resolve_areas
        spec, area_notes = await resolve_areas(self.ctx.db, spec, extracted.area_names)
        warnings += area_notes
        must_ids = list(spec.must_include_poi_ids)
        for name in extracted.must_include_names:
            found = await self.tool("resolve_poi_name", name=name[:80])
            if found["resolved"]:
                must_ids.append(found["poi_id"])
            else:
                warnings.append(f"I couldn't find '{name}' precisely, so it isn't a required stop.")
        if must_ids:
            spec = spec.model_copy(update={"must_include_poi_ids": list(dict.fromkeys(must_ids))[:6]})
        self.goto("PLAN")
        outcome = await self.tool("build_itinerary", spec=spec.model_dump(mode="json"), persist=True)
        return self._plan_response(outcome, intent, warnings)

    def _plan_response(self, outcome: dict, intent: str, warnings: list[str]) -> AssistantResponse:
        self.goto("VALIDATE")
        status = outcome["status"]
        warnings = warnings + outcome.get("warnings", [])
        if outcome.get("weather") and not outcome["weather"].get("available"):
            warnings.append(ERROR_MESSAGES["WEATHER_UNAVAILABLE"])
        if status == "ok":
            it = outcome["itinerary"]
            self.state.set_plan(it["itinerary_id"], it["version_no"],
                                [_poi_last(s["poi"]) for s in it["stops"]], outcome["trip_spec"])
            self.state.remember_results([_poi_last(s["poi"]) for s in it["stops"]], None)
            text = _plan_sentence(it)
            self.goto("EXPLAIN")
            return self.respond(intent, text, "itinerary", data={
                "itinerary": it, "trip_spec": outcome["trip_spec"],
                "assumptions": outcome["assumptions"], "validator_report": outcome["validator_report"]},
                warnings=warnings,
                suggestions=[Suggestion(label="Make it cheaper", message="Make this cheaper"),
                             Suggestion(label="More relaxed", message="Make it more relaxed"),
                             Suggestion(label="Add dinner", message="Add somewhere for dinner")])
        if status == "infeasible":
            feas = outcome.get("feasibility") or {}
            text = feas.get("message") or ERROR_MESSAGES["PLAN_INFEASIBLE"]
            self.goto("COMPLETE")
            return self.respond(intent, text, "feasibility_error", data={
                "feasibility": feas, "trip_spec": outcome["trip_spec"]}, warnings=warnings,
                suggestions=[Suggestion(label=r["description"], message=r["description"])
                             for r in feas.get("suggested_relaxations", [])[:3]])
        if status == "invalid_request":
            errors = (outcome.get("semantic") or {}).get("errors", [])
            text = " ".join(e["message"].capitalize() + "." for e in errors[:2]) or \
                "That request doesn't quite work."
            self.goto("COMPLETE")
            return self.respond(intent, text, "feasibility_error", data={
                "errors": errors, "trip_spec": outcome["trip_spec"]}, warnings=warnings)
        self.goto("COMPLETE")
        return self.respond(intent, "I couldn't build a plan that passes every check, so I won't "
                            "show an unreliable one. Try loosening a constraint.", "feasibility_error",
                            data={"validator_report": outcome.get("validator_report")}, warnings=warnings)

    async def _mod_ops(self, message: str, intent: str) -> tuple[list[dict] | None, AssistantResponse | None]:
        view = await self.tool("get_itinerary", itinerary_id=self.state.active_itinerary_id)
        cost = view["itinerary"]["summary"]["estimated_cost"]["typical"]
        self.state.active_stops = [_poi_last(s["poi"]) for s in view["itinerary"]["stops"]]
        pm = parse_modifications(message, self.state, current_cost=cost)
        ops = list(pm.operations)
        if pm.add_poi_name:
            found = await self.tool("resolve_poi_name", name=pm.add_poi_name)
            if found["resolved"]:
                ops.append({"op": "add_poi", "poi_id": found["poi_id"]})
            else:
                self.goto("CLARIFY")
                return None, self.respond(intent, f"I couldn't find “{pm.add_poi_name}”. Which place "
                                          "do you want to add?", "clarification")
        if pm.needs_target and not ops:
            if pm.ambiguous_candidates:
                opts = [c.name for c in pm.ambiguous_candidates]
                self.state.pending_clarification = PendingClarification(
                    kind="which_stop", question="Which stop do you mean?", options=opts,
                    context={"message": message[:300], "intent": intent})
                self.goto("CLARIFY")
                return None, self.respond(intent, "Which stop do you mean?", "clarification",
                                          suggestions=[Suggestion(label=o, message=o) for o in opts])
        if not ops and self.llm_ok:
            stops = "\n".join(f"{i + 1}. {s.name} ({s.category})"
                              for i, s in enumerate(self.state.active_stops))
            try:
                res = await self.llm.run(MODIFY, recorder=self.record_llm, stops=stops,
                                         budget=view["trip_spec"].get("budget_total"),
                                         vocabulary=", ".join(VOCABULARY),
                                         message=untrusted(message, 800))
                parsed = res.parsed or {}
                for o in (parsed.get("operations") or [])[:3]:
                    if not isinstance(o, dict):
                        continue
                    o = {k: v for k, v in o.items() if v is not None}
                    if o.get("op") == "add_poi" and o.get("poi_name"):
                        found = await self.tool("resolve_poi_name", name=str(o["poi_name"])[:80])
                        if not found["resolved"]:
                            continue
                        o = {"op": "add_poi", "poi_id": found["poi_id"]}
                    o.pop("poi_name", None)
                    ops.append(o)
            except LLMError:
                pass
        if not ops:
            self.goto("CLARIFY")
            return None, self.respond(intent, "What would you like to change? For example: remove "
                                      "the second stop, make it cheaper, or start later.",
                                      "clarification",
                                      suggestions=[Suggestion(label="Make it cheaper", message="Make this cheaper"),
                                                   Suggestion(label="Fewer stops", message="Reduce the plan"),
                                                   Suggestion(label="Start later", message="Start two hours later")])
        return ops, None

    async def modify(self, message: str, intent: str) -> AssistantResponse:
        if self.state.active_itinerary_id is None:
            self.goto("COMPLETE")
            return self.respond(intent, "There's no plan open yet. Want me to make one?", "message",
                                suggestions=[Suggestion(label="Plan my day", message="Plan my day")])
        self.goto("MODIFY")
        t = normalize_utterance(message)
        if re.match(r"^(undo|restore|go back)", t):
            return await self._undo(message, intent)
        ops, clarification = await self._mod_ops(message, intent)
        if clarification is not None:
            return clarification
        res = await self.registry.call("modify_itinerary", {
            "itinerary_id": self.state.active_itinerary_id, "operations": ops,
            "expected_version_no": self.state.active_version_no}, self.ctx)
        if not res.ok:
            self.goto("COMPLETE")
            msg = res.message if res.error_code in ("INVALID_MODIFICATION", "CONFLICT") else \
                "I couldn't apply that change."
            return self.respond(intent, msg, "message", data={"error": {"code": res.error_code}})
        out = res.data
        outcome = out["outcome"]
        if outcome["status"] != "ok":
            resp = self._plan_response(outcome, intent, [])
            resp.text = "That change doesn't fit: " + resp.text[0].lower() + resp.text[1:]
            return resp
        resp = self._plan_response(outcome, intent, [])
        resp.text = ("Done — " + ", ".join(out["summary"]).lower() + ". " + resp.text) if \
            out.get("summary") else resp.text
        resp.data["comparison"] = out.get("comparison")
        resp.data["change"] = out.get("summary")
        return resp

    async def _undo(self, message: str, intent: str) -> AssistantResponse:
        from app.services.plans import restore_version
        m = re.search(r"version (\d+)", normalize_utterance(message))
        current = self.state.active_version_no or 1
        target = int(m.group(1)) if m else current - 1
        if target < 1:
            self.goto("COMPLETE")
            return self.respond(intent, "This is already the original plan.", "message")
        res = await restore_version(self.ctx.db, self.state.active_itinerary_id, target, self.ctx.owner)
        if res["status"] != "ok":
            self.goto("COMPLETE")
            return self.respond(intent, "That version no longer passes today's checks, so I can't "
                                "restore it.", "feasibility_error", data=res)
        it = res["itinerary"]
        self.state.set_plan(it["itinerary_id"], it["version_no"],
                            [_poi_last(s["poi"]) for s in it["stops"]], self.state.current_trip_spec or {})
        self.goto("VALIDATE")
        self.goto("COMPLETE")
        return self.respond(intent, f"Restored version {target} as version {it['version_no']}.",
                            "itinerary", data={"itinerary": it})

    async def what_if(self, message: str, intent: str) -> AssistantResponse:
        if self.state.active_itinerary_id is None:
            return await self.create_plan(message, "CREATE_ITINERARY")
        self.goto("MODIFY")
        ops, clarification = await self._mod_ops(message, intent)
        if clarification is not None:
            return clarification
        res = await self.registry.call("create_what_if_variant", {
            "itinerary_id": self.state.active_itinerary_id, "operations": ops}, self.ctx)
        if not res.ok:
            self.goto("COMPLETE")
            return self.respond(intent, res.message or "I couldn't try that variation.", "message",
                                data={"error": {"code": res.error_code}})
        out = res.data
        outcome = out["outcome"]
        if outcome["status"] != "ok":
            self.goto("VALIDATE")
            self.goto("COMPLETE")
            feas = outcome.get("feasibility") or {}
            return self.respond(intent, "That variation wouldn't work: " + (feas.get("message") or
                                ERROR_MESSAGES["PLAN_INFEASIBLE"]), "feasibility_error",
                                data={"feasibility": feas})
        self.state.pending_variant_id = out.get("variant_id")
        self.goto("VALIDATE")
        cmp = out["comparison"]
        delta = cmp["estimated_cost"]["delta"]
        text = (f"Here's the what-if next to your current plan: {cmp['stop_count']['variant']} stops, "
                f"estimated ₹{cmp['estimated_cost']['variant']} "
                f"({'+' if delta >= 0 else '−'}₹{abs(delta)}). Your current plan is unchanged "
                f"until you apply it.")
        self.goto("EXPLAIN")
        return self.respond(intent, text, "itinerary_comparison", data={
            "current": out["previous_itinerary"], "variant": outcome["itinerary"],
            "variant_id": out.get("variant_id"), "itinerary_id": self.state.active_itinerary_id,
            "comparison": cmp, "change": out.get("summary")},
            suggestions=[Suggestion(label="Apply this version", message="Apply the what-if"),
                         Suggestion(label="Keep current plan", message="Keep my current plan")])

    async def explain_plan(self, message: str, intent: str) -> AssistantResponse:
        if self.state.active_itinerary_id is None:
            self.goto("COMPLETE")
            return self.respond(intent, "There's no plan open to explain yet.", "message")
        self.goto("EXPLAIN")
        view = await self.tool("get_itinerary", itinerary_id=self.state.active_itinerary_id)
        it = view["itinerary"]
        lines = []
        for s in it["stops"]:
            why = ", ".join(s.get("why") or [reason_text(r) for r in s["reason_codes"][:2]]) or \
                "fits your time window and budget"
            lines.append(f"{s['arrive']} {s['poi']['name']}: {why.lower()}.")
        text = ("Each stop was chosen by NavigIQ's planner for how well it matches your request, its "
                "opening hours and budget, and how close the stops are to each other. "
                + " ".join(lines) + " " + it["transition_note"])
        return self.respond(intent, text, "itinerary", data={"itinerary": it})

    # --- clarification & misc ------------------------------------------------------------------------

    async def clarification_response(self, message: str, intent: str) -> AssistantResponse:
        pending = self.state.pending_clarification
        self.state.pending_clarification = None
        if pending is None:
            return await self.discover(message, "DISCOVER")
        if pending.kind == "time_budget":
            from app.assistant.extraction import Extraction
            from app.schemas.tripspec import TripSpec
            base = TripSpec.model_validate(pending.context["spec"])
            answer = await extract_trip_spec(message, now=self.now, llm=None, base=base)
            ex = Extraction(spec=answer.spec, area_names=pending.context.get("areas", []),
                            must_include_names=pending.context.get("must", []),
                            has_time_info=True, scope=pending.context.get("scope"))
            return await self.create_plan(message, "CREATE_ITINERARY", extracted=ex, skip_clarify=True)
        if pending.kind == "mood":
            return await self.discover(message, "DISCOVER")
        if pending.kind in ("which_place", "which_stop"):
            options = pending.options
            t = normalize_utterance(message)
            chosen = next((i for i, o in enumerate(options) if normalize_utterance(o) in t or
                           t in normalize_utterance(o)), None)
            if chosen is None:
                ref = resolve_reference(message, ConversationState(
                    last_pois=[LastPOI(id=0, name=o, category="other") for o in options]))
                chosen = (ref.seq - 1) if ref.status == "resolved" and ref.seq else None
            if chosen is None:
                self.goto("COMPLETE")
                return self.respond(intent, "Sorry, I didn't catch which one. " + pending.question,
                                    "clarification",
                                    suggestions=[Suggestion(label=o, message=o) for o in options])
            if pending.kind == "which_place":
                poi_id = pending.context["ids"][chosen]
                self.state.focus(LastPOI(id=poi_id, name=options[chosen], category="other"))
                follow = pending.context.get("intent", "PLACE_DETAILS")
                handler = {"SHOW_SIMILAR": self.similar, "SAVE_PLACE": self.save}.get(follow, self.details)
                return await handler("this place", follow)
            original = pending.context.get("message", "")
            return await self.modify(f"{original} {options[chosen]}", "MODIFY_ITINERARY")
        return await self.discover(message, "DISCOVER")

    async def out_of_scope(self, message: str, intent: str) -> AssistantResponse:
        self.goto("COMPLETE")
        return self.respond(intent, "I'm NavigIQ — I help you explore Bengaluru and places within "
                            "about 90 km: ideas, places, facts and day plans. I can't help with that "
                            "one, but I'd love to find you something to do.", "message",
                            suggestions=MOOD_CHIPS[:4])


# --- helpers ---------------------------------------------------------------------------------------------

def _is_db_error(exc: Exception) -> bool:
    name = type(exc).__name__
    return any(k in name for k in ("OperationalError", "InterfaceError", "ConnectionRefused",
                                   "CannotConnectNow", "ConnectionDoesNotExist"))


def _compact(data: Any, limit: int = 1200) -> Any:
    s = str(data)
    return s[:limit]


def _weather_sentence(w: dict) -> str:
    cond = {"heavy_rain": "Heavy rain is forecast", "rain_likely": "Rain is likely",
            "light_rain": "Light rain is possible", "dry": "It looks dry"}.get(
        w.get("condition"), "The forecast is mixed")
    temp = f", around {w['mean_temp_c']}°C" if w.get("mean_temp_c") is not None else ""
    prob = (f" (up to {w['max_precip_probability']}% chance of rain)"
            if w.get("max_precip_probability") is not None else "")
    return f"{cond} in {w.get('area', 'Bengaluru')} on {w['date']}{temp}{prob}. Source: Open-Meteo."


def _plan_sentence(it: dict) -> str:
    s = it["summary"]
    n = s["stop_count"]
    cost = s["estimated_cost"]
    money = ("mostly free" if cost["max"] == 0 else
             f"an estimated ₹{cost['min']}–₹{cost['max']} for {s['party_size']} "
             f"{'person' if s['party_size'] == 1 else 'people'}")
    first = it["stops"][0]["poi"]["name"] if it["stops"] else ""
    return (f"Here's your plan: {n} stop{'s' * (n != 1)} from {it['start_time']} to "
            f"{it['end_time']}, starting at {first}, {money} (excluding transport). "
            f"{it['transition_note']}")


def _comparison_rows(details: list[dict]) -> list[dict]:
    def cost(d):
        c = d["estimated_cost"]
        return "Free" if c["max"] == 0 else f"₹{c['min']}–₹{c['max']}"
    rows = [
        {"label": "Type", "values": [_cat_name(d["category"]).capitalize() for d in details]},
        {"label": "Area", "values": [d.get("locality") or "—" for d in details]},
        {"label": "Region", "values": [d["region_bucket"].replace("_", " ").title() for d in details]},
        {"label": "Estimated cost / person", "values": [cost(d) for d in details]},
        {"label": "Typical visit", "values": [f"{d['visit_duration']['typical']} min" for d in details]},
        {"label": "Indoor / outdoor", "values": [d["indoor_outdoor"].capitalize() for d in details]},
        {"label": "Good for", "values": [", ".join(t.replace("_", " ") for t in d["experience_tags"][:5])
                                        or "—" for d in details]},
        {"label": "Hours verified", "values": ["Yes" if d.get("hours_verified") else "No"
                                               for d in details]},
    ]
    return rows
