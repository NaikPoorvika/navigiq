"""NavigIQ API application.

Error contract: every error body is {"error": {"code", "message", "details"}}.
Stack traces are logged with the request id, never returned (section 79).
"""
from contextlib import asynccontextmanager

import structlog
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.config import settings
from app.core.logging import setup_logging
from app.db.base import Base  # noqa: F401  registers all models

setup_logging()
logger = structlog.get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.session import AsyncSessionLocal
    from app.services.observability import prune
    try:
        async with AsyncSessionLocal() as db:
            removed = await prune(db)
            logger.info("trace_prune", removed=removed)
    except Exception as exc:  # noqa: BLE001 - a cold database must not stop startup
        logger.warning("startup_prune_skipped", error=type(exc).__name__)
    warmup = None
    if settings.LLM_ENABLED and settings.APP_ENV != "test":
        import asyncio
        warmup = asyncio.create_task(_warm_models())
    yield
    if warmup is not None and not warmup.done():
        warmup.cancel()
    from app.llm.service import get_llm_service
    svc = get_llm_service()
    if svc.gateway is not None:
        await svc.gateway.aclose()


async def _warm_models() -> None:
    """Load the generation and embedding models into VRAM in the background.
    A cold qwen3:14b load can exceed the per-request timeout; paying it at
    startup keeps the first user request fast. Failure is harmless."""
    from app.llm.service import get_llm_service
    from app.llm.types import ChatMessage
    svc = get_llm_service()
    if svc.gateway is None:
        return
    try:
        await svc.gateway.embed(["warm up"])
        await svc.gateway.generate([ChatMessage("user", "Reply with OK.")], max_tokens=20)
        logger.info("llm_warm")
    except Exception as exc:  # noqa: BLE001
        logger.info("llm_warmup_skipped", error=type(exc).__name__)


app = FastAPI(
    title="NavigIQ API",
    description="Bengaluru exploration companion: discover, understand and plan.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if length is not None:
        try:
            too_big = int(length) > settings.MAX_REQUEST_BYTES
        except ValueError:
            too_big = True
        if too_big:
            return JSONResponse(status_code=413, content={"error": {
                "code": "PAYLOAD_TOO_LARGE", "message": "request body too large",
                "details": {"max_bytes": settings.MAX_REQUEST_BYTES}}})
    return await call_next(request)


app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id", "X-Request-ID"],
)


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "details": details,
        "request_id": correlation_id.get()}})


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        body = exc.detail
        body["error"]["request_id"] = correlation_id.get()
        return JSONResponse(status_code=exc.status_code, content=body,
                            headers=getattr(exc, "headers", None))
    code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT", 429: "RATE_LIMITED"}.get(exc.status_code, "HTTP_ERROR")
    return _error(exc.status_code, code, str(exc.detail))


@app.exception_handler(StarletteHTTPException)
async def starlette_error(request: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return _error(exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]) or "body",
                "message": e.get("msg", "invalid")} for e in exc.errors()[:10]]
    return _error(422, "VALIDATION_ERROR", "The request is invalid.", details)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("unhandled_error", path=request.url.path, error=type(exc).__name__)
    name = type(exc).__name__
    if any(k in name for k in ("OperationalError", "InterfaceError", "ConnectionRefused",
                               "CannotConnectNow", "TimeoutError")):
        return _error(503, "DATABASE_UNAVAILABLE", "NavigIQ's data is temporarily unavailable.")
    return _error(500, "INTERNAL", "Something went wrong on our side.")


app.include_router(api_router, prefix="/api/v1")
