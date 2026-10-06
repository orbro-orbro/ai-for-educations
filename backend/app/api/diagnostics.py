from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import Authenticator
from app.api.errors import ErrorResponse, error_response
from app.auth.models import Actor
from app.diagnostics.hints import HintLadderService, HintLevelExhausted
from app.diagnostics.schema import Diagnosis, ExplanationCheck, HintEvent
from app.diagnostics.service import DiagnosisService


class NextHintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=512)


class ExplanationCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str = Field(min_length=1, max_length=8_000)


_ERROR_RESPONSES = {
    status: {"model": ErrorResponse}
    for status in (401, 404, 409, 422, 503)
}


def create_diagnostics_router(
    diagnosis_service: DiagnosisService | None,
    hint_service: HintLadderService | None,
    authenticator: Authenticator | None,
    proposal_hook: Callable[[Actor, ExplanationCheck, str], object] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["diagnostics"])

    @router.get(
        "/submissions/{submission_id}/diagnosis",
        response_model=Diagnosis,
        operation_id="getSubmissionDiagnosis",
        responses=_ERROR_RESPONSES,
    )
    def get_diagnosis(
        submission_id: Annotated[str, Path(min_length=1, max_length=128)],
        authorization: str | None = Header(default=None),
    ):
        actor = authenticator.authenticate_header(authorization)
        return diagnosis_service.get_diagnosis(actor, submission_id)

    @router.post(
        "/diagnoses/{diagnosis_id}/hints/next",
        response_model=HintEvent,
        operation_id="createNextDiagnosisHint",
        responses=_ERROR_RESPONSES,
    )
    def next_hint(
        diagnosis_id: Annotated[str, Path(min_length=1, max_length=128)],
        payload: NextHintRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = authenticator.authenticate_header(authorization)
        try:
            return hint_service.next_hint(
                actor,
                diagnosis_id,
                reason=payload.reason,
                request_id=str(request.state.request_id),
            )
        except HintLevelExhausted as exc:
            return error_response(
                request,
                409,
                "HINT_LEVEL_NOT_AVAILABLE",
                str(exc),
            )

    @router.post(
        "/diagnoses/{diagnosis_id}/explanation-check",
        response_model=ExplanationCheck,
        operation_id="checkDiagnosisExplanation",
        responses=_ERROR_RESPONSES,
    )
    def explanation_check(
        diagnosis_id: Annotated[str, Path(min_length=1, max_length=128)],
        payload: ExplanationCheckRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = authenticator.authenticate_header(authorization)
        result = diagnosis_service.check_explanation(
            actor,
            diagnosis_id,
            payload.explanation,
            request_id=str(request.state.request_id),
        )
        if result.memory_proposal_eligible and proposal_hook is not None:
            proposal_hook(actor, result, str(request.state.request_id))
        return result

    return router
