import pytest
from pydantic import ValidationError

from runner.worker.protocol import (
    MAX_FILES,
    MAX_SOURCE_BYTES,
    RunnerLimits,
    RunnerPhase,
    RunnerRequest,
    RunnerResult,
    RunnerStatus,
    ToolchainInfo,
)


def request(**overrides) -> RunnerRequest:
    data = {
        "protocol_version": "2",
        "submission_id": "sub-001",
        "source_files": [{"path": "src/main.cj", "content": "main() {}"}],
        "entrypoint": "src/main.cj",
        "timeout_ms": 5_000,
    }
    data.update(overrides)
    return RunnerRequest.model_validate(data)


def test_runner_request_accepts_v2_relative_sources_and_fixed_entrypoint() -> None:
    value = request()
    assert value.protocol_version == "2"
    assert value.entrypoint == "src/main.cj"
    assert value.timeout_seconds == 5


@pytest.mark.parametrize(
    "unsafe_path",
    ["../secret.cj", "/tmp/main.cj", "C:/temp/main.cj", "C:temp/main.cj", "dir\\main.cj", "a/./main.cj"],
)
def test_runner_request_rejects_paths_outside_job_workspace(unsafe_path: str) -> None:
    with pytest.raises(ValidationError):
        request(source_files=[{"path": unsafe_path, "content": "main() {}"}], entrypoint=unsafe_path)


def test_runner_request_rejects_user_controlled_command_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        request(command=["sh", "-c", "whoami"])


def test_runner_request_rejects_non_cangjie_source_files_before_launch():
    with pytest.raises(ValidationError):
        request(
            source_files=[
                {"path": "src/main.cj", "content": "main() {}"},
                {"path": "src/payload.txt", "content": "ignored"},
            ]
        )


def test_runner_request_enforces_file_and_total_source_limits() -> None:
    with pytest.raises(ValidationError):
        request(source_files=[{"path": f"src/{i}.cj", "content": "x"} for i in range(MAX_FILES + 1)])
    with pytest.raises(ValidationError):
        request(source_files=[{"path": "main.cj", "content": "x" * (MAX_SOURCE_BYTES + 1)}], entrypoint="main.cj")


def test_runner_result_exposes_task5_stable_contract_without_private_source() -> None:
    result = RunnerResult(
        submission_id="sub-001",
        status=RunnerStatus.timed_out,
        phase=RunnerPhase.run,
        retryable=False,
        exit_code=None,
        signal=None,
        stdout="",
        stderr="execution timed out",
        diagnostics=[],
        command_summary={"compiler": "cjc", "source_count": 1, "entrypoint": "main.cj", "output_kind": "executable"},
        limits=RunnerLimits(timeout_ms=1_000),
        toolchain=ToolchainInfo(),
    )
    dumped = result.model_dump(mode="json")
    assert dumped["status"] == "timed_out"
    assert dumped["phase"] == "run"
    assert result.timed_out is True
    assert "source_files" not in dumped


def test_runner_unavailable_is_explicit_and_retryable() -> None:
    result = RunnerResult.unavailable("sub-001", "docker engine unavailable")
    assert result.status is RunnerStatus.runner_unavailable
    assert result.phase is RunnerPhase.control
    assert result.retryable is True
    assert result.exit_code is None
