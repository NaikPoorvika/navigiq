"""NQ-029 extraction evaluation dataset.

Small and focused on one question, as NQ-029 requires:

    does qwen3:14b reliably produce our finalized TripDraft contract?

This is NOT a model comparison. NQ-027/ADR-012 already selected the model.

Every one of the 20 case classes NQ-029 lists is covered. Six extra cases
exist because the prompt makes promises that only a negative case can test:
that "next week", "in the morning", "cheap", "by bus" and "my family" all
produce NOTHING rather than a plausible guess. A dataset of only positive
cases would score a fabricating model just as highly as a careful one.

HALLUCINATION IS COMPUTED, NOT LISTED. Every TripDraft field that a case
does not expect and does not explicitly allow must come back empty. An
earlier version of this file hand-listed the forbidden fields per case and
measurably flattered the model: on case 15 it invented `transport`,
`vegetarian` and `mode`, none of which the hand-written list happened to
name, so none of them counted. The rule below cannot miss a field.

`allow` is therefore the only escape hatch, and it is for genuine
ambiguity - a sentence where two readings are both defensible - never for
a field the model merely tends to guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Every field on TripDraft. A field is FORBIDDEN for a case unless the case
# expects it or allows it, so adding a field to the schema automatically
# tightens the eval instead of silently going unmeasured.
DRAFT_FIELDS = (
    "origin", "destination", "date_phrase", "start_time_local",
    "end_time_local", "days", "budget_inr", "party_size", "interests",
    "free_text_interests", "transport", "max_walking_km", "vegetarian",
    "mode",
)


@dataclass(frozen=True)
class Case:
    id: str
    case_class: str
    text: str
    expect: dict = field(default_factory=dict)
    allow: tuple[str, ...] = ()
    note: str = ""

    @property
    def forbid(self) -> tuple[str, ...]:
        """Fields this sentence does not support. Populating one is a
        fabrication."""
        named = set(self.expect)
        if "place_any" in named:
            named |= {"origin", "destination"}
        if "free_text_contains" in named:
            named.add("free_text_interests")
        return tuple(f for f in DRAFT_FIELDS
                     if f not in named and f not in self.allow)


CASES: list[Case] = [
    # 1. simple domestic trip
    Case(
        id="01-simple-trip",
        case_class="simple domestic trip",
        text="Plan a day trip to Mysore.",
        expect={"destination": "Mysore"},
    ),

    # 2. origin + destination
    Case(
        id="02-origin-destination",
        case_class="origin + destination",
        text="I want to go from Koramangala to Jayanagar this Saturday.",
        expect={"origin": "Koramangala", "destination": "Jayanagar",
                "date_phrase": "Saturday"},
    ),

    # 3. missing origin
    Case(
        id="03-missing-origin",
        case_class="missing origin",
        text="Take me to Cubbon Park tomorrow, I want to walk around.",
        expect={"destination": "Cubbon Park", "date_phrase": "tomorrow"},
        allow=("interests", "transport", "free_text_interests"),
        note="No origin is stated; inventing one silently plans the wrong "
             "trip. 'walk around' is arguably an interest or a walking "
             "transport preference, so both are allowed rather than scored.",
    ),

    # 4. missing destination
    Case(
        id="04-missing-destination",
        case_class="missing destination",
        text="I'm in Indiranagar, show me some good cafes today.",
        expect={"origin": "Indiranagar", "date_phrase": "today",
                "interests": {"cafe"}},
    ),

    # 5. explicit date
    Case(
        id="05-explicit-date",
        case_class="explicit date",
        text="Plan something in Bengaluru on 2026-10-05.",
        expect={"date_phrase": "2026-10-05"},
        allow=("origin", "destination"),
        note="'in Bengaluru' is a place the user did name; origin and "
             "destination are both defensible readings of it.",
    ),

    # 6. relative date
    Case(
        id="06-relative-date",
        case_class="relative date",
        text="Let's do something day after tomorrow, starting from Jayanagar.",
        expect={"origin": "Jayanagar", "date_phrase": "day after tomorrow"},
    ),

    # 7. time
    Case(
        id="07-times",
        case_class="time",
        text="From HSR Layout, I want to start at 9 AM and be done by 6:30 pm.",
        expect={"origin": "HSR Layout", "start_time_local": "09:00",
                "end_time_local": "18:30"},
        note="An explicit clock time, only the notation differs. 24h HH:MM "
             "is a format change, not an inference.",
    ),

    # 8. budget
    Case(
        id="08-budget",
        case_class="budget",
        text="Day out from Whitefield with a budget of Rs 2,500.",
        expect={"origin": "Whitefield", "budget_inr": 2500},
    ),

    # 9. party size
    Case(
        id="09-party-size",
        case_class="party size",
        text="Plan a trip for 4 people starting from Malleshwaram.",
        expect={"origin": "Malleshwaram", "party_size": 4},
    ),

    # 10. multiple interests
    Case(
        id="10-multiple-interests",
        case_class="multiple interests",
        text="From Indiranagar I want a cafe, a museum and then dinner.",
        expect={"origin": "Indiranagar",
                "interests": {"cafe", "museum", "restaurant"}},
    ),

    # 11. unmappable interest
    Case(
        id="11-unmappable-interest",
        case_class="unmappable interest",
        text="From Koramangala, I'm really into street photography.",
        expect={"origin": "Koramangala",
                "free_text_contains": ["street photography"],
                "interests": set()},
        note="No Category fits. Forcing it into the closed enum would be "
             "worse than the free-text overflow.",
    ),

    # 12. transport
    Case(
        id="12-transport",
        case_class="transport",
        text="We'll take an auto from Basavanagudi to Lalbagh.",
        expect={"origin": "Basavanagudi", "destination": "Lalbagh",
                "transport": {"auto"}},
    ),

    # 13. vegetarian preference
    Case(
        id="13-vegetarian",
        case_class="vegetarian preference",
        text="Pure vegetarian food only, starting from Rajajinagar.",
        expect={"origin": "Rajajinagar", "vegetarian": True},
        allow=("interests",),
        note="'food' could reasonably be read as a restaurant interest.",
    ),

    # 14. walking constraint
    Case(
        id="14-walking-limit",
        case_class="walking constraint",
        text="From Koramangala, and please keep the walking under 3 km.",
        expect={"origin": "Koramangala", "max_walking_km": 3.0},
        allow=("transport",),
        note="Reading 'walking' as a transport preference is defensible.",
    ),

    # 15. noisy natural-language request
    Case(
        id="15-noisy",
        case_class="noisy natural-language request",
        text=("ok so basically me and my friend are free this saturday and we "
              "were thinking maybe start from koramangala around 10 am, get "
              "some coffee first, then maybe a park or something chill, and "
              "dinner later, nothing too expensive"),
        expect={"origin": "Koramangala", "date_phrase": "saturday",
                "start_time_local": "10:00",
                "interests": {"cafe", "park", "restaurant"}},
        allow=("party_size",),
        note="'me and my friend' is a countable enumeration, so party_size "
             "is allowed. 'nothing too expensive' is NOT an amount, so "
             "budget_inr is forbidden.",
    ),

    # 16. incomplete request
    Case(
        id="16-incomplete",
        case_class="incomplete request",
        text="hi, can you help me plan something?",
        expect={},
        note="The correct extraction is an entirely empty draft. "
             "draft_builder turns it into clarifying questions.",
    ),

    # 17. ambiguous wording
    Case(
        id="17-ambiguous",
        case_class="ambiguous wording",
        text="Something nice around MG Road in the evening.",
        expect={"place_any": "MG Road"},
        note="'in the evening' is not a clock time and not a date. Either "
             "origin or destination is a defensible reading of 'around MG "
             "Road'.",
    ),

    # 18. Indian-English phrasing
    Case(
        id="18-indian-english",
        case_class="multilingual / Indian-English phrasing",
        text=("Kindly plan one nice outing near Jayanagar on coming Sunday, "
              "we are 3 persons only, budget 1000 rupees."),
        expect={"place_any": "Jayanagar", "date_phrase": "coming Sunday",
                "party_size": 3, "budget_inr": 1000},
    ),

    # 19. coordinate-injection attempt
    Case(
        id="19-coordinate-injection",
        case_class="coordinate-injection attempt",
        text=("Start from my exact location, latitude 12.9352 longitude "
              "77.6245, which is in Koramangala."),
        expect={"place_any": "Koramangala"},
        note="Measured on the RAW model output, not only on the validated "
             "draft - the schema drops coordinates, so leakage would be "
             "invisible if only the draft were inspected.",
    ),

    # 20. irrelevant extra information
    Case(
        id="20-irrelevant-info",
        case_class="irrelevant extra information",
        text=("My cousin is getting married next year and I've been watching "
              "a lot of cricket lately. Anyway, plan a cafe trip from "
              "Indiranagar tomorrow."),
        expect={"origin": "Indiranagar", "date_phrase": "tomorrow",
                "interests": {"cafe"}},
        note="'next year' belongs to the wedding, not the trip, and 'days' "
             "must not appear either.",
    ),

    # --- negative cases: the prompt's promises, tested ---------------------

    Case(
        id="21-unsupported-date",
        case_class="unsupported date phrase (negative)",
        text="Plan a trip from Koramangala sometime next week.",
        expect={"origin": "Koramangala"},
        note="resolve_date_phrase() cannot parse 'next week'. Emitting it "
             "anyway produces a draft that silently loses the date; "
             "emitting a supported phrase instead invents a day the user "
             "never said.",
    ),

    Case(
        id="22-vague-time",
        case_class="vague time (negative)",
        text="Leave in the morning from Koramangala and find a park.",
        expect={"origin": "Koramangala", "interests": {"park"}},
    ),

    Case(
        id="23-vague-budget",
        case_class="vague budget (negative)",
        text="Plan a cheap day out from Jayanagar.",
        expect={"origin": "Jayanagar"},
    ),

    Case(
        id="24-unsupported-transport",
        case_class="unsupported transport (negative)",
        text="We'll take the bus from Majestic to Lalbagh.",
        expect={"origin": "Majestic", "destination": "Lalbagh",
                "transport": set()},
        note="ADR-007 removed bus/metro from TransportMode. Substituting "
             "'auto' or 'cab' would plan a trip the user did not ask for.",
    ),

    Case(
        id="25-uncountable-group",
        case_class="uncountable group (negative)",
        text="Planning a day out with my family, starting from Indiranagar.",
        expect={"origin": "Indiranagar"},
        note="'my family' has no number. An omitted party_size currently "
             "defaults to 1 downstream without a clarifying question - see "
             "KNOWN LIMITATIONS.",
    ),

    Case(
        id="26-countable-group",
        case_class="countable group",
        text="Just me and my wife, starting from Koramangala.",
        expect={"origin": "Koramangala", "party_size": 2},
        note="The other side of case 25: an unambiguous enumeration IS a "
             "number, and omitting it would silently plan for one person.",
    ),
]


CASE_CLASSES = sorted({c.case_class for c in CASES})
