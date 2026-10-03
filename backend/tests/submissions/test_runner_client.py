import httpx
import pytest
from pathlib import Path

from app.submissions.runner_client import RunnerClient, RunnerUnavailable
from app.submissions.runner_contract import RunnerRequest, RunnerStatus


def runner_payload(submission_id="sub-1", status="succeeded"):
    return {
        "protocol_version": "2",
        "submission_id": submission_id,
        "status": status,
        "phase": "run",
        "retryable": False,
        "exit_code": 0,
        "signal": None,
        "stdout": "ok",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "diagnostics": [],
        "command_summary": {
            "compiler": "cjc",
            "source_count": 1,
            "entrypoint": "main.cj",
            "output_kind": "executable",
        },
        "limits": {
            "timeout_ms": 5000,
            "max_output_chars": 65536,
            "max_files": 32,
            "max_source_bytes": 1048576,
            "pids": 64,
            "memory_bytes": 536870912,
            "cpu_cores": 1.0,
        },
        "toolchain": {"cjc": "1.2.0", "cjpm": "1.2.0", "backend": "cjnative"},
    }


def request():
    return RunnerRequest(
        submission_id="sub-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        timeout_ms=5000,
    )


def test_runner_client_serializes_v2_request_and_validates_success_response():
    observed = {}

    def handler(http_request: httpx.Request):
        observed["method"] = http_request.method
        observed["path"] = http_request.url.path
        observed["body"] = http_request.read()
        return httpx.Response(200, json=runner_payload())

    client = RunnerClient(
        "http://runner.internal",
        transport=httpx.MockTransport(handler),
    )

    result = client.execute(request())

    assert result.status is RunnerStatus.succeeded
    assert observed["method"] == "POST"
    assert observed["path"] == "/v2/execute"
    assert b'"protocol_version":"2"' in observed["body"]
    assert b'"source_files":[{"path":"main.cj","content":"main() {}"}]' in observed["body"]


def test_runner_client_rejects_503_that_is_not_explicitly_retryable_unavailable():
    payload = runner_payload(status="succeeded")
    transport = httpx.MockTransport(lambda _request: httpx.Response(503, json=payload))

    with pytest.raises(RunnerUnavailable, match="invalid 503 response"):
        RunnerClient("http://runner.internal", transport=transport).execute(request())


def test_runner_client_accepts_only_retryable_unavailable_503():
    payload = runner_payload(status="runner_unavailable") | {
        "phase": "control",
        "retryable": True,
        "exit_code": None,
        "stdout": "",
        "stderr": "runner unavailable",
        "command_summary": {
            "compiler": "cjc",
            "source_count": 0,
            "entrypoint": "",
            "output_kind": "executable",
        },
        "limits": {"timeout_ms": 0},
    }
    transport = httpx.MockTransport(lambda _request: httpx.Response(503, json=payload))

    result = RunnerClient("http://runner.internal", transport=transport).execute(request())

    assert result.status is RunnerStatus.runner_unavailable
    assert result.retryable is True


@pytest.mark.parametrize(
    "handler",
    [
        lambda _request: httpx.Response(200, content=b"not-json"),
        lambda _request: httpx.Response(
            200, json=runner_payload() | {"protocol_version": "1"}
        ),
        lambda _request: httpx.Response(200, json=runner_payload("other-submission")),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline", request=request)),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)),
    ],
)
def test_runner_client_maps_boundary_failures_to_source_safe_unavailable(handler):
    transport = httpx.MockTransport(handler)

    with pytest.raises(RunnerUnavailable) as caught:
        RunnerClient("http://runner.internal", transport=transport).execute(request())

    assert "main()" not in str(caught.value)
    assert "runner.internal" not in str(caught.value)


def test_httpx_is_a_production_dependency_for_runner_client():
    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    production = pyproject.split("[project.optional-dependencies]", 1)[0]

    assert '"httpx>=0.28,<1"' in production
