import pytest
from app.main import _model_runtime
from app.model_gateway.runtime import FileModelSettingsStore, ModelConfigurationLocked, validated_settings
from scripts.delivery_demo import DeliveryMockProvider

PAYLOAD = {"provider": "deepseek", "model": "test", "api_key": "test-sentinel-key"}

@pytest.mark.parametrize("environment", ["development", "production"])
def test_fixed_delivery_ignores_stored_shared_and_personal(monkeypatch, tmp_path, environment):
    path = tmp_path / "settings.json"
    store = FileModelSettingsStore(path)
    store.save(validated_settings(PAYLOAD))
    store.save_user("student-1", validated_settings(PAYLOAD))
    monkeypatch.setenv("MODEL_SETTINGS_PATH", str(path))
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("MODEL_PROVIDER", "disabled")
    monkeypatch.setenv("MODEL_SETTINGS_ENABLED", "1")
    injected = DeliveryMockProvider()
    runtime, service = _model_runtime(injected)
    assert runtime.provider() is injected
    assert service.provider_for("student-1") is injected
    assert service.personal_settings("student-1") is None
    assert service.snapshot().provider == "mock"
    assert service.environment_locked
    for action in [lambda: service.apply(PAYLOAD), lambda: service.apply_personal("student-1", PAYLOAD),
                   service.restore_environment, lambda: service.clear_personal("student-1"),
                   lambda: service.probe(PAYLOAD), lambda: service.probe_personal("student-1", PAYLOAD)]:
        with pytest.raises(ModelConfigurationLocked):
            action()

def test_web_configuration_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("MODEL_SETTINGS_ENABLED", raising=False)
    monkeypatch.setenv("MODEL_PROVIDER", "disabled")
    _, service = _model_runtime(None)
    assert service.environment_locked
    with pytest.raises(ModelConfigurationLocked):
        service.apply(PAYLOAD)

def test_supported_live_environment_can_opt_in(monkeypatch):
    monkeypatch.setenv("MODEL_SETTINGS_ENABLED", "1")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MODEL_PROVIDER", "disabled")
    _, service = _model_runtime(None)
    assert not service.environment_locked
    service.apply(PAYLOAD)
    assert service.snapshot().provider == "deepseek"


@pytest.mark.parametrize("error_type", ["failure", "timeout"])
def test_provider_http_errors_are_explicit_and_redacted(error_type):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.errors import install_error_handling
    from app.model_gateway.base import ProviderFailure, ProviderTimeout
    app = FastAPI()
    install_error_handling(app)
    @app.get("/test-error")
    def fail():
        raise (ProviderTimeout if error_type == "timeout" else ProviderFailure)("private-key-sentinel")
    response = TestClient(app).get("/test-error")
    assert response.status_code == 503
    assert response.json()["code"] == ("MODEL_PROVIDER_TIMEOUT" if error_type == "timeout" else "MODEL_PROVIDER_FAILURE")
    assert "private-key-sentinel" not in response.text


def test_fixed_delivery_http_routes_stay_locked_and_scoped(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.auth import Authenticator, TokenCodec
    from app.api.errors import install_error_handling
    from app.api.model_settings import create_model_settings_router
    from app.api.personal_model_settings import create_personal_model_settings_router
    from app.auth.models import Role, User, UserRepository
    monkeypatch.setenv("MODEL_SETTINGS_ENABLED", "1")
    _, service = _model_runtime(DeliveryMockProvider())
    users = UserRepository([User.with_password("teacher", "teacher", "pw", Role.TEACHER), User.with_password("student", "student", "pw", Role.STUDENT)])
    auth = Authenticator(users, TokenCodec("synthetic-lock-test-secret"))
    app = FastAPI()
    install_error_handling(app)
    app.include_router(create_model_settings_router(service, auth))
    app.include_router(create_personal_model_settings_router(service, auth))
    client = TestClient(app)
    teacher = {"Authorization": "Bearer " + auth.login("teacher", "pw")[0]}
    student = {"Authorization": "Bearer " + auth.login("student", "pw")[0]}
    for headers, path in [(teacher, "/teacher/model-settings"), (student, "/model-settings")]:
        view = client.get(path, headers=headers).json()
        assert view["provider"] == "mock" and view["environment_locked"]
        assert client.put(path, headers=headers, json=PAYLOAD).status_code == 409
        assert client.post(path + "/probe", headers=headers, json=PAYLOAD).status_code == 409
    assert client.put("/teacher/model-settings", headers=teacher, json={"provider":"environment"}).status_code == 409
    assert client.put("/model-settings", headers=student, json={"mode":"shared"}).status_code == 409
    assert client.get("/teacher/model-settings", headers=student).status_code == 404
