"""All original counterexamples enter PostgreSQL before Router filtering."""
import pytest
from sqlalchemy import select, func
from app.main import create_app
from app.model_gateway.mock import DeterministicMockProvider
from app.persistence.models import DiagnosisRow
from tests.security.test_small_sample_contract import vectors
from tests.security.analytics_assertions import assert_analytics
from tests.integration.wave3_support import Wave3PG, postgres_url, SECRET


@pytest.fixture
def gate(monkeypatch):
    pg = Wave3PG()
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", SECRET)
    # Only composition needs this variable; migration deliberately rejects it.
    monkeypatch.setenv("DATABASE_URL", postgres_url())
    pg.application = create_app(model_provider=DeterministicMockProvider())
    yield pg
    pg.close()
    pg.application.state.memory_audit._uow.sessions.kw["bind"].dispose()


@pytest.mark.parametrize("vector", vectors(), ids=lambda v:v["vector_id"])
def test_vector_through_official_router_sql_postgres(gate, vector, record_property):
    gate.seed_vector_facts(vector["facts"])
    with gate.sessions() as session:
        assert session.scalar(select(func.count()).select_from(DiagnosisRow)) == len(vector["facts"])
    filters = {k:v for k,v in vector["expected_response"]["filters"].items() if v is not None}
    response = gate.get_analytics("course-a", filters=filters)
    assert response.status_code == 200
    assert_analytics(vector, response.json())
    record_property("request", str(response.request.url))
    record_property("actual_response", response.text)
    record_property("facts_inserted", len(vector["facts"]))
    record_property("excluded_counterexamples_inserted", sum("excluded_by" in f for f in vector["facts"]))


@pytest.mark.parametrize("vector", [v for v in vectors() if v["scenario"] == "four-distinct" and v["filter_combination"] != "none"], ids=lambda v:v["vector_id"])
def test_each_filter_counterexample_remains_in_sql(gate, vector):
    gate.seed_vector_facts(vector["facts"])
    filters = {k:v for k,v in vector["expected_response"]["filters"].items() if v is not None}
    assert gate.get_analytics(filters=filters).json()["status"] == "insufficient_sample"
    for field in filters:
        weaker = {k:v for k,v in filters.items() if k != field}
        response = gate.get_analytics(filters=weaker)
        assert response.status_code == 200
        assert response.json()["status"] == "available", field
