from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from typing import List, Union
from urllib.parse import urlsplit

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str
    
    # CORS
    CORS_ORIGINS: Union[str, List[str]] = []
    
    # Security
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    
    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # LLM gateway (NQ-028). Defaults are the values accepted in ADR-012.
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_GEN_MODEL: str = "qwen3:14b"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"
    OLLAMA_EMBED_DIM: int = Field(default=768, gt=0)
    OLLAMA_NUM_CTX: int = Field(default=8192, gt=0)
    OLLAMA_KEEP_ALIVE: str = "10m"
    OLLAMA_TIMEOUT_S: float = Field(default=60.0, gt=0)
    OLLAMA_MAX_RETRIES: int = Field(default=2, ge=0, le=5)

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

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
