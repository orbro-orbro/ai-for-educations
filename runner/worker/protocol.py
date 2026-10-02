from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from runner.worker.parser import CompilerDiagnostic


PROTOCOL_VERSION = "2"
MAX_OUTPUT_CHARS = 64 * 1024
MAX_FILES = 32
MAX_FILE_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_PATH_BYTES = 255
PID_LIMIT = 64
WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class _ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def safe_source_path(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise ValueError(f"source path exceeds {MAX_PATH_BYTES} UTF-8 bytes")
    if "\\" in value:
        raise ValueError("source path must use POSIX separators")
    candidate = PurePosixPath(value)
    raw_parts = value.split("/")
    if (
        not value
        or "\x00" in value
        or candidate.is_absolute()
        or value.startswith("//")
        or WINDOWS_DRIVE_PREFIX.match(value)
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise ValueError("source path must be relative to the job workspace")
    return candidate.as_posix()


class SourceFile(_ProtocolModel):
    path: str = Field(max_length=MAX_PATH_BYTES)
    content: str

    @field_validator("path")
    @classmethod
    def path_must_stay_inside_job_workspace(cls, value: str) -> str:
        return safe_source_path(value)

    @field_validator("content")
    @classmethod
    def content_must_fit_file_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"source file exceeds {MAX_FILE_BYTES} bytes")
        return value


class RunnerRequest(_ProtocolModel):
    protocol_version: Literal["2"] = PROTOCOL_VERSION
    submission_id: str = Field(min_length=1, max_length=128)
    source_files: list[SourceFile] = Field(min_length=1, max_length=MAX_FILES)
    entrypoint: str = Field(max_length=MAX_PATH_BYTES)
    timeout_ms: int = Field(ge=100, le=30_000)

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint_path(cls, value: str) -> str:
        value = safe_source_path(value)
        if not value.endswith(".cj"):
            raise ValueError("entrypoint must be a .cj source file")
        return value

    @model_validator(mode="after")
    def validate_sources(self) -> RunnerRequest:
        paths = [source.path for source in self.source_files]
        if len(paths) != len(set(paths)):
            raise ValueError("source paths must be unique")
        if any(not path.endswith(".cj") for path in paths):
            raise ValueError("all submitted source files must use the .cj suffix")
        if self.entrypoint not in set(paths):
            raise ValueError("entrypoint must name a submitted source file")
        total = sum(len(source.content.encode("utf-8")) for source in self.source_files)
        if total > MAX_SOURCE_BYTES:
            raise ValueError(f"submitted source exceeds {MAX_SOURCE_BYTES} bytes")
        return self

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000


class RunnerStatus(StrEnum):
    succeeded = "succeeded"
    compile_failed = "compile_failed"
    run_failed = "run_failed"
    timed_out = "timed_out"
    resource_exhausted = "resource_exhausted"
    runner_unavailable = "runner_unavailable"
    internal_error = "internal_error"


class RunnerPhase(StrEnum):
    compile = "compile"
    run = "run"
    control = "control"


class CommandSummary(_ProtocolModel):
    compiler: Literal["cjc"] = "cjc"
    source_count: int = Field(ge=0, le=MAX_FILES)
    entrypoint: str = Field(max_length=MAX_PATH_BYTES)
    output_kind: Literal["executable"] = "executable"


class RunnerLimits(_ProtocolModel):
    timeout_ms: int = Field(ge=0, le=30_000)
    max_output_chars: int = MAX_OUTPUT_CHARS
    max_files: int = MAX_FILES
    max_source_bytes: int = MAX_SOURCE_BYTES
    pids: int = PID_LIMIT
    memory_bytes: int = 512 * 1024 * 1024
    cpu_cores: float = 1.0


class ToolchainInfo(_ProtocolModel):
    cjc: str = "1.2.0"
    cjpm: str = "1.2.0"
    backend: Literal["cjnative"] = "cjnative"


class RunnerResult(_ProtocolModel):
    protocol_version: Literal["2"] = PROTOCOL_VERSION
    submission_id: str = Field(min_length=1)
    status: RunnerStatus
    phase: RunnerPhase
    retryable: bool
    exit_code: int | None
    signal: int | None
    stdout: str = Field(max_length=MAX_OUTPUT_CHARS)
    stderr: str = Field(max_length=MAX_OUTPUT_CHARS)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    diagnostics: list[CompilerDiagnostic]
    command_summary: CommandSummary
    limits: RunnerLimits
    toolchain: ToolchainInfo

    @property
    def timed_out(self) -> bool:
        return self.status is RunnerStatus.timed_out

    @property
    def resource_limited(self) -> bool:
        return self.status is RunnerStatus.resource_exhausted

    @classmethod
    def unavailable(cls, submission_id: str, message: str) -> RunnerResult:
        return cls(
            submission_id=submission_id,
            status=RunnerStatus.runner_unavailable,
            phase=RunnerPhase.control,
            retryable=True,
            exit_code=None,
            signal=None,
            stdout="",
            stderr=message[:MAX_OUTPUT_CHARS],
            diagnostics=[],
            command_summary=CommandSummary(source_count=0, entrypoint=""),
            limits=RunnerLimits(timeout_ms=0),
            toolchain=ToolchainInfo(),
        )
