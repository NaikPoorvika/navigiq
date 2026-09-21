from typing import List, Union
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Development-only signing key. Refused when APP_ENV=production so a
# deployment cannot silently run with a key that is public in git history.
_DEV_SECRET_KEY = "dev-only-insecure-key-change-me-0f3a9c2e7b1d4e8a"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True,
                                      extra="ignore")

    APP_ENV: str = "development"
    DEBUG: bool = True

    # Database. Defaults to the docker-compose Postgres published on the host
    # so pure modules and tests can build Settings without a .env file.
    DATABASE_URL: str = (
        "postgresql+asyncpg://navigiq_user:navigiq_password@localhost:5433/navigiq")
    DB_POOL_SIZE: int = Field(default=10, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0)

    # CORS
    CORS_ORIGINS: Union[str, List[str]] = []

    # Security
    SECRET_KEY: str = _DEV_SECRET_KEY
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30, gt=0)
    MAX_REQUEST_BYTES: int = Field(default=256_000, gt=0)

    # Redis is an optional cache. Every caller degrades when it is down.
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = True

    # --- Geography (NavigIQ discovery envelope) ------------------------------
    # The 90 km radius is the maximum exploration envelope, not a travel
    # estimate. Distances are geodesic from this configurable centre.
    BENGALURU_CENTER_LAT: float = Field(default=12.9716, ge=-90, le=90)
    BENGALURU_CENTER_LON: float = Field(default=77.5946, ge=-180, le=180)
    BENGALURU_DISCOVERY_RADIUS_KM: float = Field(default=90.0, gt=0, le=500)
    LOCAL_TIMEZONE: str = "Asia/Kolkata"

    # --- Planning ------------------------------------------------------------
    # Fixed gap between consecutive stops. It is NOT a travel time: actual
    # transportation is deferred (ADR-022) and never estimated.
    TRANSITION_BUFFER_MINUTES: int = Field(default=15, ge=0, le=120)
    TRANSPORTATION_PROVIDER: str = "null"

    # --- Weather ---------------------------------------------------------------
    WEATHER_ENABLED: bool = True

    # --- LLM gateway (NQ-028). Defaults are the values accepted in ADR-012. ----
    LLM_ENABLED: bool = True
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_GEN_MODEL: str = "qwen3:14b"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"
    OLLAMA_EMBED_DIM: int = Field(default=768, gt=0)
    OLLAMA_NUM_CTX: int = Field(default=8192, gt=0)
    OLLAMA_KEEP_ALIVE: str = "10m"
    OLLAMA_TIMEOUT_S: float = Field(default=60.0, gt=0)
    OLLAMA_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    # Ollama serialises generation on one GPU (ENVIRONMENT.md); queueing in
    # the app keeps waits visible instead of piling requests on the server.
    LLM_MAX_CONCURRENCY: int = Field(default=2, ge=1, le=16)
    LLM_QUEUE_TIMEOUT_S: float = Field(default=30.0, gt=0)
    LLM_BREAKER_THRESHOLD: int = Field(default=3, ge=1)
    LLM_BREAKER_RESET_S: float = Field(default=30.0, gt=0)
    LLM_CACHE_TTL_S: int = Field(default=3600, ge=0)

    # --- Observability retention ---------------------------------------------
    TRACE_RETENTION_DAYS: int = Field(default=14, ge=1)

    @field_validator("OLLAMA_HOST")
    @classmethod
    def _normalise_ollama_host(cls, value: str) -> str:
        """Turn OLLAMA_HOST into a URL the gateway can call.

        OLLAMA_HOST is also the Ollama *server's* own variable, where it is
        a bind address such as "0.0.0.0:11434" - no scheme, and an address
        a client cannot connect to. If a developer sets it for the server,
        the backend reads the same value, so it is normalised here rather
        than failing on the first request.
        """
        raw = value.strip().rstrip("/")
        if not raw:
            raise ValueError("OLLAMA_HOST must not be empty")
        if "://" not in raw:
            raw = f"http://{raw}"
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"OLLAMA_HOST is not an http(s) address: {value!r}")
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(parts.hostname,
                                                       parts.hostname)
        if ":" in host:
            host = f"[{host}]"
        port = parts.port or (11434 if parts.scheme == "http" else 443)
        return f"{parts.scheme}://{host}:{port}{parts.path}"

    @model_validator(mode="after")
    def _no_dev_secret_in_production(self) -> "Settings":
        if self.APP_ENV == "production" and self.SECRET_KEY == _DEV_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set explicitly in production")
        return self

    @property
    def cors_origins(self) -> list[str]:
        if isinstance(self.CORS_ORIGINS, str):
            return [o.strip().strip('"') for o in
                    self.CORS_ORIGINS.strip("[]").split(",") if o.strip()]
        return list(self.CORS_ORIGINS)


settings = Settings()
