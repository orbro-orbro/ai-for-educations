"""Backend-owned DTOs for the public Runner v2 HTTP contract.

These models mirror ``contracts/runner-openapi.yaml`` without importing the
Runner controller or worker implementation package.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROTOCOL_VERSION = "2"
MAX_OUTPUT_CHARS = 64 * 1024
MAX_FILES = 32
MAX_FILE_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_PATH_BYTES = 255
PID_LIMIT = 64
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _safe_source_path(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise ValueError(f"source path exceeds {MAX_PATH_BYTES} UTF-8 bytes")
    candidate = PurePosixPath(value)
    parts = value.split("/")
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or candidate.is_absolute()
        or value.startswith("//")
        or _WINDOWS_DRIVE_PREFIX.match(value)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("source path must be relative to the job workspace")
    return candidate.as_posix()


class SourceFile(_ContractModel):
    path: str = Field(max_length=MAX_PATH_BYTES)
    content: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _safe_source_path(value)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"source file exceeds {MAX_FILE_BYTES} bytes")
        return value


class RunnerRequest(_ContractModel):
    protocol_version: Literal["2"] = PROTOCOL_VERSION
    submission_id: str = Field(min_length=1, max_length=128)
    source_files: list[SourceFile] = Field(min_length=1, max_length=MAX_FILES)
    entrypoint: str = Field(max_length=MAX_PATH_BYTES)
    timeout_ms: int = Field(ge=100, le=30_000)

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        value = _safe_source_path(value)
        if not value.endswith(".cj"):
            raise ValueError("entrypoint must be a .cj source file")
        return value

    @model_validator(mode="after")
    def validate_sources(self) -> "RunnerRequest":
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


class CompilerDiagnostic(_ContractModel):
    severity: str
    message: str
    code: str | None
    file: str | None
    start_line: int | None
    start_column: int | None
    end_line: int | None
    end_column: int | None


class CommandSummary(_ContractModel):
    compiler: Literal["cjc"] = "cjc"
    source_count: int = Field(ge=0, le=MAX_FILES)
    entrypoint: str = Field(max_length=MAX_PATH_BYTES)
    output_kind: Literal["executable"] = "executable"


class RunnerLimits(_ContractModel):
    timeout_ms: int = Field(ge=0, le=30_000)
    max_output_chars: int = MAX_OUTPUT_CHARS
    max_files: int = MAX_FILES
    max_source_bytes: int = MAX_SOURCE_BYTES
    pids: int = PID_LIMIT
    memory_bytes: int = 512 * 1024 * 1024
    cpu_cores: float = 1.0


class ToolchainInfo(_ContractModel):
    cjc: str = "1.2.0"
    cjpm: str = "1.2.0"
    backend: Literal["cjnative"] = "cjnative"


class RunnerResult(_ContractModel):
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
