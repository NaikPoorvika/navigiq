"""NQ-025 - Itinerary persistence.

Itineraries are IMMUTABLE once written. Every change - a modification, a
reroute, a what-if - creates a new version rather than mutating a row. That
makes undo, comparison and reroute history free, and means a stored plan can
always be replayed exactly as it was produced.

plan_snapshots exists for that replay: without the TripSpec, the candidate
set and the optimizer parameters, "why did it pick that cafe last Tuesday"
is unanswerable.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from geoalchemy2 import Geography

from app.db.base_class import Base


class TripSpecRecord(Base):
    __tablename__ = "tripspecs"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"))
    payload = Column(JSONB, nullable=False)
    version = Column(String(10), nullable=False)
    source = Column(String(20), nullable=False)          # form | llm | modification
    parent_id = Column(Integer, ForeignKey("tripspecs.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_tripspecs_payload", "payload",
                            postgresql_using="gin",
                            postgresql_ops={"payload": "jsonb_path_ops"}),)


class Itinerary(Base):
    __tablename__ = "itineraries"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"))
    tripspec_id = Column(Integer, ForeignKey("tripspecs.id"), nullable=False)
    current_version_id = Column(Integer)                 # FK added post-create
    status = Column(String(20), nullable=False, default="draft")
    mode = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','completed','abandoned')",
            name="ck_itinerary_status"),
    )


class ItineraryVersion(Base):
    __tablename__ = "itinerary_versions"
    id = Column(Integer, primary_key=True)
    itinerary_id = Column(Integer, ForeignKey("itineraries.id", ondelete="CASCADE"),
                          nullable=False)
    version_no = Column(SmallInteger, nullable=False)
    reason = Column(String(30), nullable=False)          # initial | modification | reroute
    total_cost_inr = Column(Integer, nullable=False, default=0)
    total_duration_min = Column(Integer, nullable=False, default=0)
    total_walk_m = Column(Integer, nullable=False, default=0)
    # The raw CP-SAT objective, not a 0-1 quality measure. Scales with the
    # MUST weight (100,000), so it needs integer range, and it is only
    # comparable between plans built from the same candidate set.
    objective_value = Column(Integer)
    # The validator's verdict is stored, not just its outcome. An itinerary
    # nobody can audit is an itinerary nobody should trust.
    validator_report = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("itinerary_id", "version_no", name="uq_version_no"),
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
    mode_from_prev = Column(String(20))
    travel_seconds_from_prev = Column(Integer, default=0)
    travel_distance_m_from_prev = Column(Integer, default=0)
    walk_m_from_prev = Column(Integer, default=0)
    leg_cost_inr = Column(Integer, default=0)
    notes = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("version_id", "seq", name="uq_stop_seq"),
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