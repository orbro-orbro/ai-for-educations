from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.model_gateway.base import HintRequest, ProviderFailure, ProviderTimeout
from app.model_gateway.config import model_provider_from_config
from app.model_gateway.openai_chat_completions import OpenAIChatCompletionsProvider


def _request():
    return HintRequest(
        category="conceptual",
        root_cause="private-source-sentinel",
        concept_ids=("cj.enum.match",),
        level=1,
        previous_attempt_count=0,
        approved_outline="private-answer-sentinel",
    )


def _body(content, request_id="chatcmpl-safe-id"):
    return {"id": request_id, "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


def _provider(handler, **kwargs):
    return OpenAIChatCompletionsProvider(
        api_key="secret-key-sentinel",
        model="configured-model",
        base_url="https://example.invalid/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def test_posts_json_mode_chat_completion_with_bearer_auth():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_body(json.dumps({"level": 1, "content": "Reflect."})))

    result = _provider(handler).generate_hint(_request())

    assert result.content == "Reflect."
    assert captured["url"] == "https://example.invalid/v1/chat/completions"
    assert captured["auth"] == "Bearer secret-key-sentinel"
    body = captured["body"]
    assert body["model"] == "configured-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "json" in body["messages"][0]["content"].lower()
    assert '"level"' in body["messages"][0]["content"]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_are_sanitized(status, caplog):
    def handler(_request):
        return httpx.Response(
            status,
            headers={"x-request-id": "provider-safe-id"},
            json={"error": {"message": "secret-key-sentinel private-source-sentinel"}},
        )

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderFailure) as info:
        _provider(handler).generate_hint(_request())

    assert "secret-key-sentinel" not in str(info.value)
    assert f"http_{status}" in caplog.text
    assert "provider-safe-id" in caplog.text
    for secret in ("secret-key-sentinel", "private-source-sentinel", "private-answer-sentinel"):
        assert secret not in caplog.text


def test_timeout_maps_to_provider_timeout(caplog):
    def handler(_request):
        raise httpx.ReadTimeout("private-source-sentinel")

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderTimeout):
        _provider(handler).generate_hint(_request())
    assert "private-source-sentinel" not in caplog.text


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"id": "x"}),
        httpx.Response(200, json=_body(None)),
        httpx.Response(200, json=_body("not-json")),
        httpx.Response(200, json=_body(json.dumps({"level": 9, "content": "bad"}))),
        httpx.Response(200, json=_body(json.dumps({"level": 1, "content": "ok", "extra": 1}))),
        httpx.Response(200, json=_body(json.dumps({"level": 1, "content": "ok"}), request_id="x")
                       | {"choices": [{"finish_reason": "length", "message": {"content": '{"level":1'}}]}),
    ],
)
def test_invalid_responses_are_provider_failures(response):
    with pytest.raises(ProviderFailure):
        _provider(lambda _request: response).generate_hint(_request())


def test_unsafe_request_id_is_redacted(caplog):
    def handler(_request):
        return httpx.Response(500, headers={"x-request-id": "secret-key-sentinel unsafe"})

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderFailure):
        _provider(handler).generate_hint(_request())
    assert "secret-key-sentinel" not in caplog.text
    assert "request_id=unavailable" in caplog.text


@pytest.mark.parametrize(
    ("name", "key_var", "base"),
    [
        ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com"),
        ("qwen", "QWEN_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ],
)
def test_config_builds_provider_with_official_base_url(name, key_var, base):
    provider = model_provider_from_config(
        {"APP_ENV": "development", "MODEL_PROVIDER": name, key_var: "k", "MODEL_NAME": "m"}
    )
    assert isinstance(provider, OpenAIChatCompletionsProvider)
    assert provider._endpoint == f"{base}/chat/completions"


@pytest.mark.parametrize(
    ("name", "key_var"), [("deepseek", "DEEPSEEK_API_KEY"), ("qwen", "QWEN_API_KEY")]
)
def test_config_requires_key_and_model_and_valid_timeout(name, key_var):
    env = {"APP_ENV": "production", "MODEL_PROVIDER": name}
    with pytest.raises(RuntimeError, match=key_var):
        model_provider_from_config({**env, "MODEL_NAME": "m"})
    with pytest.raises(RuntimeError, match="MODEL_NAME"):
        model_provider_from_config({**env, key_var: "k"})
    with pytest.raises(RuntimeError, match="MODEL_TIMEOUT_SECONDS"):
        model_provider_from_config({**env, key_var: "k", "MODEL_NAME": "m", "MODEL_TIMEOUT_SECONDS": "0"})


def test_config_base_url_override_and_teleagent_still_unsupported():
    provider = model_provider_from_config(
        {"MODEL_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "k", "MODEL_NAME": "m", "MODEL_BASE_URL": "https://proxy.invalid/v1/"}
    )
    assert provider._endpoint == "https://proxy.invalid/v1/chat/completions"
    with pytest.raises(RuntimeError, match="unsupported"):
        model_provider_from_config({"MODEL_PROVIDER": "teleagent"})
