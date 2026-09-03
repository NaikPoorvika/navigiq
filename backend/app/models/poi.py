from sqlalchemy import (
    Boolean, CheckConstraint, Column, ForeignKey, Index, Integer,
    Numeric, SmallInteger, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from geoalchemy2 import Geography

from app.db.base_class import Base


class POICategory(Base):
    __tablename__ = "poi_categories"
    id = Column(SmallInteger, primary_key=True)
    key = Column(String(40), unique=True, nullable=False)
    display_name = Column(String(80), nullable=False)
    default_visit_minutes = Column(Integer, nullable=False)
    is_indoor = Column(Boolean, nullable=False, default=False)
    weather_sensitive = Column(Boolean, nullable=False, default=False)
    typical_cost_inr = Column(Integer, nullable=False, default=0)
    meal_category = Column(Boolean, nullable=False, default=False)


class POI(Base):
    __tablename__ = "pois"
    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False)
    source_ref = Column(String(60), nullable=False)
    name = Column(Text, nullable=False)
    name_normalized = Column(Text, nullable=False)
    description = Column(Text)
    geom = Column(Geography("POINT", srid=4326), nullable=False)
    address = Column(Text)
    area = Column(String(80))
    primary_category = Column(SmallInteger, ForeignKey("poi_categories.id"), nullable=False)
    prominence = Column(Numeric(4, 3), nullable=False, default=0)
    prominence_parts = Column(JSONB, nullable=False, default=dict)
    visit_minutes = Column(Integer)
    cost_estimate_inr = Column(Integer)
    cost_basis = Column(String(20))
    indoor = Column(Boolean)
    weather_flags = Column(JSONB, nullable=False, default=dict)
    tags = Column(JSONB, nullable=False, default=dict)
    wikidata_id = Column(String(20))
    image_url = Column(Text)
    curated = Column(Boolean, nullable=False, default=False)
    editorial_score = Column(Numeric(4, 3))
    quality_score = Column(Numeric(4, 3), nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    content_hash = Column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "source_ref", name="uq_pois_source_ref"),
        CheckConstraint("prominence >= 0 AND prominence <= 1", name="ck_pois_prominence"),
        # GIST index on geom is created automatically by geoalchemy2
        Index("ix_pois_name_trgm", "name_normalized",
              postgresql_using="gin", postgresql_ops={"name_normalized": "gin_trgm_ops"}),
        Index("ix_pois_tags", "tags", postgresql_using="gin",
              postgresql_ops={"tags": "jsonb_path_ops"}),
        Index("ix_pois_category_active", "primary_category", "active"),
        Index("ix_pois_prominence", "prominence"),
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
    )


class POIInteraction(Base):
    __tablename__ = "poi_interactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(20), nullable=False)
    context = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_poi_interactions_user", "user_id", "poi_id"),)
