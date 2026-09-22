"""NQ-028 - OllamaGateway against a mocked Ollama server.

No GPU and no running Ollama: every response, failure and timeout is
produced by an httpx MockTransport. The central property under test is that
no failure mode ever comes back as a successful-looking result.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import app.llm.ollama as ollama_module  # noqa: E402
from app.llm import (  # noqa: E402
    ChatMessage,
    Embeddings,
    Generation,
    LLMEmbeddingDimensionMismatch,
    LLMEmptyResponse,
    LLMGateway,
    LLMMalformedResponse,
    LLMRequestRejected,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
    OllamaGateway,
)

HOST = "http://ollama.test:11434"
MESSAGES = (ChatMessage("user", "Reply with the single word: ok"),)
VECTOR = [0.01] * 768


def chat_body(content="ok", **overrides):
    body = {
        "model": "qwen3:14b",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 23,
        "eval_count": 2,
    }
    body.update(overrides)
    return body


def ok(body):
    return httpx.Response(200, json=body)


class FakeOllama:
    """Plays back outcomes in order; the last one repeats.

    An outcome is an httpx.Response, or an exception instance to raise.
    """

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def body(self, index=0):
        import json
        return json.loads(self.requests[index].content)


class LogRecorder:
    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def info(self, event, **kw):
        self.events.append(("info", event, kw))

    def warning(self, event, **kw):
        self.events.append(("warning", event, kw))

    def named(self, name):
        return [kw for _, event, kw in self.events if event == name]


@pytest.fixture
def logs(monkeypatch):
    recorder = LogRecorder()
    monkeypatch.setattr(ollama_module, "logger", recorder)
    return recorder


@pytest_asyncio.fixture
async def make_gateway():
    clients: list[httpx.AsyncClient] = []

    def build(server: FakeOllama, **overrides):
        client = httpx.AsyncClient(transport=httpx.MockTransport(server))
        clients.append(client)
        sleeps: list[float] = []

        async def record_sleep(delay):
            sleeps.append(delay)

        kwargs = dict(
            host=HOST, generation_model="qwen3:14b",
            embedding_model="nomic-embed-text", embedding_dimension=768,
            num_ctx=8192, keep_alive="10m", timeout_s=30.0, max_retries=2,
            client=client, sleep=record_sleep,
        )
        kwargs.update(overrides)
        return OllamaGateway(**kwargs), sleeps

    yield build
    for client in clients:
        await client.aclose()


# --- contract -------------------------------------------------------------

async def test_satisfies_the_gateway_protocol(make_gateway):
    gateway, _ = make_gateway(FakeOllama(ok(chat_body())))
    assert isinstance(gateway, LLMGateway)


# --- successful generation ------------------------------------------------

async def test_successful_generation(make_gateway, logs):
    server = FakeOllama(ok(chat_body("ok")))
    gateway, sleeps = make_gateway(server)

    result = await gateway.generate(MESSAGES, max_tokens=64)

    assert isinstance(result, Generation)
    assert result.text == "ok"
    assert result.model == "qwen3:14b"
    assert result.prompt_tokens == 23
    assert result.completion_tokens == 2
    assert result.attempts == 1
    assert result.latency_ms >= 0
    assert sleeps == []
    assert logs.named("llm.request.completed")[0]["operation"] == "generate"


async def test_generation_request_carries_configured_values(make_gateway):
    server = FakeOllama(ok(chat_body()))
    gateway, _ = make_gateway(server)

    await gateway.generate(MESSAGES, max_tokens=64)

    request = server.requests[0]
    body = server.body()
    assert str(request.url) == f"{HOST}/api/chat"
    assert body["model"] == "qwen3:14b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["keep_alive"] == "10m"
    assert body["messages"] == [{"role": "user", "content": "Reply with the single word: ok"}]
    assert body["options"] == {"num_ctx": 8192, "num_predict": 64, "temperature": 0.0}
    assert "format" not in body


async def test_generation_forwards_seed_and_schema(make_gateway):
    server = FakeOllama(ok(chat_body('{"intent": "plan_trip"}')))
    gateway, _ = make_gateway(server)
    schema = {"type": "object", "properties": {"intent": {"type": "string"}}}

    result = await gateway.generate(MESSAGES, seed=11, json_schema=schema)

    assert server.body()["options"]["seed"] == 11
    assert server.body()["format"] == schema
    # Returned as text: parsing and validation belong to the consuming task.
    assert result.text == '{"intent": "plan_trip"}'


async def test_reasoning_and_surrounding_whitespace_are_removed(make_gateway):
    server = FakeOllama(ok(chat_body('<think>weighing options</think>\n  {"a": 1}  ')))
    gateway, _ = make_gateway(server)
    assert (await gateway.generate(MESSAGES)).text == '{"a": 1}'


async def test_missing_model_name_falls_back_to_configured(make_gateway):
    body = chat_body()
    del body["model"]
    gateway, _ = make_gateway(FakeOllama(ok(body)))
    assert (await gateway.generate(MESSAGES)).model == "qwen3:14b"


# --- successful embedding -------------------------------------------------

async def test_successful_embedding(make_gateway, logs):
    server = FakeOllama(ok({"model": "nomic-embed-text", "embeddings": [VECTOR, VECTOR]}))
    gateway, _ = make_gateway(server)

    result = await gateway.embed(["quiet cafe", "lakeside park"])

    assert isinstance(result, Embeddings)
    assert result.dimension == 768
    assert len(result.vectors) == 2
    assert all(len(v) == 768 and isinstance(v[0], float) for v in result.vectors)
    assert result.model == "nomic-embed-text"
    assert result.attempts == 1
    assert logs.named("llm.request.completed")[0]["operation"] == "embed"


async def test_embedding_request_disables_silent_truncation(make_gateway):
    server = FakeOllama(ok({"embeddings": [VECTOR]}))
    gateway, _ = make_gateway(server)

    await gateway.embed(["quiet cafe"])

    body = server.body()
    assert str(server.requests[0].url) == f"{HOST}/api/embed"
    assert body["model"] == "nomic-embed-text"
    assert body["input"] == ["quiet cafe"]
    assert body["truncate"] is False
    assert body["keep_alive"] == "10m"


# --- timeout --------------------------------------------------------------

async def test_read_timeout_raises_llm_timeout_without_retrying(make_gateway, logs):
    server = FakeOllama(httpx.ReadTimeout("no response"))
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMTimeout) as caught:
        await gateway.generate(MESSAGES)

    assert caught.value.attempts == 1
    assert caught.value.model == "qwen3:14b"
    assert len(server.requests) == 1
    assert sleeps == []
    assert logs.named("llm.request.failed")[0]["error_code"] == "LLM_TIMEOUT"


async def test_embedding_timeout_raises_llm_timeout(make_gateway):
    gateway, _ = make_gateway(FakeOllama(httpx.ReadTimeout("no response")))
    with pytest.raises(LLMTimeout):
        await gateway.embed(["quiet cafe"])


async def test_connect_timeout_is_treated_as_unavailable_and_retried(make_gateway):
    server = FakeOllama(httpx.ConnectTimeout("no route"))
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMUnavailable):
        await gateway.generate(MESSAGES)

    assert len(server.requests) == 3
    assert sleeps == [0.5, 1.0]


# --- connection failure and bounded retry ---------------------------------

async def test_connection_failure_retries_then_raises(make_gateway, logs):
    server = FakeOllama(httpx.ConnectError("connection refused"))
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMUnavailable) as caught:
        await gateway.generate(MESSAGES)

    assert caught.value.attempts == 3
    assert isinstance(caught.value.__cause__, httpx.ConnectError)
    assert len(server.requests) == 3
    assert sleeps == [0.5, 1.0]
    assert [e["attempt"] for e in logs.named("llm.request.retry")] == [1, 2]
    assert logs.named("llm.request.failed")[0]["attempts"] == 3


async def test_transient_failure_recovers_within_the_retry_budget(make_gateway):
    server = FakeOllama(httpx.ConnectError("refused"), ok(chat_body("ok")))
    gateway, sleeps = make_gateway(server)

    result = await gateway.generate(MESSAGES)

    assert result.text == "ok"
    assert result.attempts == 2
    assert sleeps == [0.5]


async def test_server_error_is_retried(make_gateway):
    server = FakeOllama(httpx.Response(503, json={"error": "server busy"}),
                        ok(chat_body("ok")))
    gateway, _ = make_gateway(server)
    assert (await gateway.generate(MESSAGES)).attempts == 2


async def test_persistent_server_error_exhausts_retries(make_gateway):
    server = FakeOllama(httpx.Response(500, json={"error": "model failed to load"}))
    gateway, _ = make_gateway(server)

    with pytest.raises(LLMUnavailable, match="model failed to load"):
        await gateway.embed(["quiet cafe"])
    assert len(server.requests) == 3


async def test_zero_retries_means_exactly_one_attempt(make_gateway):
    server = FakeOllama(httpx.ConnectError("refused"))
    gateway, sleeps = make_gateway(server, max_retries=0)

    with pytest.raises(LLMUnavailable) as caught:
        await gateway.generate(MESSAGES)

    assert caught.value.attempts == 1
    assert len(server.requests) == 1
    assert sleeps == []


# --- rejected requests ----------------------------------------------------

async def test_unknown_model_is_rejected_without_retrying(make_gateway):
    server = FakeOllama(httpx.Response(404, json={"error": "model 'qwen3:14b' not found"}))
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMRequestRejected, match="not found") as caught:
        await gateway.generate(MESSAGES)

    assert caught.value.status_code == 404
    assert len(server.requests) == 1
    assert sleeps == []


async def test_oversized_embedding_input_is_rejected(make_gateway):
    server = FakeOllama(httpx.Response(
        400, json={"error": "the input length exceeds the context length"}))
    gateway, _ = make_gateway(server)

    with pytest.raises(LLMRequestRejected, match="exceeds the context length"):
        await gateway.embed(["a very long document"])


# --- malformed responses --------------------------------------------------

def _without(key):
    body = chat_body()
    del body[key]
    return body


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>not json</html>"),
    httpx.Response(200, json=["not", "an", "object"]),
    httpx.Response(200, json=_without("done")),
    httpx.Response(200, json=_without("message")),
    httpx.Response(200, json=chat_body(message={"role": "assistant"})),
    httpx.Response(200, json=chat_body(message={"role": "assistant", "content": 42})),
    httpx.Response(200, json=chat_body(eval_count=-1)),
    httpx.Response(200, json=chat_body(done_reason=7)),
    httpx.Response(200, json={"error": "unexpected failure"}),
], ids=["not-json", "json-array", "no-done", "no-message", "no-content",
        "content-not-string", "negative-token-count", "done-reason-not-string",
        "error-payload"])
async def test_malformed_generation_response_is_never_a_success(make_gateway, response):
    server = FakeOllama(response)
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMMalformedResponse):
        await gateway.generate(MESSAGES)

    assert len(server.requests) == 1
    assert sleeps == []


async def test_unexpected_done_reason_is_malformed(make_gateway):
    gateway, _ = make_gateway(FakeOllama(ok(chat_body("ok", done_reason="load"))))
    with pytest.raises(LLMMalformedResponse, match="done_reason"):
        await gateway.generate(MESSAGES)


@pytest.mark.parametrize("body", [
    {},
    {"embeddings": "not-a-list"},
    {"embeddings": [VECTOR]},                        # two texts, one vector
    {"embeddings": [VECTOR, "not-a-list"]},
    {"embeddings": [VECTOR, [0.1] * 767 + ["x"]]},
    {"embeddings": [VECTOR, [0.1] * 767 + [True]]},
], ids=["no-embeddings", "embeddings-not-list", "count-mismatch",
        "vector-not-list", "non-numeric-value", "boolean-value"])
async def test_malformed_embedding_response_is_never_a_success(make_gateway, body):
    gateway, _ = make_gateway(FakeOllama(ok(body)))
    with pytest.raises(LLMMalformedResponse):
        await gateway.embed(["quiet cafe", "lakeside park"])


# --- empty responses ------------------------------------------------------

@pytest.mark.parametrize("content", [
    "",
    "   \n\t",
    "<think>only reasoning, no answer</think>",
    "<think>cut off mid thought",
], ids=["empty", "whitespace", "reasoning-only", "unclosed-reasoning"])
async def test_empty_generation_is_never_a_success(make_gateway, content):
    server = FakeOllama(ok(chat_body(content, eval_count=5)))
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMEmptyResponse):
        await gateway.generate(MESSAGES)

    assert len(server.requests) == 1
    assert sleeps == []


# --- truncated / incomplete generation ------------------------------------

async def test_generation_stopped_by_length_is_truncated(make_gateway):
    server = FakeOllama(ok(chat_body("Your day begins at Cubbon Park and then",
                                     done_reason="length", eval_count=64)))
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMTruncated):
        await gateway.generate(MESSAGES, max_tokens=64)

    assert len(server.requests) == 1
    assert sleeps == []


async def test_token_count_at_limit_is_truncated_even_without_done_reason(make_gateway):
    body = chat_body("partial", eval_count=64)
    del body["done_reason"]
    gateway, _ = make_gateway(FakeOllama(ok(body)))

    with pytest.raises(LLMTruncated):
        await gateway.generate(MESSAGES, max_tokens=64)


async def test_incomplete_generation_is_truncated(make_gateway):
    gateway, _ = make_gateway(FakeOllama(ok(chat_body("partial", done=False))))
    with pytest.raises(LLMTruncated, match="did not complete"):
        await gateway.generate(MESSAGES)


async def test_truncation_is_detected_before_content_is_read(make_gateway):
    """A capped response with no usable content is reported as truncated -
    the diagnosis that says raise the limit - not merely as empty."""
    gateway, _ = make_gateway(FakeOllama(ok(chat_body("", done_reason="length",
                                                      eval_count=64))))
    with pytest.raises(LLMTruncated):
        await gateway.generate(MESSAGES, max_tokens=64)


async def test_generation_below_the_limit_succeeds(make_gateway):
    gateway, _ = make_gateway(FakeOllama(ok(chat_body("ok", eval_count=63))))
    assert (await gateway.generate(MESSAGES, max_tokens=64)).text == "ok"


# --- embedding dimension --------------------------------------------------

async def test_wrong_embedding_dimension_is_rejected(make_gateway):
    server = FakeOllama(ok({"embeddings": [[0.01] * 1024]}))
    gateway, sleeps = make_gateway(server)

    with pytest.raises(LLMEmbeddingDimensionMismatch) as caught:
        await gateway.embed(["quiet cafe"])

    assert caught.value.expected == 768
    assert caught.value.actual == 1024
    assert caught.value.model == "nomic-embed-text"
    assert len(server.requests) == 1
    assert sleeps == []


async def test_empty_vector_is_a_dimension_mismatch(make_gateway):
    gateway, _ = make_gateway(FakeOllama(ok({"embeddings": [[]]})))
    with pytest.raises(LLMEmbeddingDimensionMismatch):
        await gateway.embed(["quiet cafe"])


# --- arguments, privacy, lifecycle ----------------------------------------

async def test_invalid_arguments_fail_before_any_request(make_gateway):
    server = FakeOllama(ok(chat_body()))
    gateway, _ = make_gateway(server)

    with pytest.raises(TypeError):
        await gateway.embed("quiet cafe")
    with pytest.raises(ValueError):
        await gateway.generate([])

    assert server.requests == []


async def test_prompt_and_response_text_are_never_logged(make_gateway, logs):
    secret_prompt = (ChatMessage("user", "SECRET-PROMPT-TEXT"),)
    gateway, _ = make_gateway(FakeOllama(ok(chat_body("SECRET-RESPONSE-TEXT"))))

    await gateway.generate(secret_prompt)

    logged = repr(logs.events)
    assert "SECRET-PROMPT-TEXT" not in logged
    assert "SECRET-RESPONSE-TEXT" not in logged


async def test_closed_gateway_refuses_calls(make_gateway):
    gateway, _ = make_gateway(FakeOllama(ok(chat_body())))
    await gateway.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await gateway.generate(MESSAGES)


async def test_owned_client_is_closed_and_injected_client_is_not(make_gateway):
    owned = OllamaGateway(host=HOST, generation_model="qwen3:14b",
                          embedding_model="nomic-embed-text",
                          embedding_dimension=768, num_ctx=8192,
                          keep_alive="10m", timeout_s=30.0, max_retries=0)
    await owned.aclose()
    assert owned._client.is_closed

    injected, _ = make_gateway(FakeOllama(ok(chat_body())))
    await injected.aclose()
    assert not injected._client.is_closed


@pytest.mark.parametrize("overrides", [
    {"host": ""},
    {"embedding_dimension": 0},
    {"num_ctx": 0},
    {"max_retries": -1},
    {"timeout_s": 0},
])
def test_constructor_rejects_invalid_configuration(overrides):
    kwargs = dict(host=HOST, generation_model="qwen3:14b",
                  embedding_model="nomic-embed-text", embedding_dimension=768,
                  num_ctx=8192, keep_alive="10m", timeout_s=30.0, max_retries=2)
    kwargs.update(overrides)
    with pytest.raises(ValueError):
        OllamaGateway(**kwargs)
