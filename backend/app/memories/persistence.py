from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.memories.models import (
    DeletionReceipt,
    DeletionStatus,
    LearningMemory,
    LearningMemoryStatus,
    MemoryProposal,
    MemoryProposalStatus,
    ShareGrant,
    ShareGrantStatus,
)
from app.memories.repository import (
    IdempotencyConflict,
    IdempotencyReplay,
)
from app.persistence.models import (
    LearningMemoryRow,
    MemoryDeletionRow,
    MemoryIdempotencyResultRow,
    MemoryProposalRow,
    MemoryTombstoneRow,
    ShareGrantRow,
)


class MemoryPersistenceError(RuntimeError):
    pass


def _constraint_name(error: SQLAlchemyError) -> str | None:
    driver_error = getattr(error, "orig", None)
    diagnostics = getattr(driver_error, "diag", None)
    return getattr(diagnostics, "constraint_name", None)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqlMemoryUnitOfWork:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self._current: ContextVar[Session | None] = ContextVar(
            f"memory_session_{id(self)}", default=None
        )

    @property
    def active_session(self) -> Session | None:
        return self._current.get()

    def require_session(self) -> Session:
        session = self.active_session
        if session is None:
            raise MemoryPersistenceError("memory storage operation failed")
        return session

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.active_session is not None:
            yield
            return
        try:
            with self.sessions.begin() as session:
                token = self._current.set(session)
                try:
                    yield
                    session.flush()
                finally:
                    self._current.reset(token)
        except SQLAlchemyError as error:
            if _constraint_name(error) == "uq_memory_idempotency_scope":
                raise IdempotencyConflict(IdempotencyConflict.public_message) from error
            raise MemoryPersistenceError("memory storage operation failed") from error

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        active = self.active_session
        if active is not None:
            yield active
            return
        try:
            with self.sessions() as session:
                yield session
        except SQLAlchemyError as error:
            raise MemoryPersistenceError("memory storage operation failed") from error


class SqlMemoryRepository:
    def __init__(self, uow: SqlMemoryUnitOfWork) -> None:
        self.uow = uow

    def transaction(self):
        return self.uow.transaction()

    @contextmanager
    def proposal_claim(self, proposal_id: str):
        with self.uow.transaction():
            self.uow.require_session().execute(
                select(MemoryProposalRow.id)
                .where(MemoryProposalRow.id == proposal_id)
                .with_for_update()
            ).all()
            yield

    @contextmanager
    def memory_claim(self, logical_memory_id: str):
        with self.uow.transaction():
            self.uow.require_session().execute(
                select(LearningMemoryRow.id)
                .where(LearningMemoryRow.logical_memory_id == logical_memory_id)
                .order_by(LearningMemoryRow.version, LearningMemoryRow.id)
                .with_for_update()
            ).all()
            yield

    @contextmanager
    def deletion_claim(self, deletion_id: str):
        with self.uow.transaction():
            self.uow.require_session().execute(
                select(MemoryDeletionRow.id)
                .where(MemoryDeletionRow.id == deletion_id)
                .with_for_update()
            ).all()
            yield

    @contextmanager
    def grant_claim(self, grant_id: str):
        with self.uow.transaction():
            self.uow.require_session().execute(
                select(ShareGrantRow.id)
                .where(ShareGrantRow.id == grant_id)
                .with_for_update()
            ).all()
            yield

    def add_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        session = self.uow.require_session()
        existing = session.scalar(
            select(MemoryProposalRow).where(
                MemoryProposalRow.explanation_check_id
                == proposal.explanation_check_id
            )
        )
        if existing is not None:
            return self._proposal(session, existing)
        session.add(_proposal_row(proposal))
        session.flush()
        return proposal

    def add_corrected_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        session = self.uow.require_session()
        existing = session.scalar(
            select(MemoryProposalRow).where(
                MemoryProposalRow.previous_proposal_id
                == proposal.previous_proposal_id
            )
        )
        if existing is not None:
            return self._proposal(session, existing)
        session.add(_proposal_row(proposal))
        session.flush()
        return proposal

    def get_proposal(self, proposal_id: str) -> MemoryProposal | None:
        with self.uow.read_session() as session:
            row = session.get(MemoryProposalRow, proposal_id)
            return self._proposal(session, row) if row is not None else None

    def get_proposal_for_explanation(
        self, explanation_check_id: str
    ) -> MemoryProposal | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(MemoryProposalRow).where(
                    MemoryProposalRow.explanation_check_id == explanation_check_id
                )
            )
            return self._proposal(session, row) if row is not None else None

    def proposal_successor(self, proposal_id: str) -> MemoryProposal | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(MemoryProposalRow).where(
                    MemoryProposalRow.previous_proposal_id == proposal_id
                )
            )
            return self._proposal(session, row) if row is not None else None

    def get_proposal_correction_result(
        self, proposal_id: str, request_id: str
    ) -> MemoryProposal | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(MemoryProposalRow).where(
                    MemoryProposalRow.previous_proposal_id == proposal_id,
                    MemoryProposalRow.request_id == request_id,
                )
            )
            return self._proposal(session, row) if row is not None else None

    def remember_proposal_correction_result(
        self, proposal_id: str, request_id: str, result: MemoryProposal
    ) -> None:
        return None

    def save_proposal(self, proposal: MemoryProposal) -> MemoryProposal:
        session = self.uow.require_session()
        row = session.get(MemoryProposalRow, proposal.proposal_id)
        if row is None:
            raise MemoryPersistenceError("memory storage operation failed")
        _set_proposal(row, proposal)
        session.flush()
        return proposal

    def list_proposals(
        self, owner_user_id: str, course_id: str
    ) -> tuple[MemoryProposal, ...]:
        with self.uow.read_session() as session:
            rows = session.scalars(
                select(MemoryProposalRow)
                .where(
                    MemoryProposalRow.owner_user_id == owner_user_id,
                    MemoryProposalRow.course_id == course_id,
                )
                .order_by(MemoryProposalRow.created_at, MemoryProposalRow.id)
            ).all()
            return tuple(self._proposal(session, row) for row in rows)

    def add_memory(self, memory: LearningMemory) -> LearningMemory:
        session = self.uow.require_session()
        existing = session.scalar(
            select(LearningMemoryRow).where(
                LearningMemoryRow.source_proposal_id == memory.source_proposal_id
            )
        )
        if existing is not None:
            return _memory(existing)
        session.add(_memory_row(memory))
        session.flush()
        return memory

    def add_corrected_memory(self, memory: LearningMemory) -> LearningMemory:
        session = self.uow.require_session()
        existing = session.scalar(
            select(LearningMemoryRow).where(
                LearningMemoryRow.previous_version_id == memory.previous_version_id
            )
        )
        if existing is not None:
            return _memory(existing)
        session.add(_memory_row(memory))
        session.flush()
        return memory

    def get_memory(self, memory_id: str) -> LearningMemory | None:
        with self.uow.read_session() as session:
            row = session.get(LearningMemoryRow, memory_id)
            return _memory(row) if row is not None else None

    def get_memory_for_proposal(self, proposal_id: str) -> LearningMemory | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(LearningMemoryRow).where(
                    LearningMemoryRow.source_proposal_id == proposal_id
                )
            )
            return _memory(row) if row is not None else None

    def memory_successor(self, memory_id: str) -> LearningMemory | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(LearningMemoryRow).where(
                    LearningMemoryRow.previous_version_id == memory_id
                )
            )
            return _memory(row) if row is not None else None

    def get_memory_correction_result(
        self, memory_id: str, request_id: str
    ) -> LearningMemory | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(LearningMemoryRow).where(
                    LearningMemoryRow.previous_version_id == memory_id,
                    LearningMemoryRow.request_id == request_id,
                )
            )
            return _memory(row) if row is not None else None

    def remember_memory_correction_result(
        self, memory_id: str, request_id: str, result: LearningMemory
    ) -> None:
        return None

    def get_memory_by_index_document_id(
        self, index_document_id: str
    ) -> LearningMemory | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(LearningMemoryRow).where(
                    LearningMemoryRow.index_document_id == index_document_id
                )
            )
            return _memory(row) if row is not None else None

    def save_memory(self, memory: LearningMemory) -> LearningMemory:
        session = self.uow.require_session()
        row = session.get(LearningMemoryRow, memory.memory_id)
        if row is None:
            raise MemoryPersistenceError("memory storage operation failed")
        _set_memory(row, memory)
        session.flush()
        return memory

    def list_memories(
        self, owner_user_id: str, course_id: str
    ) -> tuple[LearningMemory, ...]:
        with self.uow.read_session() as session:
            rows = session.scalars(
                select(LearningMemoryRow)
                .where(
                    LearningMemoryRow.owner_user_id == owner_user_id,
                    LearningMemoryRow.course_id == course_id,
                )
                .order_by(LearningMemoryRow.created_at, LearningMemoryRow.id)
            ).all()
            return tuple(_memory(row) for row in rows)

    def memory_lineage(
        self, logical_memory_id: str
    ) -> tuple[LearningMemory, ...]:
        with self.uow.read_session() as session:
            rows = session.scalars(
                select(LearningMemoryRow)
                .where(LearningMemoryRow.logical_memory_id == logical_memory_id)
                .order_by(LearningMemoryRow.version, LearningMemoryRow.id)
            ).all()
            return tuple(_memory(row) for row in rows)

    def all_memories(self) -> tuple[LearningMemory, ...]:
        with self.uow.read_session() as session:
            return tuple(_memory(row) for row in session.scalars(select(LearningMemoryRow)))

    def add_grant(self, grant: ShareGrant) -> ShareGrant:
        session = self.uow.require_session()
        existing = session.scalar(
            select(ShareGrantRow).where(
                ShareGrantRow.owner_user_id == grant.owner_user_id,
                ShareGrantRow.resource_id == grant.resource_id,
                ShareGrantRow.grantee_user_id == grant.grantee_user_id,
                ShareGrantRow.purpose == grant.purpose,
            )
        )
        if existing is not None:
            return _grant(existing)
        session.add(_grant_row(grant))
        session.flush()
        return grant

    def get_grant(self, grant_id: str) -> ShareGrant | None:
        with self.uow.read_session() as session:
            row = session.get(ShareGrantRow, grant_id)
            return _grant(row) if row is not None else None

    def save_grant(self, grant: ShareGrant) -> ShareGrant:
        session = self.uow.require_session()
        row = session.get(ShareGrantRow, grant.grant_id)
        if row is None:
            raise MemoryPersistenceError("memory storage operation failed")
        _set_grant(row, grant)
        session.flush()
        return grant

    def list_grants(
        self, owner_user_id: str, course_id: str
    ) -> tuple[ShareGrant, ...]:
        with self.uow.read_session() as session:
            rows = session.scalars(
                select(ShareGrantRow)
                .where(
                    ShareGrantRow.owner_user_id == owner_user_id,
                    ShareGrantRow.course_id == course_id,
                )
                .order_by(ShareGrantRow.created_at, ShareGrantRow.id)
            ).all()
            return tuple(_grant(row) for row in rows)

    def grants_for_resource(self, resource_id: str) -> tuple[ShareGrant, ...]:
        with self.uow.read_session() as session:
            rows = session.scalars(
                select(ShareGrantRow).where(ShareGrantRow.resource_id == resource_id)
            ).all()
            return tuple(_grant(row) for row in rows)

    def add_deletion(self, receipt: DeletionReceipt) -> DeletionReceipt:
        session = self.uow.require_session()
        existing = session.scalar(
            select(MemoryDeletionRow).where(
                MemoryDeletionRow.logical_memory_id == receipt.memory_id
            )
        )
        if existing is not None:
            return _deletion(existing)
        session.add(_deletion_row(receipt))
        session.flush()
        session.add(
            MemoryTombstoneRow(
                logical_memory_id=receipt.memory_id,
                deletion_id=receipt.deletion_id,
                owner_user_id=receipt.owner_user_id,
                course_id=receipt.course_id,
                created_at=receipt.requested_at,
            )
        )
        session.flush()
        return receipt

    def get_deletion(self, deletion_id: str) -> DeletionReceipt | None:
        with self.uow.read_session() as session:
            row = session.get(MemoryDeletionRow, deletion_id)
            return _deletion(row) if row is not None else None

    def get_deletion_for_memory(
        self, logical_memory_id: str
    ) -> DeletionReceipt | None:
        with self.uow.read_session() as session:
            row = session.scalar(
                select(MemoryDeletionRow).where(
                    MemoryDeletionRow.logical_memory_id == logical_memory_id
                )
            )
            return _deletion(row) if row is not None else None

    def save_deletion(self, receipt: DeletionReceipt) -> DeletionReceipt:
        session = self.uow.require_session()
        row = session.get(MemoryDeletionRow, receipt.deletion_id)
        if row is None:
            raise MemoryPersistenceError("memory storage operation failed")
        _set_deletion(row, receipt)
        session.flush()
        return receipt

    def all_deletions(self) -> tuple[DeletionReceipt, ...]:
        with self.uow.read_session() as session:
            return tuple(_deletion(row) for row in session.scalars(select(MemoryDeletionRow)))

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
        with self.uow.read_session() as session:
            statement = select(MemoryIdempotencyResultRow).where(
                MemoryIdempotencyResultRow.actor_user_id == actor_user_id,
                MemoryIdempotencyResultRow.operation == operation,
                MemoryIdempotencyResultRow.idempotency_key == idempotency_key,
            )
            if self.uow.active_session is not None:
                statement = statement.with_for_update()
            row = session.scalar(statement)
            if row is None:
                return None
            replay = _idempotency(row)
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
        session = self.uow.require_session()
        existing = self.claim_idempotency(
            actor_user_id=actor_user_id,
            operation=operation,
            idempotency_key=idempotency_key,
            resource_type=resource_type,
            resource_id=resource_id,
            request_fingerprint=request_fingerprint,
        )
        if existing is not None:
            if existing.result_type != result_type or existing.result_id != result_id:
                raise IdempotencyConflict(IdempotencyConflict.public_message)
            return
        session.add(
            MemoryIdempotencyResultRow(
                id=str(uuid4()),
                actor_user_id=actor_user_id,
                operation=operation,
                idempotency_key=idempotency_key,
                resource_type=resource_type,
                resource_id=resource_id,
                request_fingerprint=request_fingerprint,
                result_type=result_type,
                result_id=result_id,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()

    @staticmethod
    def _proposal(session: Session, row: MemoryProposalRow) -> MemoryProposal:
        accepted = session.scalar(
            select(LearningMemoryRow.id).where(
                LearningMemoryRow.source_proposal_id == row.id
            )
        )
        explanation_check_id = row.explanation_check_id
        if explanation_check_id is None:
            explanation_check_id = session.scalar(
                select(MemoryProposalRow.explanation_check_id).where(
                    MemoryProposalRow.id == row.root_proposal_id
                )
            )
        if explanation_check_id is None:
            raise MemoryPersistenceError("memory storage operation failed")
        return _proposal(row, accepted, explanation_check_id)


def _proposal(
    row: MemoryProposalRow,
    accepted_memory_id: str | None,
    explanation_check_id: str,
) -> MemoryProposal:
    return MemoryProposal(
        proposal_id=row.id,
        root_proposal_id=row.root_proposal_id,
        previous_proposal_id=row.previous_proposal_id,
        version=row.version,
        owner_user_id=row.owner_user_id,
        course_id=row.course_id,
        diagnosis_id=row.diagnosis_id,
        explanation_check_id=explanation_check_id,
        content=row.content,
        concept_ids=tuple(row.concept_ids),
        confidence=row.confidence,
        status=MemoryProposalStatus(row.status),
        created_at=_aware(row.created_at),
        expires_at=_aware(row.expires_at),
        request_id=row.request_id,
        accepted_memory_id=accepted_memory_id,
    )


def _proposal_row(item: MemoryProposal) -> MemoryProposalRow:
    return MemoryProposalRow(
        id=item.proposal_id,
        root_proposal_id=item.root_proposal_id,
        previous_proposal_id=item.previous_proposal_id,
        version=item.version,
        owner_user_id=item.owner_user_id,
        course_id=item.course_id,
        diagnosis_id=item.diagnosis_id,
        explanation_check_id=(
            item.explanation_check_id
            if item.previous_proposal_id is None
            else None
        ),
        content=item.content,
        concept_ids=list(item.concept_ids),
        confidence=item.confidence,
        status=item.status.value,
        created_at=item.created_at,
        expires_at=item.expires_at,
        request_id=item.request_id,
    )


def _set_proposal(row: MemoryProposalRow, item: MemoryProposal) -> None:
    row.content = item.content
    row.concept_ids = list(item.concept_ids)
    row.confidence = item.confidence
    row.status = item.status.value
    row.expires_at = item.expires_at
    row.request_id = item.request_id


def _memory(row: LearningMemoryRow) -> LearningMemory:
    return LearningMemory(
        memory_id=row.id,
        logical_memory_id=row.logical_memory_id,
        previous_version_id=row.previous_version_id,
        version=row.version,
        owner_user_id=row.owner_user_id,
        course_id=row.course_id,
        memory_type=row.memory_type,
        visibility=row.visibility,
        content=row.content,
        concept_ids=tuple(row.concept_ids),
        source_diagnosis_id=row.source_diagnosis_id,
        source_proposal_id=row.source_proposal_id,
        confidence=row.confidence,
        allowed_purposes=tuple(row.allowed_purposes),
        status=LearningMemoryStatus(row.status),
        index_document_id=row.index_document_id,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
        expires_at=_aware(row.expires_at),
        request_id=row.request_id,
    )


def _memory_row(item: LearningMemory) -> LearningMemoryRow:
    return LearningMemoryRow(
        id=item.memory_id,
        logical_memory_id=item.logical_memory_id,
        previous_version_id=item.previous_version_id,
        version=item.version,
        owner_user_id=item.owner_user_id,
        course_id=item.course_id,
        memory_type=item.memory_type,
        visibility=item.visibility,
        content=item.content,
        concept_ids=list(item.concept_ids),
        source_diagnosis_id=item.source_diagnosis_id,
        source_proposal_id=item.source_proposal_id,
        confidence=item.confidence,
        allowed_purposes=list(item.allowed_purposes),
        status=item.status.value,
        index_document_id=item.index_document_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        expires_at=item.expires_at,
        request_id=item.request_id,
    )


def _set_memory(row: LearningMemoryRow, item: LearningMemory) -> None:
    row.content = item.content
    row.concept_ids = list(item.concept_ids)
    row.confidence = item.confidence
    row.allowed_purposes = list(item.allowed_purposes)
    row.status = item.status.value
    row.updated_at = item.updated_at
    row.expires_at = item.expires_at
    row.request_id = item.request_id


def _grant(row: ShareGrantRow) -> ShareGrant:
    return ShareGrant(
        grant_id=row.id,
        owner_user_id=row.owner_user_id,
        course_id=row.course_id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        grantee_user_id=row.grantee_user_id,
        purpose=row.purpose,
        status=ShareGrantStatus(row.status),
        created_at=_aware(row.created_at),
        expires_at=_aware(row.expires_at),
        revoked_at=_aware(row.revoked_at),
        request_id=row.request_id,
    )


def _grant_row(item: ShareGrant) -> ShareGrantRow:
    return ShareGrantRow(
        id=item.grant_id,
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


def _set_grant(row: ShareGrantRow, item: ShareGrant) -> None:
    row.status = item.status.value
    row.expires_at = item.expires_at
    row.revoked_at = item.revoked_at
    row.request_id = item.request_id


def _deletion(row: MemoryDeletionRow) -> DeletionReceipt:
    return DeletionReceipt(
        deletion_id=row.id,
        memory_id=row.logical_memory_id,
        owner_user_id=row.owner_user_id,
        course_id=row.course_id,
        status=DeletionStatus(row.status),
        requested_at=_aware(row.requested_at),
        completed_at=_aware(row.completed_at),
        attempts=row.attempts,
        index_cleared=row.index_cleared,
        cache_cleared=row.cache_cleared,
        model_references_cleared=row.model_references_cleared,
        reverse_lookup_absent=row.reverse_lookup_absent,
        error_code=row.error_code,
        request_id=row.request_id,
    )


def _deletion_row(item: DeletionReceipt) -> MemoryDeletionRow:
    return MemoryDeletionRow(
        id=item.deletion_id,
        logical_memory_id=item.memory_id,
        owner_user_id=item.owner_user_id,
        course_id=item.course_id,
        status=item.status.value,
        requested_at=item.requested_at,
        completed_at=item.completed_at,
        attempts=item.attempts,
        index_cleared=item.index_cleared,
        cache_cleared=item.cache_cleared,
        model_references_cleared=item.model_references_cleared,
        reverse_lookup_absent=item.reverse_lookup_absent,
        error_code=item.error_code,
        request_id=item.request_id,
    )


def _set_deletion(row: MemoryDeletionRow, item: DeletionReceipt) -> None:
    row.status = item.status.value
    row.completed_at = item.completed_at
    row.attempts = item.attempts
    row.index_cleared = item.index_cleared
    row.cache_cleared = item.cache_cleared
    row.model_references_cleared = item.model_references_cleared
    row.reverse_lookup_absent = item.reverse_lookup_absent
    row.error_code = item.error_code
    row.request_id = item.request_id


def _idempotency(row: MemoryIdempotencyResultRow) -> IdempotencyReplay:
    return IdempotencyReplay(
        actor_user_id=row.actor_user_id,
        operation=row.operation,
        idempotency_key=row.idempotency_key,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        request_fingerprint=row.request_fingerprint,
        result_type=row.result_type,
        result_id=row.result_id,
    )
