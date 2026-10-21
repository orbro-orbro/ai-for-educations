"""Per-user model overrides: isolation, fallback, and the HTTP surface."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import Authenticator, TokenCodec
from app.api.errors import install_error_handling
from app.api.personal_model_settings import create_personal_model_settings_router
from app.auth.models import Role, User, UserRepository
from app.model_gateway.config import DisabledModelProvider
from app.model_gateway.openai_chat_completions import OpenAIChatCompletionsProvider
from app.model_gateway.runtime import (
    FileModelSettingsStore,
    InMemoryModelSettingsStore,
    ModelConfigurationError,
    ModelConfigurationLocked,
    ModelSettings,
    ModelSettingsService,
    RuntimeModelProvider,
)

SHARED_KEY = "sk-shared-sentinel-1111"
PERSONAL_KEY = "sk-personal-sentinel-2222"
OTHER_KEY = "sk-other-sentinel-3333"


def _runtime(provider: str = "disabled") -> RuntimeModelProvider:
    return RuntimeModelProvider(
        DisabledModelProvider(),
        ModelSettings(provider=provider, source="environment"),
    )


def _service(*, environment: str = "development", store=None) -> ModelSettingsService:
    return ModelSettingsService(
        _runtime(),
        store if store is not None else InMemoryModelSettingsStore(),
        environment=environment,
        environ={},
    )


def _payload(key: str = PERSONAL_KEY, provider: str = "deepseek", **overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "mode": "own",
        "provider": provider,
        "model": "deepseek-chat",
        "api_key": key,
        "timeout_seconds": 30,
    }
    payload.update(overrides)
    return payload


def _client(service: ModelSettingsService) -> tuple[TestClient, dict[str, str]]:
    users = UserRepository(
        [
            User.with_password("teacher-1", "teacher", "pw", Role.TEACHER),
            User.with_password("student-1", "student1", "pw", Role.STUDENT),
            User.with_password("student-2", "student2", "pw", Role.STUDENT),
        ]
    )
    authenticator = Authenticator(users, TokenCodec("personal-settings-test-secret"))
    application = FastAPI()
    install_error_handling(application)
    application.include_router(
        create_personal_model_settings_router(service, authenticator)
    )
    tokens = {
        name: authenticator.login(name, "pw")[0]
        for name in ("teacher", "student1", "student2")
    }
    return TestClient(application), tokens


def _auth(tokens: dict[str, str], name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens[name]}"}


def test_a_personal_override_only_applies_to_its_owner():
    service = _service()
    service.apply_personal("student-1", _payload())

    assert isinstance(service.provider_for("student-1"), OpenAIChatCompletionsProvider)
    assert isinstance(service.provider_for("student-2"), DisabledModelProvider)
    assert isinstance(service.provider_for(None), DisabledModelProvider)


def test_a_user_without_an_override_inherits_the_shared_provider():
    service = _service()
    assert service.personal_settings("student-1") is None
    assert service.provider_for("student-1") is service.provider_for(None)


def test_clearing_an_override_falls_back_to_the_shared_provider():
    service = _service()
    service.apply_personal("student-1", _payload())
    service.clear_personal("student-1")

    assert service.personal_settings("student-1") is None
    assert isinstance(service.provider_for("student-1"), DisabledModelProvider)


def test_a_blank_key_reuses_only_that_users_own_key():
    service = _service()
    service.apply_personal("student-1", _payload())
    service.apply_personal("student-1", _payload(key="", model="deepseek-chat"))

    stored = service.personal_settings("student-1")
    assert stored is not None and stored.api_key == PERSONAL_KEY

    with pytest.raises(ModelConfigurationError):
        service.apply_personal("student-2", _payload(key=""))


def test_a_blank_personal_key_never_borrows_the_shared_credential():
    runtime = _runtime("deepseek")
    service = ModelSettingsService(
        runtime,
        InMemoryModelSettingsStore(),
        environment="development",
        environ={},
    )
    runtime.swap(
        DisabledModelProvider(),
        ModelSettings(
            provider="deepseek",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=SHARED_KEY,
            source="web",
        ),
    )

    with pytest.raises(ModelConfigurationError):
        service.apply_personal("student-1", _payload(key=""))


def test_the_personal_scope_cannot_target_the_deployment_environment():
    service = _service()
    with pytest.raises(ModelConfigurationError):
        service.apply_personal("student-1", _payload(provider="environment"))


def test_production_keeps_the_personal_scope_read_only():
    service = _service(environment="production")
    with pytest.raises(ModelConfigurationLocked):
        service.apply_personal("student-1", _payload())
    with pytest.raises(ModelConfigurationLocked):
        service.clear_personal("student-1")


def test_file_store_keeps_the_shared_and_personal_entries_apart(tmp_path):
    path = tmp_path / "model-settings.json"
    store = FileModelSettingsStore(path)
    store.save(
        ModelSettings(
            provider="deepseek",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=SHARED_KEY,
            source="web",
        )
    )
    store.save_user(
        "student-1",
        ModelSettings(
            provider="qwen",
            model="qwen-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=PERSONAL_KEY,
            source="web",
        ),
    )

    shared = store.load()
    personal = store.load_user("student-1")
    assert shared is not None and shared.api_key == SHARED_KEY
    assert personal is not None and personal.api_key == PERSONAL_KEY
    assert store.load_user("student-2") is None

    store.clear_user("student-1")
    assert store.load_user("student-1") is None
    assert store.load() is not None


def test_a_version_one_file_is_read_as_the_shared_configuration(tmp_path):
    path = tmp_path / "model-settings.json"
    path.write_text(
        json.dumps(
            {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "api_key": SHARED_KEY,
                "timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )
    store = FileModelSettingsStore(path)

    loaded = store.load()
    assert loaded is not None and loaded.api_key == SHARED_KEY

    store.save_user(
        "student-1",
        ModelSettings(
            provider="qwen",
            model="qwen-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=OTHER_KEY,
            source="web",
        ),
    )
    assert store.load() is not None
    assert store.load_user("student-1") is not None


def test_reading_before_any_save_reports_the_shared_scope():
    service = _service()
    client, tokens = _client(service)

    response = client.get("/model-settings", headers=_auth(tokens, "student1"))

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "shared"
    assert body["personal_configured"] is False
    assert body["key_hint"] is None


def test_the_http_surface_is_scoped_per_student():
    service = _service()
    client, tokens = _client(service)

    saved = client.put(
        "/model-settings", json=_payload(), headers=_auth(tokens, "student1")
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["scope"] == "own"
    assert body["personal_configured"] is True
    assert body["provider"] == "deepseek"
    assert body["key_hint"] == "****2222"

    other = client.get("/model-settings", headers=_auth(tokens, "student2")).json()
    assert other["scope"] == "shared"
    assert other["personal_configured"] is False


def test_switching_back_to_shared_drops_the_override():
    service = _service()
    client, tokens = _client(service)
    client.put("/model-settings", json=_payload(), headers=_auth(tokens, "student1"))

    restored = client.put(
        "/model-settings",
        json={"mode": "shared", "provider": None},
        headers=_auth(tokens, "student1"),
    )

    assert restored.status_code == 200, restored.text
    assert restored.json()["scope"] == "shared"
    assert service.personal_settings("student-1") is None


def test_a_teacher_cannot_write_the_personal_scope():
    service = _service()
    client, tokens = _client(service)

    response = client.put(
        "/model-settings", json=_payload(), headers=_auth(tokens, "teacher")
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_a_student_cannot_write_the_shared_configuration():
    service = _service()
    client, tokens = _client(service)
    client.put("/model-settings", json=_payload(), headers=_auth(tokens, "student1"))

    # The shared entry is only reachable through the teacher router; the
    # personal router never accepts a payload that changes it.
    assert service.snapshot().provider == "disabled"


def test_missing_provider_is_rejected():
    service = _service()
    client, tokens = _client(service)

    response = client.put(
        "/model-settings",
        json={"mode": "own", "model": "deepseek-chat", "api_key": PERSONAL_KEY},
        headers=_auth(tokens, "student1"),
    )

    assert response.status_code == 422

def test_a_blank_personal_key_is_not_reused_when_the_base_url_changes():
    service = _service()
    service.apply_personal("student-1", _payload())
    with pytest.raises(ModelConfigurationError):
        service.apply_personal("student-1", _payload(key="", base_url="https://attacker.example"))
    with pytest.raises(ModelConfigurationError):
        service.probe_personal("student-1", _payload(key="", base_url="https://attacker.example"))


def test_a_blank_personal_key_is_still_reused_for_the_same_endpoint():
    service = _service()
    service.apply_personal("student-1", _payload())
    updated = service.apply_personal("student-1", _payload(key="", model="deepseek-reasoner"))
    assert updated.api_key == PERSONAL_KEY
