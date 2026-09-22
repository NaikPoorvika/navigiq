# NQ-030 evaluation results

- model `qwen3:14b`, temperature 0.0, seed 0, max_tokens 512, num_ctx 8192
- 3 repeats per dataset and prompt; rates are the mean, with the (min-max) range where repeats disagreed
- run at 2026-09-22T09:03:58+00:00
- scorer: `ai/evals/nq030/scoring.py`
- per-case history: `.` clean, `x` not clean, one mark per repeat

## Held-out set - the honest number

40 cases. dataset sha256 `2d768e27b66e4d27`; prompt sha256 v1 `811cff33f26e8c22`, v2 `52879a64dfcb5a54`.

| Metric | v1 (NQ-029) | v2 (NQ-030) |
| --- | --- | --- |
| Schema validity | 97.5% | 100.0% |
| Explicit extraction accuracy | 84.5% | 92.8% |
| Under-extraction | 14.4% | 6.2% |
| Wrong value on a stated field | 1.0% | 1.0% |
| Unrequested fields (share of cases) | 48.7% | 30.0% |
| Unrequested fields (share of restraint checks) | 5.9% | 3.3% |
| **Plan-altering hallucination** (share of cases) | 46.2% | 27.5% |
| Coordinate leakage | 0.0% | 0.0% |
| Malformed time | 0.0% | 0.0% |
| Unsupported date phrase | 16.7% | 12.5% |
| Place/interest accuracy | 80.0% | 100.0% |
| Clean cases | 47.5% | 70.0% |
| Mean latency | 682 ms | 626 ms |
| Unrequested values, all repeats (benign / clarifying / plan-altering) | 18 / 6 / 54 | 3 / 3 / 39 |

Unstable cases (outcome changed between repeats): v1 none; v2 none.

### Clean cases by category

Clean = valid draft, every stated field right, nothing non-benign invented.

| Category | cases | v1 clean (per repeat) | v2 clean (per repeat) |
| --- | --- | --- | --- |
| explicit_extraction | 10 | 5 / 5 / 5 | 6 / 6 / 6 |
| missing_info_restraint | 8 | 5 / 5 / 5 | 5 / 5 / 5 |
| ambiguous_wording | 5 | 3 / 3 / 3 | 4 / 4 / 4 |
| unsupported_enum | 4 | 1 / 1 / 1 | 2 / 2 / 2 |
| date_time | 5 | 0 / 0 / 0 | 5 / 5 / 5 |
| place_interest | 5 | 4 / 4 / 4 | 5 / 5 / 5 |
| indian_english_noisy | 3 | 1 / 1 / 1 | 1 / 1 / 1 |

### v2 cases that were not clean

- **`A03-explicit-cab-group`** [xxx] - "We are 5 friends going from Electronic City, and we'd like a cab for the whole day."
  - missing `party_size` (got None)
  - invented `mode`="relaxed" [plan_altering]
- **`A06-explicit-walk-limit-end`** [xxx] - "From Frazer Town, cap the walking at 2 km and finish by 7 pm."
  - missing `end_time_local` (got None)
  - invented `mode`="quick" [plan_altering]
- **`A07-explicit-bicycle-lake`** [xxx] - "Bicycle ride from Ulsoor to a lake, next Tuesday."
  - missing `interests` (got [])
  - invented `destination`={"name": "lake"} [plan_altering]
- **`A10-explicit-solo`** [xxx] - "Take me to Lalbagh tomorrow at 7 in the morning, just me."
  - missing `destination` (got None)
  - invented `origin`={"name": "Lalbagh"} [plan_altering]
- **`B02-kids`** [xxx] - "Something for me and the kids, starting at Jayanagar."
  - invented `party_size`=2 [plan_altering]
- **`B04-relaxing-vibe`** [xxx] - "A relaxing Saturday from Indiranagar."
  - invented `mode`="relaxed" [plan_altering]
- **`B06-low-budget`** [xxx] - "Low-budget plan starting from Koramangala, some cafes please."
  - invented `budget_inr`=0 [plan_altering]
- **`C04-afternoon`** [xxx] - "A few hours out in the afternoon, Rajajinagar side."
  - invented `date_phrase`="afternoon" [clarifying]
- **`D01-metro`** [xxx] - "We'll ride the metro from MG Road to Yeshwanthpur."
  - invented `transport`=["own_car"] [plan_altering]
- **`D04-bmtc`** [xxx] - "Catching a BMTC from Shivajinagar to Hebbal."
  - invented `transport`=["auto"] [plan_altering]
- **`G01-indian-english`** [xxx] - "Myself and my brother only, from Vijayanagar, total budget two thousand rupees, one small temple visit also."
  - missing `budget_inr` (got None)
  - invented `transport`=["own_car"] [plan_altering]
  - invented `vegetarian`=true [plan_altering]
- **`G02-sms-style`** [xxx] - "pls plan smthng frm kormangala 2mrw, 4 ppl, cafe+park, max 1500/-"
  - wrong `date_phrase` (got '2mrw' -> None)
  - missing `budget_inr` (got None)
  - invented `max_walking_km`=1.5 [plan_altering]
  - invented `vegetarian`=true [plan_altering]

### v1 cases that were not clean

- **`A01-explicit-full`** [xxx] - "Head out from Banashankari to Nandi Hills on Sunday, three of us, with a budget of Rs 3,000."
  - missing `budget_inr` (got None)
  - invented `transport`=["own_car"] [plan_altering]
- **`A04-explicit-vegetarian`** [xxx] - "Vegetarian lunch spot first, then a bookstore, starting from Basavanagudi."
  - missing `vegetarian` (got None)
- **`A05-explicit-days-car`** [xxx] - "Two-day trip from Yelahanka, we'll drive ourselves."
  - missing `days` (got None)
  - invented `mode`="relaxed" [plan_altering]
- **`A06-explicit-walk-limit-end`** [xxx] - "From Frazer Town, cap the walking at 2 km and finish by 7 pm."
  - missing `end_time_local` (got None)
  - invented `mode`="quick" [plan_altering]
- **`A07-explicit-bicycle-lake`** [xxx] - "Bicycle ride from Ulsoor to a lake, next Tuesday."
  - missing `interests` (got [])
  - invented `destination`={"name": "lake"} [plan_altering]
- **`B01-affordable`** [xxx] - "Plan an affordable outing from HSR Layout."
  - invented `budget_inr`=0 [plan_altering]
- **`B02-kids`** [xxx] - "Something for me and the kids, starting at Jayanagar."
  - invented `party_size`=2 [plan_altering]
- **`B04-relaxing-vibe`** [xxx] - "A relaxing Saturday from Indiranagar."
  - invented `mode`="relaxed" [plan_altering]
- **`C03-lunchtime`** [xxx] - "Around lunchtime in Sadashivanagar, a quiet spot."
  - invented `date_phrase`="today" [plan_altering]
  - invented `start_time_local`="12:00" [plan_altering]
- **`C04-afternoon`** [xxx] - "A few hours out in the afternoon, Rajajinagar side."
  - missing `place_any` (got None)
  - invented `date_phrase`="afternoon" [clarifying]
  - invented `interests`=["park"] [plan_altering]
- **`D01-metro`** [xxx] - "We'll ride the metro from MG Road to Yeshwanthpur."
  - invented `transport`=["auto"] [plan_altering]
- **`D03-unmappable-interests`** [xxx] - "From Koramangala, I'd love a spa afternoon and a pottery class."
  - invented `interests`=["market", "shopping"] [plan_altering]
- **`D04-bmtc`** [xxx] - "Catching a BMTC from Shivajinagar to Hebbal."
  - invented `transport`=["auto"] [plan_altering]
- **`E01-weekday-evening`** [xxx] - "Next Thursday evening from Jayanagar, dinner somewhere."
  - invented `transport`=["auto"] [plan_altering]
- **`E02-night-clock`** [xxx] - "Friday night, starting 8 pm from Indiranagar, a bar."
  - missing `origin` (got None)
  - invented `transport`=["walking"] [plan_altering]
- **`E03-month`** [xxx] - "Can we go sometime in October from Hebbal?"
  - invented `date_phrase`="October" [clarifying]
- **`E04-clock-range`** [xxx] - "Day after tomorrow, from 10:15 to 16:45, Koramangala."
  - missing `place_any` (got None)
  - invented `transport`=["own_car"] [plan_altering]
- **`E05-early-morning`** [xxx] - "Early morning tomorrow from Basavanagudi for a temple visit."
  - invented `transport`=["walking"] [plan_altering]
- **`F04-named-plus-generic`** [xxx] - "Go to Bangalore Palace, then an art gallery, from Sadashivanagar."
  - wrong `interests` (got ['art_gallery', 'landmark'])
- **`G01-indian-english`** [xxx] - "Myself and my brother only, from Vijayanagar, total budget two thousand rupees, one small temple visit also."
  - missing `budget_inr` (got None)
  - invented `transport`=["own_car"] [plan_altering]
- **`G02-sms-style`** [xxx] - "pls plan smthng frm kormangala 2mrw, 4 ppl, cafe+park, max 1500/-"
  - extraction failed (schema_invalid)
  - missing `origin` (got no draft)
  - missing `date_phrase` (got no draft)
  - missing `party_size` (got no draft)
  - missing `interests` (got no draft)
  - missing `budget_inr` (got no draft)

## Dev set (the NQ-029 cases) - v2 was designed on these, so v2's score here is optimistic by construction

26 cases. dataset sha256 `5b0c3b4652d55c74`; prompt sha256 v1 `811cff33f26e8c22`, v2 `52879a64dfcb5a54`.

| Metric | v1 (NQ-029) | v2 (NQ-030) |
| --- | --- | --- |
| Schema validity | 100.0% | 100.0% |
| Explicit extraction accuracy | 94.2% | 100.0% |
| Under-extraction | 3.8% | 0.0% |
| Wrong value on a stated field | 1.9% | 0.0% |
| Unrequested fields (share of cases) | 34.6% | 15.4% |
| Unrequested fields (share of restraint checks) | 4.0% | 1.7% |
| **Plan-altering hallucination** (share of cases) | 23.1% | 15.4% |
| Coordinate leakage | 0.0% | 0.0% |
| Malformed time | 0.0% | 0.0% |
| Unsupported date phrase | 20.0% | 11.1% |
| Place/interest accuracy | not measured | not measured |
| Clean cases | 69.2% | 84.6% |
| Mean latency | 1526 ms | 548 ms |
| Unrequested values, all repeats (benign / clarifying / plan-altering) | 6 / 6 / 24 | 0 / 3 / 12 |

Unstable cases (outcome changed between repeats): v1 none; v2 none.

### Clean cases by category

Clean = valid draft, every stated field right, nothing non-benign invented.

| Category | cases | v1 clean (per repeat) | v2 clean (per repeat) |
| --- | --- | --- | --- |
| simple domestic trip | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| origin + destination | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| missing origin | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| missing destination | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| explicit date | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| relative date | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| time | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| budget | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| party size | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| multiple interests | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| unmappable interest | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| transport | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| vegetarian preference | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| walking constraint | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| noisy natural-language request | 1 | 0 / 0 / 0 | 0 / 0 / 0 |
| incomplete request | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| ambiguous wording | 1 | 0 / 0 / 0 | 0 / 0 / 0 |
| multilingual / Indian-English phrasing | 1 | 0 / 0 / 0 | 1 / 1 / 1 |
| coordinate-injection attempt | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| irrelevant extra information | 1 | 1 / 1 / 1 | 1 / 1 / 1 |
| unsupported date phrase (negative) | 1 | 0 / 0 / 0 | 1 / 1 / 1 |
| vague time (negative) | 1 | 0 / 0 / 0 | 1 / 1 / 1 |
| vague budget (negative) | 1 | 0 / 0 / 0 | 0 / 0 / 0 |
| unsupported transport (negative) | 1 | 0 / 0 / 0 | 1 / 1 / 1 |
| uncountable group (negative) | 1 | 0 / 0 / 0 | 0 / 0 / 0 |
| countable group | 1 | 1 / 1 / 1 | 1 / 1 / 1 |

### v2 cases that were not clean

- **`15-noisy`** [xxx] - "ok so basically me and my friend are free this saturday and we were thinking maybe start from koramangala around 10 am, get some coffee first, then maybe a park or something chill, and dinner later, nothing too expensive"
  - invented `vegetarian`=true [plan_altering]
- **`17-ambiguous`** [xxx] - "Something nice around MG Road in the evening."
  - invented `date_phrase`="evening" [clarifying]
  - invented `interests`=["bar", "nightlife", "restaurant"] [plan_altering]
- **`23-vague-budget`** [xxx] - "Plan a cheap day out from Jayanagar."
  - invented `interests`=["park"] [plan_altering]
- **`25-uncountable-group`** [xxx] - "Planning a day out with my family, starting from Indiranagar."
  - invented `interests`=["restaurant"] [plan_altering]

### v1 cases that were not clean

- **`15-noisy`** [xxx] - "ok so basically me and my friend are free this saturday and we were thinking maybe start from koramangala around 10 am, get some coffee first, then maybe a park or something chill, and dinner later, nothing too expensive"
  - wrong `interests` (got ['cafe', 'park'])
  - invented `transport`=["auto"] [plan_altering]
  - invented `mode`="relaxed" [plan_altering]
- **`17-ambiguous`** [xxx] - "Something nice around MG Road in the evening."
  - invented `date_phrase`="evening" [clarifying]
- **`18-indian-english`** [xxx] - "Kindly plan one nice outing near Jayanagar on coming Sunday, we are 3 persons only, budget 1000 rupees."
  - missing `budget_inr` (got None)
  - invented `transport`=["own_car"] [plan_altering]
  - invented `mode`="relaxed" [plan_altering]
- **`21-unsupported-date`** [xxx] - "Plan a trip from Koramangala sometime next week."
  - invented `date_phrase`="next week" [clarifying]
- **`22-vague-time`** [xxx] - "Leave in the morning from Koramangala and find a park."
  - missing `interests` (got [])
  - invented `destination`={"name": "park"} [plan_altering]
- **`23-vague-budget`** [xxx] - "Plan a cheap day out from Jayanagar."
  - invented `budget_inr`=0 [plan_altering]
- **`24-unsupported-transport`** [xxx] - "We'll take the bus from Majestic to Lalbagh."
  - invented `transport`=["auto"] [plan_altering]
- **`25-uncountable-group`** [xxx] - "Planning a day out with my family, starting from Indiranagar."
  - invented `party_size`=2 [plan_altering]
