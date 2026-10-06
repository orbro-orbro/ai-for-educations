from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum


class MemoryProposalStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    superseded = "superseded"
    expired = "expired"


class LearningMemoryStatus(StrEnum):
    active = "active"
    superseded = "superseded"
    expired = "expired"
    deletion_pending = "deletion_pending"
    deleted = "deleted"


class ShareGrantStatus(StrEnum):
    active = "active"
    revoked = "revoked"
    expired = "expired"


class DeletionStatus(StrEnum):
    deletion_pending = "deletion_pending"
    deleted = "deleted"


@dataclass(frozen=True, slots=True)
class MemoryProposal:
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
    status: MemoryProposalStatus
    created_at: datetime
    expires_at: datetime
    request_id: str
    accepted_memory_id: str | None = None


@dataclass(frozen=True, slots=True)
class LearningMemory:
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
    source_proposal_id: str
    confidence: float
    allowed_purposes: tuple[str, ...]
    status: LearningMemoryStatus
    index_document_id: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    request_id: str


@dataclass(frozen=True, slots=True)
class ShareGrant:
    grant_id: str
    owner_user_id: str
    course_id: str
    resource_type: str
    resource_id: str
    grantee_user_id: str
    purpose: str
    status: ShareGrantStatus
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    request_id: str


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    deletion_id: str
    memory_id: str
    owner_user_id: str
    course_id: str
    status: DeletionStatus
    requested_at: datetime
    completed_at: datetime | None
    attempts: int
    index_cleared: bool
    cache_cleared: bool
    model_references_cleared: bool
    reverse_lookup_absent: bool
    error_code: str | None
    request_id: str

    def public_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["status"] = self.status.value
        values["requested_at"] = self.requested_at.isoformat()
        values["completed_at"] = (
            self.completed_at.isoformat() if self.completed_at is not None else None
        )
        return values


@dataclass(frozen=True, slots=True)
class DiagnosisSummary:
    diagnosis_id: str
    owner_user_id: str
    course_id: str
    category: str
    concept_ids: tuple[str, ...]
    root_cause: str
    confidence: float


@dataclass(frozen=True, slots=True)
class MemoryProposalSource:
    explanation_check_id: str
    diagnosis_id: str
    owner_user_id: str
    course_id: str
    content: str
    concept_ids: tuple[str, ...]
    confidence: float
    eligible: bool
