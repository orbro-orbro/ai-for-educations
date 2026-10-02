from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from runner.worker.executor import execute, write_source_files
from runner.worker.parser import parse_compiler_diagnostics
from runner.worker.protocol import MAX_OUTPUT_CHARS, RunnerRequest, RunnerResult, RunnerStatus, SourceFile


FIXTURES = Path(__file__).parent / "fixtures"


def request_for(source: str, *, timeout_seconds: int = 5) -> RunnerRequest:
    return RunnerRequest(
        protocol_version="2",
        submission_id="sub-runner-test",
        source_files=[SourceFile(path="main.cj", content=source)],
        entrypoint="main.cj",
        timeout_ms=timeout_seconds * 1_000,
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
    assert result.status is RunnerStatus.succeeded


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
    with pytest.raises(ValidationError):
        RunnerRequest(
            protocol_version="2",
            submission_id="drive-relative",
            source_files=[SourceFile(path="C:escape.cj", content="main() {}")],
            entrypoint="C:escape.cj",
            timeout_ms=5_000,
        )


def test_execute_returns_cjc_diagnostics_in_parser_contract() -> None:
    result = execute(request_for("main() { let value = }"))

    diagnostics = parse_compiler_diagnostics(result.stderr)
    assert result.exit_code != 0
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].code == "parse_expected_expression"
    assert diagnostics[0].file == "main.cj"
    assert diagnostics[0].start_line == 1
    assert result.status is RunnerStatus.compile_failed
    assert result.diagnostics == diagnostics


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
    assert result.status is RunnerStatus.resource_exhausted


def test_compile_diagnostics_survive_public_stderr_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    from runner.worker import executor

    diagnostic = '{"severity":"error","message":"late diagnostic","file":"main.cj","line":1,"column":1}'
    raw_stderr = ("noise\n" * 12_000) + diagnostic
    monkeypatch.setattr(
        executor,
        "run_process",
        lambda *args, **kwargs: executor.ProcessResult(1, "", raw_stderr, False),
    )

    result = execute(request_for("main() {}"))

    assert result.status is RunnerStatus.compile_failed
    assert result.stderr_truncated is True
    assert len(result.stderr) == MAX_OUTPUT_CHARS
    assert [item.message for item in result.diagnostics] == ["late diagnostic"]


def test_windows_taskkill_failure_falls_back_to_direct_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    from runner.worker import executor

    class FakeProcess:
        pid = 42
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    class FailedTaskkill:
        returncode = 1

    process = FakeProcess()
    monkeypatch.setattr(executor.os, "name", "nt")
    monkeypatch.setattr(executor.subprocess, "run", lambda *args, **kwargs: FailedTaskkill())

    executor._terminate_process_tree(process)

    assert process.killed is True
