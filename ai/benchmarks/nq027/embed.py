"""Embedding model benchmark.

The dimension decided here is the most expensive number in NQ-027 to get
wrong. It becomes vector(N) in the NQ-034 migration, and changing it later
means re-embedding the whole corpus and rebuilding the HNSW index.

So it is not read from a model card or from documentation. It is the length
of a vector this machine actually returned, for this digest, at this
quantization, measured below and asserted to be consistent across every
input in the batch.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .client import OllamaClient
from .env import ModelIdentity, gpu_state, model_identity

# Short, medium and long inputs from the domain the corpus will hold, so the
# latency figures describe NavigIQ text rather than lorem ipsum.
PROBE_TEXTS: list[str] = [
    "cafe",
    "Lalbagh Botanical Garden",
    "quiet cafe near Indiranagar with outdoor seating",
    "What time does Bangalore Palace open on a Sunday?",
    "Cubbon Park is a 300-acre green space in central Bengaluru. It is "
    "closed to vehicle traffic on Sundays and public holidays, and the "
    "walking paths connect the State Central Library with the Bangalore "
    "Aquarium at the Kasturba Road end.",
    "Auto-rickshaw fares in Bengaluru start at a minimum fare covering the "
    "first two kilometres, with a per-kilometre rate after that. A night "
    "surcharge applies between 22:00 and 05:00. Drivers are required to use "
    "the meter, and prepaid counters operate at the railway stations and at "
    "Kempegowda International Airport, which is roughly 35 km north of the "
    "city centre and takes between one and two hours by road depending on "
    "the time of day and the route taken through Hebbal.",
]

# Pairs that must order correctly if the vectors carry any usable signal.
# Not a quality benchmark - a sanity check that the model is not returning
# noise, which a dimension read alone would not catch.
SIMILARITY_PROBES: list[dict] = [
    {
        "anchor": "quiet cafe with good coffee in Indiranagar",
        "closer": "a calm coffee shop in Indiranagar with outdoor seating",
        "further": "auto-rickshaw night surcharge between 22:00 and 05:00",
    },
    {
        "anchor": "temple architecture and history",
        "closer": "an ancient stone temple with carved pillars",
        "further": "rooftop bar with live music and cocktails",
    },
    {
        "anchor": "how long does it take to reach the airport",
        "closer": "travel time by road to Kempegowda International Airport",
        "further": "vegetarian thali restaurants near Malleshwaram",
    },
]


@dataclass
class EmbeddingResult:
    model: str
    identity: dict
    ok: bool
    dimension: int | None = None
    dimension_consistent: bool | None = None
    declared_embedding_length: int | None = None
    vram_mib: float | None = None
    fully_resident: bool | None = None
    single_latency_ms: dict | None = None
    batch_latency_ms: float | None = None
    batch_size: int | None = None
    texts_per_second: float | None = None
    normalised: bool | None = None
    similarity_checks: list[dict] = field(default_factory=list)
    similarity_passed: int = 0
    similarity_total: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "identity": self.identity,
            "ok": self.ok,
            "dimension": self.dimension,
            "dimension_consistent": self.dimension_consistent,
            "declared_embedding_length": self.declared_embedding_length,
            "vram_mib": (round(self.vram_mib, 1)
                         if self.vram_mib is not None else None),
            "fully_resident": self.fully_resident,
            "single_latency_ms": self.single_latency_ms,
            "batch_latency_ms": (round(self.batch_latency_ms, 2)
                                 if self.batch_latency_ms is not None else None),
            "batch_size": self.batch_size,
            "texts_per_second": (round(self.texts_per_second, 2)
                                 if self.texts_per_second is not None else None),
            "normalised": self.normalised,
            "similarity_checks": self.similarity_checks,
            "similarity_score": (f"{self.similarity_passed}/"
                                 f"{self.similarity_total}"),
            "error": self.error,
        }


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def benchmark(client: OllamaClient, model: str, *, runs: int = 5,
              keep_alive: str = "10m") -> EmbeddingResult:
    identity: ModelIdentity = model_identity(client, model)
    result = EmbeddingResult(
        model=model,
        identity=dict(vars(identity)),
        ok=False,
        declared_embedding_length=identity.embedding_length,
    )

    try:
        # Warm up so the load cost is not charged to the first measurement.
        client.embed(model, ["warmup"], keep_alive=keep_alive)

        # --- dimension, measured not assumed --------------------------
        vectors, _ = client.embed(model, PROBE_TEXTS, keep_alive=keep_alive)
        if not vectors:
            result.error = "no vectors returned"
            return result

        dims = {len(v) for v in vectors}
        result.dimension = len(vectors[0])
        result.dimension_consistent = len(dims) == 1
        if not result.dimension_consistent:
            result.error = f"inconsistent dimensions across inputs: {sorted(dims)}"
            return result

        # pgvector stores raw floats; whether they arrive unit-normalised
        # decides whether cosine and inner product agree downstream.
        norm = math.sqrt(sum(x * x for x in vectors[0]))
        result.normalised = abs(norm - 1.0) < 0.01

        # --- latency ---------------------------------------------------
        singles: list[float] = []
        for i in range(runs):
            text = PROBE_TEXTS[i % len(PROBE_TEXTS)]
            started = time.perf_counter()
            client.embed(model, [text], keep_alive=keep_alive)
            singles.append((time.perf_counter() - started) * 1000)
        singles.sort()
        result.single_latency_ms = {
            "n": len(singles),
            "mean": round(sum(singles) / len(singles), 2),
            "p50": round(singles[len(singles) // 2], 2),
            "min": round(singles[0], 2),
            "max": round(singles[-1], 2),
        }

        batch = PROBE_TEXTS * 8
        started = time.perf_counter()
        client.embed(model, batch, keep_alive=keep_alive)
        batch_ms = (time.perf_counter() - started) * 1000
        result.batch_latency_ms = batch_ms
        result.batch_size = len(batch)
        result.texts_per_second = len(batch) / (batch_ms / 1000)

        # --- signal sanity --------------------------------------------
        for probe in SIMILARITY_PROBES:
            vecs, _ = client.embed(
                model, [probe["anchor"], probe["closer"], probe["further"]],
                keep_alive=keep_alive)
            near = cosine(vecs[0], vecs[1])
            far = cosine(vecs[0], vecs[2])
            ok = near > far
            result.similarity_checks.append({
                "anchor": probe["anchor"],
                "cos_closer": round(near, 4),
                "cos_further": round(far, 4),
                "margin": round(near - far, 4),
                "ordered_correctly": ok,
            })
            result.similarity_passed += int(ok)
        result.similarity_total = len(SIMILARITY_PROBES)

        loaded = client.loaded(model)
        if loaded is None:
            # Tag/name mismatch (":latest") - match on prefix instead.
            for m in client.ps():
                if m.name.split(":")[0] == model.split(":")[0]:
                    loaded = m
                    break
        if loaded:
            result.vram_mib = loaded.vram_mib
            result.fully_resident = loaded.fully_resident

        result.ok = True
        return result

    except Exception as exc:                        # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        return result


def compare(results: list[EmbeddingResult]) -> dict:
    """Side-by-side, with the dimension consequence spelled out."""
    usable = [r for r in results if r.ok]
    return {
        "gpu_at_comparison": vars(gpu_state()),
        "candidates": [r.to_dict() for r in results],
        "dimensions_measured": {r.model: r.dimension for r in usable},
        "note": (
            "dimension is the length of a vector this machine returned, not a "
            "figure taken from documentation. It fixes vector(N) in NQ-034 and "
            "cannot be changed later without re-embedding the corpus."
        ),
    }
