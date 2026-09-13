"""Sweep execution.

Three stages, cheapest first, so GPU time is not spent on a model that cannot
qualify:

  A. probe    - can the model hold this context entirely in VRAM, and does it
                leave room for the embedding model? One smoke generation.
  B. sweep    - the performance matrix over task x context x concurrency.
  C. quality  - the full case sets, schema-constrained and unconstrained.

Two measurement hygiene rules are enforced here rather than left to whoever
reads the numbers:

  Warm up before timing. The first request after a load pays the weight-load
  cost, and load_duration is recorded per run so a stray cold run is visible
  rather than silently averaged in.

  Never repeat the same prompt back to back. Ollama caches the prompt prefix,
  so re-sending a case makes the second run look faster for a reason that has
  nothing to do with the model. Cases are cycled instead.
"""
from __future__ import annotations

import itertools
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .client import OllamaClient
from .env import ModelIdentity, gpu_state, model_identity
from .metrics import CellSummary, RunRecord, record_from, summarise
from .tasks import TaskClass, cases_for, task_check_for
from .validity import judge

# Headroom the embedding model needs alongside the generation model.
# bge-m3 is the larger candidate at ~1.2 GB on disk; 2.5 GB leaves room for
# its weights plus a working KV cache and Ollama overhead.
EMBEDDING_HEADROOM_MIB = 2560

# Tiny prompt used to force a load at a given context size.
_SMOKE_MESSAGES = [{"role": "user", "content": "Reply with the single word: ok"}]

# The smoke generation asks for one word, but a reasoning model spends tokens
# thinking before it answers. A cap tight enough to truncate that would report
# a residency problem where there is none, so the probe is generous and the
# sweep's real caps are set per task class.
_SMOKE_NUM_PREDICT = 256


@dataclass
class ProbeResult:
    """Stage A. Residency at one context size."""
    model: str
    num_ctx: int
    loaded: bool
    fully_resident: bool | None
    vram_mib: float | None
    offloaded_fraction: float | None
    gpu_free_mib_after_load: int | None
    headroom_ok: bool | None
    smoke_outcome: str
    smoke_detail: str = ""
    served_context_length: int | None = None
    context_honoured: bool | None = None
    declared_max_context: int | None = None
    error: str | None = None

    @property
    def usable(self) -> bool:
        """Can this model be measured at this context at all?

        Residency and headroom are the questions stage A exists to answer. A
        smoke generation that was merely truncated does not disqualify a
        model - the cap was the probe's, not the task's - but one that never
        produced a response does.
        """
        return bool(
            self.fully_resident
            and self.headroom_ok
            and self.context_honoured is not False
            and self.smoke_outcome not in ("transport_error", "timeout")
        )

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "num_ctx": self.num_ctx,
            "loaded": self.loaded,
            "fully_resident": self.fully_resident,
            "vram_mib": (round(self.vram_mib, 1)
                         if self.vram_mib is not None else None),
            "offloaded_fraction": self.offloaded_fraction,
            "gpu_free_mib_after_load": self.gpu_free_mib_after_load,
            "headroom_ok": self.headroom_ok,
            "embedding_headroom_required_mib": EMBEDDING_HEADROOM_MIB,
            "smoke_outcome": self.smoke_outcome,
            "smoke_detail": self.smoke_detail,
            "served_context_length": self.served_context_length,
            "context_honoured": self.context_honoured,
            "declared_max_context": self.declared_max_context,
            "usable": self.usable,
            "error": self.error,
        }


@dataclass
class ModelProbe:
    identity: ModelIdentity
    probes: list[ProbeResult] = field(default_factory=list)

    def usable_contexts(self) -> list[int]:
        """Contexts where the model is fully on the GPU with room to spare."""
        return [p.num_ctx for p in self.probes if p.usable]

    def to_dict(self) -> dict:
        return {
            "identity": {
                k: v for k, v in vars(self.identity).items()
            },
            "probes": [p.to_dict() for p in self.probes],
            "usable_contexts": self.usable_contexts(),
        }


class Runner:
    def __init__(self, client: OllamaClient, *, seed: int = 20270927,
                 keep_alive: str = "10m", verbose: bool = True) -> None:
        self.client = client
        self.seed = seed
        self.keep_alive = keep_alive
        self.verbose = verbose

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    # --- stage A ----------------------------------------------------------

    def probe(self, model: str, contexts: list[int]) -> ModelProbe:
        """Load the model at each context and record where it actually sits."""
        identity = model_identity(self.client, model)
        result = ModelProbe(identity=identity)
        # The same reasoning setting the measurement stages will use, so the
        # probe answers the question the sweep is about to ask.
        think = self.think_setting(identity)

        for num_ctx in contexts:
            self._log(f"  probe {model} @ ctx={num_ctx}")
            # Evict first so the measurement is of this context, not of a
            # session still loaded at a different one.
            self.client.unload(model)
            time.sleep(1.0)

            gen = self.client.chat(
                model, _SMOKE_MESSAGES, num_ctx=num_ctx,
                num_predict=_SMOKE_NUM_PREDICT, seed=self.seed, think=think,
                keep_alive=self.keep_alive,
            )
            verdict = judge(gen, expects_json=False)

            loaded = self.client.loaded(model)
            gpu = gpu_state()
            free_after = gpu.memory_free_mib

            headroom_ok = (None if free_after is None
                           else free_after >= EMBEDDING_HEADROOM_MIB)

            # Ollama clamps num_ctx to the model's trained maximum without
            # reporting an error. Benchmarking "16384" on a model that was
            # actually served 8192 would be a false claim, so the served
            # length is read back from /api/ps and compared.
            served = loaded.context_length if loaded else None
            honoured = None if served is None else served >= num_ctx

            result.probes.append(ProbeResult(
                model=model,
                num_ctx=num_ctx,
                loaded=loaded is not None,
                fully_resident=loaded.fully_resident if loaded else None,
                vram_mib=loaded.vram_mib if loaded else None,
                offloaded_fraction=(round(loaded.offloaded_fraction, 4)
                                    if loaded else None),
                gpu_free_mib_after_load=free_after,
                headroom_ok=headroom_ok,
                smoke_outcome=verdict.outcome.value,
                smoke_detail=verdict.detail,
                served_context_length=served,
                context_honoured=honoured,
                declared_max_context=identity.max_context_length,
                error=gen.error,
            ))

        self.client.unload(model)
        return result

    # --- one cell ---------------------------------------------------------

    def run_cell(
        self,
        *,
        model: str,
        task: TaskClass,
        cases: list[dict],
        num_ctx: int,
        concurrency: int,
        runs: int,
        constrained: bool,
        think: bool | None,
    ) -> tuple[CellSummary, list[RunRecord]]:
        """Execute one (model, task, ctx, concurrency, schema) cell."""
        if not cases:
            raise ValueError(f"{task.id}: no cases")

        # The request count is rounded up to a whole multiple of the
        # concurrency level. Otherwise a cell with fewer requests than workers
        # never puts that many in flight at once - asking for concurrency 4
        # with 2 requests measures concurrency 2 and silently labels it 4.
        total = math.ceil(runs / concurrency) * concurrency

        # Cycle the cases so no two consecutive requests share a prompt.
        plan = [cases[i % len(cases)] for i in range(total)]

        def one(case: dict) -> RunRecord:
            gen = self.client.chat(
                model,
                task.messages_for(case, constrained=constrained),
                num_ctx=num_ctx,
                num_predict=task.num_predict,
                seed=self.seed,
                schema=task.schema if constrained else None,
                think=think,
                keep_alive=self.keep_alive,
            )
            verdict = judge(
                gen,
                expects_json=task.expects_json,
                schema_validator=task.schema_validator,
                task_check=task_check_for(task, case),
            )
            if verdict.is_success and task.score is not None:
                try:
                    score, detail = task.score(case, verdict)
                    verdict.accuracy, verdict.accuracy_detail = score, detail
                except Exception as exc:            # noqa: BLE001
                    verdict.accuracy_detail = {
                        "scorer_error": f"{type(exc).__name__}: {exc}"}
            return record_from(verdict, gen, model=model, task=task.id,
                               case_id=case.get("id", "?"),
                               concurrency=concurrency)

        started = time.perf_counter()
        if concurrency == 1:
            records = [one(c) for c in plan]
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                records = list(pool.map(one, plan))
        wall_s = time.perf_counter() - started

        summary = summarise(records, wall_clock_s=wall_s)
        self._log(
            f"    {task.id:<18} ctx={num_ctx:<6} conc={concurrency} "
            f"schema={'Y' if constrained else 'N'} "
            f"valid={summary.n_valid}/{summary.n_runs} "
            + (f"p95={summary.latency_ms['p95']:.0f}ms"
               if summary.latency_ms else "p95=n/a")
        )
        return summary, records

    def warmup(self, model: str, num_ctx: int, think: bool | None) -> None:
        """One unmeasured request so the weights are resident before timing."""
        self.client.chat(model, _SMOKE_MESSAGES, num_ctx=num_ctx,
                         num_predict=16, seed=self.seed, think=think,
                         keep_alive=self.keep_alive)

    @staticmethod
    def think_setting(identity: ModelIdentity) -> bool | None:
        """Disable chain-of-thought where the model supports it.

        Reasoning tokens are the single largest cause of a generation hitting
        the cap, and NavigIQ's LLM work is structured extraction under an
        interactive latency budget, not open-ended reasoning. Models without
        the capability get None (the parameter is not sent), and whichever
        applied is recorded on every run.
        """
        return False if identity.supports_thinking else None


def plan_cells(tasks: list[str], contexts: list[int], concurrencies: list[int]
               ) -> list[tuple[str, int, int]]:
    """The stage-B matrix, as an explicit list so it can be counted first."""
    return list(itertools.product(tasks, contexts, concurrencies))


def subset_cases(task_id: str, limit: int) -> list[dict]:
    """A stable slice of a case set for the performance matrix.

    The matrix measures speed and validity, not coverage - the full case sets
    run in stage C. Taking the first N in file order keeps the slice
    deterministic across runs and across models.
    """
    return cases_for(task_id)[:limit]
