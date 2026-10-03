from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from app.submissions.runner_contract import (
    CompilerDiagnostic,
    CommandSummary,
    RunnerLimits,
    RunnerPhase,
    RunnerResult,
    RunnerStatus,
    SourceFile,
    ToolchainInfo,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class SubmissionStatus(StrEnum):
    received = "received"
    executing = "executing"
    executed = "executed"
    execution_unavailable = "execution_unavailable"
    diagnosing = "diagnosing"
    diagnosed = "diagnosed"
    needs_review = "needs_review"


_ALLOWED_TRANSITIONS = {
    SubmissionStatus.received: frozenset({SubmissionStatus.executing}),
    SubmissionStatus.executing: frozenset(
        {SubmissionStatus.executed, SubmissionStatus.execution_unavailable}
    ),
    SubmissionStatus.execution_unavailable: frozenset({SubmissionStatus.executing}),
    SubmissionStatus.executed: frozenset({SubmissionStatus.diagnosing}),
    SubmissionStatus.diagnosing: frozenset(
        {SubmissionStatus.diagnosed, SubmissionStatus.needs_review}
    ),
    SubmissionStatus.needs_review: frozenset({SubmissionStatus.diagnosing}),
    SubmissionStatus.diagnosed: frozenset(),
}


class InvalidSubmissionTransition(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Submission:
    submission_id: str
    course_id: str
    exercise_id: str
    owner_user_id: str
    source_files: tuple[SourceFile, ...]
    entrypoint: str
    is_formal: bool
    status: SubmissionStatus
    created_at: datetime
    request_id: str

    def transition_to(self, status: SubmissionStatus) -> "Submission":
        status = SubmissionStatus(status)
        if status not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidSubmissionTransition(f"{self.status.value} -> {status.value}")
        return replace(self, status=status)


@dataclass(frozen=True, slots=True)
class SubmissionTransition:
    submission_id: str
    from_status: SubmissionStatus | None
    to_status: SubmissionStatus
    changed_at: datetime
    request_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    submission_id: str
    course_id: str
    protocol_version: str
    status: RunnerStatus
    phase: RunnerPhase
    retryable: bool
    exit_code: int | None
    signal: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    diagnostics: tuple[CompilerDiagnostic, ...]
    command_summary: CommandSummary
    limits: RunnerLimits
    toolchain: ToolchainInfo
    created_at: datetime
    request_id: str

    @classmethod
    def from_runner(
        cls,
        *,
        course_id: str,
        result: RunnerResult,
        request_id: str,
    ) -> "ExecutionResult":
        return cls(
            submission_id=result.submission_id,
            course_id=course_id,
            protocol_version=result.protocol_version,
            status=result.status,
            phase=result.phase,
            retryable=result.retryable,
            exit_code=result.exit_code,
            signal=result.signal,
            stdout=result.stdout,
            stderr=result.stderr,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            diagnostics=tuple(result.diagnostics),
            command_summary=result.command_summary,
            limits=result.limits,
            toolchain=result.toolchain,
            created_at=utc_now(),
            request_id=request_id,
        )


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
