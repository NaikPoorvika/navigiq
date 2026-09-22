"""Deterministic resolution of dates and time windows (section 39).

THE LLM NEVER COMPUTES A DATE. It may copy the user's words into a
`date_phrase`; this module turns words into calendar dates, relative to a
`today` supplied by the caller in Asia/Kolkata.

Documented conventions (also in docs/nlu_conventions.md):
  today / tonight / aaj / ivattu / ಇವತ್ತು        -> today
  tomorrow / kal / naale / ನಾಳೆ                   -> today + 1
  day after tomorrow / parso / naadiddu           -> today + 2
  "this <weekday>" / "<weekday>" / "coming <wd>"   -> next occurrence on or after today
  "next <weekday>"                                 -> that weekday in NEXT calendar week
                                                      (Mon-Sun), i.e. never this week
  this weekend / weekend                          -> Saturday of this week; today if it
                                                      is already Saturday or Sunday
  next weekend                                    -> Saturday of next week
  in N days                                       -> today + N
  25 Sept / Sept 25 / 25/09 / 2026-09-25          -> that date; a day/month already past
                                                      this year rolls to next year
Numeric d/m dates are read day-first (Indian convention).

Time windows: explicit ranges ("10 AM-7 PM", "from around 11 to 8", "4 to 9")
use am/pm when given; otherwise an hour 1-6 is afternoon, 7-11 morning, and an
end hour not after the start is moved 12 hours later ("11 to 8" -> 11:00-20:00).
Day parts: morning 08:00-12:00, afternoon 12:00-17:00, evening 16:30-21:00,
tonight/night 18:30-23:00, full day 09:00-19:00.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.nlu.text import WORD_NUMBERS, normalize_utterance

IST = ZoneInfo("Asia/Kolkata")

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
            "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
            "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
            "somvar": 0, "mangalvar": 1, "budhvar": 2, "guruvar": 3, "shukravar": 4,
            "shanivar": 5, "ravivar": 6, "itvar": 6}
MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4,
          "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
          "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
          "nov": 11, "november": 11, "dec": 12, "december": 12}

TODAY_WORDS = r"today|tonight|this (?:morning|afternoon|evening)|aaj|aj|ivattu|ivathu|indu|ಇವತ್ತು|ಇಂದು|आज"
TOMORROW_WORDS = r"tomorrow|tmrw|tmr|tomm?orow|kal|naale|nale|ನಾಳೆ|कल"
DAY_AFTER_WORDS = r"day after tomorrow|day after tmrw|parso|parson|naadiddu|nadiddu|ನಾಡಿದ್ದು|परसों"

EVENING_WORDS = r"evening|night|tonight|shaam|sham|sanje|raat|rathri|ಸಂಜೆ"

DAY_PARTS = {
    "early morning": (6 * 60, 9 * 60), "morning": (8 * 60, 12 * 60),
    "subah": (8 * 60, 12 * 60), "beligge": (8 * 60, 12 * 60), "ಬೆಳಿಗ್ಗೆ": (8 * 60, 12 * 60),
    "afternoon": (12 * 60, 17 * 60), "dopahar": (12 * 60, 17 * 60),
    "madhyahna": (12 * 60, 17 * 60),
    "evening": (16 * 60 + 30, 21 * 60), "shaam": (16 * 60 + 30, 21 * 60),
    "sham": (16 * 60 + 30, 21 * 60), "sanje": (16 * 60 + 30, 21 * 60),
    "ಸಂಜೆ": (16 * 60 + 30, 21 * 60),
    "tonight": (18 * 60 + 30, 23 * 60), "night": (18 * 60 + 30, 23 * 60),
    "raat": (18 * 60 + 30, 23 * 60), "rathri": (18 * 60 + 30, 23 * 60),
    "full day": (9 * 60, 19 * 60), "whole day": (9 * 60, 19 * 60),
    "all day": (9 * 60, 19 * 60), "entire day": (9 * 60, 19 * 60),
}


@dataclass(frozen=True)
class DateResolution:
    value: date
    phrase: str
    rule: str


@dataclass(frozen=True)
class TimeWindow:
    start_min: int | None
    end_min: int | None
    duration_min: int | None
    phrase: str
    rule: str

    @property
    def start_hhmm(self) -> str | None:
        return None if self.start_min is None else f"{self.start_min // 60:02d}:{self.start_min % 60:02d}"

    @property
    def end_hhmm(self) -> str | None:
        return None if self.end_min is None else f"{self.end_min // 60:02d}:{self.end_min % 60:02d}"


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def _wb(p: str) -> str:
    return rf"(?<![\w])(?:{p})(?![\w])"


def this_weekday(today: date, wd: int) -> date:
    return today + timedelta(days=(wd - today.weekday()) % 7)


def next_weekday(today: date, wd: int) -> date:
    start_next_week = today + timedelta(days=7 - today.weekday())
    return start_next_week + timedelta(days=wd)


def resolve_date(utterance: str, today: date) -> DateResolution | None:
    t = normalize_utterance(utterance)

    m = re.search(r"(?<!\d)(20\d\d)-(\d{1,2})-(\d{1,2})(?!\d)", t)
    if m:
        try:
            return DateResolution(date(int(m[1]), int(m[2]), int(m[3])), m[0], "iso")
        except ValueError:
            pass
    if re.search(_wb(DAY_AFTER_WORDS), t):
        return DateResolution(today + timedelta(days=2),
                              re.search(_wb(DAY_AFTER_WORDS), t)[0], "day_after_tomorrow")
    m = re.search(_wb(r"in (\d+|one|two|three|four|five|six|seven) days?"), t)
    if m:
        n = WORD_NUMBERS.get(m[1]) or int(m[1]) if not m[1].isdigit() else int(m[1])
        return DateResolution(today + timedelta(days=int(n)), m[0], "in_n_days")
    m = re.search(_wb(r"next weekend"), t)
    if m:
        return DateResolution(next_weekday(today, 5), m[0], "next_weekend")
    m = re.search(_wb(r"(?:this |coming )?weekend"), t)
    if m:
        if today.weekday() >= 5:
            return DateResolution(today, m[0], "this_weekend_today")
        return DateResolution(this_weekday(today, 5), m[0], "this_weekend")
    wd_names = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
    m = (re.search(_wb(rf"next ({wd_names})"), t)
         or re.search(_wb(rf"({wd_names}),? (?:of )?next week"), t)
         or re.search(_wb(rf"next week,? (?:on )?({wd_names})"), t))
    if m:
        return DateResolution(next_weekday(today, WEEKDAYS[m[1]]), m[0], "next_weekday")
    m = re.search(_wb(rf"(?:this |coming |on )?({wd_names})"), t)
    if m and not re.search(_wb(rf"({wd_names})s"), t):
        return DateResolution(this_weekday(today, WEEKDAYS[m[1]]), m[0], "this_weekday")
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    m = (re.search(_wb(rf"(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?({month_names})"), t)
         or re.search(_wb(rf"({month_names}) (\d{{1,2}})(?:st|nd|rd|th)?"), t))
    if m:
        if m[1].isdigit():
            d, mo = int(m[1]), MONTHS[m[2]]
        else:
            mo, d = MONTHS[m[1]], int(m[2])
        resolved = _roll_forward(today, mo, d)
        if resolved:
            return DateResolution(resolved, m[0], "day_month")
    m = re.search(r"(?<![\d:])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d:])", t)
    if m:
        d, mo = int(m[1]), int(m[2])
        if m[3]:
            y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            try:
                return DateResolution(date(y, mo, d), m[0], "dmy")
            except ValueError:
                pass
        else:
            resolved = _roll_forward(today, mo, d)
            if resolved:
                return DateResolution(resolved, m[0], "dm")
    m = re.search(_wb(TOMORROW_WORDS), t)
    if m:
        return DateResolution(today + timedelta(days=1), m[0], "tomorrow")
    m = re.search(_wb(TODAY_WORDS), t)
    if m:
        return DateResolution(today, m[0], "today")
    return None


@dataclass(frozen=True)
class DateRange:
    """A multi-day span. `start` is None when only a length was given ("3 days")."""
    start: date | None
    end: date | None
    days: int
    phrase: str
    rule: str


# English counts take "day(s)"; Hindi / Kannada counts only their own word for
# day, so "things to do day after tomorrow" is never a two-day trip.
_N_DAYS = (r"(\d{1,2}|one|two|three|four|five|six|seven)[- ]?days?|"
           r"(do|teen|char|chaar|paanch) din|(eradu|mooru|naalku|aidu) dina")
_DAY_COUNT = {"do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5,
              "eradu": 2, "mooru": 3, "naalku": 4, "aidu": 5}
_RANGE_SEP = r"\s*(?:-|–|—|to|till|until|through|thru|and)\s*"


def _joins_non_adjacent(m: re.Match) -> bool:
    """"saturday and sunday" is a span; "monday and friday" is two separate days."""
    return " and " in m[0] and (WEEKDAYS[m[2]] - WEEKDAYS[m[1]]) % 7 != 1


def resolve_date_range(utterance: str, today: date) -> DateRange | None:
    """Multi-day phrases. Conventions (docs/nlu_conventions.md):
      "3 days" / "3-day trip" / "for three days"   -> 3 days from the start date given
                                                      elsewhere (or unresolved start)
      "friday to sunday" / "fri-sun"               -> next Friday .. the Sunday after
      "10 to 12 october" / "oct 10 - oct 12"       -> those dates (rolled forward)
      "whole weekend" / "both days this weekend"   -> Saturday .. Sunday of this weekend
      "next weekend" alone stays one day (Saturday), as does "weekend".
    "in 3 days" is a single date, never a span.
    """
    t = normalize_utterance(utterance)
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    wd_names = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
    ordinal = r"(?:st|nd|rd|th)?"

    m = (re.search(_wb(rf"(\d{{1,2}}){ordinal}{_RANGE_SEP}(\d{{1,2}}){ordinal} (?:of )?"
                       rf"({month_names})"), t))
    if m:
        mo = MONTHS[m[3]]
        start, end = _roll_forward(today, mo, int(m[1])), _roll_forward(today, mo, int(m[2]))
        if start and end and end >= start:
            return DateRange(start, end, (end - start).days + 1, m[0], "day_range_month")
    m = (re.search(_wb(rf"({month_names}) (\d{{1,2}}){ordinal}{_RANGE_SEP}"
                       rf"(?:({month_names}) )?(\d{{1,2}}){ordinal}"), t)
         or None)
    if m:
        mo1 = MONTHS[m[1]]
        mo2 = MONTHS[m[3]] if m[3] else mo1
        start = _roll_forward(today, mo1, int(m[2]))
        end = _roll_forward(start or today, mo2, int(m[4])) if start else None
        if start and end and end >= start:
            return DateRange(start, end, (end - start).days + 1, m[0], "month_day_range")
    m = re.search(_wb(rf"(\d{{1,2}}){ordinal} (?:of )?({month_names}){_RANGE_SEP}"
                      rf"(\d{{1,2}}){ordinal} (?:of )?({month_names})"), t)
    if m:
        start = _roll_forward(today, MONTHS[m[2]], int(m[1]))
        end = _roll_forward(start or today, MONTHS[m[4]], int(m[3])) if start else None
        if start and end and end >= start:
            return DateRange(start, end, (end - start).days + 1, m[0], "day_month_range")
    m = re.search(_wb(rf"(?:from |this |coming )?({wd_names}){_RANGE_SEP}"
                      rf"(?:this |the )?({wd_names})"), t)
    if m and not _joins_non_adjacent(m):
        start = this_weekday(today, WEEKDAYS[m[1]])
        end = start + timedelta(days=(WEEKDAYS[m[2]] - WEEKDAYS[m[1]]) % 7)
        if end > start:
            return DateRange(start, end, (end - start).days + 1, m[0], "weekday_range")
    m = re.search(_wb(r"(?:(?:the )?(?:whole|entire|full) weekend|all weekend|"
                      r"both days (?:of )?(?:this |the )?weekend|(?:this |the )?weekend,? both days|"
                      r"saturday and sunday|sat and sun|sat-sun|sat sun)"), t)
    if m:
        start = today if today.weekday() == 5 else this_weekday(today, 5)
        if today.weekday() == 6:
            return None
        return DateRange(start, start + timedelta(days=1), 2, m[0], "whole_weekend")
    m = re.search(_wb(rf"(?<!in )(?<!in a )(?:for |a |an |over )?(?:the )?(?:next )?"
                      rf"(?:{_N_DAYS})(?: (?:trip|itinerary|plan|getaway|"
                      rf"break|holiday|vacation|visit|stay|tour))?(?! (?:from now|later|ago|"
                      rf"back|before|a week))"), t)
    if m:
        raw = m[1] or m[2] or m[3]
        n = int(raw) if raw.isdigit() else (_DAY_COUNT.get(raw) or WORD_NUMBERS.get(raw))
        if isinstance(n, int) and n >= 2:
            start = today if "next" in m[0] else None
            return DateRange(start, start + timedelta(days=n - 1) if start else None, n, m[0],
                             "n_days")
    return None


def _roll_forward(today: date, month: int, day: int) -> date | None:
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate < today:
        try:
            candidate = date(today.year + 1, month, day)
        except ValueError:
            return None
    return candidate


_H = r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"


def _to_min(h: str, m: str | None, ampm: str | None) -> int | None:
    hour, minute = int(h), int(m or 0)
    if minute > 59 or hour > 24:
        return None
    if ampm:
        ampm = ampm.replace(".", "")
        if hour > 12:
            return None
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
    return hour * 60 + minute


def _infer_meridiem(start: int, has_ampm: bool) -> int:
    if has_ampm or start >= 13 * 60:
        return start
    hour = start // 60
    if 1 <= hour <= 6:
        return start + 12 * 60
    return start


def resolve_time_window(utterance: str) -> TimeWindow | None:
    t = normalize_utterance(utterance)
    # "noon to 5", "from midday", "till midnight": named clock times.
    t = re.sub(r"\b(noon|midday|mid-day)\b", "12 pm", t)
    t = re.sub(r"\bmidnight\b", "11:59 pm", t)
    # "7 baje" (Hindi), "8 gantege" (Kannada): o'clock markers carry no meridiem.
    t = re.sub(r"(\d{1,2})\s*(?:baje|bje|gantege|gante|ganteyinda)\b", r"\1", t)
    # Explicit range: "10 am to 7 pm", "from around 11 to 8", "between 4 and 9", "10-6".
    range_re = re.compile(rf"(?<![\d/\-:])(?:from|between|b/w)?\s*(?:around|about|approx\.?|~)?"
                          rf"\s*{_H}\s*(?:-|to|till|until|and|upto|up to|tak|se|inda|rinda|ninda)\s*"
                          rf"(?:around|about)?\s*{_H}(?![\d/\-])")
    for m in range_re.finditer(t):
        if re.match(r"\s*(rs|inr|rupees|km|kms|people|persons|friends|stops|hours|hrs)\b",
                    t[m.end():m.end() + 10]):
            continue
        if _looks_like_money(t, m.start()):
            continue
        s_ampm, e_ampm = m[3], m[6]
        start = _to_min(m[1], m[2], s_ampm)
        end = _to_min(m[4], m[5], e_ampm)
        if start is None or end is None:
            continue
        if e_ampm and not s_ampm and start // 60 <= 12:
            # "10 to 7 pm": start inherits the end's meridiem when that keeps order.
            alt = _to_min(m[1], m[2], e_ampm)
            start = alt if alt is not None and alt < end else start
        start = _infer_meridiem(start, bool(s_ampm))
        if not e_ampm and end <= start:
            end += 12 * 60
        if (not s_ampm and not e_ampm and start < 12 * 60 and end <= 12 * 60
                and re.search(_wb(EVENING_WORDS), t)):
            # "7 to 11 at night": both hours shift into the evening.
            start, end = start + 12 * 60, end + 12 * 60
        if end == 24 * 60:
            end = 23 * 60 + 59
        if 0 <= start < end <= 24 * 60:
            return TimeWindow(start, end, end - start, m[0].strip(), "explicit_range")
    duration = resolve_duration(t)
    # Anchors, possibly both in separate phrases: "leave 5 am, back by 1 pm",
    # "start at noon and end by 6", "after 5 pm", "till 9 pm".
    start = end = None
    ms = (re.search(rf"(?:after|from|starting(?: at| from)?|start(?:ing)? (?:at|by|around)|"
                    rf"begin(?:ning)? at|leav(?:e|ing)(?: at| by| around)?|head(?:ing)? out at|"
                    rf"set off at|depart(?:ing)?(?: at)?)\s+{_H}", t)
          or re.search(rf"(?<![\d:]){_H}\s*(?:onwards|on wards|se|inda|rinda)(?!\s*\d)", t))
    if ms:
        start = _to_min(ms[1], ms[2], ms[3])
        if start is not None:
            start = _infer_meridiem(start, bool(ms[3]))
            if not ms[3] and start < 12 * 60 and re.search(_wb(EVENING_WORDS), t):
                start += 12 * 60           # "date night ... from 7" -> 19:00
    me = re.search(rf"(?:till|until|by|before|end(?:ing)? (?:at|by)|finish(?:ing)? (?:at|by)|"
                   rf"back (?:at|by)|done (?:at|by)|wrap up (?:at|by))\s+{_H}", t)
    if me and (ms is None or me.start() >= ms.end()):
        end = _to_min(me[1], me[2], me[3])
        if end is not None:
            end = _infer_meridiem(end, bool(me[3]))
            if start is not None and end <= start and not me[3] and end + 12 * 60 < 24 * 60:
                end += 12 * 60             # "start at 10, back by 2" -> 14:00
            if start is not None and end <= start and not ms[3] and start >= 12 * 60 \
                    and start - 12 * 60 < end:
                start -= 12 * 60           # "head out at 6, back by 6 pm" -> 06:00
            if start is not None and end <= start:
                end = None
    if start is not None and end is not None:
        return TimeWindow(start, end, end - start, f"{ms[0]} .. {me[0]}", "start_and_end")
    if start is not None:
        end = min(start + duration, 23 * 60 + 30) if duration else None
        return TimeWindow(start, end, duration, ms[0], "start_only")
    if end is not None:
        return TimeWindow(None, end, duration, me[0], "end_only")
    for phrase in sorted(DAY_PARTS, key=len, reverse=True):
        if re.search(_wb(re.escape(phrase)), t):
            s, e = DAY_PARTS[phrase]
            return TimeWindow(s, e, e - s, phrase, "day_part")
    if duration:
        return TimeWindow(None, None, duration, f"{duration} minutes", "duration_only")
    return None


def _looks_like_money(t: str, pos: int) -> bool:
    return bool(re.search(r"(rs|inr|budget|under|below)\s*$", t[max(0, pos - 10):pos]))


def resolve_duration(t: str) -> int | None:
    t = normalize_utterance(t)
    if re.search(_wb(r"half a day|half day|half-day"), t):
        return 240
    m = re.search(_wb(r"(\d+(?:\.\d)?|one|two|three|four|five|six|seven|eight|nine|ten|"
                      r"a couple of|couple of|a few|an|a)\s*(?:hours?|hrs?|ghante|ghanta)"), t)
    if m:
        raw = m[1]
        n = float(raw) if raw[0].isdigit() else float(WORD_NUMBERS.get(raw, 0))
        if 0 < n <= 16:
            return int(round(n * 60))
    m = re.search(_wb(r"(\d{2,3})\s*(?:minutes|mins)"), t)
    if m and 15 <= int(m[1]) <= 600:
        return int(m[1])
    return None


def round_up_to_quarter(minute: int) -> int:
    return min(23 * 60 + 45, ((minute + 14) // 15) * 15)


def minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def combine(d: date, minute: int) -> datetime:
    return datetime.combine(d, time(minute // 60, minute % 60), tzinfo=IST)
