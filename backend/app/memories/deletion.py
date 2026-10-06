from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Callable
from uuid import uuid4

from app.audit.service import AuditLog
from app.auth.models import Actor
from app.courses.service import ResourceNotAvailable
from app.memories.models import (
    DeletionReceipt,
    DeletionStatus,
    LearningMemoryStatus,
    ShareGrantStatus,
)
from app.memories.policy import MemoryPolicy
from app.memories.repository import MemoryRepository
from app.memories.retrieval import RetrievalDeletionError, RetrievalIndex


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DeletionService:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        policy: MemoryPolicy,
        retrieval_index: RetrievalIndex,
        audit: AuditLog,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._index = retrieval_index
        self._audit = audit
        self._clock = clock
        self._id_factory = id_factory

    @contextmanager
    def _atomic_mutation(self):
        with self._repository.transaction():
            with self._audit.transaction():
                yield

    def delete_memory(
        self, actor: Actor, memory_id: str, *, request_id: str
    ) -> DeletionReceipt:
        memory = self._repository.get_memory(memory_id)
        if memory is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(actor, memory.owner_user_id, memory.course_id)
        with self._repository.memory_claim(memory.logical_memory_id):
            memory = self._repository.get_memory(memory_id)
            if memory is None:
                raise ResourceNotAvailable()
            self._policy.require_owner(
                actor, memory.owner_user_id, memory.course_id
            )
            existing = self._repository.get_deletion_for_memory(
                memory.logical_memory_id
            )
            if existing is not None:
                return existing
            deletion_id = self._id_factory()
            with self._repository.deletion_claim(deletion_id):
                with self._atomic_mutation():
                    existing = self._repository.get_deletion_for_memory(
                        memory.logical_memory_id
                    )
                    if existing is not None:
                        return existing
                    now = self._clock()
                    lineage = self._repository.memory_lineage(
                        memory.logical_memory_id
                    )
                    for version in lineage:
                        self._repository.save_memory(
                            replace(
                                version,
                                content=None,
                                status=LearningMemoryStatus.deletion_pending,
                                updated_at=now,
                            )
                        )
                        for grant in self._repository.grants_for_resource(
                            version.source_diagnosis_id
                        ):
                            if grant.status is ShareGrantStatus.active:
                                self._repository.save_grant(
                                    replace(
                                        grant,
                                        status=ShareGrantStatus.revoked,
                                        revoked_at=now,
                                    )
                                )
                    receipt = self._repository.add_deletion(
                        DeletionReceipt(
                            deletion_id=deletion_id,
                            memory_id=memory.logical_memory_id,
                            owner_user_id=memory.owner_user_id,
                            course_id=memory.course_id,
                            status=DeletionStatus.deletion_pending,
                            requested_at=now,
                            completed_at=None,
                            attempts=0,
                            index_cleared=False,
                            cache_cleared=True,
                            model_references_cleared=True,
                            reverse_lookup_absent=False,
                            error_code=None,
                            request_id=request_id,
                        )
                    )
                    self._audit.record(
                        event_type="learning_memory_deletion_requested",
                        actor=actor,
                        target_type="learning_memory",
                        target_id=memory.logical_memory_id,
                        owner_user_id=memory.owner_user_id,
                        course_id=memory.course_id,
                        outcome="deletion_pending",
                        reason_code="student_deleted",
                        request_id=request_id,
                        related_id=deletion_id,
                    )
        return self._run_claimed_attempt(
            actor, receipt.deletion_id, request_id=request_id
        )

    def retry(
        self, actor: Actor, deletion_id: str, *, request_id: str
    ) -> DeletionReceipt:
        receipt = self._repository.get_deletion(deletion_id)
        if receipt is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(
            actor, receipt.owner_user_id, receipt.course_id
        )
        return self._run_claimed_attempt(actor, deletion_id, request_id=request_id)

    def _run_claimed_attempt(
        self, actor: Actor, deletion_id: str, *, request_id: str
    ) -> DeletionReceipt:
        with self._repository.deletion_claim(deletion_id):
            receipt = self._repository.get_deletion(deletion_id)
            if receipt is None:
                raise ResourceNotAvailable()
            self._policy.require_owner(
                actor, receipt.owner_user_id, receipt.course_id
            )
            if receipt.status is DeletionStatus.deleted:
                return receipt
            return self._attempt(actor, receipt, request_id=request_id)

    def get_status(
        self,
        actor: Actor,
        deletion_id: str,
        *,
        request_id: str | None = None,
    ) -> DeletionReceipt:
        receipt = self._repository.get_deletion(deletion_id)
        if receipt is None:
            raise ResourceNotAvailable()
        self._policy.require_owner(
            actor, receipt.owner_user_id, receipt.course_id
        )
        self._audit.record(
            event_type="learning_memory_deletion_status_read",
            actor=actor,
            target_type="memory_deletion",
            target_id=receipt.deletion_id,
            owner_user_id=receipt.owner_user_id,
            course_id=receipt.course_id,
            outcome="allowed",
            reason_code="owner_course_match",
            request_id=request_id or f"internal:get-deletion:{receipt.deletion_id}",
            related_id=receipt.memory_id,
        )
        return receipt

    def _attempt(
        self, actor: Actor, receipt: DeletionReceipt, *, request_id: str
    ) -> DeletionReceipt:
        lineage = self._repository.memory_lineage(receipt.memory_id)
        document_ids = frozenset(item.index_document_id for item in lineage)
        attempts = receipt.attempts + 1
        try:
            for document_id in document_ids:
                self._index.delete(document_id)
        except RetrievalDeletionError:
            with self._atomic_mutation():
                pending = self._repository.save_deletion(
                    replace(
                        receipt,
                        attempts=attempts,
                        index_cleared=False,
                        reverse_lookup_absent=False,
                        error_code="INDEX_DELETE_FAILED",
                    )
                )
                self._audit.record(
                    event_type="learning_memory_deletion_attempted",
                    actor=actor,
                    target_type="learning_memory",
                    target_id=receipt.memory_id,
                    owner_user_id=receipt.owner_user_id,
                    course_id=receipt.course_id,
                    outcome="deletion_pending",
                    reason_code="index_delete_failed",
                    request_id=request_id,
                    related_id=receipt.deletion_id,
                )
                return pending
        reverse_lookup_absent = self._index.verify_absent(document_ids)
        if not reverse_lookup_absent:
            with self._atomic_mutation():
                pending = self._repository.save_deletion(
                    replace(
                        receipt,
                        attempts=attempts,
                        index_cleared=True,
                        reverse_lookup_absent=False,
                        error_code="REVERSE_LOOKUP_NOT_EMPTY",
                    )
                )
                self._audit.record(
                    event_type="learning_memory_deletion_verified",
                    actor=actor,
                    target_type="learning_memory",
                    target_id=receipt.memory_id,
                    owner_user_id=receipt.owner_user_id,
                    course_id=receipt.course_id,
                    outcome="deletion_pending",
                    reason_code="reverse_lookup_not_empty",
                    request_id=request_id,
                    related_id=receipt.deletion_id,
                )
                return pending
        now = self._clock()
        with self._atomic_mutation():
            for version in lineage:
                current = self._repository.get_memory(version.memory_id)
                if current is None:
                    continue
                self._repository.save_memory(
                    replace(
                        current,
                        content=None,
                        status=LearningMemoryStatus.deleted,
                        updated_at=now,
                    )
                )
            completed = self._repository.save_deletion(
                replace(
                    receipt,
                    status=DeletionStatus.deleted,
                    completed_at=now,
                    attempts=attempts,
                    index_cleared=True,
                    reverse_lookup_absent=True,
                    error_code=None,
                )
            )
            self._audit.record(
                event_type="learning_memory_deletion_completed",
                actor=actor,
                target_type="learning_memory",
                target_id=receipt.memory_id,
                owner_user_id=receipt.owner_user_id,
                course_id=receipt.course_id,
                outcome="deleted",
                reason_code="derived_data_absent",
                request_id=request_id,
                related_id=receipt.deletion_id,
            )
            return completed
