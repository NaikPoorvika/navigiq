from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from asgi_correlation_id import CorrelationIdMiddleware
from app.config import settings
from app.db.base import Base  # noqa: F401  registers all models
from app.api.v1.router import api_router
from app.core.logging import setup_logging
from app.llm import build_llm_gateway

# Setup structlog
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions.
    #
    # One LLM gateway per process (NQ-028), reached by request handlers
    # through app.api.deps.get_llm_gateway. Constructing it does not talk to
    # Ollama, so the API still starts - and the deterministic /plan path
    # still works (ADR-002) - when no model server is running.
    app.state.llm_gateway = build_llm_gateway(settings)
    try:
        yield
    finally:
        # Shutdown actions
        await app.state.llm_gateway.aclose()

app = FastAPI(
    title="NavigIQ API",
    description="Backend API for the NavigIQ travel planning application",
    version="0.1.0",
    lifespan=lifespan,
)

# Add Request ID / Correlation ID tracking
app.add_middleware(CorrelationIdMiddleware)

# Parse CORS origins
if isinstance(settings.CORS_ORIGINS, str):
    origins = [origin.strip() for origin in settings.CORS_ORIGINS.strip("[]").split(",") if origin.strip()]
else:
    origins = settings.CORS_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

