"""POI interactions, saved places and explicit preferences (sections 36-37).

Interactions are implicit signals used for novelty (shown, dismissed,
visited). They are never written into preferences: only an explicit action
("save", the preferences form) changes what NavigIQ believes the user likes,
so one isolated click cannot redefine a user.
"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.taxonomy import is_valid_category, is_valid_mood
from app.models.poi import INTERACTION_ACTIONS
from app.services.planning.store import Owner
from app.services.poi.repository import fetch_by_ids

MAX_SHOWN_RECORDED = 12


class InteractionError(ValueError):
    code = "INVALID_INTERACTION"


async def poi_exists(db: AsyncSession, poi_id: int) -> bool:
    return bool((await db.execute(text("SELECT 1 FROM pois WHERE id=:i AND active"),
                                  {"i": poi_id})).first())


async def record(db: AsyncSession, owner: Owner, poi_id: int, action: str,
                 context: dict | None = None, *, commit: bool = True) -> None:
    if action not in INTERACTION_ACTIONS:
        raise InteractionError(f"unknown action {action!r}")
    if owner.user_id is None and not owner.session_id:
        return                      # nothing to attribute it to; silently not recorded
    await db.execute(text("""
        INSERT INTO poi_interactions (user_id, session_id, poi_id, action, context)
        VALUES (:u, :s, :p, :a, CAST(:c AS jsonb))
    """), {"u": owner.user_id, "s": None if owner.user_id else owner.session_id, "p": poi_id,
           "a": action, "c": json.dumps(context or {})})
    if commit:
        await db.commit()


async def record_shown(db: AsyncSession, owner: Owner, poi_ids: list[int], surface: str) -> None:
    ids = poi_ids[:MAX_SHOWN_RECORDED]
    if not ids or (owner.user_id is None and not owner.session_id):
        return
    await db.execute(text("""
        INSERT INTO poi_interactions (user_id, session_id, poi_id, action, context)
        SELECT :u, :s, p.id, 'shown', CAST(:c AS jsonb) FROM pois p
        WHERE p.id = ANY(CAST(:ids AS int[]))
    """), {"u": owner.user_id, "s": None if owner.user_id else owner.session_id, "ids": ids,
           "c": json.dumps({"surface": surface})})
    await db.commit()


async def save_poi(db: AsyncSession, owner: Owner, poi_id: int, note: str | None = None) -> dict:
    if owner.user_id is None:
        raise PermissionError("sign in to save places")
    if not await poi_exists(db, poi_id):
        raise LookupError("place not found")
    await db.execute(text("""
        INSERT INTO saved_pois (user_id, poi_id, note) VALUES (:u, :p, :n)
        ON CONFLICT (user_id, poi_id) DO UPDATE SET note = COALESCE(EXCLUDED.note, saved_pois.note)
    """), {"u": owner.user_id, "p": poi_id, "n": note})
    await record(db, owner, poi_id, "save", commit=False)
    await db.commit()
    return {"poi_id": poi_id, "saved": True}


async def unsave_poi(db: AsyncSession, owner: Owner, poi_id: int) -> dict:
    if owner.user_id is None:
        raise PermissionError("sign in to manage saved places")
    await db.execute(text("DELETE FROM saved_pois WHERE user_id=:u AND poi_id=:p"),
                     {"u": owner.user_id, "p": poi_id})
    await record(db, owner, poi_id, "unsave", commit=False)
    await db.commit()
    return {"poi_id": poi_id, "saved": False}


async def list_saved(db: AsyncSession, owner: Owner) -> list[dict]:
    if owner.user_id is None:
        return []
    rows = (await db.execute(text("""
        SELECT poi_id, note, created_at FROM saved_pois WHERE user_id=:u ORDER BY created_at DESC
    """), {"u": owner.user_id})).all()
    recs = await fetch_by_ids(db, [r.poi_id for r in rows])
    return [{**recs[r.poi_id].card(), "note": r.note, "saved_at": r.created_at.isoformat()}
            for r in rows if r.poi_id in recs]


async def saved_ids(db: AsyncSession, owner: Owner) -> set[int]:
    if owner.user_id is None:
        return set()
    return set((await db.execute(text("SELECT poi_id FROM saved_pois WHERE user_id=:u"),
                                 {"u": owner.user_id})).scalars().all())


async def dismiss_poi(db: AsyncSession, owner: Owner, poi_id: int) -> dict:
    if not await poi_exists(db, poi_id):
        raise LookupError("place not found")
    await record(db, owner, poi_id, "dismiss")
    return {"poi_id": poi_id, "dismissed": True}


PREF_ARRAYS = ("favorite_categories", "disliked_categories", "favorite_moods",
               "dietary_preferences", "party_preferences", "favorite_areas")
DIETARY = {"vegetarian", "pure_vegetarian", "vegan", "halal", "jain"}
PARTY = {"solo", "couple", "friends", "family", "family_with_kids", "parents", "colleagues"}


def validate_preferences(p: dict) -> dict:
    out: dict = {}
    for key in PREF_ARRAYS:
        if key not in p:
            continue
        values = [str(v)[:60] for v in (p[key] or [])][:20]
        if key in ("favorite_categories", "disliked_categories"):
            bad = [v for v in values if not is_valid_category(v)]
        elif key == "favorite_moods":
            bad = [v for v in values if not is_valid_mood(v)]
        elif key == "dietary_preferences":
            bad = [v for v in values if v not in DIETARY]
        elif key == "party_preferences":
            bad = [v for v in values if v not in PARTY]
        else:
            bad = []
        if bad:
            raise InteractionError(f"invalid {key}: {bad}")
        out[key] = list(dict.fromkeys(values))
    if "favorite_categories" in out and "disliked_categories" in out and \
            set(out["favorite_categories"]) & set(out["disliked_categories"]):
        raise InteractionError("a category cannot be both favourite and disliked")
    if "preferred_pace" in p:
        if p["preferred_pace"] not in (None, "quick", "balanced", "relaxed"):
            raise InteractionError("invalid preferred_pace")
        out["preferred_pace"] = p["preferred_pace"]
    if "typical_budget_inr" in p:
        v = p["typical_budget_inr"]
        if v is not None and (not isinstance(v, int) or not 0 <= v <= 200_000):
            raise InteractionError("invalid typical_budget_inr")
        out["typical_budget_inr"] = v
    if "indoor_outdoor_preference" in p:
        if p["indoor_outdoor_preference"] not in (None, "indoor", "outdoor", "any"):
            raise InteractionError("invalid indoor_outdoor_preference")
        out["indoor_outdoor_preference"] = p["indoor_outdoor_preference"]
    return out


async def get_preferences(db: AsyncSession, owner: Owner) -> dict:
    if owner.user_id is None:
        raise PermissionError("sign in to keep preferences")
    row = (await db.execute(text("SELECT * FROM user_preferences WHERE user_id=:u"),
                            {"u": owner.user_id})).mappings().first()
    base = {k: [] for k in PREF_ARRAYS} | {"preferred_pace": None, "typical_budget_inr": None,
                                            "indoor_outdoor_preference": None}
    if row:
        base.update({k: row[k] for k in base})
    return base


async def update_preferences(db: AsyncSession, owner: Owner, patch: dict) -> dict:
    if owner.user_id is None:
        raise PermissionError("sign in to keep preferences")
    clean = validate_preferences(patch)
    current = await get_preferences(db, owner)
    merged = {**current, **clean}
    if set(merged["favorite_categories"]) & set(merged["disliked_categories"]):
        raise InteractionError("a category cannot be both favourite and disliked")
    await db.execute(text("""
        INSERT INTO user_preferences (user_id, favorite_categories, disliked_categories,
            favorite_moods, preferred_pace, typical_budget_inr, indoor_outdoor_preference,
            dietary_preferences, party_preferences, favorite_areas, updated_at)
        VALUES (:u, :fc, :dc, :fm, :pace, :budget, :io, :diet, :party, :areas, now())
        ON CONFLICT (user_id) DO UPDATE SET favorite_categories=EXCLUDED.favorite_categories,
            disliked_categories=EXCLUDED.disliked_categories, favorite_moods=EXCLUDED.favorite_moods,
            preferred_pace=EXCLUDED.preferred_pace, typical_budget_inr=EXCLUDED.typical_budget_inr,
            indoor_outdoor_preference=EXCLUDED.indoor_outdoor_preference,
            dietary_preferences=EXCLUDED.dietary_preferences,
            party_preferences=EXCLUDED.party_preferences, favorite_areas=EXCLUDED.favorite_areas,
            updated_at=now()
    """), {"u": owner.user_id, "fc": merged["favorite_categories"],
           "dc": merged["disliked_categories"], "fm": merged["favorite_moods"],
           "pace": merged["preferred_pace"], "budget": merged["typical_budget_inr"],
           "io": merged["indoor_outdoor_preference"], "diet": merged["dietary_preferences"],
           "party": merged["party_preferences"], "areas": merged["favorite_areas"]})
    await db.commit()
    return merged
