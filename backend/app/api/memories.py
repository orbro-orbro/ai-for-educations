from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.auth import Authenticator
from app.api.errors import error_response, request_id_for
from app.memories.deletion import DeletionService
from app.memories.models import (
    DeletionReceipt,
    DiagnosisSummary,
    LearningMemory,
    MemoryProposal,
    ShareGrant,
)
from app.memories.service import (
    MemoryConflict,
    MemoryProposalNotEligible,
    MemoryService,
)


BoundedPathId = Annotated[str, Path(min_length=1, max_length=128)]
CourseIdQuery = Annotated[str, Query(min_length=1, max_length=128)]


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposalCorrectionRequest(_StrictRequest):
    content: str = Field(min_length=1, max_length=8000, pattern=r".*\S.*")


class MemoryCorrectionRequest(_StrictRequest):
    content: str = Field(min_length=1, max_length=8000, pattern=r".*\S.*")


class ShareGrantCreateRequest(_StrictRequest):
    grantee_user_id: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=256)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        return value.astimezone(UTC)


class MemoryProposalResponse(BaseModel):
    proposal_id: str
    root_proposal_id: str
    previous_proposal_id: str | None
    version: int
    owner_user_id: str
    course_id: str
    diagnosis_id: str
    explanation_check_id: str
    content: str
    concept_ids: tuple[str, ...]
    confidence: float
    status: str
    created_at: datetime
    expires_at: datetime
    request_id: str


class LearningMemoryResponse(BaseModel):
    memory_id: str
    logical_memory_id: str
    previous_version_id: str | None
    version: int
    owner_user_id: str
    course_id: str
    memory_type: str
    visibility: str
    content: str | None
    concept_ids: tuple[str, ...]
    source_diagnosis_id: str
    confidence: float
    allowed_purposes: tuple[str, ...]
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    request_id: str


class ShareGrantResponse(BaseModel):
    grant_id: str
    owner_user_id: str
    course_id: str
    resource_type: str
    resource_id: str
    grantee_user_id: str
    purpose: str
    status: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    request_id: str


class DeletionReceiptResponse(BaseModel):
    deletion_id: str
    memory_id: str
    owner_user_id: str
    course_id: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    attempts: int
    index_cleared: bool
    cache_cleared: bool
    model_references_cleared: bool
    reverse_lookup_absent: bool
    error_code: str | None
    request_id: str


class DiagnosisSummaryResponse(BaseModel):
    diagnosis_id: str
    owner_user_id: str
    course_id: str
    category: str
    concept_ids: tuple[str, ...]
    root_cause: str
    confidence: float


def _proposal(item: MemoryProposal) -> MemoryProposalResponse:
    return MemoryProposalResponse(
        proposal_id=item.proposal_id,
        root_proposal_id=item.root_proposal_id,
        previous_proposal_id=item.previous_proposal_id,
        version=item.version,
        owner_user_id=item.owner_user_id,
        course_id=item.course_id,
        diagnosis_id=item.diagnosis_id,
        explanation_check_id=item.explanation_check_id,
        content=item.content,
        concept_ids=item.concept_ids,
        confidence=item.confidence,
        status=item.status.value,
        created_at=item.created_at,
        expires_at=item.expires_at,
        request_id=item.request_id,
    )


def _memory(item: LearningMemory) -> LearningMemoryResponse:
    return LearningMemoryResponse(
        memory_id=item.memory_id,
        logical_memory_id=item.logical_memory_id,
        previous_version_id=item.previous_version_id,
        version=item.version,
        owner_user_id=item.owner_user_id,
        course_id=item.course_id,
        memory_type=item.memory_type,
        visibility=item.visibility,
        content=item.content,
        concept_ids=item.concept_ids,
        source_diagnosis_id=item.source_diagnosis_id,
        confidence=item.confidence,
        allowed_purposes=item.allowed_purposes,
        status=item.status.value,
        created_at=item.created_at,
        updated_at=item.updated_at,
        expires_at=item.expires_at,
        request_id=item.request_id,
    )


def _grant(item: ShareGrant) -> ShareGrantResponse:
    return ShareGrantResponse(
        grant_id=item.grant_id,
        owner_user_id=item.owner_user_id,
        course_id=item.course_id,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        grantee_user_id=item.grantee_user_id,
        purpose=item.purpose,
        status=item.status.value,
        created_at=item.created_at,
        expires_at=item.expires_at,
        revoked_at=item.revoked_at,
        request_id=item.request_id,
    )


def _receipt(item: DeletionReceipt) -> DeletionReceiptResponse:
    return DeletionReceiptResponse(**item.public_dict())


def _summary(item: DiagnosisSummary) -> DiagnosisSummaryResponse:
    return DiagnosisSummaryResponse(
        diagnosis_id=item.diagnosis_id,
        owner_user_id=item.owner_user_id,
        course_id=item.course_id,
        category=item.category,
        concept_ids=item.concept_ids,
        root_cause=item.root_cause,
        confidence=item.confidence,
    )


def _actor(authenticator: Authenticator, authorization: str | None):
    return authenticator.authenticate_header(authorization)


def _conflict_response(request: Request, error: RuntimeError):
    code = getattr(error, "public_error_code", "MEMORY_STATE_CONFLICT")
    message = getattr(error, "public_message", "The memory operation conflicted.")
    return error_response(request, 409, code, message)


def create_memories_router(
    service: MemoryService,
    deletion: DeletionService,
    authenticator: Authenticator,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/me/memory-proposals",
        response_model=list[MemoryProposalResponse],
        operation_id="listMyMemoryProposals",
    )
    def list_my_proposals(
        request: Request,
        course_id: CourseIdQuery,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return [
            _proposal(item)
            for item in service.list_proposals(
                actor, course_id, request_id=request_id_for(request)
            )
        ]

    @router.post(
        "/memory-proposals/{proposal_id}/accept",
        response_model=LearningMemoryResponse,
        operation_id="acceptMemoryProposal",
    )
    def accept_proposal(
        proposal_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _memory(
                service.accept_proposal(
                    actor, proposal_id, request_id=request_id_for(request)
                )
            )
        except (MemoryConflict, MemoryProposalNotEligible) as error:
            return _conflict_response(request, error)

    @router.post(
        "/memory-proposals/{proposal_id}/reject",
        response_model=MemoryProposalResponse,
        operation_id="rejectMemoryProposal",
    )
    def reject_proposal(
        proposal_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _proposal(
                service.reject_proposal(
                    actor, proposal_id, request_id=request_id_for(request)
                )
            )
        except MemoryConflict as error:
            return _conflict_response(request, error)

    @router.patch(
        "/memory-proposals/{proposal_id}",
        response_model=MemoryProposalResponse,
        operation_id="correctMemoryProposal",
    )
    def correct_proposal(
        proposal_id: BoundedPathId,
        payload: ProposalCorrectionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _proposal(
                service.correct_proposal(
                    actor,
                    proposal_id,
                    payload.content,
                    request_id=request_id_for(request),
                )
            )
        except MemoryConflict as error:
            return _conflict_response(request, error)

    @router.get(
        "/me/memories",
        response_model=list[LearningMemoryResponse],
        operation_id="listMyLearningMemories",
    )
    def list_my_memories(
        request: Request,
        course_id: CourseIdQuery,
        query: str | None = Query(default=None),
        purpose: str = Query(default="learning_support"),
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        values = (
            service.search_memories(
                actor,
                course_id,
                query,
                purpose=purpose,
                request_id=request_id_for(request),
            )
            if query is not None
            else service.list_memories(
                actor, course_id, request_id=request_id_for(request)
            )
        )
        return [_memory(item) for item in values]

    @router.patch(
        "/memories/{memory_id}",
        response_model=LearningMemoryResponse,
        operation_id="correctLearningMemory",
    )
    def correct_memory(
        memory_id: BoundedPathId,
        payload: MemoryCorrectionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _memory(
                service.correct_memory(
                    actor,
                    memory_id,
                    payload.content,
                    request_id=request_id_for(request),
                )
            )
        except MemoryConflict as error:
            return _conflict_response(request, error)

    @router.delete(
        "/memories/{memory_id}",
        response_model=DeletionReceiptResponse,
        status_code=202,
        operation_id="deleteLearningMemory",
    )
    def delete_memory(
        memory_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return _receipt(
            deletion.delete_memory(
                actor, memory_id, request_id=request_id_for(request)
            )
        )

    @router.get(
        "/memory-deletions/{deletion_id}",
        response_model=DeletionReceiptResponse,
        operation_id="getMemoryDeletion",
    )
    def get_deletion(
        deletion_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return _receipt(
            deletion.get_status(
                actor, deletion_id, request_id=request_id_for(request)
            )
        )

    @router.post(
        "/memory-deletions/{deletion_id}/retry",
        response_model=DeletionReceiptResponse,
        operation_id="retryMemoryDeletion",
    )
    def retry_deletion(
        deletion_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return _receipt(
            deletion.retry(actor, deletion_id, request_id=request_id_for(request))
        )

    @router.post(
        "/diagnoses/{diagnosis_id}/share-grants",
        response_model=ShareGrantResponse,
        status_code=201,
        operation_id="createDiagnosisShareGrant",
    )
    def create_share_grant(
        diagnosis_id: BoundedPathId,
        payload: ShareGrantCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return _grant(
            service.create_share_grant(
                actor,
                diagnosis_id,
                payload.grantee_user_id,
                purpose=payload.purpose,
                expires_at=payload.expires_at,
                request_id=request_id_for(request),
            )
        )

    @router.get(
        "/me/share-grants",
        response_model=list[ShareGrantResponse],
        operation_id="listMyShareGrants",
    )
    def list_share_grants(
        request: Request,
        course_id: CourseIdQuery,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return [
            _grant(item)
            for item in service.list_share_grants(
                actor, course_id, request_id=request_id_for(request)
            )
        ]

    @router.get(
        "/share-grants/{grant_id}",
        response_model=ShareGrantResponse,
        operation_id="getShareGrant",
    )
    def get_share_grant(
        grant_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return _grant(
            service.get_share_grant(
                actor, grant_id, request_id=request_id_for(request)
            )
        )

    @router.delete(
        "/share-grants/{grant_id}",
        response_model=ShareGrantResponse,
        operation_id="revokeShareGrant",
    )
    def revoke_share_grant(
        grant_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return _grant(
            service.revoke_share_grant(
                actor, grant_id, request_id=request_id_for(request)
            )
        )

    @router.get(
        "/share-grants/{grant_id}/diagnosis-summary",
        response_model=DiagnosisSummaryResponse,
        operation_id="getSharedDiagnosisSummary",
    )
    def get_shared_summary(
        grant_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        actor = _actor(authenticator, authorization)
        return _summary(
            service.read_shared_diagnosis(
                actor, grant_id, request_id=request_id_for(request)
            )
        )

    return router
