from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock, RLock
from typing import ContextManager, Protocol

from app.memories.models import (
    DeletionReceipt,
    DeletionStatus,
    LearningMemory,
    LearningMemoryStatus,
    MemoryProposal,
    ShareGrant,
    ShareGrantStatus,
)


class IdempotencyConflict(RuntimeError):
    public_error_code = "IDEMPOTENCY_KEY_REUSED"
    public_message = "The idempotency key was already used for another request."


@dataclass(frozen=True, slots=True)
class IdempotencyReplay:
    actor_user_id: str
    operation: str
    idempotency_key: str
    resource_type: str
    resource_id: str
    request_fingerprint: str
    result_type: str
    result_id: str


class MemoryRepository(Protocol):
    def transaction(self) -> ContextManager[None]: ...
    def proposal_source_claim(
        self, explanation_check_id: str
    ) -> ContextManager[None]: ...
    def proposal_claim(self, proposal_id: str) -> ContextManager[None]: ...
    def memory_claim(self, logical_memory_id: str) -> ContextManager[None]: ...
    def deletion_claim(self, deletion_id: str) -> ContextManager[None]: ...
    def grant_claim(self, grant_id: str) -> ContextManager[None]: ...
    def add_proposal(self, proposal: MemoryProposal) -> MemoryProposal: ...
    def add_corrected_proposal(self, proposal: MemoryProposal) -> MemoryProposal: ...
    def get_proposal(self, proposal_id: str) -> MemoryProposal | None: ...
    def get_proposal_for_explanation(
        self, explanation_check_id: str
    ) -> MemoryProposal | None: ...
    def proposal_successor(self, proposal_id: str) -> MemoryProposal | None: ...
    def get_proposal_correction_result(
        self, proposal_id: str, request_id: str
    ) -> MemoryProposal | None: ...
    def remember_proposal_correction_result(
        self, proposal_id: str, request_id: str, result: MemoryProposal
    ) -> None: ...
    def save_proposal(self, proposal: MemoryProposal) -> MemoryProposal: ...
    def list_proposals(
        self, owner_user_id: str, course_id: str
    ) -> tuple[MemoryProposal, ...]: ...
    def add_memory(self, memory: LearningMemory) -> LearningMemory: ...
    def add_corrected_memory(self, memory: LearningMemory) -> LearningMemory: ...
    def get_memory(self, memory_id: str) -> LearningMemory | None: ...
    def get_memory_for_proposal(self, proposal_id: str) -> LearningMemory | None: ...
    def memory_successor(self, memory_id: str) -> LearningMemory | None: ...
    def get_memory_correction_result(
        self, memory_id: str, request_id: str
    ) -> LearningMemory | None: ...
    def remember_memory_correction_result(
        self, memory_id: str, request_id: str, result: LearningMemory
    ) -> None: ...
    def get_memory_by_index_document_id(
        self, index_document_id: str
    ) -> LearningMemory | None: ...
    def save_memory(self, memory: LearningMemory) -> LearningMemory: ...
    def list_memories(
        self, owner_user_id: str, course_id: str
    ) -> tuple[LearningMemory, ...]: ...
    def memory_lineage(
        self, logical_memory_id: str
    ) -> tuple[LearningMemory, ...]: ...
    def add_grant(self, grant: ShareGrant) -> ShareGrant: ...
    def get_grant(self, grant_id: str) -> ShareGrant | None: ...
    def save_grant(self, grant: ShareGrant) -> ShareGrant: ...
    def list_grants(
        self, owner_user_id: str, course_id: str
    ) -> tuple[ShareGrant, ...]: ...
    def grants_for_resource(self, resource_id: str) -> tuple[ShareGrant, ...]: ...
    def add_deletion(self, receipt: DeletionReceipt) -> DeletionReceipt: ...
    def get_deletion(self, deletion_id: str) -> DeletionReceipt | None: ...
    def get_deletion_for_memory(
        self, logical_memory_id: str
    ) -> DeletionReceipt | None: ...
    def save_deletion(self, receipt: DeletionReceipt) -> DeletionReceipt: ...
    def pending_deletions(self) -> tuple[DeletionReceipt, ...]: ...
    def claim_idempotency(
        self,
        *,
        actor_user_id: str,
        operation: str,
        idempotency_key: str,
        resource_type: str,
        resource_id: str,
        request_fingerprint: str,
    ) -> IdempotencyReplay | None: ...
    def remember_idempotency_result(
        self,
        *,
        actor_user_id: str,
        operation: str,
        idempotency_key: str,
        resource_type: str,
        resource_id: str,
        request_fingerprint: str,
        result_type: str,
        result_id: str,
    ) -> None: ...


class InMemoryMemoryRepository:
    """Task 7 reference store; SQL persistence belongs to the Gate."""

    def __init__(self) -> None:
        self._proposals: dict[str, MemoryProposal] = {}
        self._proposal_by_explanation: dict[str, str] = {}
        self._proposal_successor: dict[str, str] = {}
        self._proposal_correction_results: dict[tuple[str, str], str] = {}
        self._memories: dict[str, LearningMemory] = {}
        self._memory_by_proposal: dict[str, str] = {}
        self._memory_successor: dict[str, str] = {}
        self._memory_correction_results: dict[tuple[str, str], str] = {}
        self._grants: dict[str, ShareGrant] = {}
        self._deletions: dict[str, DeletionReceipt] = {}
        self._deletion_by_logical_memory: dict[str, str] = {}
        self._idempotency: dict[tuple[str, str, str], IdempotencyReplay] = {}
        self._lock = RLock()
        self._claim_registry_lock = Lock()
        self._claim_locks: dict[tuple[str, str], RLock] = {}

    def _claim_lock(self, claim_type: str, resource_id: str) -> RLock:
        key = (claim_type, resource_id)
        with self._claim_registry_lock:
            return self._claim_locks.setdefault(key, RLock())

    @contextmanager
    def transaction(self):
        with self._lock:
            snapshots = (
                self._proposals.copy(),
                self._proposal_by_explanation.copy(),
                self._proposal_successor.copy(),
                self._proposal_correction_results.copy(),
                self._memories.copy(),
                self._memory_by_proposal.copy(),
                self._memory_successor.copy(),
                self._memory_correction_results.copy(),
                self._grants.copy(),
                self._deletions.copy(),
                self._deletion_by_logical_memory.copy(),
                self._idempotency.copy(),
            )
            try:
                yield
            except BaseException:
                (
                    self._proposals,
                    self._proposal_by_explanation,
                    self._proposal_successor,
                    self._proposal_correction_results,
                    self._memories,
                    self._memory_by_proposal,
                    self._memory_successor,
                    self._memory_correction_results,
                    self._grants,
                    self._deletions,
                    self._deletion_by_logical_memory,
                    self._idempotency,
                ) = snapshots
                raise

    @contextmanager
    def proposal_source_claim(self, explanation_check_id: str):
        with self._claim_lock("proposal_source", explanation_check_id):
            yield

    @contextmanager
    def proposal_claim(self, proposal_id: str):
        with self._claim_lock("proposal", proposal_id):
            yield

    @contextmanager
    def memory_claim(self, logical_memory_id: str):
        with self._claim_lock("memory", logical_memory_id):
            yield

    @contextmanager
    def deletion_claim(self, deletion_id: str):
        with self._claim_lock("deletion", deletion_id):
            yield

    @contextmanager
    def grant_claim(self, grant_id: str):
        with self._claim_lock("grant", grant_id):
            yield

    def add_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        with self._lock:
            existing_id = self._proposal_by_explanation.get(
                proposal.explanation_check_id
            )
            if existing_id is not None:
                return self._proposals[existing_id]
            self._proposals[proposal.proposal_id] = proposal
            self._proposal_by_explanation[proposal.explanation_check_id] = (
                proposal.proposal_id
            )
            if proposal.previous_proposal_id is not None:
                self._proposal_successor[proposal.previous_proposal_id] = (
                    proposal.proposal_id
                )
            return proposal

    def add_corrected_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        with self._lock:
            if proposal.previous_proposal_id in self._proposal_successor:
                return self._proposals[
                    self._proposal_successor[proposal.previous_proposal_id]
                ]
            self._proposals[proposal.proposal_id] = proposal
            self._proposal_successor[proposal.previous_proposal_id] = proposal.proposal_id
            return proposal

    def get_proposal(self, proposal_id: str) -> MemoryProposal | None:
        with self._lock:
            return self._proposals.get(proposal_id)

    def get_proposal_for_explanation(
        self, explanation_check_id: str
    ) -> MemoryProposal | None:
        with self._lock:
            proposal_id = self._proposal_by_explanation.get(explanation_check_id)
            return self._proposals.get(proposal_id) if proposal_id else None

    def proposal_successor(self, proposal_id: str) -> MemoryProposal | None:
        with self._lock:
            successor_id = self._proposal_successor.get(proposal_id)
            return self._proposals.get(successor_id) if successor_id else None

    def get_proposal_correction_result(
        self, proposal_id: str, request_id: str
    ) -> MemoryProposal | None:
        with self._lock:
            result_id = self._proposal_correction_results.get(
                (proposal_id, request_id)
            )
            return self._proposals.get(result_id) if result_id else None

    def remember_proposal_correction_result(
        self, proposal_id: str, request_id: str, result: MemoryProposal
    ) -> None:
        with self._lock:
            self._proposal_correction_results[(proposal_id, request_id)] = (
                result.proposal_id
            )

    def save_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal
            return proposal

    def list_proposals(self, owner_user_id: str, course_id: str) -> tuple[MemoryProposal, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._proposals.values()
                        if item.owner_user_id == owner_user_id
                        and item.course_id == course_id
                    ),
                    key=lambda item: (item.created_at, item.proposal_id),
                )
            )

    def add_memory(self, memory: LearningMemory) -> LearningMemory:
        with self._lock:
            existing_id = self._memory_by_proposal.get(memory.source_proposal_id)
            if existing_id is not None:
                return self._memories[existing_id]
            self._memories[memory.memory_id] = memory
            self._memory_by_proposal[memory.source_proposal_id] = memory.memory_id
            if memory.previous_version_id is not None:
                self._memory_successor[memory.previous_version_id] = memory.memory_id
            return memory

    def add_corrected_memory(self, memory: LearningMemory) -> LearningMemory:
        with self._lock:
            if memory.previous_version_id in self._memory_successor:
                return self._memories[
                    self._memory_successor[memory.previous_version_id]
                ]
            self._memories[memory.memory_id] = memory
            self._memory_successor[memory.previous_version_id] = memory.memory_id
            return memory

    def get_memory(self, memory_id: str) -> LearningMemory | None:
        with self._lock:
            return self._memories.get(memory_id)

    def get_memory_for_proposal(self, proposal_id: str) -> LearningMemory | None:
        with self._lock:
            memory_id = self._memory_by_proposal.get(proposal_id)
            return self._memories.get(memory_id) if memory_id else None

    def memory_successor(self, memory_id: str) -> LearningMemory | None:
        with self._lock:
            successor_id = self._memory_successor.get(memory_id)
            return self._memories.get(successor_id) if successor_id else None

    def get_memory_correction_result(
        self, memory_id: str, request_id: str
    ) -> LearningMemory | None:
        with self._lock:
            result_id = self._memory_correction_results.get((memory_id, request_id))
            return self._memories.get(result_id) if result_id else None

    def remember_memory_correction_result(
        self, memory_id: str, request_id: str, result: LearningMemory
    ) -> None:
        with self._lock:
            self._memory_correction_results[(memory_id, request_id)] = result.memory_id

    def get_memory_by_index_document_id(
        self, index_document_id: str
    ) -> LearningMemory | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self._memories.values()
                    if item.index_document_id == index_document_id
                ),
                None,
            )

    def save_memory(self, memory: LearningMemory) -> LearningMemory:
        with self._lock:
            current = self._memories.get(memory.memory_id)
            if current is None:
                self._memories[memory.memory_id] = memory
                return memory
            if current.status is LearningMemoryStatus.deleted:
                return current
            if (
                current.status is LearningMemoryStatus.deletion_pending
                and memory.status
                not in {
                    LearningMemoryStatus.deletion_pending,
                    LearningMemoryStatus.deleted,
                }
            ):
                return current
            self._memories[memory.memory_id] = memory
            return memory

    def list_memories(self, owner_user_id: str, course_id: str) -> tuple[LearningMemory, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._memories.values()
                        if item.owner_user_id == owner_user_id
                        and item.course_id == course_id
                    ),
                    key=lambda item: (item.created_at, item.memory_id),
                )
            )

    def memory_lineage(self, logical_memory_id: str) -> tuple[LearningMemory, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._memories.values()
                        if item.logical_memory_id == logical_memory_id
                    ),
                    key=lambda item: item.version,
                )
            )

    def all_memories(self) -> tuple[LearningMemory, ...]:
        with self._lock:
            return tuple(self._memories.values())

    def add_grant(self, grant: ShareGrant) -> ShareGrant:
        with self._lock:
            existing = next(
                (
                    item
                    for item in self._grants.values()
                    if item.owner_user_id == grant.owner_user_id
                    and item.resource_id == grant.resource_id
                    and item.grantee_user_id == grant.grantee_user_id
                    and item.purpose == grant.purpose
                    and item.status is ShareGrantStatus.active
                ),
                None,
            )
            if existing is not None:
                return existing
            self._grants[grant.grant_id] = grant
            return grant

    def get_grant(self, grant_id: str) -> ShareGrant | None:
        with self._lock:
            return self._grants.get(grant_id)

    def save_grant(self, grant: ShareGrant) -> ShareGrant:
        with self._lock:
            self._grants[grant.grant_id] = grant
            return grant

    def list_grants(self, owner_user_id: str, course_id: str) -> tuple[ShareGrant, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._grants.values()
                        if item.owner_user_id == owner_user_id
                        and item.course_id == course_id
                    ),
                    key=lambda item: (item.created_at, item.grant_id),
                )
            )

    def grants_for_resource(self, resource_id: str) -> tuple[ShareGrant, ...]:
        with self._lock:
            return tuple(
                item for item in self._grants.values() if item.resource_id == resource_id
            )

    def add_deletion(self, receipt: DeletionReceipt) -> DeletionReceipt:
        with self._lock:
            existing_id = self._deletion_by_logical_memory.get(receipt.memory_id)
            if existing_id is not None:
                return self._deletions[existing_id]
            self._deletions[receipt.deletion_id] = receipt
            self._deletion_by_logical_memory[receipt.memory_id] = receipt.deletion_id
            return receipt

    def get_deletion(self, deletion_id: str) -> DeletionReceipt | None:
        with self._lock:
            return self._deletions.get(deletion_id)

    def get_deletion_for_memory(
        self, logical_memory_id: str
    ) -> DeletionReceipt | None:
        with self._lock:
            deletion_id = self._deletion_by_logical_memory.get(logical_memory_id)
            return self._deletions.get(deletion_id) if deletion_id else None

    def save_deletion(self, receipt: DeletionReceipt) -> DeletionReceipt:
        with self._lock:
            current = self._deletions.get(receipt.deletion_id)
            if current is not None and current.status is DeletionStatus.deleted:
                return current
            self._deletions[receipt.deletion_id] = receipt
            return receipt

    def pending_deletions(self) -> tuple[DeletionReceipt, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._deletions.values()
                if item.status is DeletionStatus.deletion_pending
            )

    def all_deletions(self) -> tuple[DeletionReceipt, ...]:
        with self._lock:
            return tuple(self._deletions.values())

    def claim_idempotency(
        self,
        *,
        actor_user_id: str,
        operation: str,
        idempotency_key: str,
        resource_type: str,
        resource_id: str,
        request_fingerprint: str,
    ) -> IdempotencyReplay | None:
        with self._lock:
            replay = self._idempotency.get(
                (actor_user_id, operation, idempotency_key)
            )
            if replay is None:
                return None
            if (
                replay.resource_type != resource_type
                or replay.resource_id != resource_id
                or replay.request_fingerprint != request_fingerprint
            ):
                raise IdempotencyConflict(IdempotencyConflict.public_message)
            return replay

    def remember_idempotency_result(
        self,
        *,
        actor_user_id: str,
        operation: str,
        idempotency_key: str,
        resource_type: str,
        resource_id: str,
        request_fingerprint: str,
        result_type: str,
        result_id: str,
    ) -> None:
        replay = IdempotencyReplay(
            actor_user_id=actor_user_id,
            operation=operation,
            idempotency_key=idempotency_key,
            resource_type=resource_type,
            resource_id=resource_id,
            request_fingerprint=request_fingerprint,
            result_type=result_type,
            result_id=result_id,
        )
        with self._lock:
            existing = self.claim_idempotency(
                actor_user_id=actor_user_id,
                operation=operation,
                idempotency_key=idempotency_key,
                resource_type=resource_type,
                resource_id=resource_id,
                request_fingerprint=request_fingerprint,
            )
            if existing is not None and existing != replay:
                raise IdempotencyConflict(IdempotencyConflict.public_message)
            self._idempotency[(actor_user_id, operation, idempotency_key)] = replay
