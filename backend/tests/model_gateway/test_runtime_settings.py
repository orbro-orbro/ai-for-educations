from __future__ import annotations

import json
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import Authenticator, TokenCodec
from app.api.errors import install_error_handling
from app.api.model_settings import create_model_settings_router
from app.auth.models import Role, User, UserRepository
from app.model_gateway.base import ProviderFailure
from app.model_gateway.config import DisabledModelProvider
from app.model_gateway.mock import DeterministicMockProvider
from app.model_gateway.openai_chat_completions import OpenAIChatCompletionsProvider
from app.model_gateway.runtime import (
    FileModelSettingsStore,
    InMemoryModelSettingsStore,
    ModelConfigurationError,
    ModelConfigurationLocked,
    ModelSettings,
    ModelSettingsService,
    ModelSettingsStorageError,
    RuntimeModelProvider,
    build_provider,
    probe_connection,
    settings_from_environment,
    validated_settings,
)

REMOTE_KEY = "sk-runtime-sentinel-9876"


def _settings(provider: str = "disabled") -> ModelSettings:
    return ModelSettings(provider=provider, source="environment")


def _service(*, environment: str = "development", store=None, client=None):
    runtime = RuntimeModelProvider(DisabledModelProvider(), _settings())
    service = ModelSettingsService(
        runtime,
        store if store is not None else InMemoryModelSettingsStore(),
        environment=environment,
        environ={},
        client=client,
    )
    return runtime, service


def _client(service: ModelSettingsService):
    users = UserRepository(
        [
            User.with_password("teacher-1", "teacher", "pw", Role.TEACHER),
            User.with_password("student-1", "student", "pw", Role.STUDENT),
        ]
    )
    authenticator = Authenticator(users, TokenCodec("runtime-settings-test-secret"))
    application = FastAPI()
    install_error_handling(application)
    application.include_router(create_model_settings_router(service, authenticator))
    tokens = {
        name: authenticator.login(name, "pw")[0] for name in ("teacher", "student")
    }
    return TestClient(application), tokens


def _auth(tokens, name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens[name]}"}


def _deepseek_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key": REMOTE_KEY,
        "timeout_seconds": 30,
    }
    payload.update(overrides)
    return payload


def test_remote_configuration_requires_a_key_and_a_model():
    with pytest.raises(ModelConfigurationError):
        validated_settings({"provider": "deepseek", "model": "deepseek-chat"})
    with pytest.raises(ModelConfigurationError):
        validated_settings({"provider": "deepseek", "api_key": REMOTE_KEY})


def test_remote_configuration_rejects_plaintext_http_endpoints():
    with pytest.raises(ModelConfigurationError):
        validated_settings(
            _deepseek_payload(base_url="http://models.example.com/v1")
        )
    allowed = validated_settings(_deepseek_payload(base_url="http://127.0.0.1:8080/v1"))
    assert allowed.base_url == "http://127.0.0.1:8080/v1"


def test_remote_configuration_rejects_embedded_credentials():
    with pytest.raises(ModelConfigurationError):
        validated_settings(
            _deepseek_payload(base_url="https://user:pass@models.example.com/v1")
        )


def test_unsupported_provider_is_rejected():
    with pytest.raises(ModelConfigurationError):
        validated_settings({"provider": "teleagent"})


def test_default_base_url_comes_from_the_provider_preset():
    settings = validated_settings(_deepseek_payload())
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.source == "web"


def test_control_providers_need_no_credentials():
    assert validated_settings({"provider": "mock"}).provider == "mock"
    assert validated_settings({"provider": "disabled"}).provider == "disabled"


def test_build_provider_covers_every_supported_name():
    assert isinstance(build_provider(_settings("disabled")), DisabledModelProvider)
    assert isinstance(build_provider(_settings("mock")), DeterministicMockProvider)
    remote = validated_settings(_deepseek_payload())
    assert isinstance(build_provider(remote), OpenAIChatCompletionsProvider)
    assert isinstance(build_provider(_settings("environment"), environ={}), DisabledModelProvider)


def test_environment_settings_describe_each_startup_mode():
    assert settings_from_environment({}).provider == "disabled"
    qwen = settings_from_environment(
        {
            "MODEL_PROVIDER": "qwen",
            "MODEL_NAME": "qwen-max",
            "QWEN_API_KEY": REMOTE_KEY,
        }
    )
    assert qwen.provider == "qwen"
    assert qwen.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert qwen.source == "environment"
    assert settings_from_environment({"MODEL_PROVIDER": "mock"}).provider == "mock"


def test_swap_is_visible_through_the_wrapper_the_services_hold():
    runtime, service = _service()
    with pytest.raises(ProviderFailure):
        runtime.generate_hint(None)
    service.apply(_deepseek_payload())
    assert isinstance(runtime.provider(), OpenAIChatCompletionsProvider)
    assert runtime.snapshot().provider == "deepseek"


def test_rejected_configuration_keeps_the_previous_provider_active():
    runtime, service = _service()
    with pytest.raises(ModelConfigurationError):
        service.apply(_deepseek_payload(api_key=""))
    assert isinstance(runtime.provider(), DisabledModelProvider)
    assert runtime.snapshot().provider == "disabled"


def test_secret_stays_out_of_the_runtime_snapshot():
    runtime, service = _service()
    settings = service.apply(_deepseek_payload())
    assert settings.api_key == REMOTE_KEY
    assert settings.key_hint == "****9876"
    assert REMOTE_KEY not in repr(runtime.snapshot())
    # The key is persisted for the next restart, but only inside the store payload
    # that is never serialized into an HTTP response.
    assert REMOTE_KEY in json.dumps(settings.stored_payload())


def test_production_deployment_cannot_be_reconfigured_from_the_web():
    _runtime, service = _service(environment="production")
    with pytest.raises(ModelConfigurationLocked):
        service.apply(_deepseek_payload())
    with pytest.raises(ModelConfigurationLocked):
        service.probe(_deepseek_payload())


def test_restoring_the_environment_clears_the_stored_configuration():
    runtime, service = _service()
    service.apply(_deepseek_payload())
    restored = service.restore_environment()
    assert restored.provider == "disabled"
    assert isinstance(runtime.provider(), DisabledModelProvider)


def test_file_store_round_trip_is_private_and_atomic(tmp_path):
    store = FileModelSettingsStore(tmp_path / "model-settings.json")
    assert store.load() is None
    settings = validated_settings(_deepseek_payload())
    store.save(settings)
    loaded = store.load()
    assert loaded is not None
    assert loaded.provider == "deepseek"
    assert loaded.api_key == REMOTE_KEY
    if sys.platform != "win32":
        assert (tmp_path / "model-settings.json").stat().st_mode & 0o077 == 0
    store.clear()
    assert store.load() is None


def test_corrupt_file_store_is_reported_not_ignored(tmp_path):
    path = tmp_path / "model-settings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelSettingsStorageError):
        FileModelSettingsStore(path).load()


def test_blank_key_reuses_the_current_key_for_the_same_provider():
    _runtime, service = _service()
    service.apply(_deepseek_payload())
    updated = service.apply(_deepseek_payload(api_key="", model="deepseek-reasoner"))
    assert updated.model == "deepseek-reasoner"
    assert updated.api_key == REMOTE_KEY


def test_blank_key_is_not_reused_when_the_provider_changes():
    _runtime, service = _service()
    service.apply(_deepseek_payload())
    with pytest.raises(ModelConfigurationError):
        service.apply(
            {
                "provider": "qwen",
                "model": "qwen-plus",
                "api_key": "",
            }
        )


def test_probe_can_reuse_the_current_key():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    service = _service(client=httpx.Client(transport=httpx.MockTransport(handler)))[1]
    service.apply(_deepseek_payload())
    outcome = service.probe({"provider": "deepseek", "model": "deepseek-chat", "api_key": ""})
    assert outcome.status == "ok"
    assert captured["authorization"] == f"Bearer {REMOTE_KEY}"


def test_teacher_reads_the_current_state_without_the_key():
    _runtime, service = _service()
    client, tokens = _client(service)
    service.apply(_deepseek_payload())
    response = client.get("/teacher/model-settings", headers=_auth(tokens, "teacher"))
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "deepseek"
    assert body["model"] == "deepseek-chat"
    assert body["configured"] is True
    assert body["key_hint"] == "****9876"
    assert body["source"] == "web"
    assert body["environment_locked"] is False
    assert REMOTE_KEY not in response.text


def test_teacher_applies_a_configuration_and_sees_it_immediately():
    runtime, service = _service()
    client, tokens = _client(service)
    response = client.put(
        "/teacher/model-settings",
        headers=_auth(tokens, "teacher"),
        json=_deepseek_payload(),
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "deepseek"
    assert isinstance(runtime.provider(), OpenAIChatCompletionsProvider)


def test_teacher_can_switch_back_to_the_environment():
    _runtime, service = _service()
    client, tokens = _client(service)
    service.apply(_deepseek_payload())
    response = client.put(
        "/teacher/model-settings",
        headers=_auth(tokens, "teacher"),
        json={"provider": "environment"},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "disabled"
    assert response.json()["source"] == "environment"


def test_students_cannot_see_or_change_the_model_configuration():
    _runtime, service = _service()
    client, tokens = _client(service)
    for method, path, payload in (
        ("get", "/teacher/model-settings", None),
        ("put", "/teacher/model-settings", _deepseek_payload()),
        ("post", "/teacher/model-settings/probe", _deepseek_payload()),
    ):
        response = getattr(client, method)(
            path, headers=_auth(tokens, "student"), **({"json": payload} if payload else {})
        )
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_AVAILABLE"


def test_locked_deployment_returns_conflict():
    _runtime, service = _service(environment="production")
    client, tokens = _client(service)
    response = client.put(
        "/teacher/model-settings",
        headers=_auth(tokens, "teacher"),
        json=_deepseek_payload(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "MODEL_CONFIGURATION_MANAGED"


def test_invalid_configuration_returns_a_validation_error_without_echoing_the_key():
    _runtime, service = _service()
    client, tokens = _client(service)
    response = client.put(
        "/teacher/model-settings",
        headers=_auth(tokens, "teacher"),
        json=_deepseek_payload(api_key=""),
    )
    assert response.status_code == 422
    assert "api_key" in response.json()["message"]


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (200, "ok"),
        (401, "invalid_credentials"),
        (403, "invalid_credentials"),
        (404, "model_or_endpoint_not_found"),
        (429, "rate_limited"),
        (400, "rejected_request"),
        (500, "http_error"),
    ],
)
def test_probe_maps_upstream_status_codes(status_code, expected):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "upstream detail"})

    service = _service(client=httpx.Client(transport=httpx.MockTransport(handler)))[1]
    outcome = service.probe(_deepseek_payload())
    assert outcome.status == expected
    assert outcome.http_status == status_code


def test_probe_reports_timeouts_and_transport_errors():
    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def transport_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    settings = validated_settings(_deepseek_payload())
    assert probe_connection(
        settings, client=httpx.Client(transport=httpx.MockTransport(timeout_handler))
    ).status == "timeout"
    assert probe_connection(
        settings, client=httpx.Client(transport=httpx.MockTransport(transport_handler))
    ).status == "transport_error"


def test_probe_sends_the_key_in_a_header_and_never_returns_the_body():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    service = _service(client=httpx.Client(transport=httpx.MockTransport(handler)))[1]
    outcome = service.probe(_deepseek_payload())
    assert outcome.status == "ok"
    assert captured["authorization"] == f"Bearer {REMOTE_KEY}"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert "choices" not in repr(outcome)


def test_probe_rejects_control_providers():
    _runtime, service = _service()
    with pytest.raises(ModelConfigurationError):
        service.probe({"provider": "mock"})

def test_blank_key_is_not_reused_when_the_base_url_changes():
    # Reusing the stored key for a different endpoint would send the credential there.
    runtime, service = _service()
    service.apply(_deepseek_payload())
    with pytest.raises(ModelConfigurationError):
        service.apply(_deepseek_payload(api_key="", base_url="https://attacker.example"))
    assert runtime.snapshot().base_url == "https://api.deepseek.com"


def test_probe_never_sends_the_stored_key_to_a_different_endpoint():
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    service = _service(client=httpx.Client(transport=httpx.MockTransport(handler)))[1]
    service.apply(_deepseek_payload())
    with pytest.raises(ModelConfigurationError):
        service.probe(
            {"provider": "deepseek", "model": "deepseek-chat", "api_key": "", "base_url": "https://attacker.example/v1"}
        )
    assert sent == [], "no request may leave the server with the stored credential"


@pytest.mark.parametrize("base_url", ["", "https://api.deepseek.com", "https://api.deepseek.com/"])
def test_blank_key_is_still_reused_for_the_same_endpoint(base_url):
    _runtime, service = _service()
    service.apply(_deepseek_payload())
    updated = service.apply(_deepseek_payload(api_key="", model="deepseek-reasoner", base_url=base_url))
    assert updated.api_key == REMOTE_KEY
