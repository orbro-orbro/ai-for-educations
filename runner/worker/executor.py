from __future__ import annotations

import codecs
import math
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from runner.worker.protocol import MAX_OUTPUT_CHARS, RunnerRequest, RunnerResult, SourceFile


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_PROGRAM_NAME = "runner-program"
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


class _CappedText:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._parts: list[str] = []
        self._length = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def consume(self, stream: BinaryIO) -> None:
        while chunk := stream.read(8192):
            self._append(self._decoder.decode(chunk))
        self._append(self._decoder.decode(b"", final=True))

    def _append(self, text: str) -> None:
        remaining = self._limit - self._length
        if remaining <= 0:
            return
        accepted = text[:remaining]
        self._parts.append(accepted)
        self._length += len(accepted)

    @property
    def value(self) -> str:
        return "".join(self._parts)


def execute(request: RunnerRequest) -> RunnerResult:
    """Compile and run one Cangjie request in a fresh, disposable workspace."""

    sources = _validate_command(request)
    temp_root = os.environ.get("RUNNER_TEMP_ROOT")
    with tempfile.TemporaryDirectory(prefix="knowbound-runner-", dir=temp_root) as job_dir:
        workspace = Path(job_dir)
        write_source_files(workspace, request.source_files)
        deadline = time.monotonic() + request.timeout_seconds
        compiler = _compile_command(sources)
        compile_result = run_process(compiler, workspace, _remaining(deadline))
        if compile_result.timed_out or compile_result.exit_code != 0:
            return _runner_result(request, compile_result)

        executable = _compiled_program(workspace)
        run_result = run_process([os.fspath(executable)], workspace, _remaining(deadline))
        combined = ProcessResult(
            exit_code=run_result.exit_code,
            stdout=_cap(compile_result.stdout + run_result.stdout),
            stderr=_cap(compile_result.stderr + run_result.stderr),
            timed_out=run_result.timed_out,
        )
        return _runner_result(request, combined)


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
    stdout = _CappedText(MAX_OUTPUT_CHARS)
    stderr = _CappedText(MAX_OUTPUT_CHARS)
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
        process.wait()
    finally:
        for reader in readers:
            reader.join(timeout=5)

    return ProcessResult(
        exit_code=None if timed_out else process.returncode,
        stdout=stdout.value,
        stderr=stderr.value,
        timed_out=timed_out,
    )


def _job_environment(cwd: Path) -> dict[str, str]:
    environment = os.environ.copy()
    workspace = os.fspath(cwd)
    environment.update({"TMPDIR": workspace, "TMP": workspace, "TEMP": workspace})
    return environment


def _validate_command(request: RunnerRequest) -> tuple[str, ...]:
    command = request.command
    if not command or command[0] != "cjc" or len(command) < 2:
        raise CommandRejected("only cjc source compilation is allowed")

    requested_sources: list[str] = []
    available_sources = {source.path for source in request.source_files}
    for argument in command[1:]:
        try:
            path = _safe_relative_path(argument)
        except ValueError as exc:
            raise CommandRejected(str(exc)) from exc
        normalized = path.as_posix()
        if path.suffix != ".cj" or normalized not in available_sources:
            raise CommandRejected("cjc arguments must name submitted .cj files")
        requested_sources.append(normalized)
    return tuple(requested_sources)


def _safe_relative_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or candidate.is_absolute()
        or normalized.startswith("//")
        or _WINDOWS_DRIVE.match(normalized)
        or ".." in candidate.parts
        or "." in candidate.parts
    ):
        raise ValueError("source path must stay inside the job workspace")
    return candidate


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


def _runner_result(request: RunnerRequest, result: ProcessResult) -> RunnerResult:
    return RunnerResult(
        submission_id=request.submission_id,
        exit_code=result.exit_code,
        stdout=_cap(result.stdout),
        stderr=_cap(result.stderr),
        timed_out=result.timed_out,
        resource_limited=not result.timed_out and _is_resource_limit_exit(result.exit_code),
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
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    else:
        process.kill()


def _set_process_limits(timeout_seconds: float):
    def apply_limits() -> None:
        import resource

        cpu_seconds = max(1, math.ceil(timeout_seconds))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply_limits
