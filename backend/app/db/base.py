# Import all the models here so that Alembic can read them
from app.db.base_class import Base
from app.models.user import RefreshToken, User, UserPreferences
from app.models.poi import (
    POI,
    Place,
    POIAlias,
    POICategory,
    POICategoryLink,
    POIEmbedding,
    POIInteraction,
    POIOpeningHours,
    SavedPOI,
)
from app.models.itinerary import (
    Itinerary, ItineraryStop, ItineraryVersion, PlanSnapshot, TripSpecRecord,
)
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.conversation import Conversation, Message
from app.models.observability import AgentRun, Feedback, LLMCall, ToolCall

__all__ = [
    "Base", "User", "RefreshToken", "UserPreferences",
    "POI", "Place", "POIAlias", "POICategory", "POICategoryLink", "POIEmbedding",
    "POIInteraction", "POIOpeningHours", "SavedPOI",
    "Itinerary", "ItineraryStop", "ItineraryVersion", "PlanSnapshot", "TripSpecRecord",
    "KnowledgeChunk", "KnowledgeDocument", "Conversation", "Message",
    "AgentRun", "Feedback", "LLMCall", "ToolCall",
]
