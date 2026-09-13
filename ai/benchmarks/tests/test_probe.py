"""Stage A semantics.

Two mistakes stage A can make, both caught here:

  - disqualifying a model for a truncation the probe itself caused, by
    capping a reasoning model at a handful of tokens;
  - reporting a context size the server silently clamped, which would put a
    number in the report that never happened.
"""
from __future__ import annotations

from nq027.env import ModelIdentity
from nq027.runner import ModelProbe, ProbeResult, Runner


def probe(**kwargs) -> ProbeResult:
    base = dict(
        model="m", num_ctx=8192, loaded=True, fully_resident=True,
        vram_mib=6000.0, offloaded_fraction=0.0,
        gpu_free_mib_after_load=9000, headroom_ok=True,
        smoke_outcome="valid", served_context_length=8192,
        context_honoured=True, declared_max_context=32768,
    )
    base.update(kwargs)
    return ProbeResult(**base)


def test_healthy_probe_is_usable():
    assert probe().usable


def test_cpu_offload_is_not_usable():
    assert not probe(fully_resident=False, offloaded_fraction=0.3).usable


def test_insufficient_headroom_is_not_usable():
    assert not probe(headroom_ok=False, gpu_free_mib_after_load=900).usable


def test_truncated_smoke_does_not_disqualify():
    """The probe's own cap caused it; the sweep sets real per-task caps."""
    assert probe(smoke_outcome="truncated").usable


def test_transport_failure_disqualifies():
    assert not probe(smoke_outcome="transport_error").usable
    assert not probe(smoke_outcome="timeout").usable


def test_clamped_context_is_not_usable():
    """Asking for 16384 and being served 8192 is not a 16384 measurement."""
    assert not probe(num_ctx=16384, served_context_length=8192,
                     context_honoured=False).usable


def test_unknown_served_context_does_not_block():
    """An older server that omits context_length should not fail every model."""
    assert probe(served_context_length=None, context_honoured=None).usable


def test_usable_contexts_filters_the_list():
    model_probe = ModelProbe(
        identity=ModelIdentity(model="m"),
        probes=[
            probe(num_ctx=4096),
            probe(num_ctx=8192),
            probe(num_ctx=16384, context_honoured=False,
                  served_context_length=8192),
        ],
    )
    assert model_probe.usable_contexts() == [4096, 8192]


def test_thinking_is_disabled_only_where_supported():
    thinker = ModelIdentity(model="qwen3:8b",
                            capabilities=["completion", "tools", "thinking"])
    plain = ModelIdentity(model="llama3:8b", capabilities=["completion"])
    assert Runner.think_setting(thinker) is False
    assert Runner.think_setting(plain) is None
