from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.model_gateway.base import HintRequest, ProviderFailure, ProviderTimeout
from app.model_gateway.config import model_provider_from_config
from app.model_gateway.openai_responses import OpenAIResponsesProvider


def _request():
    return HintRequest(
        category="conceptual",
        root_cause="private-source-sentinel",
        concept_ids=("cj.enum.match",),
        level=1,
        previous_attempt_count=0,
        approved_outline="private-answer-sentinel",
    )


def _response(payload: dict):
    return {
        "id": "resp-safe-id",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps(payload)}
                ],
            }
        ],
    }


def test_responses_provider_uses_stateless_strict_json_schema():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response({"level": 1, "content": "Reflect."}))

    provider = OpenAIResponsesProvider(
        api_key="secret-key-sentinel",
        model="configured-model",
        base_url="https://example.invalid",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.generate_hint(_request())

    assert result.content == "Reflect."
    assert captured["url"] == "https://example.invalid/v1/responses"
    assert captured["authorization"] == "Bearer secret-key-sentinel"
    assert captured["body"]["model"] == "configured-model"
    assert captured["body"]["store"] is False
    assert captured["body"]["text"]["format"]["type"] == "json_schema"
    assert captured["body"]["text"]["format"]["strict"] is True
    assert captured["body"]["text"]["format"]["schema"]["additionalProperties"] is False


@pytest.mark.parametrize("status", [400, 429, 500])
def test_http_errors_are_sanitized_provider_failures(status, caplog):
    def handler(_request: httpx.Request):
        return httpx.Response(
            status,
            headers={"x-request-id": "provider-safe-id"},
            json={"error": {"message": "secret-key-sentinel private-source-sentinel"}},
        )

    provider = OpenAIResponsesProvider(
        api_key="secret-key-sentinel",
        model="configured-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderFailure):
        provider.generate_hint(_request())

    logged = caplog.text
    assert "provider-safe-id" in logged
    assert "secret-key-sentinel" not in logged
    assert "private-source-sentinel" not in logged
    assert "private-answer-sentinel" not in logged


def test_timeout_is_mapped_without_leaking_private_input(caplog):
    def handler(_request: httpx.Request):
        raise httpx.ReadTimeout("private-source-sentinel")

    provider = OpenAIResponsesProvider(
        api_key="secret-key-sentinel",
        model="configured-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderTimeout):
        provider.generate_hint(_request())

    assert "private-source-sentinel" not in caplog.text
    assert "secret-key-sentinel" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        {"not_output": []},
        _response({"level": 9, "content": "invalid"}),
        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "not-json"}]}]},
    ],
)
def test_invalid_responses_are_provider_failures(body):
    provider = OpenAIResponsesProvider(
        api_key="key",
        model="model",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=body)
            )
        ),
    )

    with pytest.raises(ProviderFailure):
        provider.generate_hint(_request())


def test_production_configuration_requires_real_provider_key_and_model():
    with pytest.raises(RuntimeError, match="MODEL_PROVIDER"):
        model_provider_from_config({"APP_ENV": "production"})
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        model_provider_from_config(
            {"APP_ENV": "production", "MODEL_PROVIDER": "openai", "MODEL_NAME": "m"}
        )
    with pytest.raises(RuntimeError, match="MODEL_NAME"):
        model_provider_from_config(
            {
                "APP_ENV": "production",
                "MODEL_PROVIDER": "openai",
                "OPENAI_API_KEY": "key",
            }
        )
    with pytest.raises(RuntimeError, match="mock"):
        model_provider_from_config(
            {"APP_ENV": "production", "MODEL_PROVIDER": "mock"}
        )


def test_development_without_provider_is_explicitly_disabled():
    provider = model_provider_from_config({"APP_ENV": "development"})

    with pytest.raises(ProviderFailure, match="disabled"):
        provider.generate_hint(_request())
