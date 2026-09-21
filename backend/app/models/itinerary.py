"""Itinerary persistence.

Itineraries are IMMUTABLE once written. Every change - a modification, a
restore, an applied what-if - creates a new version rather than mutating a
row, so undo, history and comparison are free and a stored plan can always
be replayed exactly as it was produced.

A what-if is a version with kind='variant'. It has no version_no, is never
the current version, and is either applied (copied into a new real version)
or rejected. The original plan is untouched until the user applies it.

Ownership: user_id for signed-in users, session_id (an opaque anonymous
token) otherwise. Anonymous exploration and planning never require an account.

Transport columns on itinerary_stops are retained for the future
TransportationProvider (ADR-022) and are always NULL in this version.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base_class import Base


class TripSpecRecord(Base):
    __tablename__ = "tripspecs"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"))
    payload = Column(JSONB, nullable=False)
    version = Column(String(10), nullable=False)
    source = Column(String(20), nullable=False)          # form | llm | modification | what_if
    parent_id = Column(Integer, ForeignKey("tripspecs.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_tripspecs_payload", "payload",
                            postgresql_using="gin",
                            postgresql_ops={"payload": "jsonb_path_ops"}),)


class Itinerary(Base):
    __tablename__ = "itineraries"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"))
    session_id = Column(String(64), index=True)
    title = Column(Text)
    tripspec_id = Column(Integer, ForeignKey("tripspecs.id"), nullable=False)
    # Circular with itinerary_versions.itinerary_id, so the FK is added
    # after both tables exist (use_alter).
    current_version_id = Column(Integer, ForeignKey(
        "itinerary_versions.id", ondelete="SET NULL", use_alter=True,
        name="fk_itinerary_current_version"))
    status = Column(String(20), nullable=False, default="draft")
    mode = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','saved','active','completed','abandoned')",
            name="ck_itinerary_status"),
        CheckConstraint("user_id IS NOT NULL OR session_id IS NOT NULL",
                        name="ck_itinerary_owner"),
    )


class ItineraryVersion(Base):
    __tablename__ = "itinerary_versions"
    id = Column(Integer, primary_key=True)
    itinerary_id = Column(Integer, ForeignKey("itineraries.id", ondelete="CASCADE"),
                          nullable=False)
    version_no = Column(SmallInteger)                    # NULL for variants
    kind = Column(String(10), nullable=False, default="version")
    variant_status = Column(String(10))
    parent_version_id = Column(Integer, ForeignKey("itinerary_versions.id"))
    reason = Column(String(30), nullable=False)          # initial | modification | restore | what_if | apply_variant
    change_operation = Column(JSONB)
    label = Column(Text)
    tripspec_snapshot = Column(JSONB)
    itinerary = Column(JSONB)               # rendered exactly as shown
    total_cost_inr = Column(Integer, nullable=False, default=0)
    total_duration_min = Column(Integer, nullable=False, default=0)
    total_walk_m = Column(Integer, nullable=False, default=0)
    # The raw CP-SAT objective, only comparable between plans built from the
    # same candidate set.
    objective_value = Column(Integer)
    # The validator's verdict is stored, not just its outcome. An itinerary
    # nobody can audit is an itinerary nobody should trust.
    validator_report = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("itinerary_id", "version_no", name="uq_version_no"),
        CheckConstraint("kind IN ('version','variant')", name="ck_version_kind"),
        CheckConstraint(
            "(kind = 'version' AND version_no IS NOT NULL AND variant_status IS NULL) OR "
            "(kind = 'variant' AND version_no IS NULL AND "
            " variant_status IN ('pending','applied','rejected'))",
            name="ck_version_variant_shape"),
    )


class ItineraryStop(Base):
    __tablename__ = "itinerary_stops"
    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("itinerary_versions.id",
                                            ondelete="CASCADE"), nullable=False)
    seq = Column(SmallInteger, nullable=False)
    poi_id = Column(Integer, ForeignKey("pois.id"), nullable=False)
    arrive_min = Column(SmallInteger, nullable=False)
    depart_min = Column(SmallInteger, nullable=False)
    visit_minutes = Column(SmallInteger, nullable=False)
    cost_inr = Column(Integer, nullable=False, default=0)
    transition_buffer_min = Column(SmallInteger, nullable=False, default=0)
    # Reserved for the future TransportationProvider. Always NULL today.
    mode_from_prev = Column(String(20))
    travel_seconds_from_prev = Column(Integer)
    travel_distance_m_from_prev = Column(Integer)
    walk_m_from_prev = Column(Integer)
    leg_cost_inr = Column(Integer)
    notes = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("version_id", "seq", name="uq_stop_seq"),
        CheckConstraint("depart_min >= arrive_min", name="ck_stop_times"),
    )


class PlanSnapshot(Base):
    """Everything needed to replay a plan exactly as it was produced."""
    __tablename__ = "plan_snapshots"
    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("itinerary_versions.id",
                                            ondelete="CASCADE"), nullable=False)
    tripspec = Column(JSONB, nullable=False)
    candidate_poi_ids = Column(JSONB, nullable=False)
    optimizer_params = Column(JSONB, nullable=False)
    optimizer_status = Column(String(20), nullable=False)
    solve_ms = Column(Integer)
    weather = Column(JSONB)
    feasibility_report = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
