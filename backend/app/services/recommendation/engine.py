"""Recommendation service: geography -> candidates -> hard filters -> scores
-> diverse selection (ADR-027). Deterministic given its inputs.

Adaptive geography (section 8): a request with an anchor searches locally
(3 km, widened once to 6 km when results are thin) and NEVER reaches the
regional bands; "city" requests draw from CITY_CORE + CITY; regional
requests ("outside Bengaluru", "weekend escape") from OUTSKIRTS +
NEARBY_ESCAPE; the 90 km envelope is only the outer limit.
"""
from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.taxonomy import MOOD_DEFINITIONS, REGIONAL_CATEGORIES, Mood, is_valid_mood
from app.geo.regions import geo_config
from app.services.poi.repository import (
    CandidateQuery, POIRecord, attach_hours, fetch_by_ids, fetch_candidates,
)
from app.services.recommendation.scoring import (
    Anchor, NoveltyContext, Preferences, RecommendationRequest, Scored, config, hard_filter,
    jaccard, score_poi, select_diverse,
)


@dataclass
class RecommendationResult:
    items: list[Scored]
    scope: str
    anchor: dict | None
    candidate_count: int
    filtered: dict[str, int]
    config_version: str
    widened: bool = False
    overlap_with_previous: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "items": [s.to_dict() for s in self.items],
            "meta": {
                "scope": self.scope, "anchor": self.anchor,
                "candidate_count": self.candidate_count, "filtered": self.filtered,
                "ranking_config_version": self.config_version, "widened": self.widened,
                "overlap_with_previous": self.overlap_with_previous, "notes": self.notes,
            },
        }


def infer_scope(req: RecommendationRequest) -> str:
    if req.scope:
        return req.scope
    if req.anchor is not None:
        return "local"
    wanted = set(req.categories)
    if wanted and wanted <= REGIONAL_CATEGORIES:
        return "anywhere"
    return "city"


def build_query(req: RecommendationRequest, scope: str, radius_km: float | None) -> CandidateQuery:
    cfg = geo_config()
    moods = [m for m in req.moods if is_valid_mood(m)]
    any_cats = list(req.categories)
    any_tags = list(req.tags)
    for m in moods:
        d = MOOD_DEFINITIONS[Mood(m)]
        any_cats += d["categories"]
        any_tags += d["tags"]
    relevance = bool(any_cats or any_tags or moods) and req.mode not in ("similar",)
    q = CandidateQuery(
        recommendable_only=req.recommendable_only,
        exclude_ids=list(req.exclude_ids) or None,
        avoid_categories=req.avoid_categories or None,
        avoid_tags=req.avoid_tags or None,
        max_cost_typical=req.budget_per_person,
        any_categories=sorted(set(any_cats)) if relevance else None,
        any_tags=sorted(set(any_tags)) if relevance else None,
        any_moods=sorted(set(moods)) if relevance else None,
        limit=700,
    )
    if scope == "local" and req.anchor is not None:
        q.anchor_lat, q.anchor_lon = req.anchor.lat, req.anchor.lon
        q.radius_km = radius_km or req.anchor.radius_km
    elif scope == "regional":
        q.buckets = [b.value for b in cfg.scope_buckets["regional"]]
    elif scope in ("city", "local"):
        q.buckets = [b.value for b in cfg.scope_buckets["city"]]
    else:
        q.buckets = [b.value for b in cfg.scope_buckets["anywhere"]]
    if req.similar_to is not None and req.anchor is None:
        # Similar places stay in the reference's neighbourhood of the map:
        # a city cafe's lookalikes are city cafes, an escape's are escapes.
        q.buckets = ([b.value for b in cfg.scope_buckets["regional"]]
                     if req.similar_to.region_bucket in ("OUTSKIRTS", "NEARBY_ESCAPE")
                     else [b.value for b in cfg.scope_buckets["city"]])
    return q


async def load_novelty(db: AsyncSession, *, user_id: uuid.UUID | None, session_id: str | None,
                       previous_ids: list[int] | None = None) -> NoveltyContext:
    cfg = config()["novelty"]
    ctx = NoveltyContext(previous_ids=set(previous_ids or []))
    if user_id is None and not session_id:
        return ctx
    now = datetime.now(timezone.utc)
    rows = (await db.execute(text("""
        SELECT poi_id, action, created_at FROM poi_interactions
        WHERE (CAST(:uid AS uuid) IS NOT NULL AND user_id = CAST(:uid AS uuid))
           OR (CAST(:sid AS text) IS NOT NULL AND session_id = CAST(:sid AS text))
        ORDER BY created_at DESC LIMIT 2000
    """), {"uid": str(user_id) if user_id else None, "sid": session_id})).all()
    shown_cut = now - timedelta(hours=cfg["shown_window_hours"])
    dismiss_cut = now - timedelta(days=cfg["dismissed_window_days"])
    for r in rows:
        ts = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        if r.action in ("shown", "view", "click") and ts >= shown_cut:
            ctx.shown_recently.add(r.poi_id)
        elif r.action == "dismiss" and ts >= dismiss_cut:
            ctx.dismissed.add(r.poi_id)
        elif r.action == "mark_visited":
            ctx.visited.add(r.poi_id)
    if user_id is not None:
        saved = (await db.execute(text("SELECT poi_id FROM saved_pois WHERE user_id = :u"),
                                  {"u": user_id})).scalars().all()
        ctx.saved = set(saved)
    if ctx.previous_ids:
        prev = await fetch_by_ids(db, ctx.previous_ids, include_inactive=True)
        ctx.previous_categories = {p.category for p in prev.values()}
    return ctx


async def load_preferences(db: AsyncSession, user_id: uuid.UUID | None) -> Preferences | None:
    if user_id is None:
        return None
    row = (await db.execute(text("""
        SELECT favorite_categories, disliked_categories, favorite_moods
        FROM user_preferences WHERE user_id = :u
    """), {"u": user_id})).first()
    saved = (await db.execute(text("""
        SELECT c.key, count(*) FROM saved_pois s JOIN pois p ON p.id = s.poi_id
        JOIN poi_categories c ON c.id = p.primary_category WHERE s.user_id = :u GROUP BY 1
    """), {"u": user_id})).all()
    if row is None and not saved:
        return None
    return Preferences(
        favorite_categories=set(row.favorite_categories or []) if row else set(),
        disliked_categories=set(row.disliked_categories or []) if row else set(),
        favorite_moods=set(row.favorite_moods or []) if row else set(),
        saved_categories={k: n for k, n in saved},
    )


async def semantic_scores(db: AsyncSession, poi_ids: list[int],
                          vector: list[float] | None = None,
                          reference_poi: int | None = None) -> dict[int, float]:
    """Cosine similarity from pgvector, for a query vector or a reference POI.
    Empty when embeddings are unavailable - callers treat that as neutral."""
    if not poi_ids or (vector is None and reference_poi is None):
        return {}
    if reference_poi is not None:
        rows = (await db.execute(text("""
            SELECT e.poi_id, 1 - (e.embedding <=> r.embedding) AS sim
            FROM poi_embeddings e, poi_embeddings r
            WHERE r.poi_id = :ref AND e.poi_id = ANY(CAST(:ids AS int[]))
        """), {"ref": reference_poi, "ids": poi_ids})).all()
    else:
        literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
        rows = (await db.execute(text("""
            SELECT poi_id, 1 - (embedding <=> CAST(:v AS vector)) AS sim FROM poi_embeddings
            WHERE poi_id = ANY(CAST(:ids AS int[]))
        """), {"v": literal, "ids": poi_ids})).all()
    return {r.poi_id: max(0.0, min(1.0, float(r.sim))) for r in rows}


async def recommend(db: AsyncSession, req: RecommendationRequest) -> RecommendationResult:
    scope = infer_scope(req)
    geo = geo_config()
    radius = req.anchor.radius_km if req.anchor else None
    widened = False
    q = build_query(req, scope, radius)
    candidates = await fetch_candidates(db, q)
    if scope == "local" and req.anchor is not None and len(candidates) < max(3, req.limit):
        wider = max(radius or 0, geo.adaptive["near_place_max"])
        if wider > (radius or 0):
            q = build_query(req, scope, wider)
            candidates = await fetch_candidates(db, q)
            widened = True
    if req.at is not None:
        await attach_hours(db, candidates, req.at.weekday())
    if req.similar_to is not None and req.semantic is None:
        req.semantic = await semantic_scores(db, [c.id for c in candidates],
                                             reference_poi=req.similar_to.id)
    filtered: Counter = Counter()
    scored: list[Scored] = []
    for poi in candidates:
        reason = hard_filter(poi, req)
        if reason:
            filtered[reason] += 1
            continue
        scored.append(score_poi(poi, req))
    items = select_diverse(scored, req.limit, mode=req.mode, seed=req.seed,
                           requested=set(req.categories) or None)
    result = RecommendationResult(
        items=items, scope=scope,
        anchor=({"name": req.anchor.name, "lat": req.anchor.lat, "lon": req.anchor.lon,
                 "radius_km": q.radius_km} if req.anchor else None),
        candidate_count=len(candidates), filtered=dict(filtered),
        config_version=config()["version"], widened=widened,
    )
    if req.novelty.previous_ids:
        result.overlap_with_previous = round(
            jaccard({s.poi.id for s in items}, req.novelty.previous_ids), 3)
    if not items:
        result.notes.append("no_candidates")
    return result


async def reference_poi(db: AsyncSession, poi_id: int) -> POIRecord | None:
    return (await fetch_by_ids(db, [poi_id])).get(poi_id)


def make_anchor(name: str, lat: float, lon: float, radius_km: float | None = None) -> Anchor:
    return Anchor(name=name, lat=lat, lon=lon,
                  radius_km=radius_km or geo_config().adaptive["near_place"])
