# Evaluation history (append-only)

Every held-out result is recorded here BEFORE anything is changed in
response to it. Once a test split has been looked at and the system changed
because of it, that split is relabelled `dev` and a new, unseen test split is
written. Numbers in README/docs always cite the latest untouched split.

## Intent classification (gate: accuracy >= 0.95)

| Date | Split | n | Rules only | Rules + qwen3:14b | Notes |
|---|---|---|---|---|---|
| 2026-09-21 | test v1 (t001-t120) | 120 | 0.925 | 0.942 | First held-out run. Failures: greetings with a tail ("hey there") and generic phrases resolving to random POIs through trigram word-similarity; "what's ..." grabbed by the details rule; save/different phrasings. v1 relabelled dev. |
| 2026-09-21 | test v2 (h001-h120) | 120 | 0.817 | 0.925 | Harder, more varied phrasing. Main cause: interest-word catch-all rules claimed 0.85 confidence, so the LLM was never consulted on questions like "does Cubbon Park close at night?"; trips to other cities matched the planning rule before the out-of-scope check. v2 relabelled dev. |
| 2026-09-21 | test v3 (k001-k120) | 120 | 0.708 | 0.917 | After calibrating question-shaped catch-alls. LLM alone on the same split: 0.892; rules and LLM are each right where the other fails (oracle 0.975), so the arbitration policy - not either component - is the bottleneck. Catch-all rules ("discover" 14/23, "area_search" 7/10 on this split) are far less precise than on dev, where they were tuned. v3 relabelled dev. |
| 2026-09-21 | test v4 (m001-m120) | 120 | 0.750 | **0.967** | After: catch-all rules defer to the model when one is available (rules still decide alone when it is not); DISCOVER/PLACE_SEARCH disagreements keep the rules' area-aware label; the intent prompt (v2.1) names the languages users write in. By language with the model: en 0.962, Hinglish 1.0, romanized Kannada 1.0, Kannada script 1.0. Remaining misses: the model files "is photography allowed / can I bring food" under local knowledge; "hiya" read as out of scope; "more nature in the plan" caught by the planning rule. **Current held-out result.** |

## TripSpec extraction (gates: schema-valid >= 0.99, critical-field >= 0.92, relative-date >= 0.98, hard-constraint >= 0.98)

| Date | Split | n | Config | Schema | Critical | Rel. date | Hard | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-09-21 | test v1 (t001-t040) | 40 | rules | 1.00 | 0.974 | 1.00 | 0.919 | |
| 2026-09-21 | test v1 (t001-t040) | 40 | rules + qwen3:14b | 1.00 | 0.974 | 1.00 | 0.946 | Hard-constraint misses: separate start and end phrases ("leave 5 am, back by 1 pm", "start at noon and end by 6") yielded only one of the two; "4000 for both of us" has no currency word and was not read as money; "a gentle morning" not read as relaxed pace. v1 relabelled dev. |
| 2026-09-21 | test v2 (u001-u040) | 40 | rules | 1.00 | 0.941 | 0.971 | 0.957 | |
| 2026-09-21 | test v2 (u001-u040) | 40 | rules + qwen3:14b | 1.00 | 0.941 | 0.971 | 0.957 | Identical: the rules win every field they fill and the model may only add ungrounded-free extras, so it rarely changes the result. Misses: "Monday next week"; bare hours in an evening context ("date night ... from 7"); "head out at 6, back by 6 pm"; area names swallowing following words ("Basavanagudi the day after tomorrow", "varege Indiranagar", "from now"); "chilled" pace; a destination named with "a full day at Nandi Hills". v2 relabelled dev. |
| 2026-09-21 | test v3 (w001-w040) | 40 | rules | 1.00 | 0.986 | 1.00 | 0.978 | |
| 2026-09-21 | test v3 (w001-w040) | 40 | rules + qwen3:14b | 1.00 | 0.986 | 1.00 | 0.978 | Hard-constraint gate missed by one field: an avoided-area list ("avoid Whitefield and Electronic City") kept only the first area. Other misses: "3 colleagues and me" (3, not 4), "we're 2 couples" (2, not 4). v3 relabelled dev after fixing these. |

## Plan modification (gates: operation accuracy >= 0.95, target resolution >= 0.95)

| Date | Split | n | Rules only | Rules + qwen3:14b | Notes |
|---|---|---|---|---|---|
| 2026-09-21 | test v1 (e001-e040) | 40 | ops 1.00, targets 1.00, clarification 1.00 | ops 1.00, targets 1.00 | First held-out run, after dev-only work (dev was 0.74 before it). Caveat: dev and test were written in the same sitting by the same author, so phrasing overlap is likely higher than with real users; treat as an upper bound. |

## Reference resolution (gate: >= 0.95)

| Date | Split | n | Accuracy | Notes |
|---|---|---|---|---|
| 2026-09-21 | test v1 (q001-q020) | 20 | 1.00 | Deterministic resolver; ambiguous references are reported as ambiguous. Same authorship caveat as above. |

## Retrieval (gate: hybrid recall@6 >= 0.85)

Real corpus (290 Wikipedia articles, 248 POI pages, 1 guide; 2,494 chunks; nomic-embed-text).

| Date | Split | Answerable | Sparse R@6 / MRR | Dense R@6 / MRR | Hybrid R@6 / MRR | Notes |
|---|---|---|---|---|---|---|
| 2026-09-21 | test v1 | 54 | 0.889 / 0.666 | 0.963 / 0.872 | **1.000 / 0.855** | Questions were written from the articles' opening paragraphs, so lexical overlap with the corpus is higher than for real users; dense retrieval alone is the better guide to paraphrase robustness. The relevance check alone refuses none of the unanswerable questions - refusal happens at the answer stage (below). |

## Grounded answers (gates: citation coverage >= 0.98; numeric grounding failures, fabricated citations, fabricated URLs == 0)

Every answer is re-audited independently of the answer module (citations against returned sources, numbers against the cited chunks' full text, URLs against source URLs).

| Date | Split | Config | Answer rate | Key-term recall | Refusal (unanswerable) | Coverage | Numeric fails | Fab. cites | Fab. URLs |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-21 | test v1 | extractive (LLM down) | 0.944 | 0.667 | 0.333 | 1.00 | 0 | 0 | 0 |
| 2026-09-21 | test v1 | qwen3:14b | 1.000 | **0.963** | **1.000** | **1.00** | **0** | **0** | **0** |

Before this run the extractive fallback was improved on dev only (key-term recall 0.60 -> 0.87, unanswerable refusal 0.0 -> 0.6): it now requires the question's own words (or the answer shape: a year for "when", a quantity with a unit for "how far") in the quoted sentence and refuses otherwise. On the held-out split it still answered a volatile question ("today's entry ticket price") from encyclopaedic text; volatile questions are now refused unless live facts are supplied (dev-only change after this run).
