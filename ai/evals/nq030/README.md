# NQ-030 — TripDraft extraction: restraint prompt + held-out evaluation

One question:

> Did restraint improve **without** damaging explicit extraction?

**Answer, on 40 held-out cases: yes, on balance — with three genuine
case-level regressions and a class of failure the prompt cannot fix.**
Plan-altering hallucination fell from **46.2% → 27.5%** of cases while explicit
extraction *rose* from **84.5% → 92.8%**. But v2 still substitutes a supported
transport mode for an unsupported one in 2 of 2 held-out cases, and the reason
turned out to be the decoding grammar, not the model's understanding.

Full numbers: [`results/report.md`](results/report.md). Raw model output for
every call: `results/*.json`.

---

## 1. The NQ-029 baseline

Model `qwen3:14b`, prompt v1, 26 cases, from `ai/evals/nq029/`:

| | |
| --- | --- |
| schema validity | 100% |
| critical-field accuracy | 92.6% |
| hallucination rate | 26.9% |
| unsupported date phrase | 18.2% |
| coordinate leakage / malformed time | 0% / 0% |

**The aggregate hid the important result.** Positive extraction was
substantially better than restraint:

| | cases | clean |
| --- | --- | --- |
| positive — extract what was said | 21 | 18 (86%) |
| negative — don't invent what wasn't | 5 | **0 (0%)** |

**The NQ-029 baseline failed all five original restraint cases.** It turned
"the bus" into `auto`, "cheap" into `budget_inr: 0`, "my family" into
`party_size: 2`, "sometime next week" into an unresolvable `date_phrase`, and
"find a park" into a destination literally named "park".

## 2. What the failures turned out to be

### Finding 1 — constrained decoding causes part of the "hallucination"

With JSON-schema constrained decoding off, the same prompt and the same model
answer differently:

| input | schema **off** | schema **on** |
| --- | --- | --- |
| "We'll take the bus…" | `"transport": ["bus"]` | `"transport": ["auto"]` |
| "…with my family…" | `interests: ["family"]` | `interests: ["restaurant"]` |
| "…3 persons only, budget 1000 rupees" | budget 1000, nothing invented | **budget lost**, `own_car` + `relaxed` + `vegetarian` invented |

Both v1 and v2 behave this way. Two mechanisms explain it:

1. **Enum coercion.** Once the model starts writing a key, the grammar only
   lets it finish with an allowed value. A model that means "bus" is forced
   to write the most probable *legal* token: `auto`. What looks like a
   substitution is the grammar overriding a correct intent.
2. **Fixed key order.** The grammar emits keys in schema order (`budget_inr`
   before `party_size`) and cannot go back. If a sentence gives the party size
   first, writing `party_size` permanently skips `budget_inr`. The model's
   remaining intent then leaks into later keys (`transport`, `vegetarian`,
   `mode`). v1's own worked example wrote `party_size` before `budget_inr`,
   teaching exactly the order the grammar punishes.

This is outside what a prompt alone can fully fix — see §7.

### Finding 2 — the model is not bit-reproducible

Re-running the NQ-029 baseline (v1, temperature 0, seed 0) in a new session
changed **2 of 26** raw responses, moving the hallucination rate from 26.9% to
30.8%. Within a single session, three repeats were bit-identical for both
prompts. **The ranges in `results/report.md` therefore do not bound the real
variance**: a difference of one or two cases between prompts is inside the
noise. The cause (KV-cache reuse, GPU floating-point order, …) has not been
isolated.

## 3. What v2 changed

`backend/app/llm/prompts/tripdraft_extraction_v2.md`. v1 is untouched
(sha256-pinned) and still selectable, so the baseline can be re-run.

- **One global restraint rule first**, ahead of every field section:
  "Extraction is not interpretation… When uncertain, OMIT rather than GUESS",
  plus an evidence test: point at the words, or don't output the field.
- **Extracting vs inferring**, taught with paired examples ("Budget is Rs
  2500" → 2500; "a cheap day out" → nothing, and never 0).
- **The schema key order, injected from the schema actually sent**, with the
  instruction to decide every field before writing and never to open a key
  that has no allowed value. Every example is now written in schema order,
  and a test enforces that.
- **"Don't express it through another field"**: "cheap" must not become
  cheap-sounding interests, "evening" must not become a date phrase.
- **Field rules sharpened**: named place vs generic kind of place; date
  wording vs time of day; walking as transport vs walking as an activity;
  numeric vs qualitative budgets, including Indian-English forms; countable
  vs uncountable groups; pace vs mood.
- **Negative examples**: unsupported transport, vague budget, unsupported
  date, uncountable group, generic attraction, time of day.

The production default is now v2 (`PROMPT_VERSION = "v2"` in
`backend/app/llm/extraction.py`). The model, gateway, schema, draft_builder,
resolver and planner are unchanged.

## 4. Methodology

**Two datasets, kept apart.**

- **dev** = the 26 NQ-029 cases. v2 was designed against their failures and
  revised **3 times** on them, then frozen. v2's dev score is optimistic by
  construction and is reported only for context.
- **held-out** = `heldout.json`, **40 new cases**, written after v2 was
  frozen and run exactly once per prompt. v2 was not changed afterwards.

| category | held-out cases |
| --- | --- |
| explicit extraction | 10 |
| missing-information restraint | 8 |
| ambiguous wording | 5 |
| unsupported enum values | 4 |
| date/time distinction | 5 |
| place/interest distinction | 5 |
| Indian-English / noisy | 3 |

**The freeze is enforced, not promised** (`test_scoring.py`):

- `heldout.json` and the v2 prompt are sha256-pinned (line-ending
  normalised). Any edit fails the build.
- A leakage guard fails if any held-out input shares a 5-word phrase with the
  v2 prompt. It caught one real overlap (B05, "Plan a day out from…"), which
  was reworded **before** any prompt had been run on the set.
- No held-out input repeats a dev input.

One honest caveat: the same author wrote v2 and the held-out set, so the set
cannot be fully blind to the prompt's concepts. The wording is independent,
and several held-out cases deliberately test concepts in forms the prompt
never names ("BMTC" for bus, "the kids", "Low-budget", "two thousand
rupees").

**Scoring** (`scoring.py`) is deterministic and measures both directions:

- **stated fields** are scored as correct, missing (under-extraction) or
  wrong;
- **every other field** must stay empty, computed rather than hand-listed;
- **each unrequested value is classified** by what `draft_builder.py`
  would do with it:
  - *benign*: equal to its default when absent — `vegetarian: false`,
    `mode: balanced`, `party_size: 1`, `days: 1`, 3 km walking,
    walking+auto transport — or a field nothing consumes yet
    (`free_text_interests`);
  - *clarifying*: an unresolvable `date_phrase`, which becomes a question;
  - *plan-altering*: everything else;
- **a wrong value for a stated field counts as plan-altering.** NQ-029's
  scorer filed bus → auto as a "missed field", so the most dangerous answer
  never reached its hallucination number.

Coordinate leakage, malformed times and unsupported dates are measured on the
raw model output, before `TripDraft` can hide them. Every run records the
model, prompt version and hash, dataset hash, seed, temperature, token cap and
timestamp.

## 5. Results — held-out (the honest number)

`qwen3:14b`, temperature 0, seed 0, 3 repeats (bit-identical within the
session).

| Metric | v1 (NQ-029) | v2 (NQ-030) |
| --- | --- | --- |
| Schema validity | 97.5% (39/40) | **100%** (40/40) |
| Explicit extraction accuracy | 84.5% (82/97) | **92.8%** (90/97) |
| Under-extraction | 14.4% (14/97) | **6.2%** (6/97) |
| Wrong value on a stated field | 1.0% (1/97) | 1.0% (1/97) |
| Unrequested fields — cases | 48.7% (19/39) | **30.0%** (12/40) |
| Unrequested fields — per restraint check | 5.9% (26/444) | **3.3%** (15/453) |
| **Plan-altering hallucination** | 46.2% (18/39) | **27.5%** (11/40) |
| Coordinate leakage | 0% | 0% |
| Malformed time | 0% (of 5) | 0% (of 4) |
| Unsupported date phrase | 16.7% (3/18) | 12.5% (2/16) |
| Place/interest accuracy | 80% (4/5) | **100%** (5/5) |
| Clean cases | 47.5% (19/40) | **70.0%** (28/40) |
| Mean latency | 682 ms | 626 ms |

Unrequested values by severity (benign / clarifying / plan-altering): v1
6 / 2 / 18, v2 1 / 1 / 13, per repeat.

**By category, clean cases:**

| category | cases | v1 | v2 |
| --- | --- | --- | --- |
| explicit extraction | 10 | 5 | 6 |
| missing-info restraint | 8 | 5 | 5 |
| ambiguous wording | 5 | 3 | 4 |
| unsupported enum | 4 | 1 | 2 |
| date/time | 5 | **0** | **5** |
| place/interest | 5 | 4 | 5 |
| Indian-English / noisy | 3 | 1 | 1 |

Dev set, for context only: plan-altering hallucination 23.1% → 15.4%;
explicit extraction 94.2% → 100%; clean cases 69.2% → 84.6%.

## 6. Regression analysis

**Explicit extraction did not degrade in aggregate — it improved** (84.5% →
92.8%, under-extraction 14.4% → 6.2%). v2 fixed 12 held-out cases, most
visibly all five date/time cases: v1 invented `transport` on four of them.

**But three held-out cases were clean under v1 and are not under v2:**

| case | v1 | v2 | likely cause |
| --- | --- | --- | --- |
| A03 "We are **5 friends**… a cab" | `party_size: 5` ✓ | party size **dropped**, `mode: relaxed` invented | over-correction: v2's negative example "with friends → omit" generalised to a sentence that *does* give a number |
| A10 "Take me **to** Lalbagh" | destination ✓ | filed as **origin** | not explained by any v2 rule |
| B06 "**Low-budget** plan…" | no budget ✓ | `budget_inr: 0` | the exact failure v2 targets, in a form it doesn't name ("low cost" is listed, "low-budget" isn't) |

A03 is the over-correction the task warned about. It is one case, but it
touches an explicit number — the category that matters most to get right.

## 7. What is still wrong under v2

**Unsupported transport is still substituted — 2 of 2 held-out cases.**
"ride the metro" → `own_car`; "catching a BMTC" → `auto`. v2 fixed bus → auto
on the dev set, where the prompt names bus explicitly, but it does not
generalise. This is Finding 1: once the transport key is open, the grammar
must finish it with a legal value. **A prompt cannot reliably fix this.** The
real fixes are architectural and are the user's decision, not NQ-030's:

- send a derived decoding schema that lets `transport` carry an out-of-enum
  marker, then drop it when mapping to `TripDraft`; or
- decode without the grammar and rely on `TripDraft` validation, which under
  ADR-016 refuses (422) rather than silently substituting. That trades a
  quiet wrong answer for a loud failure, and schema validity would then
  measure something real; or
- reorder `TripDraft` fields to match natural sentence order. This changes
  the schema, which NQ-030 is not permitted to do without approval.

**Other open failures on v2 (held-out):**

- **Mood as pace:** "A relaxing Saturday" → `mode: relaxed`. Also appears
  unprompted in A03 and A06.
- **Uncountable group:** "me and the kids" → `party_size: 2`.
- **Generic place as destination:** "Bicycle ride… to a lake" →
  `destination: "lake"`. This happens under both prompts; "find a lake"
  (F02) is handled correctly, "ride to a lake" is not.
- **Time of day as date:** "in the afternoon" → `date_phrase: "afternoon"`.
  This is clarifying, not plan-altering.
- **Indian-English budgets in words or shorthand are missed:** "two thousand
  rupees" and "max 1500/-". The model read the latter as `max_walking_km:
  1.5`.
- **v2 invents `vegetarian: true` in Indian-English requests** (G01, G02).
  v1 did not on G01; v1's G02 answer failed schema validation outright, so
  it can't be compared. This is inference from phrasing or perceived culture,
  exactly what the prompt forbids, and should be treated as a serious
  failure mode rather than a small rate.
- **SMS shorthand:** "2mrw" is copied through unresolved.

## 8. Limitations

- **Small sample.** 40 held-out cases; one case moves a category rate by
  10–33 points. Category-level differences of one case are not evidence.
- **Cross-session nondeterminism** (Finding 2) is real and unquantified. In
  this run the three in-session repeats were identical, so they understate
  variance. A proper interval needs runs across fresh sessions.
- **Latency is confounded.** v1 always ran first on each dataset (cold
  cache); v1's held-out maximum of 4.3 s is the first call. v2's prompt is
  ~2,600 tokens against v1's ~1,500 but ran no slower, so prompt length is not
  a practical latency concern here.
- **"Benign" is defined against today's `draft_builder` defaults.** If
  `free_text_interests` becomes consumed by the planner, invented free text
  becomes plan-altering and the numbers move.
- **The held-out set now reflects v2's concepts.** It stays valid for v2. A
  v3 needs a new held-out set, because v3 would be designed knowing these
  failures.

## 9. Conclusion

v2 is a clear, balanced improvement and is now the default. Plan-altering
hallucination fell by about 40% relative (46.2% → 27.5%) and every
place/interest and date/time held-out case is now clean. Explicit extraction
improved rather than degraded, with three specific case regressions recorded
above.

It is not finished. **27.5% of held-out requests still get a plan-altering
invention.** The largest single remaining cause — substituting an allowed
transport mode for an unsupported one — is produced by constrained decoding
itself and needs an architectural decision, not more prompt text. v2 was not
revised after the held-out run. Any v3 must start from a new held-out set.

## Reproduce

```bash
python -m pytest ai/evals/nq030 -q          # scorer + freeze tests, no GPU
python ai/evals/nq030/evaluate.py           # v1+v2 x heldout+dev x 3 repeats
python ai/evals/nq029/run.py                # the NQ-029 v1 baseline (pinned)
```

Expect small cross-session differences in the raw outputs (Finding 2).
