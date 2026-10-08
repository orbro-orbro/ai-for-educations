import pytest
from app.main import create_app
from app.model_gateway.mock import DeterministicMockProvider
from tests.integration.wave3_support import Wave3PG, postgres_url, SECRET


def test_default_sql_application_mounts_teacher_routes_and_preserves_security_dependencies(monkeypatch):
    pg = Wave3PG()
    try:
        pg.seed_diagnoses(students=5)
        monkeypatch.setenv("DATABASE_URL",postgres_url())
        monkeypatch.setenv("AUTH_TOKEN_SECRET",SECRET)
        monkeypatch.setenv("APP_ENV","test")
        app = create_app(model_provider=DeterministicMockProvider())
        repository = app.state.teacher_analytics_repository
        from app.analytics.persistence import SqlTeacherAnalyticsRepository
        assert isinstance(repository,SqlTeacherAnalyticsRepository)
        assert repository.uow is app.state.memory_audit._uow
        assert app.state.deletion_service._source_context is app.state.memory_source
        from app.auth.persistence import SqlTokenRevocations
        assert isinstance(app.state.authenticator._revocations,SqlTokenRevocations)
        pg.application = app
        assert pg.get_analytics().json()["sample_size"] == 5
        assert pg.post_review().status_code == 200
    finally:
        pg.close()


def test_development_application_uses_dynamic_domain_projection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL",raising=False)
    monkeypatch.setenv("APP_ENV","development")
    from app.analytics.data_source import InMemoryTeacherAnalyticsDataSource
    app = create_app(model_provider=DeterministicMockProvider())
    assert isinstance(app.state.teacher_analytics_repository,InMemoryTeacherAnalyticsDataSource)
    assert app.state.teacher_analytics_repository._diagnostics is app.state.diagnostic_repository
