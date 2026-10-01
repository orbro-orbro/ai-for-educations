import re
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator

MAX_OUTPUT_CHARS = 64 * 1024
WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:/")


class SourceFile(BaseModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def path_must_stay_inside_job_workspace(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if (
            not normalized
            or candidate.is_absolute()
            or WINDOWS_DRIVE_PREFIX.match(normalized)
            or ".." in candidate.parts
        ):
            raise ValueError("source path must be relative to the job workspace")
        return candidate.as_posix()


class RunnerRequest(BaseModel):
    submission_id: str = Field(min_length=1)
    source_files: list[SourceFile] = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(gt=0, le=30)


class RunnerResult(BaseModel):
    submission_id: str = Field(min_length=1)
    exit_code: int | None
    stdout: str = Field(max_length=MAX_OUTPUT_CHARS)
    stderr: str = Field(max_length=MAX_OUTPUT_CHARS)
    timed_out: bool = False
    resource_limited: bool = False
