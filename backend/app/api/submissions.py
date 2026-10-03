from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import Authenticator
from app.api.errors import error_response
from app.diagnostics.rules import RuleMatch
from app.submissions.models import Submission, SubmissionStatus
from app.submissions.repository import SubmissionPersistenceError
from app.submissions.service import (
    ExecutionResultNotAvailable,
    InvalidSubmissionInput,
    SubmissionService,
)
from app.submissions.runner_contract import (
    CommandSummary,
    CompilerDiagnostic,
    RunnerLimits,
    RunnerPhase,
    RunnerStatus,
    ToolchainInfo,
)


class SourceFileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class SourceFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=262_144)


class SubmissionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_files: list[SourceFileInput] = Field(min_length=1, max_length=32)
    entrypoint: str = Field(min_length=1, max_length=255)
    is_formal: bool = True


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: str
    course_id: str
    exercise_id: str
    owner_user_id: str
    source_files: list[SourceFileResponse]
    entrypoint: str
    is_formal: bool
    status: SubmissionStatus
    created_at: datetime
    request_id: str


class RuleMatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    misconception_id: str
    root_concept_id: str
    related_concept_ids: list[str]
    diagnostic_indices: list[int]
    evidence_kind: str
    evidence_summary: str
    source_references: list[str]
    match_strength: str


class ExecutionResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: str
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
    diagnostics: list[CompilerDiagnostic]
    command_summary: CommandSummary
    limits: RunnerLimits
    toolchain: ToolchainInfo
    created_at: datetime
    request_id: str
    rule_matches: list[RuleMatchResponse]


def _submission_response(submission: Submission, request_id: str) -> SubmissionResponse:
    return SubmissionResponse(
        submission_id=submission.submission_id,
        course_id=submission.course_id,
        exercise_id=submission.exercise_id,
        owner_user_id=submission.owner_user_id,
        source_files=[SourceFileResponse.model_validate(item.model_dump()) for item in submission.source_files],
        entrypoint=submission.entrypoint,
        is_formal=submission.is_formal,
        status=submission.status,
        created_at=submission.created_at,
        request_id=request_id,
    )


def _rule_match_response(match: RuleMatch) -> RuleMatchResponse:
    return RuleMatchResponse(
        misconception_id=match.misconception_id,
        root_concept_id=match.root_concept_id,
        related_concept_ids=list(match.related_concept_ids),
        diagnostic_indices=list(match.diagnostic_indices),
        evidence_kind=match.evidence_kind,
        evidence_summary=match.evidence_summary,
        source_references=list(match.source_references),
        match_strength=match.match_strength,
    )


def _persistence_unavailable(request: Request):
    return error_response(
        request,
        503,
        "PERSISTENCE_UNAVAILABLE",
        "Submission storage is temporarily unavailable.",
    )


def create_submissions_router(
    service: SubmissionService,
    authenticator: Authenticator,
) -> APIRouter:
    router = APIRouter(tags=["submissions"])

    @router.post(
        "/exercises/{exercise_id}/submissions",
        response_model=SubmissionResponse,
        status_code=201,
        operation_id="createExerciseSubmission",
    )
    def create_submission(
        exercise_id: Annotated[str, Path(min_length=1, max_length=128)],
        payload: SubmissionCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = authenticator.authenticate_header(authorization)
        try:
            submission = service.submit(
                actor=actor,
                exercise_id=exercise_id,
                source_files=[item.model_dump() for item in payload.source_files],
                entrypoint=payload.entrypoint,
                is_formal=payload.is_formal,
                request_id=str(request.state.request_id),
            )
        except InvalidSubmissionInput:
            return error_response(
                request,
                422,
                "VALIDATION_ERROR",
                "Request validation failed.",
            )
        except SubmissionPersistenceError:
            return _persistence_unavailable(request)
        return _submission_response(submission, str(request.state.request_id))

    @router.get(
        "/submissions/{submission_id}",
        response_model=SubmissionResponse,
        operation_id="getSubmission",
    )
    def get_submission(
        submission_id: Annotated[str, Path(min_length=1, max_length=128)],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = authenticator.authenticate_header(authorization)
        try:
            return _submission_response(
                service.get_submission(actor, submission_id),
                str(request.state.request_id),
            )
        except SubmissionPersistenceError:
            return _persistence_unavailable(request)

    @router.get(
        "/submissions/{submission_id}/execution-result",
        response_model=ExecutionResultResponse,
        operation_id="getSubmissionExecutionResult",
    )
    def get_execution_result(
        submission_id: Annotated[str, Path(min_length=1, max_length=128)],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = authenticator.authenticate_header(authorization)
        try:
            result, matches = service.get_execution_result(actor, submission_id)
        except ExecutionResultNotAvailable:
            return error_response(
                request,
                409,
                "EXECUTION_RESULT_NOT_AVAILABLE",
                "Execution result is not available.",
            )
        except SubmissionPersistenceError:
            return _persistence_unavailable(request)
        return ExecutionResultResponse(
            submission_id=result.submission_id,
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
            diagnostics=list(result.diagnostics),
            command_summary=result.command_summary,
            limits=result.limits,
            toolchain=result.toolchain,
            created_at=result.created_at,
            request_id=str(request.state.request_id),
            rule_matches=[_rule_match_response(item) for item in matches],
        )

    return router
