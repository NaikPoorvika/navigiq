from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from asgi_correlation_id import CorrelationIdMiddleware
from app.config import settings
from app.api.v1.router import api_router
from app.core.logging import setup_logging

# Setup structlog
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    yield
    # Shutdown actions

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
