from __future__ import annotations

import codecs
import math
import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from runner.worker.parser import parse_compiler_diagnostics
from runner.worker.protocol import (
    MAX_OUTPUT_CHARS,
    PID_LIMIT,
    CommandSummary,
    RunnerLimits,
    RunnerPhase,
    RunnerRequest,
    RunnerResult,
    RunnerStatus,
    SourceFile,
    ToolchainInfo,
    safe_source_path,
)


_PROGRAM_NAME = "runner-program"
_MAX_CAPTURE_CHARS = 1024 * 1024
_RESOURCE_EXIT_CODES = {137, 152, 153}
_RESOURCE_SIGNALS = {
    value
    for name in ("SIGKILL", "SIGXCPU", "SIGXFSZ")
    if (value := getattr(signal, name, None)) is not None
}


class CommandRejected(ValueError):
    """Raised before execution when a command is outside the runner allowlist."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class _CappedText:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._parts: list[str] = []
        self._length = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._truncated = False

    def consume(self, stream: BinaryIO) -> None:
        while chunk := stream.read(8192):
            self._append(self._decoder.decode(chunk))
        self._append(self._decoder.decode(b"", final=True))

    def _append(self, text: str) -> None:
        remaining = self._limit - self._length
        if remaining <= 0:
            if text:
                self._truncated = True
            return
        accepted = text[:remaining]
        self._parts.append(accepted)
        self._length += len(accepted)
        if len(accepted) < len(text):
            self._truncated = True

    @property
    def value(self) -> str:
        return "".join(self._parts)

    @property
    def truncated(self) -> bool:
        return self._truncated


def execute(request: RunnerRequest) -> RunnerResult:
    """Compile and run one Cangjie request in a fresh, disposable workspace."""

    sources = _validated_sources(request)
    temp_root = os.environ.get("RUNNER_TEMP_ROOT")
    with tempfile.TemporaryDirectory(prefix="knowbound-runner-", dir=temp_root) as job_dir:
        workspace = Path(job_dir)
        write_source_files(workspace, request.source_files)
        deadline = time.monotonic() + request.timeout_seconds
        compiler = _compile_command(sources)
        compile_result = run_process(compiler, workspace, _remaining(deadline))
        if compile_result.timed_out or compile_result.exit_code != 0:
            return _runner_result(request, compile_result, RunnerPhase.compile, compile_result.stderr)

        try:
            executable = _compiled_program(workspace)
        except RuntimeError as exc:
            return _internal_error(request, RunnerPhase.compile, str(exc), compile_result)
        run_result = run_process([os.fspath(executable)], workspace, _remaining(deadline))
        combined = ProcessResult(
            exit_code=run_result.exit_code,
            stdout=compile_result.stdout + run_result.stdout,
            stderr=compile_result.stderr + run_result.stderr,
            timed_out=run_result.timed_out,
            stdout_truncated=compile_result.stdout_truncated or run_result.stdout_truncated,
            stderr_truncated=compile_result.stderr_truncated or run_result.stderr_truncated,
        )
        return _runner_result(request, combined, RunnerPhase.run, compile_result.stderr)


def write_source_files(workspace: Path, source_files: Iterable[SourceFile]) -> None:
    """Write files without following links or permitting workspace traversal."""

    root = workspace.resolve(strict=True)
    for source in source_files:
        relative = _safe_relative_path(source.path)
        target = workspace.joinpath(*relative.parts)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        _assert_no_symlink(root, parent)
        if target.is_symlink():
            raise ValueError("source path must not traverse a symlink")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError as exc:
            raise ValueError("source paths must be unique regular files") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source.content)


def run_process(args: list[str], cwd: Path, timeout_seconds: float) -> ProcessResult:
    """Run an argument array directly and drain output into bounded buffers."""

    if timeout_seconds <= 0:
        return ProcessResult(None, "", "execution timed out", True)

    process_kwargs: dict[str, object] = {
        "cwd": cwd,
        "env": _job_environment(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    if os.name == "posix":
        process_kwargs["start_new_session"] = True
        process_kwargs["preexec_fn"] = _set_process_limits(timeout_seconds)
    elif os.name == "nt":
        process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(args, **process_kwargs)
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = _CappedText(_MAX_CAPTURE_CHARS)
    stderr = _CappedText(_MAX_CAPTURE_CHARS)
    readers = [
        threading.Thread(target=stdout.consume, args=(process.stdout,), daemon=True),
        threading.Thread(target=stderr.consume, args=(process.stderr,), daemon=True),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    finally:
        for reader in readers:
            reader.join(timeout=5)

    return ProcessResult(
        exit_code=None if timed_out else process.returncode,
        stdout=stdout.value,
        stderr=stderr.value,
        timed_out=timed_out,
        stdout_truncated=stdout.truncated,
        stderr_truncated=stderr.truncated,
    )


def _job_environment(cwd: Path) -> dict[str, str]:
    environment = os.environ.copy()
    workspace = os.fspath(cwd)
    environment.update({"TMPDIR": workspace, "TMP": workspace, "TEMP": workspace})
    return environment


def _validated_sources(request: RunnerRequest) -> tuple[str, ...]:
    available = {source.path for source in request.source_files}
    if request.entrypoint not in available:
        raise CommandRejected("entrypoint must name a submitted source file")
    if any(not path.endswith(".cj") for path in available):
        raise CommandRejected("all submitted sources must be .cj files")
    return (request.entrypoint, *sorted(available - {request.entrypoint}))


def _safe_relative_path(value: str) -> PurePosixPath:
    return PurePosixPath(safe_source_path(value))


def _assert_no_symlink(root: Path, parent: Path) -> None:
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("source path escaped the job workspace") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("source path must not traverse a symlink")
    if parent.resolve(strict=True) != parent.absolute():
        raise ValueError("source path must not traverse a symlink")


def _compile_command(sources: tuple[str, ...]) -> list[str]:
    return [
        "cjc",
        *sources,
        "--diagnostic-format=json",
        "--output-type=exe",
        "-o",
        _PROGRAM_NAME,
    ]


def _compiled_program(workspace: Path) -> Path:
    candidates = [workspace / _PROGRAM_NAME, workspace / f"{_PROGRAM_NAME}.exe"]
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise RuntimeError("cjc succeeded without producing the expected executable")


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _runner_result(
    request: RunnerRequest,
    result: ProcessResult,
    phase: RunnerPhase,
    compiler_stderr: str,
) -> RunnerResult:
    resource_limited = not result.timed_out and _is_resource_limit_exit(result.exit_code)
    if result.timed_out:
        status = RunnerStatus.timed_out
    elif resource_limited:
        status = RunnerStatus.resource_exhausted
    elif result.exit_code == 0:
        status = RunnerStatus.succeeded
    elif phase is RunnerPhase.compile:
        status = RunnerStatus.compile_failed
    else:
        status = RunnerStatus.run_failed
    stdout = _cap(result.stdout)
    stderr = _cap(result.stderr)
    return RunnerResult(
        submission_id=request.submission_id,
        status=status,
        phase=phase,
        retryable=False,
        exit_code=result.exit_code,
        signal=(-result.exit_code if result.exit_code is not None and result.exit_code < 0 else None),
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=result.stdout_truncated or len(result.stdout) > len(stdout),
        stderr_truncated=result.stderr_truncated or len(result.stderr) > len(stderr),
        diagnostics=parse_compiler_diagnostics(compiler_stderr),
        command_summary=CommandSummary(
            source_count=len(request.source_files),
            entrypoint=request.entrypoint,
        ),
        limits=RunnerLimits(timeout_ms=request.timeout_ms),
        toolchain=ToolchainInfo(),
    )


def _internal_error(
    request: RunnerRequest,
    phase: RunnerPhase,
    message: str,
    partial: ProcessResult,
) -> RunnerResult:
    return RunnerResult(
        submission_id=request.submission_id,
        status=RunnerStatus.internal_error,
        phase=phase,
        retryable=False,
        exit_code=partial.exit_code,
        signal=None,
        stdout=_cap(partial.stdout),
        stderr=_cap(message),
        diagnostics=parse_compiler_diagnostics(partial.stderr),
        command_summary=CommandSummary(source_count=len(request.source_files), entrypoint=request.entrypoint),
        limits=RunnerLimits(timeout_ms=request.timeout_ms),
        toolchain=ToolchainInfo(),
    )


def _cap(value: str) -> str:
    return value[:MAX_OUTPUT_CHARS]


def _is_resource_limit_exit(exit_code: int | None) -> bool:
    if exit_code is None:
        return False
    if exit_code in _RESOURCE_EXIT_CODES:
        return True
    if exit_code < 0:
        return -exit_code in _RESOURCE_SIGNALS
    return False


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=5,
            )
            if completed.returncode != 0 and process.poll() is None:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
    else:
        process.kill()


def _set_process_limits(timeout_seconds: float):
    def apply_limits() -> None:
        import resource

        cpu_seconds = max(1, math.ceil(timeout_seconds))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_NPROC, (PID_LIMIT, PID_LIMIT))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply_limits
