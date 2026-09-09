# Import all the models here so that Alembic can read them
from app.db.base_class import Base
from app.models.user import User
from app.models.poi import (
    POI,
    POICategory,
    POICategoryLink,
    POIInteraction,
    POIOpeningHours,
)
from app.models.itinerary import (
    Itinerary, ItineraryStop, ItineraryVersion, PlanSnapshot, TripSpecRecord,
)
__all__ = [
    "Base", "User", "POI", "POICategory",
    "POICategoryLink", "POIInteraction", "POIOpeningHours",
]
