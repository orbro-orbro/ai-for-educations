from __future__ import annotations

from app.diagnostics.persistence import SqlDiagnosticRepository
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.main import create_app


TASK6_ROUTES = {
    ("/submissions/{submission_id}/diagnosis", "GET"),
    ("/diagnoses/{diagnosis_id}/hints/next", "POST"),
    ("/diagnoses/{diagnosis_id}/explanation-check", "POST"),
}


def test_composed_application_mounts_task6_and_wires_shared_services() -> None:
    application = create_app()

    assert TASK6_ROUTES <= {
        (path, method.upper())
        for path, item in application.openapi()["paths"].items()
        for method in item
    }
    assert isinstance(
        application.state.diagnostic_repository, InMemoryDiagnosticRepository
    )
    assert application.state.diagnosis_service is not None
    assert application.state.hint_service is not None


def test_configured_database_uses_registered_sql_diagnostic_repository(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'gate.db').as_posix()}")

    application = create_app()

    assert isinstance(application.state.diagnostic_repository, SqlDiagnosticRepository)

