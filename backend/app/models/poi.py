"""POI inventory models (schema v2, ADR-023/024/026).

The POI table carries the full exploration model: geography inside the
Bengaluru envelope, controlled categories and tags, honest cost and duration
ranges with their confidence, suitability flags and source attribution.

Free-form lists (tags, dietary, accessibility) are Postgres arrays with GIN
indexes rather than join tables: they are read on every recommendation and
written only by the idempotent ingestion pipeline, so the join cost buys
nothing (ADR-026).
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Computed, DateTime, ForeignKey, Index,
    Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector

from app.db.base_class import Base

REGION_BUCKETS = ("CITY_CORE", "CITY", "OUTSKIRTS", "NEARBY_ESCAPE")
INTERACTION_ACTIONS = (
    "view", "click", "save", "unsave", "dismiss", "add_to_plan",
    "remove_from_plan", "show_similar", "tell_me_more", "mark_visited", "shown",
)
EMBEDDING_DIM = 768


class POICategory(Base):
    __tablename__ = "poi_categories"
    id = Column(SmallInteger, primary_key=True)
    key = Column(String(40), unique=True, nullable=False)
    display_name = Column(String(80), nullable=False)
    group_key = Column(String(20), nullable=False, default="other")
    indoor_outdoor = Column(String(10), nullable=False, default="mixed")
    default_visit_minutes = Column(Integer, nullable=False)
    visit_min = Column(Integer, nullable=False, default=30)
    visit_max = Column(Integer, nullable=False, default=120)
    is_indoor = Column(Boolean, nullable=False, default=False)
    weather_sensitive = Column(Boolean, nullable=False, default=False)
    typical_cost_inr = Column(Integer, nullable=False, default=0)
    cost_min = Column(Integer, nullable=False, default=0)
    cost_max = Column(Integer, nullable=False, default=0)
    meal_category = Column(Boolean, nullable=False, default=False)
    is_theme = Column(Boolean, nullable=False, default=False)


class POI(Base):
    __tablename__ = "pois"
    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False)
    source_ref = Column(String(60), nullable=False)
    slug = Column(String(160), nullable=False, unique=True)
    name = Column(Text, nullable=False)
    name_normalized = Column(Text, nullable=False)
    short_description = Column(Text)
    description = Column(Text)
    description_source = Column(String(20))
    geom = Column(Geography("POINT", srid=4326), nullable=False)
    address = Column(Text)

    distance_from_center_km = Column(Numeric(7, 3), nullable=False)
    region_bucket = Column(String(20), nullable=False)
    district = Column(String(80))
    locality = Column(String(120))
    neighborhood = Column(String(120))

    primary_category = Column(SmallInteger, ForeignKey("poi_categories.id"), nullable=False)
    tags = Column(JSONB, nullable=False, default=dict)          # raw source tags
    experience_tags = Column(ARRAY(Text), nullable=False, default=list)
    mood_tags = Column(ARRAY(Text), nullable=False, default=list)
    food_tags = Column(ARRAY(Text), nullable=False, default=list)
    dietary_tags = Column(ARRAY(Text), nullable=False, default=list)
    activity_tags = Column(ARRAY(Text), nullable=False, default=list)
    accessibility_tags = Column(ARRAY(Text), nullable=False, default=list)
    indoor_outdoor = Column(String(10), nullable=False, default="unknown")
    weather_suitability = Column(String(20), nullable=False, default="all_weather")

    opening_hours_raw = Column(Text)
    opening_hours_confidence = Column(Numeric(3, 2), nullable=False, default=0)

    visit_duration_min = Column(Integer, nullable=False)
    visit_duration_typical = Column(Integer, nullable=False)
    visit_duration_max = Column(Integer, nullable=False)
    estimated_cost_min = Column(Integer, nullable=False, default=0)
    estimated_cost_typical = Column(Integer, nullable=False, default=0)
    estimated_cost_max = Column(Integer, nullable=False, default=0)
    cost_confidence = Column(String(20), nullable=False, default="category_default")

    prominence = Column(Numeric(4, 3), nullable=False, default=0)
    prominence_parts = Column(JSONB, nullable=False, default=dict)
    quality_score = Column(Numeric(4, 3), nullable=False, default=0)
    editorial_score = Column(Numeric(4, 3))
    data_confidence = Column(Numeric(3, 2), nullable=False, default=0)
    curated = Column(Boolean, nullable=False, default=False)
    recommendable = Column(Boolean, nullable=False, default=False)

    family_friendly = Column(Boolean)
    kids_friendly = Column(Boolean)
    senior_friendly = Column(Boolean)
    couple_friendly = Column(Boolean)
    solo_friendly = Column(Boolean)
    group_friendly = Column(Boolean)

    recommended_as_primary_destination = Column(Boolean, nullable=False, default=False)
    requires_large_time_block = Column(Boolean, nullable=False, default=False)
    short_escape = Column(Boolean, nullable=False, default=False)
    day_trip_suitable = Column(Boolean, nullable=False, default=False)

    is_chain = Column(Boolean, nullable=False, default=False)
    chain_key = Column(String(80))

    wikidata_id = Column(String(20))
    wikipedia_title = Column(Text)
    image_url = Column(Text)
    image_attribution = Column(JSONB)
    source_urls = Column(ARRAY(Text), nullable=False, default=list)
    source_names = Column(ARRAY(Text), nullable=False, default=list)
    source_license = Column(String(160), nullable=False, default="ODbL-1.0")
    source_updated_at = Column(DateTime(timezone=True))

    search_text = Column(Text, nullable=False, default="")
    search_tsv = Column(TSVECTOR, Computed("to_tsvector('simple', search_text)", persisted=True))

    active = Column(Boolean, nullable=False, default=True)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "source_ref", name="uq_pois_source_ref"),
        CheckConstraint("prominence >= 0 AND prominence <= 1", name="ck_pois_prominence"),
        CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="ck_pois_quality"),
        CheckConstraint("distance_from_center_km >= 0", name="ck_pois_distance"),
        CheckConstraint(f"region_bucket IN {REGION_BUCKETS}", name="ck_pois_region"),
        CheckConstraint("indoor_outdoor IN ('indoor','outdoor','mixed','unknown')",
                        name="ck_pois_indoor_outdoor"),
        CheckConstraint("0 < visit_duration_min AND visit_duration_min <= visit_duration_typical "
                        "AND visit_duration_typical <= visit_duration_max",
                        name="ck_pois_duration_order"),
        CheckConstraint("0 <= estimated_cost_min AND estimated_cost_min <= estimated_cost_typical "
                        "AND estimated_cost_typical <= estimated_cost_max",
                        name="ck_pois_cost_order"),
        Index("ix_pois_name_trgm", "name_normalized",
              postgresql_using="gin", postgresql_ops={"name_normalized": "gin_trgm_ops"}),
        Index("ix_pois_tags", "tags", postgresql_using="gin",
              postgresql_ops={"tags": "jsonb_path_ops"}),
        Index("ix_pois_category_active", "primary_category", "active"),
        Index("ix_pois_prominence", "prominence"),
        Index("ix_pois_experience_tags", "experience_tags", postgresql_using="gin"),
        Index("ix_pois_mood_tags", "mood_tags", postgresql_using="gin"),
        Index("ix_pois_region", "region_bucket", "active"),
        Index("ix_pois_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_pois_recommendable_quality", "recommendable", "quality_score"),
    )


class POIAlias(Base):
    __tablename__ = "poi_aliases"
    id = Column(Integer, primary_key=True)
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="CASCADE"), nullable=False)
    alias = Column(Text, nullable=False)
    alias_normalized = Column(Text, nullable=False)
    source = Column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("poi_id", "alias_normalized", name="uq_poi_alias"),
        Index("ix_poi_aliases_trgm", "alias_normalized", postgresql_using="gin",
              postgresql_ops={"alias_normalized": "gin_trgm_ops"}),
    )


class POICategoryLink(Base):
    __tablename__ = "poi_category_links"
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="CASCADE"), primary_key=True)
    category_id = Column(SmallInteger, ForeignKey("poi_categories.id"), primary_key=True)
    weight = Column(Numeric(3, 2), nullable=False, default=1.0)


class POIOpeningHours(Base):
    __tablename__ = "poi_opening_hours"
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="CASCADE"), primary_key=True)
    day_of_week = Column(SmallInteger, primary_key=True)
    open_min = Column(SmallInteger, primary_key=True)
    close_min = Column(SmallInteger, nullable=False)
    is_24h = Column(Boolean, nullable=False, default=False)
    closed_all_day = Column(Boolean, nullable=False, default=False)
    source = Column(String(30), nullable=False)
    confidence = Column(Numeric(3, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_hours_dow"),
        CheckConstraint("open_min BETWEEN 0 AND 1440", name="ck_hours_open"),
        CheckConstraint("close_min BETWEEN 0 AND 1440", name="ck_hours_close"),
        CheckConstraint("close_min > open_min OR closed_all_day", name="ck_hours_interval"),
    )


class POIInteraction(Base):
    __tablename__ = "poi_interactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"))
    session_id = Column(String(64))
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(20), nullable=False)
    context = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_poi_interactions_user", "user_id", "poi_id"),
        Index("ix_poi_interactions_user_time", "user_id", "created_at"),
        Index("ix_poi_interactions_session_time", "session_id", "created_at"),
        CheckConstraint("user_id IS NOT NULL OR session_id IS NOT NULL",
                        name="ck_interaction_owner"),
        CheckConstraint(f"action IN {INTERACTION_ACTIONS}", name="ck_interaction_action"),
    )


class SavedPOI(Base):
    __tablename__ = "saved_pois"
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"),
                     primary_key=True)
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="CASCADE"), primary_key=True)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class POIEmbedding(Base):
    __tablename__ = "poi_embeddings"
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="CASCADE"), primary_key=True)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    model = Column(String(80), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_poi_embeddings_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class Place(Base):
    """Gazetteer: named localities from OpenStreetMap, used to resolve
    "near Jayanagar" to real coordinates. Never authored by hand."""
    __tablename__ = "places"
    id = Column(Integer, primary_key=True)
    source_ref = Column(String(60), nullable=False, unique=True)
    name = Column(Text, nullable=False)
    name_normalized = Column(Text, nullable=False)
    aliases = Column(ARRAY(Text), nullable=False, default=list)
    place_type = Column(String(20), nullable=False)
    geom = Column(Geography("POINT", srid=4326), nullable=False)
    distance_from_center_km = Column(Numeric(7, 3), nullable=False)
    region_bucket = Column(String(20), nullable=False)
    district = Column(String(80))
    importance = Column(Numeric(4, 3), nullable=False, default=0)

    __table_args__ = (
        Index("ix_places_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}),
    )
