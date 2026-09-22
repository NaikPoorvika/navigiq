"""Assistant, knowledge, trip-spec, weather, preferences, saved and feedback
endpoints."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    api_error, assistant_limiter, client_key, current_user, get_db, optional_user, owner, role_of,
)
from app.assistant.response import AssistantResponse
from app.assistant.tools import PreferencesArgs
from app.llm.service import get_llm_service
from app.models.user import User
from app.nlu.timeparse import now_ist
from app.services import conversations, interactions
from app.services.planning.store import Owner

router = APIRouter()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)


def _gateway():
    llm = get_llm_service()
    return llm, (llm.gateway if llm.enabled else None)


@router.post("/assistant/chat", response_model=AssistantResponse)
async def chat(body: ChatRequest, request: Request, response: Response,
               db: AsyncSession = Depends(get_db), user: User | None = Depends(optional_user),
               who: Owner = Depends(owner)) -> AssistantResponse:
    assistant_limiter.check(client_key(request, user, who.session_id))
    if user is None and not who.session_id:
        raise api_error(status.HTTP_400_BAD_REQUEST, "SESSION_REQUIRED",
                        "send X-NavigIQ-Session or sign in")
    llm, gateway = _gateway()
    try:
        resp = await conversations.chat(db, message=body.message,
                                        conversation_id=body.conversation_id, owner=who,
                                        role=role_of(user), llm=llm, gateway=gateway)
    except conversations.ConversationNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "conversation not found")
    response.headers["X-Trace-Id"] = resp.trace_id
    return resp


@router.get("/assistant/conversations/{conversation_id}")
async def conversation(conversation_id: str, db: AsyncSession = Depends(get_db),
                       who: Owner = Depends(owner)) -> dict:
    try:
        return await conversations.history(db, conversation_id, who)
    except conversations.ConversationNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "conversation not found")


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=500)


@router.post("/knowledge/ask")
async def ask(body: AskRequest, db: AsyncSession = Depends(get_db)) -> dict:
    from app.knowledge.answer import answer_question
    llm, gateway = _gateway()
    ans = await answer_question(db, body.question, llm=llm, gateway=gateway)
    return ans.to_dict()


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1500)
    use_llm: bool = True


@router.post("/trip-spec/extract")
async def extract(body: ExtractRequest, db: AsyncSession = Depends(get_db)) -> dict:
    from app.assistant.extraction import extract_trip_spec
    from app.services.plans import resolve_areas
    llm, _ = _gateway()
    ex = await extract_trip_spec(body.text, now=now_ist(), llm=llm, use_llm=body.use_llm)
    spec, notes = await resolve_areas(db, ex.spec, ex.area_names)
    return {"trip_spec": spec.model_dump(mode="json"), "areas": ex.area_names,
            "must_include_names": ex.must_include_names, "has_time_info": ex.has_time_info,
            "notes": ex.notes + notes, "llm_used": ex.llm_used, "field_sources": ex.field_sources}


@router.post("/trip-spec/validate")
async def validate_spec(spec: dict) -> dict:
    from pydantic import ValidationError
    from app.schemas.tripspec import TripSpec
    from app.services.planning.validators.semantic import validate_semantics
    try:
        parsed = TripSpec.model_validate(spec)
    except ValidationError as exc:
        return {"valid": False, "schema_errors": [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in exc.errors()[:10]], "errors": [], "warnings": []}
    return {"schema_errors": [], **validate_semantics(parsed).to_dict()}


@router.get("/weather")
async def weather(on: date | None = None, area: Annotated[str | None, Query(max_length=80)] = None,
                  db: AsyncSession = Depends(get_db)) -> dict:
    from app.assistant.tools import ToolContext, WeatherArgs, h_weather
    from app.assistant.trace import Trace
    return await h_weather(ToolContext(db=db, owner=Owner(None, None), role=None, trace=Trace()),
                           WeatherArgs(on=on, area=area))


def time_of_day(minute: int) -> str:
    """Day parts used by the home screen; same boundaries as docs/nlu_conventions.md."""
    if 5 * 60 <= minute < 12 * 60:
        return "morning"
    if 12 * 60 <= minute < 16 * 60 + 30:
        return "afternoon"
    if 16 * 60 + 30 <= minute < 21 * 60:
        return "evening"
    return "night"


@router.get("/context")
async def context() -> dict:
    """The real context the home screen may use: the IST clock and, when the
    provider answers, the next few hours of weather. Never invented: weather
    comes back `available: false` rather than a guess."""
    from app.geo.regions import geo_config
    from app.nlu.timeparse import now_ist
    from app.services.weather.client import get_window
    now = now_ist()
    minute = now.hour * 60 + now.minute
    cfg = geo_config()
    w = await get_window(cfg.center_lat, cfg.center_lon, now.date(), now.hour,
                         min(23, now.hour + 3))
    return {
        "now": now.isoformat(timespec="minutes"), "date": now.date().isoformat(),
        "weekday": now.strftime("%A"), "is_weekend": now.weekday() >= 5,
        "time_of_day": time_of_day(minute), "city": "Bengaluru", "timezone": "Asia/Kolkata",
        "weather": w.to_dict(),
    }


me_extra = APIRouter()


@me_extra.get("/preferences")
async def get_prefs(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await interactions.get_preferences(db, Owner(user.id, None))


@me_extra.put("/preferences")
async def put_prefs(body: PreferencesArgs, user: User = Depends(current_user),
                    db: AsyncSession = Depends(get_db)) -> dict:
    patch = {k: (v if not isinstance(v, list) else [getattr(x, "value", x) for x in v])
             for k, v in body.model_dump(exclude_none=True).items()}
    try:
        return await interactions.update_preferences(db, Owner(user.id, None), patch)
    except interactions.InteractionError as exc:
        raise api_error(422, "INVALID_PREFERENCES", str(exc))


@me_extra.get("/saved")
async def saved(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await interactions.list_saved(db, Owner(user.id, None))}


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: str = Field(pattern="^(answer|poi|itinerary|recommendation)$")
    target_id: str = Field(min_length=1, max_length=80)
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(body: FeedbackRequest, db: AsyncSession = Depends(get_db),
                   who: Owner = Depends(owner)) -> None:
    await db.execute(text("""
        INSERT INTO feedback (user_id, session_id, target_type, target_id, rating, comment)
        VALUES (:u, :s, :t, :i, :r, :c)
    """), {"u": who.user_id, "s": who.session_id, "t": body.target_type, "i": body.target_id,
           "r": body.rating, "c": body.comment})
    await db.commit()
