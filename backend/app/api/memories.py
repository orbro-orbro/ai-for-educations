from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request, Security
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.auth import Authenticator
from app.api.errors import ErrorResponse, error_response, request_id_for
from app.memories.deletion import DeletionService
from app.memories.models import (
    DeletionReceipt as DomainDeletionReceipt,
    DiagnosisSummary as DomainDiagnosisSummary,
    LearningMemory as DomainLearningMemory,
    MemoryProposal as DomainMemoryProposal,
    ShareGrant as DomainShareGrant,
)
from app.memories.service import (
    MemoryConflict,
    MemoryProposalNotEligible,
    MemoryService,
)


BoundedPathId = Annotated[str, Path(min_length=1, max_length=128)]
CourseIdQuery = Annotated[str, Query(min_length=1, max_length=128)]
IdempotencyKeyHeader = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=128),
]

_READ_ONLY = {"readOnly": True}
_WRITE_ONLY = {"writeOnly": True}
_ERROR_RESPONSES = {
    status: {"model": ErrorResponse}
    for status in (401, 404, 409, 422, 503)
}
_BEARER = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposalCorrectionRequest(_StrictRequest):
    content: str = Field(
        min_length=1,
        max_length=8000,
        pattern=r".*\S.*",
        json_schema_extra=_WRITE_ONLY,
    )


class MemoryCorrectionRequest(_StrictRequest):
    content: str = Field(
        min_length=1,
        max_length=8000,
        pattern=r".*\S.*",
        json_schema_extra=_WRITE_ONLY,
    )


class ShareGrantCreateRequest(_StrictRequest):
    grantee_user_id: str = Field(
        min_length=1, max_length=128, json_schema_extra=_WRITE_ONLY
    )
    purpose: str = Field(
        min_length=1, max_length=256, json_schema_extra=_WRITE_ONLY
    )
    expires_at: datetime | None = Field(
        default=None, json_schema_extra=_WRITE_ONLY
    )

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        return value.astimezone(UTC)


class MemoryProposal(BaseModel):
    proposal_id: str = Field(json_schema_extra=_READ_ONLY)
    root_proposal_id: str = Field(json_schema_extra=_READ_ONLY)
    previous_proposal_id: str | None = Field(json_schema_extra=_READ_ONLY)
    version: int = Field(json_schema_extra=_READ_ONLY)
    owner_user_id: str = Field(json_schema_extra=_READ_ONLY)
    course_id: str = Field(json_schema_extra=_READ_ONLY)
    diagnosis_id: str = Field(json_schema_extra=_READ_ONLY)
    explanation_check_id: str = Field(json_schema_extra=_READ_ONLY)
    content: str
    concept_ids: tuple[str, ...]
    confidence: float
    status: str = Field(json_schema_extra=_READ_ONLY)
    created_at: datetime = Field(json_schema_extra=_READ_ONLY)
    expires_at: datetime = Field(json_schema_extra=_READ_ONLY)
    request_id: str = Field(json_schema_extra=_READ_ONLY)


class LearningMemory(BaseModel):
    memory_id: str = Field(json_schema_extra=_READ_ONLY)
    logical_memory_id: str = Field(json_schema_extra=_READ_ONLY)
    previous_version_id: str | None = Field(json_schema_extra=_READ_ONLY)
    version: int = Field(json_schema_extra=_READ_ONLY)
    owner_user_id: str = Field(json_schema_extra=_READ_ONLY)
    course_id: str = Field(json_schema_extra=_READ_ONLY)
    memory_type: str
    visibility: str
    content: str | None
    concept_ids: tuple[str, ...]
    source_diagnosis_id: str = Field(json_schema_extra=_READ_ONLY)
    confidence: float
    allowed_purposes: tuple[str, ...]
    status: str = Field(json_schema_extra=_READ_ONLY)
    created_at: datetime = Field(json_schema_extra=_READ_ONLY)
    updated_at: datetime = Field(json_schema_extra=_READ_ONLY)
    expires_at: datetime | None
    request_id: str = Field(json_schema_extra=_READ_ONLY)


class ShareGrant(BaseModel):
    grant_id: str = Field(json_schema_extra=_READ_ONLY)
    owner_user_id: str = Field(json_schema_extra=_READ_ONLY)
    course_id: str = Field(json_schema_extra=_READ_ONLY)
    resource_type: str = Field(json_schema_extra=_READ_ONLY)
    resource_id: str = Field(json_schema_extra=_READ_ONLY)
    grantee_user_id: str
    purpose: str
    status: str = Field(json_schema_extra=_READ_ONLY)
    created_at: datetime = Field(json_schema_extra=_READ_ONLY)
    expires_at: datetime | None
    revoked_at: datetime | None = Field(json_schema_extra=_READ_ONLY)
    request_id: str = Field(json_schema_extra=_READ_ONLY)


class DeletionReceipt(BaseModel):
    deletion_id: str = Field(json_schema_extra=_READ_ONLY)
    memory_id: str = Field(json_schema_extra=_READ_ONLY)
    owner_user_id: str = Field(json_schema_extra=_READ_ONLY)
    course_id: str = Field(json_schema_extra=_READ_ONLY)
    status: str = Field(json_schema_extra=_READ_ONLY)
    requested_at: datetime = Field(json_schema_extra=_READ_ONLY)
    completed_at: datetime | None = Field(json_schema_extra=_READ_ONLY)
    attempts: int = Field(json_schema_extra=_READ_ONLY)
    index_cleared: bool = Field(json_schema_extra=_READ_ONLY)
    cache_cleared: bool = Field(json_schema_extra=_READ_ONLY)
    model_references_cleared: bool = Field(json_schema_extra=_READ_ONLY)
    reverse_lookup_absent: bool = Field(json_schema_extra=_READ_ONLY)
    error_code: str | None = Field(json_schema_extra=_READ_ONLY)
    request_id: str = Field(json_schema_extra=_READ_ONLY)


class DiagnosisSummary(BaseModel):
    diagnosis_id: str
    owner_user_id: str
    course_id: str
    category: str
    concept_ids: tuple[str, ...]
    root_cause: str
    confidence: float


def _proposal(item: DomainMemoryProposal) -> MemoryProposal:
    return MemoryProposal(
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


def _memory(item: DomainLearningMemory) -> LearningMemory:
    return LearningMemory(
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


def _grant(item: DomainShareGrant) -> ShareGrant:
    return ShareGrant(
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


def _receipt(item: DomainDeletionReceipt) -> DeletionReceipt:
    return DeletionReceipt(**item.public_dict())


def _summary(item: DomainDiagnosisSummary) -> DiagnosisSummary:
    return DiagnosisSummary(
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
    router = APIRouter(
        tags=["memories"],
        dependencies=[Security(_BEARER)],
        responses=_ERROR_RESPONSES,
    )

    @router.get(
        "/me/memory-proposals",
        response_model=list[MemoryProposal],
        operation_id="listMyMemoryProposals",
    )
    def list_my_proposals(
        request: Request,
        course_id: CourseIdQuery,
        authorization: str | None = Header(default=None, include_in_schema=False),
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
        response_model=LearningMemory,
        operation_id="acceptMemoryProposal",
    )
    def accept_proposal(
        proposal_id: BoundedPathId,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _memory(
                service.accept_proposal(
                    actor,
                    proposal_id,
                    request_id=request_id_for(request),
                    idempotency_key=_idempotency_key,
                )
            )
        except (MemoryConflict, MemoryProposalNotEligible) as error:
            return _conflict_response(request, error)

    @router.post(
        "/memory-proposals/{proposal_id}/reject",
        response_model=MemoryProposal,
        operation_id="rejectMemoryProposal",
    )
    def reject_proposal(
        proposal_id: BoundedPathId,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _proposal(
                service.reject_proposal(
                    actor,
                    proposal_id,
                    request_id=request_id_for(request),
                    idempotency_key=_idempotency_key,
                )
            )
        except MemoryConflict as error:
            return _conflict_response(request, error)

    @router.patch(
        "/memory-proposals/{proposal_id}",
        response_model=MemoryProposal,
        operation_id="correctMemoryProposal",
    )
    def correct_proposal(
        proposal_id: BoundedPathId,
        payload: ProposalCorrectionRequest,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _proposal(
                service.correct_proposal(
                    actor,
                    proposal_id,
                    payload.content,
                    request_id=request_id_for(request),
                    idempotency_key=_idempotency_key,
                )
            )
        except MemoryConflict as error:
            return _conflict_response(request, error)

    @router.get(
        "/me/memories",
        response_model=list[LearningMemory],
        operation_id="listMyLearningMemories",
    )
    def list_my_memories(
        request: Request,
        course_id: CourseIdQuery,
        query: str | None = Query(default=None),
        purpose: str = Query(default="learning_support"),
        authorization: str | None = Header(default=None, include_in_schema=False),
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
        response_model=LearningMemory,
        operation_id="correctLearningMemory",
    )
    def correct_memory(
        memory_id: BoundedPathId,
        payload: MemoryCorrectionRequest,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        try:
            actor = _actor(authenticator, authorization)
            return _memory(
                service.correct_memory(
                    actor,
                    memory_id,
                    payload.content,
                    request_id=request_id_for(request),
                    idempotency_key=_idempotency_key,
                )
            )
        except MemoryConflict as error:
            return _conflict_response(request, error)

    @router.delete(
        "/memories/{memory_id}",
        response_model=DeletionReceipt,
        status_code=202,
        operation_id="deleteLearningMemory",
    )
    def delete_memory(
        memory_id: BoundedPathId,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = _actor(authenticator, authorization)
        return _receipt(
            deletion.delete_memory(
                actor,
                memory_id,
                request_id=request_id_for(request),
                idempotency_key=_idempotency_key,
            )
        )

    @router.get(
        "/memory-deletions/{deletion_id}",
        response_model=DeletionReceipt,
        operation_id="getMemoryDeletion",
    )
    def get_deletion(
        deletion_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = _actor(authenticator, authorization)
        return _receipt(
            deletion.get_status(
                actor, deletion_id, request_id=request_id_for(request)
            )
        )

    @router.post(
        "/memory-deletions/{deletion_id}/retry",
        response_model=DeletionReceipt,
        operation_id="retryMemoryDeletion",
    )
    def retry_deletion(
        deletion_id: BoundedPathId,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = _actor(authenticator, authorization)
        return _receipt(
            deletion.retry(
                actor,
                deletion_id,
                request_id=request_id_for(request),
                idempotency_key=_idempotency_key,
            )
        )

    @router.post(
        "/diagnoses/{diagnosis_id}/share-grants",
        response_model=ShareGrant,
        status_code=201,
        operation_id="createDiagnosisShareGrant",
    )
    def create_share_grant(
        diagnosis_id: BoundedPathId,
        payload: ShareGrantCreateRequest,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
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
                idempotency_key=_idempotency_key,
            )
        )

    @router.get(
        "/me/share-grants",
        response_model=list[ShareGrant],
        operation_id="listMyShareGrants",
    )
    def list_share_grants(
        request: Request,
        course_id: CourseIdQuery,
        authorization: str | None = Header(default=None, include_in_schema=False),
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
        response_model=ShareGrant,
        operation_id="getShareGrant",
    )
    def get_share_grant(
        grant_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = _actor(authenticator, authorization)
        return _grant(
            service.get_share_grant(
                actor, grant_id, request_id=request_id_for(request)
            )
        )

    @router.delete(
        "/share-grants/{grant_id}",
        response_model=ShareGrant,
        operation_id="revokeShareGrant",
    )
    def revoke_share_grant(
        grant_id: BoundedPathId,
        request: Request,
        _idempotency_key: IdempotencyKeyHeader,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = _actor(authenticator, authorization)
        return _grant(
            service.revoke_share_grant(
                actor,
                grant_id,
                request_id=request_id_for(request),
                idempotency_key=_idempotency_key,
            )
        )

    @router.get(
        "/share-grants/{grant_id}/diagnosis-summary",
        response_model=DiagnosisSummary,
        operation_id="getSharedDiagnosisSummary",
    )
    def get_shared_summary(
        grant_id: BoundedPathId,
        request: Request,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = _actor(authenticator, authorization)
        return _summary(
            service.read_shared_diagnosis(
                actor, grant_id, request_id=request_id_for(request)
            )
        )

    return router
