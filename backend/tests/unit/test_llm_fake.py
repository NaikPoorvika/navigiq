"""NQ-028 - FakeLLM.

The fake is the test double every model-consuming task will use, so it must
be deterministic, honour the same gateway contract as the real
implementation, and refuse the same things the real one refuses.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.llm import (  # noqa: E402
    ChatMessage,
    Embeddings,
    FakeLLM,
    Generation,
    LLMEmptyResponse,
    LLMGateway,
    LLMTruncated,
    LLMUnavailable,
)

MESSAGES = (
    ChatMessage("system", "You convert travel requests into structured data."),
    ChatMessage("user", "Plan a day in Indiranagar this Saturday."),
)


# --- contract -------------------------------------------------------------

def test_satisfies_the_gateway_protocol():
    assert isinstance(FakeLLM(), LLMGateway)


def test_chat_message_rejects_unknown_role():
    with pytest.raises(ValueError):
        ChatMessage("tool", "x")


def test_chat_message_rejects_non_string_content():
    with pytest.raises(TypeError):
        ChatMessage("user", 42)


# --- generation -----------------------------------------------------------

async def test_default_generation_returns_a_generation():
    result = await FakeLLM().generate(MESSAGES)
    assert isinstance(result, Generation)
    assert result.text.startswith("fake-response-")
    assert result.model == "fake-generation"
    assert result.attempts == 1
    assert result.completion_tokens == 1


async def test_default_generation_is_deterministic_across_instances():
    first = await FakeLLM().generate(MESSAGES, seed=7)
    second = await FakeLLM().generate(MESSAGES, seed=7)
    assert first.text == second.text


async def test_default_generation_depends_on_the_request():
    fake = FakeLLM()
    base = await fake.generate(MESSAGES)
    other_text = await fake.generate([ChatMessage("user", "Plan a day in Jayanagar.")])
    other_seed = await fake.generate(MESSAGES, seed=1)
    assert len({base.text, other_text.text, other_seed.text}) == 3


async def test_default_output_parses_as_json_when_a_schema_is_given():
    result = await FakeLLM().generate(MESSAGES, json_schema={"type": "object"})
    assert isinstance(json.loads(result.text), dict)


async def test_scripted_responses_are_returned_in_order():
    fake = FakeLLM(responses=["first answer", "second answer"])
    assert (await fake.generate(MESSAGES)).text == "first answer"
    assert (await fake.generate(MESSAGES)).text == "second answer"


async def test_scripted_error_is_raised_not_returned():
    failure = LLMUnavailable("ollama is down")
    fake = FakeLLM(responses=[failure])
    with pytest.raises(LLMUnavailable) as caught:
        await fake.generate(MESSAGES)
    assert caught.value is failure


async def test_exhausted_script_is_a_loud_error():
    fake = FakeLLM(responses=["only one"])
    await fake.generate(MESSAGES)
    with pytest.raises(RuntimeError, match="exhausted"):
        await fake.generate(MESSAGES)


async def test_responder_decides_from_the_messages():
    fake = FakeLLM(responder=lambda msgs: f"echo {msgs[-1].content}")
    result = await fake.generate(MESSAGES)
    assert result.text == "echo Plan a day in Indiranagar this Saturday."


def test_responses_and_responder_are_mutually_exclusive():
    with pytest.raises(ValueError):
        FakeLLM(responses=["x"], responder=lambda msgs: "y")


def test_script_accepts_only_text_or_llm_errors():
    with pytest.raises(TypeError):
        FakeLLM(responses=["ok", 123])


@pytest.mark.parametrize("scripted", ["", "   ", "\n\t "])
async def test_empty_output_is_never_a_success(scripted):
    with pytest.raises(LLMEmptyResponse):
        await FakeLLM(responses=[scripted]).generate(MESSAGES)


async def test_output_reaching_max_tokens_is_truncated():
    with pytest.raises(LLMTruncated):
        await FakeLLM(responses=["one two three"]).generate(MESSAGES, max_tokens=3)


async def test_output_under_max_tokens_succeeds():
    result = await FakeLLM(responses=["one two three"]).generate(MESSAGES, max_tokens=4)
    assert result.text == "one two three"


async def test_calls_are_recorded():
    fake = FakeLLM()
    await fake.generate(MESSAGES, max_tokens=50, temperature=0.2, seed=3,
                        json_schema={"type": "object"})
    [call] = fake.generate_calls
    assert call.messages == MESSAGES
    assert call.max_tokens == 50
    assert call.temperature == 0.2
    assert call.seed == 3
    assert call.json_schema == {"type": "object"}


@pytest.mark.parametrize("kwargs, error", [
    ({"messages": []}, ValueError),
    ({"messages": "plan a trip"}, TypeError),
    ({"messages": ["plan a trip"]}, TypeError),
    ({"max_tokens": 0}, ValueError),
    ({"temperature": 3.0}, ValueError),
    ({"seed": "7"}, TypeError),
    ({"json_schema": "object"}, TypeError),
])
async def test_generate_rejects_malformed_arguments(kwargs, error):
    call = {"messages": MESSAGES, **kwargs}
    messages = call.pop("messages")
    with pytest.raises(error):
        await FakeLLM().generate(messages, **call)


# --- embedding ------------------------------------------------------------

async def test_embedding_returns_one_768_vector_per_text():
    result = await FakeLLM().embed(["quiet cafe", "lakeside park", "temple"])
    assert isinstance(result, Embeddings)
    assert result.dimension == 768
    assert len(result.vectors) == 3
    assert all(len(vector) == 768 for vector in result.vectors)


async def test_embeddings_are_unit_vectors():
    result = await FakeLLM().embed(["quiet cafe"])
    norm = math.sqrt(sum(v * v for v in result.vectors[0]))
    assert math.isclose(norm, 1.0, rel_tol=1e-9)


async def test_embeddings_are_deterministic_and_text_specific():
    first = await FakeLLM().embed(["quiet cafe", "lakeside park"])
    second = await FakeLLM().embed(["quiet cafe", "lakeside park"])
    assert first.vectors == second.vectors
    assert first.vectors[0] != first.vectors[1]


async def test_embedding_dimension_is_configurable():
    fake = FakeLLM(embedding_dimension=16)
    result = await fake.embed(["x"])
    assert fake.embedding_dimension == 16
    assert len(result.vectors[0]) == 16


def test_embedding_dimension_must_be_positive():
    with pytest.raises(ValueError):
        FakeLLM(embedding_dimension=0)


@pytest.mark.parametrize("texts, error", [
    ("quiet cafe", TypeError),     # one vector per character is never intended
    ([], ValueError),
    (["ok", 5], TypeError),
])
async def test_embed_rejects_malformed_arguments(texts, error):
    with pytest.raises(error):
        await FakeLLM().embed(texts)


async def test_embed_calls_are_recorded():
    fake = FakeLLM()
    await fake.embed(["a", "b"])
    assert fake.embed_calls == [("a", "b")]


# --- lifecycle ------------------------------------------------------------

async def test_closed_gateway_refuses_calls():
    fake = FakeLLM()
    async with fake:
        await fake.generate(MESSAGES)
    with pytest.raises(RuntimeError, match="closed"):
        await fake.generate(MESSAGES)
    with pytest.raises(RuntimeError, match="closed"):
        await fake.embed(["x"])
