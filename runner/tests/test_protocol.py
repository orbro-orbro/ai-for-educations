import pytest
from pydantic import ValidationError

from runner.worker.protocol import RunnerRequest, RunnerResult, SourceFile


def test_runner_request_accepts_relative_source_paths() -> None:
    request = RunnerRequest(
        submission_id="sub-001",
        source_files=[SourceFile(path="src/main.cj", content="main() {}")],
        command=["cjc", "src/main.cj"],
        timeout_seconds=5,
    )

    assert request.source_files[0].path == "src/main.cj"
    assert request.timeout_seconds == 5


@pytest.mark.parametrize("unsafe_path", ["../secret.cj", "/tmp/main.cj", "C:/temp/main.cj"])
def test_runner_request_rejects_paths_outside_job_workspace(unsafe_path: str) -> None:
    with pytest.raises(ValidationError):
        RunnerRequest(
            submission_id="sub-001",
            source_files=[SourceFile(path=unsafe_path, content="main() {}")],
            command=["cjc", "main.cj"],
            timeout_seconds=5,
        )


def test_runner_result_tracks_limits_without_private_source() -> None:
    result = RunnerResult(
        submission_id="sub-001",
        exit_code=None,
        stdout="",
        stderr="execution timed out",
        timed_out=True,
        resource_limited=False,
    )

    assert result.timed_out is True
    assert "source_files" not in result.model_dump()
