"""NQ-017 - Deterministic POI ranking.

Selects and orders candidates for the optimizer. Pure scoring: no database
access, no side effects, fully testable.

Returns a component breakdown alongside every score. That breakdown is what
makes explanations honest later - "chosen because it matched your category
and was 400 m away" is verifiable; "chosen because it scored 0.73" is not.

RankingStrategy exists so the post-MVP XGBoost ranker is a drop-in. There is
exactly one implementation today and that is deliberate.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[4] / "data" / "config" / "ranking.yaml"


@lru_cache(maxsize=1)
def _config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


@dataclass
class RankingContext:
    """Everything the scorer needs beyond the POI itself."""
    wanted_categories: list[str]
    chosen_category_counts: dict[str, int]
    is_raining: bool = False
    arrival_min_of_day: int | None = None


@dataclass
class ScoredPOI:
    poi: dict
    score: float
    components: dict[str, float]

    def to_dict(self) -> dict:
        return {**self.poi, "rank_score": round(self.score, 4),
                "rank_components": {k: round(v, 4)
                                    for k, v in self.components.items()}}


def _category_match(poi: dict, wanted: list[str]) -> float:
    """1.0 exact primary match, else the best secondary link weight, else 0."""
    if not wanted:
        return 0.5          # no preference stated - neutral, not zero
    # Match on the category the search actually matched, not the primary. A
    # lake found via a sunset link must score as a sunset match, or it ranks
    # below everything and never reaches the optimizer.
    matched = poi.get("matched_category") or poi.get("category")
    if matched in wanted:
        return 1.0
    best = 0.0
    for link in poi.get("secondary_categories", []):
        if link["category"] in wanted:
            best = max(best, float(link["weight"]))
    return best


def _proximity(distance_m: float, falloff_m: float) -> float:
    """Linear falloff. Zero beyond falloff, never negative."""
    return max(0.0, 1.0 - (distance_m / falloff_m))


def _diversity(poi: dict, counts: dict[str, int], decay: float) -> float:
    """Decays with each POI already chosen in the same category.

    Without this the optimizer happily returns three cafes in a row because
    each individually scores well.
    """
    already = counts.get(poi.get("matched_category")
                         or poi.get("category", ""), 0)
    return decay ** already


def _weather_fit(poi: dict, ctx: RankingContext, cfg: dict) -> float:
    w = cfg["weather"]
    score = 0.5     # neutral when no weather context applies

    if ctx.is_raining:
        indoor = poi.get("indoor")
        if indoor is True:
            score = w["rain_indoor_bonus"]
        elif indoor is False:
            score = w["rain_outdoor_penalty"]

    if ctx.arrival_min_of_day is not None:
        in_golden = (w["golden_hour_start_min"] <= ctx.arrival_min_of_day
                     <= w["golden_hour_end_min"])
        is_sunset = poi.get("category") == "sunset" or any(
            l["category"] == "sunset"
            for l in poi.get("secondary_categories", [])
        )
        if in_golden and is_sunset:
            score = max(score, w["golden_hour_sunset_bonus"])

    return score


class RankingStrategy(Protocol):
    def score(self, poi: dict, ctx: RankingContext) -> ScoredPOI: ...


class DeterministicRanker:
    """The only implementation at MVP."""

    def __init__(self, config: dict | None = None) -> None:
        self.cfg = config or _config()
        self.w = self.cfg["weights"]

    def score(self, poi: dict, ctx: RankingContext) -> ScoredPOI:
        prominence = poi.get("editorial_score")
        if prominence is None:
            prominence = poi.get("prominence", 0.0)

        components = {
            "category_match": _category_match(poi, ctx.wanted_categories),
            "prominence": float(prominence),
            "proximity": _proximity(poi.get("distance_m", 0),
                                    self.cfg["proximity_falloff_m"]),
            "diversity": _diversity(poi, ctx.chosen_category_counts,
                                    self.cfg["diversity_decay"]),
            "weather_fit": _weather_fit(poi, ctx, self.cfg),
        }
        total = sum(self.w[k] * v for k, v in components.items())
        return ScoredPOI(poi=poi, score=total, components=components)

    def rank(
        self,
        pois: list[dict],
        wanted_categories: list[str],
        *,
        is_raining: bool = False,
        arrival_min_of_day: int | None = None,
        limit: int | None = None,
    ) -> list[ScoredPOI]:
        """Greedy selection: diversity is recomputed as each POI is chosen.

        A single sort would let the top N all share one category, because
        each would be scored against an empty selection.
        """
        limit = limit or self.cfg["candidate_limit"]
        remaining = list(pois)
        chosen: list[ScoredPOI] = []
        counts: dict[str, int] = {}

        while remaining and len(chosen) < limit:
            ctx = RankingContext(
                wanted_categories=wanted_categories,
                chosen_category_counts=counts,
                is_raining=is_raining,
                arrival_min_of_day=arrival_min_of_day,
            )
            scored = [self.score(p, ctx) for p in remaining]
            best = max(scored, key=lambda s: (s.score, -s.poi.get("distance_m", 0)))
            chosen.append(best)
            key = best.poi.get("matched_category") or best.poi.get("category", "")
            counts[key] = counts.get(key, 0) + 1
            remaining.remove(best.poi)

        return chosen
