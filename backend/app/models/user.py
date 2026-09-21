import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from app.db.base_class import Base


class User(Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    display_name = Column(String(80))
    is_active = Column(Boolean(), default=True)
    # Never settable through the public API (registration schema has no such
    # field). Kept for operators.
    is_superuser = Column(Boolean(), default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    """Opaque refresh tokens, stored only as SHA-256 hashes.

    Rotation: every refresh revokes the presented token and issues a new one
    in the same family. Presenting an already-revoked token revokes the whole
    family - the standard response to a stolen refresh token being replayed.
    """
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    family_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserPreferences(Base):
    """Explicit preferences only. Implicit signals live in poi_interactions
    and are never written here, so one click cannot redefine a user."""
    __tablename__ = "user_preferences"
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"),
                     primary_key=True)
    favorite_categories = Column(ARRAY(Text), nullable=False, default=list)
    disliked_categories = Column(ARRAY(Text), nullable=False, default=list)
    favorite_moods = Column(ARRAY(Text), nullable=False, default=list)
    preferred_pace = Column(String(10))
    typical_budget_inr = Column(Integer)
    indoor_outdoor_preference = Column(String(10))
    dietary_preferences = Column(ARRAY(Text), nullable=False, default=list)
    party_preferences = Column(ARRAY(Text), nullable=False, default=list)
    favorite_areas = Column(ARRAY(Text), nullable=False, default=list)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("preferred_pace IS NULL OR preferred_pace IN ('quick','balanced','relaxed')",
                        name="ck_pref_pace"),
        CheckConstraint("typical_budget_inr IS NULL OR typical_budget_inr >= 0",
                        name="ck_pref_budget"),
        CheckConstraint("indoor_outdoor_preference IS NULL OR "
                        "indoor_outdoor_preference IN ('indoor','outdoor','any')",
                        name="ck_pref_io"),
    )
