"""Writes must target this task's synthetic resources, never an existing Gate."""
import pytest
from tests.integration.wave3_support import postgres_url


def test_wave4_postgres_target_is_separate_from_wave3(monkeypatch):
    monkeypatch.setenv("WAVE4_TEST_MODE", "1")
    monkeypatch.setenv("WAVE4_POSTGRES_URL", "postgresql+psycopg://knowbound:wave4-test-only@127.0.0.1:55440/wave4_router")
    assert postgres_url("wave3_browser").endswith(":55440/wave4_browser")
    assert postgres_url().endswith(":55440/wave4_router")


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://knowbound:x@127.0.0.1:55430/wave3_router",
    "postgresql+psycopg://knowbound:x@postgres:55440/wave4_router",
    "postgresql+psycopg://knowbound:x@127.0.0.1:55440/knowbound",
    "sqlite:///test.db",
])
def test_wave4_rejects_foreign_database_urls(monkeypatch, url):
    monkeypatch.setenv("WAVE4_TEST_MODE", "1")
    monkeypatch.setenv("WAVE4_POSTGRES_URL", url)
    with pytest.raises(ValueError):
        postgres_url()


def test_wave4_requires_explicit_database_selection(monkeypatch):
    monkeypatch.setenv("WAVE4_TEST_MODE", "1")
    monkeypatch.delenv("WAVE4_POSTGRES_URL", raising=False)
    with pytest.raises(ValueError):
        postgres_url()


def test_wave4_browser_and_runner_use_distinct_ports(monkeypatch):
    from tests.integration.wave3_support import runner_endpoint, browser_origins
    monkeypatch.setenv("WAVE4_TEST_MODE", "1")
    assert runner_endpoint() == "http://127.0.0.1:8209"
    assert browser_origins() == "http://127.0.0.1:5219,http://localhost:5219"


def test_wave3_defaults_remain_compatible(monkeypatch):
    from tests.integration.wave3_support import runner_endpoint, browser_origins
    monkeypatch.delenv("WAVE4_TEST_MODE", raising=False)
    assert runner_endpoint() == "http://127.0.0.1:8199"
    assert browser_origins() == "http://127.0.0.1:5199,http://localhost:5199"


def test_environment_script_prepares_migrations_without_nested_python_c():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    launcher = (root / "scripts/use-delivery-test-environment.ps1").read_text(encoding="utf-8")
    source = (root / "backend/scripts/delivery_environment.py").read_text(encoding="utf-8")
    assert "python -c" not in launcher and "-c '" not in launcher
    assert "delivery_environment.py" in launcher and "migrate" in launcher
    assert "def prepare_migrations" in source
    assert "0005_memories_audit" in source


def test_initializer_accepts_only_matching_task_labels():
    from scripts.delivery_environment import validate_target
    validate_target({"com.docker.compose.project": "knowbound-wave4-test", "knowbound.task": "wave4-task11-test"}, "wave4_router")


@pytest.mark.parametrize("project,task,db", [
    ("knowbound-cj", "wave4-task11-test", "wave4_router"),
    ("knowbound-wave3-gate", "wave3-integration-gate", "wave4_router"),
    ("knowbound-wave4-test", "wave4-task11-test", "knowbound"),
    ("knowbound-wave4-test", "wave4-task11-test", "wave4_router;DROP DATABASE knowbound"),
    ("knowbound-wave4-test", "wrong", "wave4_router"),
])
def test_initializer_rejects_foreign_targets(project, task, db):
    from scripts.delivery_environment import validate_target
    with pytest.raises(ValueError):
        validate_target({"com.docker.compose.project": project, "knowbound.task": task}, db)
