from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Callable, Protocol
from uuid import uuid4

from app.audit.service import AuditLog
from app.auth.models import Actor, Role
from app.courses.service import ResourceNotAvailable
from app.memories.models import (
    DiagnosisSummary,
    LearningMemory,
    LearningMemoryStatus,
    MemoryProposal,
    MemoryProposalSource,
    MemoryProposalStatus,
    ShareGrant,
    ShareGrantStatus,
)
from app.memories.policy import MemoryPolicy
from app.memories.repository import MemoryRepository
from app.memories.retrieval import RetrievalIndex


class MemoryConflict(RuntimeError):
    public_error_code = "MEMORY_STATE_CONFLICT"
    public_message = "The memory state does not allow this operation."


class MemoryProposalNotEligible(RuntimeError):
    public_error_code = "MEMORY_PROPOSAL_NOT_ELIGIBLE"
    public_message = "The explanation is not eligible for a memory proposal."


class MemorySource(Protocol):
    def proposal_source(self, explanation_check_id: str) -> MemoryProposalSource | None: ...
    def diagnosis_summary(self, diagnosis_id: str) -> DiagnosisSummary | None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    return value.astimezone(UTC)


def _request_fingerprint(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("idempotency_key is required")
    return normalized


class DiagnosticMemorySource:
    """Read-only adapter over Task 6's authoritative records."""

    def __init__(
        self,
        *,
        diagnostics,
        submissions,
        confidence_threshold: float,
    ) -> None:
        self._diagnostics = diagnostics
        self._submissions = submissions
        self._threshold = confidence_threshold

    def proposal_source(self, explanation_check_id: str) -> MemoryProposalSource | None:
        check = next(
            (
                item
                for item in self._diagnostics.explanation_checks()
                if item.explanation_check_id == explanation_check_id
            ),
            None,
        )
        if check is None:
            return None
        diagnosis = self._diagnostics.get(check.diagnosis_id)
        submission = (
            self._submissions.get(diagnosis.submission_id)
            if diagnosis is not None
            else None
        )
        if (
            diagnosis is None
            or submission is None
            or diagnosis.owner_user_id != submission.owner_user_id
            or diagnosis.course_id != submission.course_id
            or check.diagnosis_id != diagnosis.diagnosis_id
        ):
            return None
        eligible = (
            check.memory_proposal_eligible
            and check.understands
            and check.confidence >= self._threshold
            and diagnosis.confidence >= self._threshold
            and not diagnosis.requires_teacher_review
            and bool(check.concept_ids)
            and set(check.concept_ids) <= set(diagnosis.concept_ids)
        )
        return MemoryProposalSource(
            explanation_check_id=check.explanation_check_id,
            diagnosis_id=diagnosis.diagnosis_id,
            owner_user_id=diagnosis.owner_user_id,
            course_id=diagnosis.course_id,
            content=diagnosis.root_cause,
            concept_ids=diagnosis.concept_ids,
            confidence=min(check.confidence, diagnosis.confidence),
            eligible=eligible,
        )

    def diagnosis_summary(self, diagnosis_id: str) -> DiagnosisSummary | None:
        diagnosis = self._diagnostics.get(diagnosis_id)
        submission = (
            self._submissions.get(diagnosis.submission_id)
            if diagnosis is not None
            else None
        )
        if (
            diagnosis is None
            or submission is None
            or diagnosis.owner_user_id != submission.owner_user_id
            or diagnosis.course_id != submission.course_id
        ):
            return None
        return DiagnosisSummary(
            diagnosis_id=diagnosis.diagnosis_id,
            owner_user_id=diagnosis.owner_user_id,
            course_id=diagnosis.course_id,
            category=diagnosis.category.value,
            concept_ids=diagnosis.concept_ids,
            root_cause=diagnosis.root_cause,
            confidence=diagnosis.confidence,
        )


class MemoryService:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        source: MemorySource,
        policy: MemoryPolicy,
        retrieval_index: RetrievalIndex,
        audit: AuditLog,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
        proposal_ttl: timedelta = timedelta(days=30),
    ) -> None:
        self._repository = repository
        self._source = source
        self._policy = policy
        self._index = retrieval_index
        self._audit = audit
        self._clock = clock
        self._id_factory = id_factory
        self._proposal_ttl = proposal_ttl

    @contextmanager
    def _atomic_mutation(self):
        with self._repository.transaction():
            with self._audit.transaction():
                yield

    def create_proposal(
        self,
        actor: Actor,
        explanation_check_id: str,
        *,
        request_id: str,
        expires_at: datetime | None = None,
    ) -> MemoryProposal:
        source = self._source.proposal_source(explanation_check_id)
        if source is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, source.owner_user_id, source.course_id)
        if not source.eligible:
            raise MemoryProposalNotEligible(MemoryProposalNotEligible.public_message)
        now = self._clock()
        proposal_id = self._id_factory()
        normalized_expiry = _normalize_aware_datetime(expires_at)
        with self._atomic_mutation():
            existing = self._repository.get_proposal_for_explanation(
                explanation_check_id
            )
            if existing is not None:
                return existing
            proposal = self._repository.add_proposal(
                MemoryProposal(
                    proposal_id=proposal_id,
                    root_proposal_id=proposal_id,
                    previous_proposal_id=None,
                    version=1,
                    owner_user_id=source.owner_user_id,
                    course_id=source.course_id,
                    diagnosis_id=source.diagnosis_id,
                    explanation_check_id=source.explanation_check_id,
                    content=source.content,
                    concept_ids=source.concept_ids,
                    confidence=source.confidence,
                    status=MemoryProposalStatus.pending,
                    created_at=now,
                    expires_at=normalized_expiry or now + self._proposal_ttl,
                    request_id=request_id,
                )
            )
            self._audit.record(
                event_type="memory_proposal_created",
                actor=actor,
                target_type="memory_proposal",
                target_id=proposal.proposal_id,
                owner_user_id=proposal.owner_user_id,
                course_id=proposal.course_id,
                outcome="created",
                reason_code="task6_eligible",
                request_id=request_id,
                related_id=proposal.diagnosis_id,
            )
            return proposal

    def list_proposals(
        self,
        actor: Actor,
        course_id: str,
        *,
        request_id: str | None = None,
    ) -> tuple[MemoryProposal, ...]:
        self._policy.require_student_course(actor, course_id)
        values = tuple(
            self._expire_proposal(item)
            for item in self._repository.list_proposals(actor.user_id, course_id)
        )
        self._audit.record(
            event_type="memory_proposals_listed",
            actor=actor,
            target_type="course_memory_proposal_collection",
            target_id=course_id,
            owner_user_id=actor.user_id,
            course_id=course_id,
            outcome="allowed",
            reason_code="owner_course_match",
            request_id=request_id or f"internal:list-proposals:{course_id}",
        )
        return values

    def get_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        *,
        request_id: str | None = None,
    ) -> MemoryProposal:
        proposal = self._repository.get_proposal(proposal_id)
        if proposal is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, proposal.owner_user_id, proposal.course_id)
        proposal = self._expire_proposal(proposal)
        self._audit.record(
            event_type="memory_proposal_read",
            actor=actor,
            target_type="memory_proposal",
            target_id=proposal.proposal_id,
            owner_user_id=proposal.owner_user_id,
            course_id=proposal.course_id,
            outcome="allowed",
            reason_code="owner_course_match",
            request_id=request_id or f"internal:get-proposal:{proposal.proposal_id}",
        )
        return proposal

    def accept_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        *,
        request_id: str,
        idempotency_key: str,
    ) -> LearningMemory:
        idempotency_key = _required_idempotency_key(idempotency_key)
        fingerprint = _request_fingerprint({})
        with self._repository.proposal_claim(proposal_id):
            with self._atomic_mutation():
                proposal = self._repository.get_proposal(proposal_id)
                if proposal is None:
                    raise ResourceNotAvailable()
                self._policy.require_owner(
                    actor, proposal.owner_user_id, proposal.course_id
                )
                replay = self._repository.claim_idempotency(
                    actor_user_id=actor.user_id,
                    operation="accept_proposal",
                    idempotency_key=idempotency_key,
                    resource_type="memory_proposal",
                    resource_id=proposal_id,
                    request_fingerprint=fingerprint,
                )
                if replay is not None:
                    existing = self._repository.get_memory(replay.result_id)
                    if existing is None:
                        raise MemoryConflict(MemoryConflict.public_message)
                    return existing
                proposal = self._expire_proposal_claimed(proposal)
                if proposal.status is MemoryProposalStatus.accepted:
                    existing = self._repository.get_memory_for_proposal(proposal_id)
                    if existing is None:
                        raise MemoryConflict(MemoryConflict.public_message)
                    self._repository.remember_idempotency_result(
                        actor_user_id=actor.user_id,
                        operation="accept_proposal",
                        idempotency_key=idempotency_key,
                        resource_type="memory_proposal",
                        resource_id=proposal_id,
                        request_fingerprint=fingerprint,
                        result_type="learning_memory",
                        result_id=existing.memory_id,
                    )
                    return existing
                if proposal.status is not MemoryProposalStatus.pending:
                    raise MemoryConflict(MemoryConflict.public_message)
                now = self._clock()
                memory_id = self._id_factory()
                memory = self._repository.add_memory(
                    LearningMemory(
                        memory_id=memory_id,
                        logical_memory_id=memory_id,
                        previous_version_id=None,
                        version=1,
                        owner_user_id=proposal.owner_user_id,
                        course_id=proposal.course_id,
                        memory_type="misconception_state",
                        visibility="private",
                        content=proposal.content,
                        concept_ids=proposal.concept_ids,
                        source_diagnosis_id=proposal.diagnosis_id,
                        source_proposal_id=proposal.proposal_id,
                        confidence=proposal.confidence,
                        allowed_purposes=("learning_support",),
                        status=LearningMemoryStatus.active,
                        index_document_id=f"memory-index:{memory_id}",
                        created_at=now,
                        updated_at=now,
                        expires_at=None,
                        request_id=request_id,
                    )
                )
                self._repository.save_proposal(
                    replace(
                        proposal,
                        status=MemoryProposalStatus.accepted,
                        accepted_memory_id=memory.memory_id,
                    )
                )
                self._repository.remember_idempotency_result(
                    actor_user_id=actor.user_id,
                    operation="accept_proposal",
                    idempotency_key=idempotency_key,
                    resource_type="memory_proposal",
                    resource_id=proposal_id,
                    request_fingerprint=fingerprint,
                    result_type="learning_memory",
                    result_id=memory.memory_id,
                )
                self._audit.record(
                    event_type="memory_proposal_accepted",
                    actor=actor,
                    target_type="learning_memory",
                    target_id=memory.memory_id,
                    owner_user_id=memory.owner_user_id,
                    course_id=memory.course_id,
                    outcome="active",
                    reason_code="student_accepted",
                    request_id=request_id,
                    related_id=proposal.proposal_id,
                )
            with self._repository.memory_claim(memory.logical_memory_id):
                current = self._repository.get_memory(memory.memory_id)
                if current is None:
                    raise ResourceNotAvailable()
                if current.status is LearningMemoryStatus.active:
                    self._index.upsert(current)
                return current

    def reject_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        *,
        request_id: str,
        idempotency_key: str,
    ) -> MemoryProposal:
        idempotency_key = _required_idempotency_key(idempotency_key)
        fingerprint = _request_fingerprint({})
        with self._repository.proposal_claim(proposal_id):
            with self._atomic_mutation():
                proposal = self._required_owned_proposal(actor, proposal_id)
                replay = self._repository.claim_idempotency(
                    actor_user_id=actor.user_id,
                    operation="reject_proposal",
                    idempotency_key=idempotency_key,
                    resource_type="memory_proposal",
                    resource_id=proposal_id,
                    request_fingerprint=fingerprint,
                )
                if replay is not None:
                    result = self._repository.get_proposal(replay.result_id)
                    if result is None:
                        raise MemoryConflict(MemoryConflict.public_message)
                    return result
                proposal = self._expire_proposal_claimed(proposal)
                if proposal.status is MemoryProposalStatus.rejected:
                    self._repository.remember_idempotency_result(
                        actor_user_id=actor.user_id,
                        operation="reject_proposal",
                        idempotency_key=idempotency_key,
                        resource_type="memory_proposal",
                        resource_id=proposal_id,
                        request_fingerprint=fingerprint,
                        result_type="memory_proposal",
                        result_id=proposal.proposal_id,
                    )
                    return proposal
                if proposal.status is not MemoryProposalStatus.pending:
                    raise MemoryConflict(MemoryConflict.public_message)
                rejected = self._repository.save_proposal(
                    replace(proposal, status=MemoryProposalStatus.rejected)
                )
                self._repository.remember_idempotency_result(
                    actor_user_id=actor.user_id,
                    operation="reject_proposal",
                    idempotency_key=idempotency_key,
                    resource_type="memory_proposal",
                    resource_id=proposal_id,
                    request_fingerprint=fingerprint,
                    result_type="memory_proposal",
                    result_id=rejected.proposal_id,
                )
                self._audit.record(
                    event_type="memory_proposal_rejected",
                    actor=actor,
                    target_type="memory_proposal",
                    target_id=proposal.proposal_id,
                    owner_user_id=proposal.owner_user_id,
                    course_id=proposal.course_id,
                    outcome="rejected",
                    reason_code="student_rejected",
                    request_id=request_id,
                )
                return rejected

    def correct_proposal(
        self,
        actor: Actor,
        proposal_id: str,
        content: str,
        *,
        request_id: str,
        idempotency_key: str,
    ) -> MemoryProposal:
        if not content.strip():
            raise ValueError("content is required")
        idempotency_key = _required_idempotency_key(idempotency_key)
        fingerprint = _request_fingerprint({"content": content.strip()})
        with self._repository.proposal_claim(proposal_id):
            with self._atomic_mutation():
                proposal = self._required_owned_proposal(actor, proposal_id)
                replay = self._repository.claim_idempotency(
                    actor_user_id=actor.user_id,
                    operation="correct_proposal",
                    idempotency_key=idempotency_key,
                    resource_type="memory_proposal",
                    resource_id=proposal_id,
                    request_fingerprint=fingerprint,
                )
                if replay is not None:
                    result = self._repository.get_proposal(replay.result_id)
                    if result is None:
                        raise MemoryConflict(MemoryConflict.public_message)
                    return result
                proposal = self._expire_proposal_claimed(proposal)
                if proposal.status is not MemoryProposalStatus.pending:
                    raise MemoryConflict(MemoryConflict.public_message)
                corrected = self._repository.add_corrected_proposal(
                    replace(
                        proposal,
                        proposal_id=self._id_factory(),
                        previous_proposal_id=proposal.proposal_id,
                        version=proposal.version + 1,
                        content=content.strip(),
                        status=MemoryProposalStatus.pending,
                        created_at=self._clock(),
                        request_id=request_id,
                    )
                )
                self._repository.save_proposal(
                    replace(proposal, status=MemoryProposalStatus.superseded)
                )
                self._repository.remember_idempotency_result(
                    actor_user_id=actor.user_id,
                    operation="correct_proposal",
                    idempotency_key=idempotency_key,
                    resource_type="memory_proposal",
                    resource_id=proposal_id,
                    request_fingerprint=fingerprint,
                    result_type="memory_proposal",
                    result_id=corrected.proposal_id,
                )
                self._audit.record(
                    event_type="memory_proposal_corrected",
                    actor=actor,
                    target_type="memory_proposal",
                    target_id=corrected.proposal_id,
                    owner_user_id=proposal.owner_user_id,
                    course_id=proposal.course_id,
                    outcome="pending",
                    reason_code="student_corrected",
                    request_id=request_id,
                    related_id=proposal.proposal_id,
                )
                return corrected

    def list_memories(
        self,
        actor: Actor,
        course_id: str,
        *,
        request_id: str | None = None,
    ) -> tuple[LearningMemory, ...]:
        self._policy.require_student_course(actor, course_id)
        visible = self._active_memories(actor.user_id, course_id)
        self._audit.record(
            event_type="learning_memories_listed",
            actor=actor,
            target_type="course_memory_collection",
            target_id=course_id,
            owner_user_id=actor.user_id,
            course_id=course_id,
            outcome="allowed",
            reason_code="owner_course_match",
            request_id=request_id or f"internal:list-memories:{course_id}",
        )
        return visible

    def get_memory(
        self,
        actor: Actor,
        memory_id: str,
        *,
        request_id: str | None = None,
    ) -> LearningMemory:
        memory = self._repository.get_memory(memory_id)
        if memory is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, memory.owner_user_id, memory.course_id)
        memory = self._expire_memory(memory)
        self._audit.record(
            event_type="learning_memory_read",
            actor=actor,
            target_type="learning_memory",
            target_id=memory.memory_id,
            owner_user_id=memory.owner_user_id,
            course_id=memory.course_id,
            outcome="allowed",
            reason_code="owner_course_match",
            request_id=request_id or f"internal:get-memory:{memory.memory_id}",
        )
        return memory

    def search_memories(
        self,
        actor: Actor,
        course_id: str,
        query: str,
        *,
        purpose: str,
        request_id: str | None = None,
    ) -> tuple[LearningMemory, ...]:
        self._policy.require_student_course(actor, course_id)
        candidates = tuple(
            item
            for item in self._active_memories(actor.user_id, course_id)
            if purpose in item.allowed_purposes
        )
        candidate_by_document = {
            item.index_document_id: item.memory_id for item in candidates
        }
        returned_ids = self._index.search(
            query,
            candidate_document_ids=frozenset(candidate_by_document),
            owner_user_id=actor.user_id,
            course_id=course_id,
            purpose=purpose,
        )
        results: list[LearningMemory] = []
        seen: set[str] = set()
        for document_id in returned_ids:
            expected_memory_id = candidate_by_document.get(document_id)
            if expected_memory_id is None or expected_memory_id in seen:
                continue
            current = self._repository.get_memory_by_index_document_id(document_id)
            if current is None or current.memory_id != expected_memory_id:
                continue
            try:
                self._policy.require_owner(
                    actor, current.owner_user_id, current.course_id
                )
            except ResourceNotAvailable:
                continue
            current = self._expire_memory(current)
            if (
                current.status is LearningMemoryStatus.active
                and current.owner_user_id == actor.user_id
                and current.course_id == course_id
                and purpose in current.allowed_purposes
            ):
                results.append(current)
                seen.add(current.memory_id)
        self._audit.record(
            event_type="learning_memories_searched",
            actor=actor,
            target_type="course_memory_collection",
            target_id=course_id,
            owner_user_id=actor.user_id,
            course_id=course_id,
            outcome="allowed",
            reason_code="prefilter_and_postcheck",
            request_id=request_id or f"internal:search-memories:{course_id}",
        )
        return tuple(results)

    def correct_memory(
        self,
        actor: Actor,
        memory_id: str,
        content: str,
        *,
        request_id: str,
        idempotency_key: str,
    ) -> LearningMemory:
        if not content.strip():
            raise ValueError("content is required")
        idempotency_key = _required_idempotency_key(idempotency_key)
        fingerprint = _request_fingerprint({"content": content.strip()})
        current = self._repository.get_memory(memory_id)
        if current is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, current.owner_user_id, current.course_id)
        with self._repository.memory_claim(current.logical_memory_id):
            with self._atomic_mutation():
                replay = self._repository.claim_idempotency(
                    actor_user_id=actor.user_id,
                    operation="correct_memory",
                    idempotency_key=idempotency_key,
                    resource_type="learning_memory",
                    resource_id=memory_id,
                    request_fingerprint=fingerprint,
                )
                if replay is not None:
                    result = self._repository.get_memory(replay.result_id)
                    if result is None:
                        raise MemoryConflict(MemoryConflict.public_message)
                    return result
                current = self._repository.get_memory(memory_id)
                if current is None:
                    raise ResourceNotAvailable()
                current = self._expire_memory_claimed(current)
                if current.status is not LearningMemoryStatus.active:
                    raise MemoryConflict(MemoryConflict.public_message)
                now = self._clock()
                new_id = self._id_factory()
                self._repository.save_memory(
                    replace(
                        current,
                        status=LearningMemoryStatus.superseded,
                        updated_at=now,
                    )
                )
                corrected = self._repository.add_corrected_memory(
                    replace(
                        current,
                        memory_id=new_id,
                        previous_version_id=current.memory_id,
                        version=current.version + 1,
                        content=content.strip(),
                        source_proposal_id=None,
                        status=LearningMemoryStatus.active,
                        index_document_id=f"memory-index:{new_id}",
                        created_at=now,
                        updated_at=now,
                        request_id=request_id,
                    )
                )
                self._repository.remember_idempotency_result(
                    actor_user_id=actor.user_id,
                    operation="correct_memory",
                    idempotency_key=idempotency_key,
                    resource_type="learning_memory",
                    resource_id=memory_id,
                    request_fingerprint=fingerprint,
                    result_type="learning_memory",
                    result_id=corrected.memory_id,
                )
                self._audit.record(
                    event_type="learning_memory_corrected",
                    actor=actor,
                    target_type="learning_memory",
                    target_id=corrected.memory_id,
                    owner_user_id=corrected.owner_user_id,
                    course_id=corrected.course_id,
                    outcome="active",
                    reason_code="student_corrected",
                    request_id=request_id,
                    related_id=current.memory_id,
                )
            self._index.upsert(corrected)
            return corrected

    def create_share_grant(
        self,
        actor: Actor,
        diagnosis_id: str,
        grantee_user_id: str,
        *,
        purpose: str,
        request_id: str,
        idempotency_key: str,
        expires_at: datetime | None = None,
    ) -> ShareGrant:
        expires_at = _normalize_aware_datetime(expires_at)
        idempotency_key = _required_idempotency_key(idempotency_key)
        fingerprint = _request_fingerprint(
            {
                "grantee_user_id": grantee_user_id,
                "purpose": purpose,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }
        )
        summary = self._source.diagnosis_summary(diagnosis_id)
        if summary is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, summary.owner_user_id, summary.course_id)
        self._policy.require_teacher_for_course(grantee_user_id, summary.course_id)
        with self._atomic_mutation():
            replay = self._repository.claim_idempotency(
                actor_user_id=actor.user_id,
                operation="create_share_grant",
                idempotency_key=idempotency_key,
                resource_type="diagnosis_summary",
                resource_id=diagnosis_id,
                request_fingerprint=fingerprint,
            )
            if replay is not None:
                existing = self._repository.get_grant(replay.result_id)
                if existing is None:
                    raise MemoryConflict(MemoryConflict.public_message)
                return existing
            grant = self._repository.add_grant(
                ShareGrant(
                    grant_id=self._id_factory(),
                    owner_user_id=summary.owner_user_id,
                    course_id=summary.course_id,
                    resource_type="diagnosis_summary",
                    resource_id=summary.diagnosis_id,
                    grantee_user_id=grantee_user_id,
                    purpose=purpose,
                    status=ShareGrantStatus.active,
                    created_at=self._clock(),
                    expires_at=expires_at,
                    revoked_at=None,
                    request_id=request_id,
                )
            )
            self._repository.remember_idempotency_result(
                actor_user_id=actor.user_id,
                operation="create_share_grant",
                idempotency_key=idempotency_key,
                resource_type="diagnosis_summary",
                resource_id=diagnosis_id,
                request_fingerprint=fingerprint,
                result_type="share_grant",
                result_id=grant.grant_id,
            )
            self._audit.record(
                event_type="share_grant_created",
                actor=actor,
                target_type="share_grant",
                target_id=grant.grant_id,
                owner_user_id=grant.owner_user_id,
                course_id=grant.course_id,
                outcome="active",
                reason_code="student_explicit_grant",
                request_id=request_id,
                related_id=diagnosis_id,
            )
            return grant

    def list_share_grants(
        self,
        actor: Actor,
        course_id: str,
        *,
        request_id: str | None = None,
    ) -> tuple[ShareGrant, ...]:
        self._policy.require_student_course(actor, course_id)
        values = tuple(
            self._expire_grant(item)
            for item in self._repository.list_grants(actor.user_id, course_id)
        )
        self._audit.record(
            event_type="share_grants_listed",
            actor=actor,
            target_type="course_share_grant_collection",
            target_id=course_id,
            owner_user_id=actor.user_id,
            course_id=course_id,
            outcome="allowed",
            reason_code="owner_course_match",
            request_id=request_id or f"internal:list-share-grants:{course_id}",
        )
        return values

    def get_share_grant(
        self,
        actor: Actor,
        grant_id: str,
        *,
        request_id: str | None = None,
    ) -> ShareGrant:
        grant = self._repository.get_grant(grant_id)
        if grant is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, grant.owner_user_id, grant.course_id)
        grant = self._expire_grant(grant)
        self._audit.record(
            event_type="share_grant_read",
            actor=actor,
            target_type="share_grant",
            target_id=grant.grant_id,
            owner_user_id=grant.owner_user_id,
            course_id=grant.course_id,
            outcome="allowed",
            reason_code="owner_course_match",
            request_id=request_id or f"internal:get-share-grant:{grant.grant_id}",
            related_id=grant.resource_id,
        )
        return grant

    def revoke_share_grant(
        self,
        actor: Actor,
        grant_id: str,
        *,
        request_id: str,
        idempotency_key: str,
    ) -> ShareGrant:
        idempotency_key = _required_idempotency_key(idempotency_key)
        fingerprint = _request_fingerprint({})
        with self._repository.grant_claim(grant_id):
            with self._atomic_mutation():
                grant = self._repository.get_grant(grant_id)
                if grant is None:
                    raise ResourceNotAvailable()
                self._policy.require_owner(
                    actor, grant.owner_user_id, grant.course_id
                )
                replay = self._repository.claim_idempotency(
                    actor_user_id=actor.user_id,
                    operation="revoke_share_grant",
                    idempotency_key=idempotency_key,
                    resource_type="share_grant",
                    resource_id=grant_id,
                    request_fingerprint=fingerprint,
                )
                if replay is not None:
                    result = self._repository.get_grant(replay.result_id)
                    if result is None:
                        raise MemoryConflict(MemoryConflict.public_message)
                    return result
                grant = self._expire_grant_claimed(grant)
                if grant.status in {
                    ShareGrantStatus.revoked,
                    ShareGrantStatus.expired,
                }:
                    self._repository.remember_idempotency_result(
                        actor_user_id=actor.user_id,
                        operation="revoke_share_grant",
                        idempotency_key=idempotency_key,
                        resource_type="share_grant",
                        resource_id=grant_id,
                        request_fingerprint=fingerprint,
                        result_type="share_grant",
                        result_id=grant.grant_id,
                    )
                    return grant
                revoked = self._repository.save_grant(
                    replace(
                        grant,
                        status=ShareGrantStatus.revoked,
                        revoked_at=self._clock(),
                    )
                )
                self._repository.remember_idempotency_result(
                    actor_user_id=actor.user_id,
                    operation="revoke_share_grant",
                    idempotency_key=idempotency_key,
                    resource_type="share_grant",
                    resource_id=grant_id,
                    request_fingerprint=fingerprint,
                    result_type="share_grant",
                    result_id=revoked.grant_id,
                )
                self._audit.record(
                    event_type="share_grant_revoked",
                    actor=actor,
                    target_type="share_grant",
                    target_id=grant.grant_id,
                    owner_user_id=grant.owner_user_id,
                    course_id=grant.course_id,
                    outcome="revoked",
                    reason_code="student_revoked",
                    request_id=request_id,
                    related_id=grant.resource_id,
                )
                return revoked

    def read_shared_diagnosis(
        self,
        actor: Actor,
        grant_id: str,
        *,
        request_id: str | None = None,
    ) -> DiagnosisSummary:
        with self._repository.grant_claim(grant_id):
            grant = self._repository.get_grant(grant_id)
            if grant is None:
                raise ResourceNotAvailable()
            grant = self._expire_grant_claimed(grant)
            if grant.status is not ShareGrantStatus.active:
                raise ResourceNotAvailable()
            self._policy.require_grantee_teacher(
                actor, grant.grantee_user_id, grant.course_id
            )
            summary = self._source.diagnosis_summary(grant.resource_id)
            if (
                summary is None
                or grant.resource_type != "diagnosis_summary"
                or summary.owner_user_id != grant.owner_user_id
                or summary.course_id != grant.course_id
            ):
                raise ResourceNotAvailable()
            self._audit.record(
                event_type="shared_diagnosis_read",
                actor=actor,
                target_type="diagnosis_summary",
                target_id=summary.diagnosis_id,
                owner_user_id=summary.owner_user_id,
                course_id=summary.course_id,
                outcome="allowed",
                reason_code="active_exact_grant",
                request_id=request_id or f"internal:share-read:{grant.grant_id}",
                related_id=grant.grant_id,
            )
            return summary

    def read_diagnosis_for_teacher(
        self,
        actor: Actor,
        diagnosis_id: str,
        *,
        request_id: str | None = None,
    ) -> DiagnosisSummary:
        summary = self._source.diagnosis_summary(diagnosis_id)
        if summary is None:
            raise ResourceNotAvailable()
        grants = self._repository.grants_for_resource(diagnosis_id)
        for grant in grants:
            current = self._expire_grant(grant)
            if (
                current.status is ShareGrantStatus.active
                and current.grantee_user_id == actor.user_id
                and current.owner_user_id == summary.owner_user_id
                and current.course_id == summary.course_id
            ):
                return self.read_shared_diagnosis(
                    actor, current.grant_id, request_id=request_id
                )
        raise ResourceNotAvailable()

    def _required_owned_proposal(
        self, actor: Actor, proposal_id: str
    ) -> MemoryProposal:
        proposal = self._repository.get_proposal(proposal_id)
        if proposal is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, proposal.owner_user_id, proposal.course_id)
        return proposal

    def _expire_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        with self._repository.proposal_claim(proposal.proposal_id):
            return self._expire_proposal_claimed(proposal)

    def _expire_proposal_claimed(self, proposal: MemoryProposal) -> MemoryProposal:
        current = self._repository.get_proposal(proposal.proposal_id)
        if current is None:
            raise ResourceNotAvailable()
        if (
            current.status is MemoryProposalStatus.pending
            and self._clock() >= current.expires_at
        ):
            current = self._repository.save_proposal(
                replace(current, status=MemoryProposalStatus.expired)
            )
        return current

    def _expire_memory(self, memory: LearningMemory) -> LearningMemory:
        with self._repository.memory_claim(memory.logical_memory_id):
            return self._expire_memory_claimed(memory)

    def _expire_memory_claimed(self, memory: LearningMemory) -> LearningMemory:
        current = self._repository.get_memory(memory.memory_id)
        if current is None:
            raise ResourceNotAvailable()
        if (
            current.status is LearningMemoryStatus.active
            and current.expires_at is not None
            and self._clock() >= current.expires_at
        ):
            current = self._repository.save_memory(
                replace(
                    current,
                    status=LearningMemoryStatus.expired,
                    updated_at=self._clock(),
                )
            )
        return current

    def _active_memories(
        self, owner_user_id: str, course_id: str
    ) -> tuple[LearningMemory, ...]:
        values = tuple(
            self._expire_memory(item)
            for item in self._repository.list_memories(owner_user_id, course_id)
        )
        return tuple(
            item for item in values if item.status is LearningMemoryStatus.active
        )

    def _expire_grant(self, grant: ShareGrant) -> ShareGrant:
        with self._repository.grant_claim(grant.grant_id):
            return self._expire_grant_claimed(grant)

    def _expire_grant_claimed(self, grant: ShareGrant) -> ShareGrant:
        current = self._repository.get_grant(grant.grant_id)
        if current is None:
            raise ResourceNotAvailable()
        if (
            current.status is ShareGrantStatus.active
            and current.expires_at is not None
            and self._clock() >= current.expires_at
        ):
            current = self._repository.save_grant(
                replace(current, status=ShareGrantStatus.expired)
            )
        return current
