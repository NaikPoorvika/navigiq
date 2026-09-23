"""NQ-028 - LLM gateway configuration.

The gateway's settings are the ADR-012 decisions. These tests pin the
defaults to those values, keep .env.example from drifting away from them,
and prove the factory actually uses what configuration says.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from app.config import Settings, settings# noqa: E402
from app.llm import OllamaGateway, build_llm_gateway  # noqa: E402

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

OLLAMA_KEYS = (
    "OLLAMA_HOST", "OLLAMA_GEN_MODEL", "OLLAMA_EMBED_MODEL", "OLLAMA_EMBED_DIM",
    "OLLAMA_NUM_CTX", "OLLAMA_KEEP_ALIVE", "OLLAMA_TIMEOUT_S", "OLLAMA_MAX_RETRIES",
)


@pytest.fixture
def clean_env(monkeypatch):
    for key in OLLAMA_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None,
                    DATABASE_URL="postgresql+asyncpg://u:p@localhost:5433/db",
                    **overrides)


def test_defaults_are_the_adr_012_values(clean_env):
    settings = make_settings()
    assert settings.OLLAMA_HOST == "http://localhost:11434"
    # The default in config.py, not whatever this machine's .env sets:
    # laptops run a smaller model locally (ADR-019).
    assert Settings.model_fields["OLLAMA_GEN_MODEL"].default == "qwen3:14b"
    assert Settings.model_fields["OLLAMA_EMBED_MODEL"].default == "nomic-embed-text"
    assert Settings.model_fields["OLLAMA_EMBED_DIM"].default == 768
    assert Settings.model_fields["OLLAMA_NUM_CTX"].default == 8192
    assert Settings.model_fields["OLLAMA_KEEP_ALIVE"].default == "10m"
    assert Settings.model_fields["OLLAMA_TIMEOUT_S"].default == 60.0
    assert settings.OLLAMA_MAX_RETRIES == 2


def test_environment_overrides_defaults(clean_env):
    clean_env.setenv("OLLAMA_GEN_MODEL", "qwen3:8b")
    clean_env.setenv("OLLAMA_EMBED_DIM", "1024")
    clean_env.setenv("OLLAMA_MAX_RETRIES", "0")
    settings = make_settings()
    assert settings.OLLAMA_GEN_MODEL == "qwen3:8b"
    assert settings.OLLAMA_EMBED_DIM == 1024
    assert settings.OLLAMA_MAX_RETRIES == 0


def test_env_example_agrees_with_defaults(clean_env):
    """.env.example documents the accepted values; it must not drift."""
    documented = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OLLAMA_") and "=" in line:
            key, value = line.split("=", 1)
            documented[key] = value
    assert set(documented) == set(OLLAMA_KEYS)
    from_example = make_settings(**documented)
    defaults = make_settings()
    for key in OLLAMA_KEYS:
        assert getattr(from_example, key) == getattr(defaults, key), key


@pytest.mark.parametrize("raw, expected", [
    ("http://localhost:11434", "http://localhost:11434"),
    ("http://localhost:11434/", "http://localhost:11434"),
    ("localhost:11434", "http://localhost:11434"),
    ("localhost", "http://localhost:11434"),
    # The Ollama server's own bind value - not connectable as written.
    ("0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("0.0.0.0", "http://127.0.0.1:11434"),
    ("http://host.docker.internal:11434", "http://host.docker.internal:11434"),
    ("https://llm.example", "https://llm.example:443"),
])
def test_host_is_normalised_to_a_callable_url(clean_env, raw, expected):
    assert make_settings(OLLAMA_HOST=raw).OLLAMA_HOST == expected


@pytest.mark.parametrize("overrides", [
    {"OLLAMA_EMBED_DIM": 0},
    {"OLLAMA_NUM_CTX": 0},
    {"OLLAMA_TIMEOUT_S": 0},
    {"OLLAMA_MAX_RETRIES": -1},
    {"OLLAMA_MAX_RETRIES": 6},
    {"OLLAMA_HOST": ""},
    {"OLLAMA_HOST": "ftp://localhost:11434"},
])
def test_invalid_values_are_rejected(clean_env, overrides):
    with pytest.raises(ValidationError):
        make_settings(**overrides)


async def test_factory_builds_gateway_from_settings(clean_env):
    settings = make_settings(OLLAMA_GEN_MODEL="custom-gen:1b",
                             OLLAMA_EMBED_MODEL="custom-embed",
                             OLLAMA_EMBED_DIM=1024)
    gateway = build_llm_gateway(settings)
    try:
        assert isinstance(gateway, OllamaGateway)
        assert gateway.generation_model == "custom-gen:1b"
        assert gateway.embedding_model == "custom-embed"
        assert gateway.embedding_dimension == 1024
    finally:
        await gateway.aclose()


async def test_factory_defaults_to_application_settings(clean_env):
    gateway = build_llm_gateway()
    try:
        # The settings, not a hardcoded name: a laptop may override the
        # model locally (ADR-019), and the default itself is checked above.
        assert gateway.generation_model == settings.OLLAMA_GEN_MODEL
        assert gateway.embedding_model == settings.OLLAMA_EMBED_MODEL
        assert gateway.embedding_dimension == settings.OLLAMA_EMBED_DIM
    finally:
        await gateway.aclose()
