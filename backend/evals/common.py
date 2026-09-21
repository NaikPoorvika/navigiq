"""Shared helpers for the evaluation suites (section 105).

Datasets live in <repo>/data/evals/*.jsonl, one example per line, each with
a `split`: `dev` examples may be used while improving the system; `test`
examples are only ever scored and reported. Numbers quoted in reports and
docs come from the test split.

Evaluations use a FIXED "now" so relative dates ("tomorrow", "this
Saturday") have stable expected answers: Monday 2026-09-21, 10:00 IST.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core.paths import data_dir

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=IST)


def load(name: str, split: str = "all") -> list[dict]:
    path = data_dir() / "evals" / f"{name}.jsonl"
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{n}: {exc}") from exc
        if split == "all" or row.get("split") == split:
            rows.append(row)
    ids = [r["id"] for r in rows]
    dupes = [i for i, c in Counter(ids).items() if c > 1]
    if dupes:
        raise ValueError(f"{path.name}: duplicate ids {dupes}")
    return rows


@dataclass
class SuiteResult:
    suite: str
    config: str                          # e.g. "rules" or "rules+llm(qwen3:14b)"
    split: str
    n: int
    metrics: dict[str, float]
    gates: dict[str, tuple[float, str, bool]] = field(default_factory=dict)  # value, op+target, ok
    failures: list[dict] = field(default_factory=list)
    breakdown: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(ok for _, _, ok in self.gates.values())

    def to_dict(self) -> dict:
        return {"suite": self.suite, "config": self.config, "split": self.split, "n": self.n,
                "metrics": self.metrics,
                "gates": {k: {"value": v, "target": t, "ok": ok}
                          for k, (v, t, ok) in self.gates.items()},
                "passed": self.passed, "breakdown": self.breakdown,
                "failures": self.failures[:60]}


def gate(result: SuiteResult, name: str, value: float, target: str) -> None:
    """target like '>=0.95' or '==0'."""
    op, num = (target[:2], float(target[2:])) if target[:2] in (">=", "<=", "==") else \
        (target[:1], float(target[1:]))
    ok = {">=": value >= num, "<=": value <= num, "==": value == num,
          ">": value > num, "<": value < num}[op]
    result.gates[name] = (round(value, 4), target, ok)


def per_label(pairs: list[tuple[str, str]]) -> dict[str, dict[str, float]]:
    """Precision/recall per label from (expected, predicted) pairs."""
    tp: Counter = Counter()
    fp: Counter = Counter()
    fn: Counter = Counter()
    for exp, got in pairs:
        if exp == got:
            tp[exp] += 1
        else:
            fp[got] += 1
            fn[exp] += 1
    labels = sorted(set(tp) | set(fp) | set(fn))
    out = {}
    for lab in labels:
        p = tp[lab] / (tp[lab] + fp[lab]) if tp[lab] + fp[lab] else 0.0
        r = tp[lab] / (tp[lab] + fn[lab]) if tp[lab] + fn[lab] else 0.0
        out[lab] = {"precision": round(p, 3), "recall": round(r, 3), "support": tp[lab] + fn[lab]}
    return out


def confusion(pairs: list[tuple[str, str]], top: int = 10) -> list[dict]:
    c: Counter = Counter((e, g) for e, g in pairs if e != g)
    return [{"expected": e, "predicted": g, "count": n} for (e, g), n in c.most_common(top)]


def by_group(rows: list[dict], key: str, correct: list[bool]) -> dict[str, float]:
    tot: dict[str, int] = defaultdict(int)
    ok: dict[str, int] = defaultdict(int)
    for r, c in zip(rows, correct):
        g = r.get(key, "?")
        tot[g] += 1
        ok[g] += int(c)
    return {g: round(ok[g] / tot[g], 3) for g in sorted(tot)}


def reports_dir() -> Path:
    from app.core.paths import artifacts_dir
    d = artifacts_dir() / "reports"
    d.mkdir(exist_ok=True)
    return d
