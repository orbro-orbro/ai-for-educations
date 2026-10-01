from __future__ import annotations

import os
from pathlib import Path

import pytest

from runner.worker.executor import CommandRejected, execute, write_source_files
from runner.worker.parser import parse_compiler_diagnostics
from runner.worker.protocol import MAX_OUTPUT_CHARS, RunnerRequest, RunnerResult, SourceFile


FIXTURES = Path(__file__).parent / "fixtures"


def request_for(source: str, *, timeout_seconds: int = 5) -> RunnerRequest:
    return RunnerRequest(
        submission_id="sub-runner-test",
        source_files=[SourceFile(path="main.cj", content=source)],
        command=["cjc", "main.cj"],
        timeout_seconds=timeout_seconds,
    )


def execute_or_skip_windows_app_control(request: RunnerRequest) -> RunnerResult:
    try:
        return execute(request)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 4551:
            pytest.skip("Windows application control blocks temporary executables")
        raise


def test_execute_compiles_and_runs_minimal_cangjie_program() -> None:
    result = execute_or_skip_windows_app_control(
        request_for((FIXTURES / "hello_world.cj").read_text(encoding="utf-8"))
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello from cangjie"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.resource_limited is False


def test_execute_terminates_infinite_loop_at_request_timeout() -> None:
    result = execute_or_skip_windows_app_control(
        request_for(
            (FIXTURES / "infinite_loop.cj").read_text(encoding="utf-8"),
            timeout_seconds=1,
        )
    )

    assert result.exit_code is None
    assert result.timed_out is True
    assert result.resource_limited is False


@pytest.mark.parametrize(
    "command",
    [
        ["cjc", "main.cj;touch", "escaped"],
        ["cjc", "main.cj", "&&", "whoami"],
        ["cmd.exe", "/c", "whoami"],
        ["sh", "-c", "whoami"],
        ["cjc", "-o", "outside", "main.cj"],
    ],
)
def test_execute_rejects_non_allowlisted_commands(command: list[str], tmp_path: Path) -> None:
    request = request_for((FIXTURES / "hello_world.cj").read_text(encoding="utf-8"))
    unsafe_request = request.model_copy(update={"command": command})

    with pytest.raises(CommandRejected):
        execute(unsafe_request)

    assert list(tmp_path.iterdir()) == []


def test_execute_caps_excessive_output() -> None:
    source = """main() {
    while (true) {
        println("0123456789abcdef0123456789abcdef")
    }
}
"""
    result = execute_or_skip_windows_app_control(request_for(source, timeout_seconds=1))

    assert result.timed_out is True
    assert len(result.stdout) == MAX_OUTPUT_CHARS


def test_execute_rejects_windows_drive_relative_source_before_writing() -> None:
    request = RunnerRequest(
        submission_id="drive-relative",
        source_files=[SourceFile(path="C:escape.cj", content="main() {}")],
        command=["cjc", "C:escape.cj"],
        timeout_seconds=5,
    )

    with pytest.raises(CommandRejected):
        execute(request)


def test_execute_returns_cjc_diagnostics_in_parser_contract() -> None:
    result = execute(request_for("main() { let value = }"))

    diagnostics = parse_compiler_diagnostics(result.stderr)
    assert result.exit_code != 0
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].code == "parse_expected_expression"
    assert diagnostics[0].file == "main.cj"
    assert diagnostics[0].start_line == 1


def test_write_source_files_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ValueError, match="symlink"):
        write_source_files(
            workspace,
            [SourceFile(path="linked/escape.cj", content="main() {}")],
        )

    assert not (outside / "escape.cj").exists()


def test_execute_removes_job_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RUNNER_TEMP_ROOT", os.fspath(tmp_path))

    result = execute_or_skip_windows_app_control(
        request_for((FIXTURES / "hello_world.cj").read_text(encoding="utf-8"))
    )

    assert result.exit_code == 0
    assert list(tmp_path.iterdir()) == []


def test_resource_limit_exit_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from runner.worker import executor

    monkeypatch.setattr(executor, "run_process", lambda *args, **kwargs: executor.ProcessResult(137, "", "", False))

    result = execute(request_for((FIXTURES / "hello_world.cj").read_text(encoding="utf-8")))

    assert result.exit_code == 137
    assert result.resource_limited is True
