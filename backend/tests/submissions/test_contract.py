from pathlib import Path
import subprocess
import sys

import yaml

from app.api.submissions import create_submissions_router


ROOT = Path(__file__).resolve().parents[3]


def test_task5_backend_imports_without_runner_implementation_package(tmp_path):
    backend = ROOT / "backend"
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(backend)!r}); "
        "import app.submissions.models, app.submissions.runner_client, "
        "app.submissions.service, app.submissions.persistence, "
        "app.diagnostics.rules, app.api.submissions"
    )

    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_task5_contract_is_mergeable_and_declares_submission_boundaries():
    contract = yaml.safe_load(
        (ROOT / "contracts/fragments/task-5-submissions.yaml").read_text(encoding="utf-8")
    )

    assert set(contract["paths"]) == {
        "/exercises/{exercise_id}/submissions",
        "/submissions/{submission_id}",
        "/submissions/{submission_id}/execution-result",
    }
    operations = [
        operation
        for path in contract["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    ]
    assert len({item["operationId"] for item in operations}) == len(operations)
    assert all(item["security"] == [{"bearerAuth": []}] for item in operations)
    assert {"401", "404", "409", "422", "503"} <= set(
        contract["paths"]["/exercises/{exercise_id}/submissions"]["post"]["responses"]
    )
    schemas = contract["components"]["schemas"]
    assert {"Role", "ErrorResponse"}.isdisjoint(schemas)
    assert "securitySchemes" not in contract["components"]
    for name in (
        "SubmissionCreateRequest",
        "SourceFileInput",
        "Submission",
        "ExecutionResult",
        "CompilerDiagnostic",
        "RuleMatch",
    ):
        assert schemas[name]["additionalProperties"] is False

    runtime_ids = {
        route.operation_id
        for route in create_submissions_router(None, None).routes
        if route.operation_id
    }
    assert runtime_ids == {item["operationId"] for item in operations}
