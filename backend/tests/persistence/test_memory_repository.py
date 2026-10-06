from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.audit.persistence import SqlAuditLog
from app.auth.models import Actor, Role
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
from app.memories.persistence import SqlMemoryRepository, SqlMemoryUnitOfWork
from app.memories.repository import IdempotencyConflict
from app.memories.retrieval import InMemoryRetrievalIndex
from app.memories.service import MemoryService
from app.memories.source import SqlDiagnosticMemorySource
from app.persistence.models import (
    AuditEventRow,
    Base,
    CourseRow,
    DiagnosisConceptRow,
    DiagnosisRow,
    EnrollmentRow,
    ExerciseRow,
    ExplanationCheckRow,
    SubmissionRow,
    UserRow,
)


NOW = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)
STUDENT = Actor("student-1", Role.STUDENT)


class CourseAccess:
    def require_student(self, actor: Actor, course_id: str) -> None:
        if actor != STUDENT or course_id != "course-1":
            from app.courses.service import ResourceNotAvailable

            raise ResourceNotAvailable()

    def require_teacher(self, actor: Actor, course_id: str) -> None:
        from app.courses.service import ResourceNotAvailable

        raise ResourceNotAvailable()


@pytest.fixture
def sql_memory(tmp_path):
    database = tmp_path / "memory.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all(
            [
                UserRow(
                    id="student-1",
                    username="student-1",
                    password_hash="unused",
                    role="student",
                    active=True,
                ),
                UserRow(
                    id="teacher-1",
                    username="teacher-1",
                    password_hash="unused",
                    role="teacher",
                    active=True,
                ),
            ]
        )
        session.add(
            CourseRow(id="course-1", title="仓颉语言设计", owner_teacher_id="teacher-1")
        )
        session.add(
            EnrollmentRow(course_id="course-1", user_id="student-1", role="student")
        )
        session.add(
            ExerciseRow(
                id="exercise-1",
                course_id="course-1",
                title="exercise",
                is_published=True,
            )
        )
        session.add(
            SubmissionRow(
                id="submission-1",
                course_id="course-1",
                exercise_id="exercise-1",
                owner_user_id="student-1",
                source_files=[{"path": "main.cj", "content": "main() {}"}],
                entrypoint="main.cj",
                is_formal=True,
                status="diagnosed",
                created_at=NOW,
                request_id="seed-submission",
            )
        )
        session.add(
            DiagnosisRow(
                id="diagnosis-1",
                submission_id="submission-1",
                course_id="course-1",
                owner_user_id="student-1",
                category="conceptual",
                locations=[{"file": "main.cj", "start_line": 1, "end_line": 1}],
                root_cause="Class references and struct values have different semantics.",
                confidence=0.93,
                recommended_hint_level=1,
                requires_teacher_review=False,
                created_at=NOW,
                request_id="seed-diagnosis",
            )
        )
        session.add(
            DiagnosisConceptRow(
                diagnosis_id="diagnosis-1",
                course_id="course-1",
                concept_id="cj.class-struct",
                ordinal=0,
            )
        )
        session.add(
            ExplanationCheckRow(
                id="check-1",
                diagnosis_id="diagnosis-1",
                understands=True,
                concept_ids=["cj.class-struct"],
                evidence_summary="Evidence-bound explanation.",
                confidence=0.91,
                feedback="Correct distinction.",
                memory_proposal_eligible=True,
                created_at=NOW,
                request_id="seed-check",
            )
        )
    uow = SqlMemoryUnitOfWork(sessions)
    return {
        "sessions": sessions,
        "uow": uow,
        "repository": SqlMemoryRepository(uow),
        "audit": SqlAuditLog(uow),
        "source": SqlDiagnosticMemorySource(uow, confidence_threshold=0.75),
    }


def _proposal() -> MemoryProposal:
    return MemoryProposal(
        proposal_id="proposal-1",
        root_proposal_id="proposal-1",
        previous_proposal_id=None,
        version=1,
        owner_user_id="student-1",
        course_id="course-1",
        diagnosis_id="diagnosis-1",
        explanation_check_id="check-1",
        content="Class references and struct values have different semantics.",
        concept_ids=("cj.class-struct",),
        confidence=0.91,
        status=MemoryProposalStatus.pending,
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
        request_id="proposal-request",
    )


def _memory() -> LearningMemory:
    return LearningMemory(
        memory_id="memory-1",
        logical_memory_id="memory-1",
        previous_version_id=None,
        version=1,
        owner_user_id="student-1",
        course_id="course-1",
        memory_type="misconception_state",
        visibility="private",
        content="Class references and struct values have different semantics.",
        concept_ids=("cj.class-struct",),
        source_diagnosis_id="diagnosis-1",
        source_proposal_id="proposal-1",
        confidence=0.91,
        allowed_purposes=("learning_support",),
        status=LearningMemoryStatus.active,
        index_document_id="memory-index:memory-1",
        created_at=NOW,
        updated_at=NOW,
        expires_at=None,
        request_id="accept-request",
    )


def test_sql_repository_rebuilds_all_domain_records_with_aware_datetimes(sql_memory):
    repository = sql_memory["repository"]
    proposal = _proposal()
    memory = _memory()
    grant = ShareGrant(
        grant_id="grant-1",
        owner_user_id="student-1",
        course_id="course-1",
        resource_type="diagnosis_summary",
        resource_id="diagnosis-1",
        grantee_user_id="teacher-1",
        purpose="student_requested_review",
        status=ShareGrantStatus.active,
        created_at=NOW,
        expires_at=None,
        revoked_at=None,
        request_id="grant-request",
    )
    deletion = DeletionReceipt(
        deletion_id="deletion-1",
        memory_id="memory-1",
        owner_user_id="student-1",
        course_id="course-1",
        status=DeletionStatus.deletion_pending,
        requested_at=NOW,
        completed_at=None,
        attempts=0,
        index_cleared=False,
        cache_cleared=True,
        model_references_cleared=True,
        reverse_lookup_absent=False,
        error_code=None,
        request_id="delete-request",
    )
    with repository.transaction():
        repository.add_proposal(proposal)
        repository.add_memory(memory)
        repository.save_proposal(
            replace(
                proposal,
                status=MemoryProposalStatus.accepted,
                accepted_memory_id=memory.memory_id,
            )
        )
        repository.add_grant(grant)
        repository.add_deletion(deletion)

    rebuilt = SqlMemoryRepository(SqlMemoryUnitOfWork(sql_memory["sessions"]))
    assert rebuilt.get_proposal("proposal-1") == replace(
        proposal,
        status=MemoryProposalStatus.accepted,
        accepted_memory_id="memory-1",
    )
    assert rebuilt.get_memory("memory-1") == memory
    assert rebuilt.get_grant("grant-1") == grant
    assert rebuilt.get_deletion("deletion-1") == deletion
    for value in (
        rebuilt.get_proposal("proposal-1").created_at,
        rebuilt.get_memory("memory-1").updated_at,
        rebuilt.get_grant("grant-1").created_at,
        rebuilt.get_deletion("deletion-1").requested_at,
    ):
        assert value.utcoffset() is not None


def test_audit_failure_rolls_back_acceptance_and_memory_insert(sql_memory):
    repository = sql_memory["repository"]
    audit = sql_memory["audit"]
    with repository.transaction():
        repository.add_proposal(_proposal())

    original_record = audit.record

    def fail_after_flush(**kwargs):
        original_record(**kwargs)
        raise RuntimeError("forced audit failure")

    audit.record = fail_after_flush
    from app.memories.policy import MemoryPolicy

    service = MemoryService(
        repository=repository,
        source=sql_memory["source"],
        policy=MemoryPolicy(CourseAccess()),
        retrieval_index=InMemoryRetrievalIndex(),
        audit=audit,
        clock=lambda: NOW,
        id_factory=lambda: "memory-1",
    )
    with pytest.raises(RuntimeError, match="forced audit failure"):
        service.accept_proposal(
            STUDENT,
            "proposal-1",
            request_id="accept-request",
            idempotency_key="accept-key",
        )

    rebuilt = SqlMemoryRepository(SqlMemoryUnitOfWork(sql_memory["sessions"]))
    assert rebuilt.get_proposal("proposal-1").status is MemoryProposalStatus.pending
    assert rebuilt.get_memory("memory-1") is None
    with sql_memory["sessions"]() as session:
        assert session.scalars(select(AuditEventRow)).all() == []


def test_idempotency_scope_rejects_resource_or_payload_reuse(sql_memory):
    repository = sql_memory["repository"]
    with repository.transaction():
        assert repository.claim_idempotency(
            actor_user_id="student-1",
            operation="correct_memory",
            idempotency_key="same-key",
            resource_type="learning_memory",
            resource_id="memory-1",
            request_fingerprint="a" * 64,
        ) is None
        repository.remember_idempotency_result(
            actor_user_id="student-1",
            operation="correct_memory",
            idempotency_key="same-key",
            resource_type="learning_memory",
            resource_id="memory-1",
            request_fingerprint="a" * 64,
            result_type="learning_memory",
            result_id="memory-2",
        )

    replay = repository.claim_idempotency(
        actor_user_id="student-1",
        operation="correct_memory",
        idempotency_key="same-key",
        resource_type="learning_memory",
        resource_id="memory-1",
        request_fingerprint="a" * 64,
    )
    assert replay.result_id == "memory-2"
    for resource_id, fingerprint in (("memory-other", "a" * 64), ("memory-1", "b" * 64)):
        with pytest.raises(IdempotencyConflict) as error:
            repository.claim_idempotency(
                actor_user_id="student-1",
                operation="correct_memory",
                idempotency_key="same-key",
                resource_type="learning_memory",
                resource_id=resource_id,
                request_fingerprint=fingerprint,
            )
        assert error.value.public_error_code == "IDEMPOTENCY_KEY_REUSED"


def test_sql_source_uses_authoritative_join_and_current_membership(sql_memory):
    source = sql_memory["source"]
    proposal = source.proposal_source("check-1")
    summary = source.diagnosis_summary("diagnosis-1")

    assert proposal is not None and proposal.eligible is True
    assert proposal.owner_user_id == "student-1"
    assert proposal.course_id == "course-1"
    assert proposal.concept_ids == ("cj.class-struct",)
    assert summary is not None
    assert summary.root_cause == "Class references and struct values have different semantics."


def test_sql_service_replays_same_correction_and_rejects_changed_body(sql_memory):
    repository = sql_memory["repository"]
    proposal = _proposal()
    memory = _memory()
    with repository.transaction():
        repository.add_proposal(proposal)
        repository.add_memory(memory)
        repository.save_proposal(
            replace(
                proposal,
                status=MemoryProposalStatus.accepted,
                accepted_memory_id=memory.memory_id,
            )
        )

    from app.memories.policy import MemoryPolicy

    service = MemoryService(
        repository=repository,
        source=sql_memory["source"],
        policy=MemoryPolicy(CourseAccess()),
        retrieval_index=InMemoryRetrievalIndex(),
        audit=sql_memory["audit"],
        clock=lambda: NOW + timedelta(minutes=1),
        id_factory=lambda: "memory-2",
    )
    first = service.correct_memory(
        STUDENT,
        "memory-1",
        "Corrected value semantics.",
        request_id="correct-1",
        idempotency_key="correction-key",
    )
    replay = service.correct_memory(
        STUDENT,
        "memory-1",
        "Corrected value semantics.",
        request_id="correct-2",
        idempotency_key="correction-key",
    )
    assert replay == first
    with pytest.raises(IdempotencyConflict):
        service.correct_memory(
            STUDENT,
            "memory-1",
            "Different body.",
            request_id="correct-3",
            idempotency_key="correction-key",
        )
    assert repository.memory_successor("memory-1") == first


def test_sql_service_versions_one_root_proposal_without_duplicating_check(sql_memory):
    repository = sql_memory["repository"]
    with repository.transaction():
        repository.add_proposal(_proposal())

    from app.memories.policy import MemoryPolicy

    service = MemoryService(
        repository=repository,
        source=sql_memory["source"],
        policy=MemoryPolicy(CourseAccess()),
        retrieval_index=InMemoryRetrievalIndex(),
        audit=sql_memory["audit"],
        clock=lambda: NOW + timedelta(minutes=1),
        id_factory=lambda: "proposal-2",
    )
    corrected = service.correct_proposal(
        STUDENT,
        "proposal-1",
        "Corrected proposal content.",
        request_id="proposal-correct-1",
        idempotency_key="proposal-correction-key",
    )

    assert corrected.previous_proposal_id == "proposal-1"
    assert corrected.explanation_check_id == "check-1"
    assert repository.proposal_successor("proposal-1") == corrected
