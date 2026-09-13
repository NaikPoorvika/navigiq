"""A thin, explicit Ollama HTTP client.

Deliberately thin: no retries that could hide a failure, no fallbacks that
could turn an error into a plausible-looking answer. Every field the grader
needs to judge a run - done_reason, eval_count, the raw text - is carried
through untouched.

Streaming is used for generation so time-to-first-token is a real measurement
rather than an estimate derived from total latency.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT_S = 300.0

NS_PER_S = 1_000_000_000
NS_PER_MS = 1_000_000


@dataclass
class GenResult:
    """One generation attempt.

    transport_ok False means a complete response never arrived - that is a
    failure regardless of any partial text that did.
    """
    transport_ok: bool
    error: str | None = None

    text: str = ""
    thinking: str = ""

    done: bool | None = None
    done_reason: str | None = None

    prompt_eval_count: int | None = None
    eval_count: int | None = None
    prompt_eval_duration_ns: int | None = None
    eval_duration_ns: int | None = None
    load_duration_ns: int | None = None
    total_duration_ns: int | None = None

    ttft_ms: float | None = None
    wall_ms: float = 0.0

    # Echoed request parameters, so a result row is self-describing.
    model: str = ""
    num_ctx: int | None = None
    num_predict: int | None = None
    schema_constrained: bool = False
    thinking_disabled: bool | None = None

    @property
    def gen_tps(self) -> float | None:
        """Generation tokens per second, from the server counters."""
        if self.eval_count and self.eval_duration_ns:
            return self.eval_count / (self.eval_duration_ns / NS_PER_S)
        return None

    @property
    def prompt_tps(self) -> float | None:
        """Prompt (prefill) tokens per second."""
        if self.prompt_eval_count and self.prompt_eval_duration_ns:
            return self.prompt_eval_count / (self.prompt_eval_duration_ns / NS_PER_S)
        return None

    @property
    def load_ms(self) -> float | None:
        if self.load_duration_ns is None:
            return None
        return self.load_duration_ns / NS_PER_MS

    def to_dict(self) -> dict:
        return {
            "transport_ok": self.transport_ok,
            "error": self.error,
            "done": self.done,
            "done_reason": self.done_reason,
            "prompt_eval_count": self.prompt_eval_count,
            "eval_count": self.eval_count,
            "ttft_ms": self.ttft_ms,
            "wall_ms": self.wall_ms,
            "gen_tps": self.gen_tps,
            "prompt_tps": self.prompt_tps,
            "load_ms": self.load_ms,
            "model": self.model,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "schema_constrained": self.schema_constrained,
            "thinking_disabled": self.thinking_disabled,
            "text_chars": len(self.text),
            "thinking_chars": len(self.thinking),
        }


@dataclass
class LoadedModel:
    """A row from /api/ps. fully_resident is the CPU-offload gate."""
    name: str
    size: int
    size_vram: int
    context_length: int | None = None
    digest: str | None = None

    @property
    def fully_resident(self) -> bool:
        """True only if every byte of the model sits in VRAM.

        Ollama silently splits a model across GPU and CPU when it does not
        fit. The split is not an error and the model still answers, just far
        slower. size_vram < size is the only reliable signal.
        """
        return self.size > 0 and self.size_vram >= self.size

    @property
    def vram_mib(self) -> float:
        return self.size_vram / (1024 * 1024)

    @property
    def offloaded_fraction(self) -> float:
        if self.size <= 0:
            return 0.0
        return max(0.0, (self.size - self.size_vram) / self.size)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "size_vram": self.size_vram,
            "context_length": self.context_length,
            "digest": self.digest,
            "fully_resident": self.fully_resident,
            "vram_mib": round(self.vram_mib, 1),
            "offloaded_fraction": round(self.offloaded_fraction, 4),
        }


class OllamaClient:
    def __init__(self, host: str = DEFAULT_HOST,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s

    # --- metadata ---------------------------------------------------------

    def version(self) -> str:
        r = requests.get(f"{self.host}/api/version", timeout=30)
        r.raise_for_status()
        return r.json().get("version")

    def show(self, model: str) -> dict:
        r = requests.post(f"{self.host}/api/show", json={"model": model},
                          timeout=60)
        r.raise_for_status()
        return r.json()

    def tags(self) -> list[dict]:
        r = requests.get(f"{self.host}/api/tags", timeout=60)
        r.raise_for_status()
        return r.json().get("models", [])

    def ps(self) -> list[LoadedModel]:
        """Currently loaded models and their VRAM residency."""
        r = requests.get(f"{self.host}/api/ps", timeout=30)
        r.raise_for_status()
        return [
            LoadedModel(
                name=m.get("name") or m.get("model", ""),
                size=int(m.get("size") or 0),
                size_vram=int(m.get("size_vram") or 0),
                context_length=m.get("context_length"),
                digest=m.get("digest"),
            )
            for m in r.json().get("models", [])
        ]

    def loaded(self, model: str) -> LoadedModel | None:
        """The loaded entry for a model, tolerating tag normalisation.

        /api/ps reports the resolved name, so a model requested as "bge-m3"
        comes back as "bge-m3:latest". An exact-match lookup would report it
        as not loaded and silently turn the residency gate into UNKNOWN.
        """
        running = self.ps()
        for m in running:
            if m.name == model:
                return m
        wanted = model if ":" in model else f"{model}:latest"
        for m in running:
            if m.name == wanted:
                return m
        return None

    def unload(self, model: str) -> None:
        """Evict a model so the next measurement starts from a known state.

        keep_alive 0 tells the server to drop it immediately. Errors are
        swallowed: failing to unload is not a benchmark result.
        """
        try:
            requests.post(
                f"{self.host}/api/chat",
                json={"model": model, "messages": [], "keep_alive": 0},
                timeout=120,
            )
        except Exception:                           # noqa: BLE001
            pass

    # --- generation -------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        num_ctx: int,
        num_predict: int,
        temperature: float = 0.0,
        seed: int = 20270927,
        schema: dict | None = None,
        think: bool | None = None,
        keep_alive: str | int | None = None,
    ) -> GenResult:
        """One streamed chat completion.

        Returns a GenResult in every case, including transport failure. This
        method never raises for a model-side problem: classifying the outcome
        belongs to validity.py, not to the client.
        """
        body: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "temperature": temperature,
                "seed": seed,
            },
        }
        if schema is not None:
            body["format"] = schema
        if think is not None:
            body["think"] = think
        if keep_alive is not None:
            body["keep_alive"] = keep_alive

        result = GenResult(
            transport_ok=False, model=model, num_ctx=num_ctx,
            num_predict=num_predict, schema_constrained=schema is not None,
            thinking_disabled=(think is False) if think is not None else None,
        )

        chunks: list[str] = []
        thinking: list[str] = []
        started = time.perf_counter()
        first_token_at: float | None = None

        try:
            with requests.post(f"{self.host}/api/chat", json=body,
                               stream=True, timeout=self.timeout_s) as resp:
                if resp.status_code != 200:
                    result.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    result.wall_ms = (time.perf_counter() - started) * 1000
                    return result

                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        result.error = f"unparseable stream line: {line[:200]!r}"
                        result.wall_ms = (time.perf_counter() - started) * 1000
                        return result

                    err = obj.get("error")
                    if err:
                        result.error = f"server error: {err}"
                        result.wall_ms = (time.perf_counter() - started) * 1000
                        return result

                    msg = obj.get("message") or {}
                    piece = msg.get("content") or ""
                    think_piece = msg.get("thinking") or ""

                    if (piece or think_piece) and first_token_at is None:
                        first_token_at = time.perf_counter()
                    if piece:
                        chunks.append(piece)
                    if think_piece:
                        thinking.append(think_piece)

                    if obj.get("done"):
                        result.done = True
                        result.done_reason = obj.get("done_reason")
                        result.prompt_eval_count = obj.get("prompt_eval_count")
                        result.eval_count = obj.get("eval_count")
                        result.prompt_eval_duration_ns = obj.get("prompt_eval_duration")
                        result.eval_duration_ns = obj.get("eval_duration")
                        result.load_duration_ns = obj.get("load_duration")
                        result.total_duration_ns = obj.get("total_duration")

        except requests.Timeout:
            result.error = f"timeout after {self.timeout_s}s"
            result.wall_ms = (time.perf_counter() - started) * 1000
            return result
        except Exception as exc:                    # noqa: BLE001
            result.error = f"{type(exc).__name__}: {exc}"
            result.wall_ms = (time.perf_counter() - started) * 1000
            return result

        result.wall_ms = (time.perf_counter() - started) * 1000
        if first_token_at is not None:
            result.ttft_ms = (first_token_at - started) * 1000
        result.text = "".join(chunks)
        result.thinking = "".join(thinking)

        # A stream that ended without a done frame is incomplete, whatever
        # text arrived before it stopped.
        if not result.done:
            result.error = result.error or "stream ended without a done frame"
            return result

        result.transport_ok = True
        return result

    # --- embeddings -------------------------------------------------------

    def embed(self, model: str, inputs: list[str], *,
              keep_alive: str | int | None = None) -> tuple[list[list[float]], dict]:
        """Returns (vectors, server timings). Raises on transport failure."""
        body: dict = {"model": model, "input": inputs}
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        started = time.perf_counter()
        r = requests.post(f"{self.host}/api/embed", json=body,
                          timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()
        timings = {
            "wall_ms": (time.perf_counter() - started) * 1000,
            "total_duration_ns": data.get("total_duration"),
            "load_duration_ns": data.get("load_duration"),
            "prompt_eval_count": data.get("prompt_eval_count"),
        }
        return data.get("embeddings", []), timings
