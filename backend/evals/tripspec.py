"""TripSpec extraction eval over data/evals/tripspec.jsonl.

Each example lists only the fields the text states (`expect`) and, where
useful, fields that must stay empty (`absent`) so invented values count as
errors. Scoring per field:

  exact        date, start_time, end_time, budget_*, party_*, pace, stop counts,
               indoor_preference
  subset       interests, avoid_interests, dietary/meal/accessibility lists,
               must-include names (the expected values must all be present)
  set-equal    areas, avoid_areas (extra areas are as wrong as missing ones)

Gates (section 105): schema-valid >= 0.99, critical-field accuracy >= 0.92,
relative-date accuracy >= 0.98, hard-constraint accuracy >= 0.98.
"""
from __future__ import annotations

from app.assistant.extraction import extract_trip_spec

from .common import NOW, SuiteResult, by_group, gate, load

EXACT = {"date", "start_time", "end_time", "budget_total", "budget_per_person", "party_size",
         "party_type", "pace", "desired_stop_count", "max_stop_count", "indoor_preference"}
SUBSET = {"interests", "avoid_interests", "dietary_preferences", "meal_preferences",
          "accessibility_requirements", "must"}
SETEQ = {"areas", "avoid_areas"}
CRITICAL = {"date", "start_time", "end_time", "budget_total", "budget_per_person", "party_size",
            "interests", "areas"}
HARD = {"budget_total", "budget_per_person", "end_time", "avoid_interests", "dietary_preferences",
        "accessibility_requirements", "must", "avoid_areas"}


def observed(ex) -> dict:
    d = ex.spec.model_dump(mode="json")
    d["areas"] = [a.lower() for a in ex.area_names]
    d["avoid_areas"] = [a.lower() for a in (ex.avoid_area_names or d.get("avoid_areas") or [])]
    d["must"] = [m.lower() for m in ex.must_include_names]
    return d


def field_ok(name: str, want, got) -> bool:
    if name in SUBSET:
        got_set = {str(g).lower() for g in (got or [])}
        if name == "must":
            return all(any(w in g or g in w for g in got_set) for w in want)
        return set(want) <= got_set
    if name in SETEQ:
        return {w.lower() for w in want} == {str(g).lower() for g in (got or [])}
    return want == got


def is_empty(v) -> bool:
    return v in (None, [], "", {})


async def run(db, *, llm=None, split: str = "test", config: str = "rules") -> SuiteResult:
    rows = load("tripspec", split)
    counts = {k: [0, 0] for k in ("all", "critical", "hard", "date", "absent")}
    per_field: dict[str, list[int]] = {}
    valid = 0
    failures = []
    correct_rows = []
    for r in rows:
        try:
            ex = await extract_trip_spec(r["text"], now=NOW, llm=llm)
            got = observed(ex)
            valid += 1
        except Exception as exc:  # noqa: BLE001 - a crash is a schema failure
            failures.append({"id": r["id"], "error": type(exc).__name__})
            correct_rows.append(False)
            continue
        row_ok = True
        for name, want in r["expect"].items():
            ok = field_ok(name, want, got.get(name))
            pf = per_field.setdefault(name, [0, 0])
            pf[0] += ok
            pf[1] += 1
            buckets = ["all"] + (["critical"] if name in CRITICAL else []) + \
                (["hard"] if name in HARD else []) + (["date"] if name == "date" else [])
            for b in buckets:
                counts[b][0] += ok
                counts[b][1] += 1
            if not ok:
                row_ok = False
                failures.append({"id": r["id"], "text": r["text"], "field": name,
                                 "expected": want, "got": got.get(name)})
        for name in r.get("absent", []):
            ok = is_empty(got.get(name))
            counts["absent"][0] += ok
            counts["absent"][1] += 1
            if not ok:
                row_ok = False
                failures.append({"id": r["id"], "text": r["text"], "field": name,
                                 "expected": "absent", "got": got.get(name)})
        correct_rows.append(row_ok)

    def rate(k: str) -> float:
        ok, n = counts[k]
        return ok / n if n else 1.0

    metrics = {"schema_valid": round(valid / len(rows), 4), "field_accuracy": round(rate("all"), 4),
               "critical_field_accuracy": round(rate("critical"), 4),
               "hard_constraint_accuracy": round(rate("hard"), 4),
               "relative_date_accuracy": round(rate("date"), 4),
               "no_invented_fields": round(rate("absent"), 4),
               "fully_correct_examples": round(sum(correct_rows) / len(rows), 4)}
    res = SuiteResult("tripspec", config, split, len(rows), metrics, failures=failures,
                      breakdown={"per_field": {k: round(v[0] / v[1], 3)
                                               for k, v in sorted(per_field.items())},
                                 "by_language": by_group(rows, "lang", correct_rows)})
    gate(res, "schema_valid", metrics["schema_valid"], ">=0.99")
    gate(res, "critical_field_accuracy", metrics["critical_field_accuracy"], ">=0.92")
    gate(res, "relative_date_accuracy", metrics["relative_date_accuracy"], ">=0.98")
    gate(res, "hard_constraint_accuracy", metrics["hard_constraint_accuracy"], ">=0.98")
    return res
