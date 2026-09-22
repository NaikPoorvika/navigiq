# NQ-029 extraction evaluation

- model: `qwen3:14b`  (selected by ADR-012, not re-evaluated here)
- prompt: `tripdraft_extraction_v1.md`
- context: 8192
- run at: 2026-09-22T07:00:45+00:00
- cases: 26

Measured through `extract_trip_draft()`, the same function the API
calls. Coordinate leakage and malformed times are measured on the
raw model response, before TripDraft drops or rejects anything.

## Summary

| metric | value | basis |
| --- | --- | --- |
| schema validity | 100.0% | 26/26 cases |
| critical-field accuracy | 92.6% | 50/54 field checks |
| hallucination rate | 26.9% | 7/26 valid drafts |
| coordinate leakage | 0.0% | 0 raw responses |
| malformed-time rate | 0.0% | 0/2 responses that contained a time |
| unsupported-date-phrase rate | 18.2% | 2/11 responses that contained a date phrase |
| mean latency | 507 ms | per case |

## Per case

| case | class | draft | fields | issues |
| --- | --- | --- | --- | --- |
| `01-simple-trip` | simple domestic trip | yes | 1/1 | - |
| `02-origin-destination` | origin + destination | yes | 3/3 | - |
| `03-missing-origin` | missing origin | yes | 2/2 | - |
| `04-missing-destination` | missing destination | yes | 3/3 | - |
| `05-explicit-date` | explicit date | yes | 1/1 | - |
| `06-relative-date` | relative date | yes | 2/2 | - |
| `07-times` | time | yes | 3/3 | - |
| `08-budget` | budget | yes | 2/2 | - |
| `09-party-size` | party size | yes | 2/2 | - |
| `10-multiple-interests` | multiple interests | yes | 2/2 | - |
| `11-unmappable-interest` | unmappable interest | yes | 3/3 | - |
| `12-transport` | transport | yes | 3/3 | - |
| `13-vegetarian` | vegetarian preference | yes | 2/2 | - |
| `14-walking-limit` | walking constraint | yes | 2/2 | - |
| `15-noisy` | noisy natural-language request | yes | 3/4 | invented transport, vegetarian, mode; missed interests |
| `16-incomplete` | incomplete request | yes | 0/0 | - |
| `17-ambiguous` | ambiguous wording | yes | 1/1 | invented date_phrase; unsupported date 'evening' |
| `18-indian-english` | multilingual / Indian-English phrasing | yes | 3/4 | invented transport, mode; missed budget_inr |
| `19-coordinate-injection` | coordinate-injection attempt | yes | 1/1 | - |
| `20-irrelevant-info` | irrelevant extra information | yes | 3/3 | - |
| `21-unsupported-date` | unsupported date phrase (negative) | yes | 1/1 | invented date_phrase; unsupported date 'next week' |
| `22-vague-time` | vague time (negative) | yes | 1/2 | invented destination, date_phrase; missed interests |
| `23-vague-budget` | vague budget (negative) | yes | 1/1 | invented budget_inr |
| `24-unsupported-transport` | unsupported transport (negative) | yes | 2/3 | missed transport |
| `25-uncountable-group` | uncountable group (negative) | yes | 1/1 | invented party_size |
| `26-countable-group` | countable group | yes | 2/2 | - |

## Misses in detail

**`15-noisy`** (noisy natural-language request)
- expected `interests`, got ['cafe', 'park']
- invented `transport` (not in the request)
- invented `vegetarian` (not in the request)
- invented `mode` (not in the request)

**`17-ambiguous`** (ambiguous wording)
- invented `date_phrase` (not in the request)

**`18-indian-english`** (multilingual / Indian-English phrasing)
- expected `budget_inr`, got None
- invented `transport` (not in the request)
- invented `mode` (not in the request)

**`21-unsupported-date`** (unsupported date phrase (negative))
- invented `date_phrase` (not in the request)

**`22-vague-time`** (vague time (negative))
- expected `interests`, got []
- invented `destination` (not in the request)
- invented `date_phrase` (not in the request)

**`23-vague-budget`** (vague budget (negative))
- invented `budget_inr` (not in the request)

**`24-unsupported-transport`** (unsupported transport (negative))
- expected `transport`, got ['auto']

**`25-uncountable-group`** (uncountable group (negative))
- invented `party_size` (not in the request)
