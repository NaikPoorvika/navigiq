import uuid

from sqlalchemy import Boolean, Column, Float, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from app.db.base_class import Base


class User(Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean(), default=True)
    is_superuser = Column(Boolean(), default=False)

    # Profile - what the planner actually uses. Nothing else is collected.
    display_name = Column(String(80))
    home_name = Column(String(200))
    home_lat = Column(Float)
    home_lon = Column(Float)
    interests = Column(ARRAY(String(40)), nullable=False, server_default="{}")
    vegetarian = Column(Boolean(), nullable=False, server_default="false")
