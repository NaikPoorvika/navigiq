"""Environment capture - the provenance block attached to every result file.

A benchmark number without the machine, driver, model digest and quantization
that produced it is an anecdote. Everything here is read from the live system
at run time; nothing is hard-coded or carried over from a previous run.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .client import OllamaClient

# nvidia-smi fields we record, in query order.
_GPU_FIELDS = [
    "name", "memory.total", "memory.used", "memory.free",
    "driver_version", "temperature.gpu", "utilization.gpu",
]


@dataclass
class GpuState:
    name: str | None = None
    memory_total_mib: int | None = None
    memory_used_mib: int | None = None
    memory_free_mib: int | None = None
    driver_version: str | None = None
    temperature_c: int | None = None
    utilization_pct: int | None = None
    error: str | None = None


def gpu_state() -> GpuState:
    """Current GPU state via nvidia-smi. Never raises."""
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(_GPU_FIELDS)}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip().splitlines()
    except Exception as exc:                       # noqa: BLE001 - diagnostic only
        return GpuState(error=f"{type(exc).__name__}: {exc}")

    if not out:
        return GpuState(error="nvidia-smi returned no rows")

    parts = [p.strip() for p in out[0].split(",")]
    if len(parts) != len(_GPU_FIELDS):
        return GpuState(error=f"unexpected nvidia-smi row: {out[0]!r}")

    def _int(v: str) -> int | None:
        try:
            return int(float(v))
        except ValueError:
            return None

    return GpuState(
        name=parts[0],
        memory_total_mib=_int(parts[1]),
        memory_used_mib=_int(parts[2]),
        memory_free_mib=_int(parts[3]),
        driver_version=parts[4],
        temperature_c=_int(parts[5]),
        utilization_pct=_int(parts[6]),
    )


def git_commit() -> str | None:
    """The commit the benchmark ran from, so a result can be replayed."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=15, check=True,
        ).stdout.strip()
    except Exception:                              # noqa: BLE001
        return None


def git_dirty() -> bool | None:
    """True if the tree had uncommitted changes - the result is then not
    exactly reproducible from the recorded commit, and says so."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True,
            timeout=15, check=True,
        ).stdout.strip()
        return bool(out)
    except Exception:                              # noqa: BLE001
        return None


@dataclass
class ModelIdentity:
    """What was actually loaded - digest pins it beyond the mutable tag."""
    model: str
    digest: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    family: str | None = None
    format: str | None = None
    max_context_length: int | None = None
    embedding_length: int | None = None
    capabilities: list[str] = field(default_factory=list)
    size_bytes: int | None = None
    error: str | None = None

    @property
    def supports_thinking(self) -> bool:
        return "thinking" in self.capabilities

    @property
    def supports_tools(self) -> bool:
        return "tools" in self.capabilities


def model_identity(client: OllamaClient, model: str) -> ModelIdentity:
    """Digest, quantization and capabilities straight from /api/show + /api/tags."""
    try:
        show = client.show(model)
    except Exception as exc:                       # noqa: BLE001
        return ModelIdentity(model=model, error=f"{type(exc).__name__}: {exc}")

    details = show.get("details") or {}
    info = show.get("model_info") or {}

    ctx = next((v for k, v in info.items() if k.endswith(".context_length")), None)
    emb = next((v for k, v in info.items() if k.endswith(".embedding_length")), None)

    digest = size = None
    try:
        for tag in client.tags():
            if tag.get("name") == model or tag.get("model") == model:
                digest, size = tag.get("digest"), tag.get("size")
                break
    except Exception:                              # noqa: BLE001
        pass

    return ModelIdentity(
        model=model,
        digest=digest,
        parameter_size=details.get("parameter_size"),
        quantization_level=details.get("quantization_level"),
        family=details.get("family"),
        format=details.get("format"),
        max_context_length=ctx,
        embedding_length=emb,
        capabilities=list(show.get("capabilities") or []),
        size_bytes=size,
    )


@dataclass
class RunEnvironment:
    """Captured once per benchmark invocation."""
    captured_at_utc: str
    ollama_version: str | None
    ollama_host: str
    ollama_env: dict
    python_version: str
    platform: str
    processor: str
    cpu_count: int | None
    gpu: dict
    git_commit: str | None
    git_dirty: bool | None

    def to_dict(self) -> dict:
        return asdict(self)


# OLLAMA_* settings that change measured behaviour and must be recorded.
_RELEVANT_OLLAMA_ENV = [
    "OLLAMA_HOST", "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS",
    "OLLAMA_MAX_QUEUE", "OLLAMA_KEEP_ALIVE", "OLLAMA_FLASH_ATTENTION",
    "OLLAMA_KV_CACHE_TYPE", "OLLAMA_GPU_OVERHEAD", "OLLAMA_MODELS",
    "OLLAMA_CONTEXT_LENGTH", "OLLAMA_NEW_ENGINE",
]


def capture(client: OllamaClient) -> RunEnvironment:
    """Snapshot the machine. Called once per benchmark run."""
    import os

    try:
        version = client.version()
    except Exception as exc:                       # noqa: BLE001
        version = f"unavailable: {type(exc).__name__}"

    return RunEnvironment(
        captured_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ollama_version=version,
        ollama_host=client.host,
        ollama_env={k: os.environ[k] for k in _RELEVANT_OLLAMA_ENV if k in os.environ},
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        processor=platform.processor(),
        cpu_count=os.cpu_count(),
        gpu=asdict(gpu_state()),
        git_commit=git_commit(),
        git_dirty=git_dirty(),
    )


if __name__ == "__main__":                         # quick manual check
    c = OllamaClient()
    print(json.dumps(capture(c).to_dict(), indent=2))
