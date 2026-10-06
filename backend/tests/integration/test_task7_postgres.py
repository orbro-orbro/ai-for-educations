from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth.models import Actor, Role, User
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, Enrollment, Exercise
from app.courses.service import CourseService, ResourceNotAvailable
from app.diagnostics.schema import (
    CompilerDiagnosticEvidence,
    Diagnosis,
    DiagnosisCategory,
    DiagnosisLocation,
    ExplanationCheck,
)
from app.knowledge.models import Concept
from app.memories.models import LearningMemoryStatus, MemoryProposalStatus
from app.memories.policy import CourseServiceMemoryAccess, MemoryPolicy
from app.memories.repository import IdempotencyConflict
from app.memories.retrieval import InMemoryRetrievalIndex
from app.memories.service import MemoryConflict, MemoryService
from app.persistence.models import CourseAuthorizedTeacherRow, EnrollmentRow
from app.persistence.repositories import create_sql_repositories


BACKEND = Path(__file__).resolve().parents[2]


def _postgres_url() -> str:
    value = os.environ.get("TASK7_POSTGRES_URL")
    if not value:
        pytest.skip("TASK7_POSTGRES_URL is required for the real PostgreSQL Gate")
    assert value.startswith("postgresql"), "Task 7 Gate requires real PostgreSQL"
    return value


def _alembic(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(autouse=True)
def _ensure_head():
    url = _postgres_url()
    command.upgrade(_alembic(url), "0005_memories_audit")


@dataclass(frozen=True)
class Seed:
    suffix: str
    teacher_id: str
    reviewer_id: str
    student_id: str
    course_id: str
    exercise_id: str
    submission_id: str
    diagnosis_id: str
    explanation_id: str
    concept_id: str

    @property
    def actor(self) -> Actor:
        return Actor(self.student_id, Role.STUDENT)

    @property
    def reviewer(self) -> Actor:
        return Actor(self.reviewer_id, Role.TEACHER)


def _seed(url: str, suffix: str | None = None) -> tuple[object, Seed]:
    suffix = suffix or uuid4().hex[:10]
    seed = Seed(
        suffix=suffix,
        teacher_id=f"teacher-{suffix}",
        reviewer_id=f"reviewer-{suffix}",
        student_id=f"student-{suffix}",
        course_id=f"course-{suffix}",
        exercise_id=f"exercise-{suffix}",
        submission_id=f"submission-{suffix}",
        diagnosis_id=f"diagnosis-{suffix}",
        explanation_id=f"explanation-{suffix}",
        concept_id=f"cj.concept.{suffix}",
    )
    repositories = create_sql_repositories(url)
    repositories.users.add(
        User.with_password(seed.teacher_id, seed.teacher_id, "pw", Role.TEACHER)
    )
    repositories.users.add(
        User.with_password(seed.reviewer_id, seed.reviewer_id, "pw", Role.TEACHER)
    )
    repositories.users.add(
        User.with_password(seed.student_id, seed.student_id, "pw", Role.STUDENT)
    )
    repositories.courses.add(
        Course(
            seed.course_id,
            "仓颉语言设计",
            seed.teacher_id,
        )
    )
    with repositories.memory_uow.sessions.begin() as session:
        session.add(
            CourseAuthorizedTeacherRow(
                course_id=seed.course_id,
                teacher_id=seed.reviewer_id,
            )
        )
    repositories.enrollments.add(
        Enrollment(seed.course_id, seed.student_id, Role.STUDENT)
    )
    repositories.courses.add_exercise(
        Exercise(seed.exercise_id, seed.course_id, "Entry", True)
    )
    repositories.knowledge.load_course(
        seed.course_id,
        [
            Concept.model_validate(
                {
                    "id": seed.concept_id,
                    "topic": "class_struct_semantics",
                    "title": "Reference and value semantics",
                    "summary": "Classes and structs have different semantics.",
                    "review_status": "approved",
                    "source": {
                        "kind": "toolchain_experiment",
                        "references": [f"exp:{suffix}"],
                        "toolchain_version": "cjc 1.2.0 (cjnative)",
                        "verification_status": "experiment_verified",
                    },
                }
            )
        ],
        [],
        [],
    )
    repositories.submissions.create(
        submission_id=seed.submission_id,
        course_id=seed.course_id,
        exercise_id=seed.exercise_id,
        owner_user_id=seed.student_id,
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id=f"request-submission-{suffix}",
    )
    repositories.diagnostics.save_diagnosis(
        Diagnosis(
            diagnosis_id=seed.diagnosis_id,
            submission_id=seed.submission_id,
            course_id=seed.course_id,
            owner_user_id=seed.student_id,
            category=DiagnosisCategory.conceptual,
            locations=(DiagnosisLocation(file="main.cj", start_line=1, end_line=1),),
            concept_ids=(seed.concept_id,),
            root_cause="The student confused class references with struct values.",
            evidence=(
                CompilerDiagnosticEvidence(
                    kind="compiler_diagnostic",
                    summary="Compiler evidence.",
                    diagnostic_index=0,
                ),
            ),
            confidence=0.93,
            recommended_hint_level=1,
            requires_teacher_review=False,
            created_at=datetime.now(UTC),
            request_id=f"request-diagnosis-{suffix}",
        )
    )
    _add_explanation(repositories, seed, seed.explanation_id)
    return repositories, seed


def _add_explanation(repositories, seed: Seed, explanation_id: str) -> None:
    repositories.diagnostics.add_explanation(
        ExplanationCheck(
            explanation_check_id=explanation_id,
            diagnosis_id=seed.diagnosis_id,
            understands=True,
            concept_ids=(seed.concept_id,),
            evidence_summary="Evidence-bound explanation.",
            confidence=0.91,
            feedback="Correct.",
            memory_proposal_eligible=True,
            created_at=datetime.now(UTC),
            request_id=f"request-{explanation_id}",
        )
    )


def _service(repositories, *, audit=None, index=None) -> MemoryService:
    courses = CourseService(
        repositories.users,
        repositories.courses,
        repositories.enrollments,
        AuthorizationPolicy(),
    )
    return MemoryService(
        repository=repositories.memories,
        source=repositories.memory_source,
        policy=MemoryPolicy(CourseServiceMemoryAccess(courses)),
        retrieval_index=index or InMemoryRetrievalIndex(),
        audit=audit or repositories.audit,
    )


def test_00_migration_round_trip_preserves_task2_to_task6_rows():
    url = _postgres_url()
    config = _alembic(url)
    command.downgrade(config, "base")
    command.upgrade(config, "0004_diagnostics_hints")
    _, seed = _seed(url, f"migration-{uuid4().hex[:8]}")

    command.upgrade(config, "0005_memories_audit")
    command.downgrade(config, "0004_diagnostics_hints")
    repositories = create_sql_repositories(url)
    assert repositories.users.get(seed.student_id) is not None
    assert repositories.courses.get(seed.course_id) is not None
    assert repositories.submissions.get(seed.submission_id) is not None
    assert repositories.diagnostics.get(seed.diagnosis_id) is not None
    assert repositories.diagnostics.get_explanation(
        seed.diagnosis_id, f"request-{seed.explanation_id}"
    ) is not None

    command.upgrade(config, "0005_memories_audit")


def test_postgres_rejects_invalid_states_and_malformed_lineage_roots():
    url = _postgres_url()
    repositories, seed = _seed(url)
    service = _service(repositories)
    proposal = service.create_proposal(
        seed.actor, seed.explanation_id, request_id=f"proposal-{seed.suffix}"
    )
    memory = service.accept_proposal(
        seed.actor,
        proposal.proposal_id,
        request_id=f"accept-{seed.suffix}",
        idempotency_key=f"accept-{seed.suffix}",
    )
    engine = repositories.memory_uow.sessions.kw["bind"]

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text("UPDATE learning_memories SET status='forged' WHERE id=:id"),
                    {"id": memory.memory_id},
                )
        finally:
            transaction.rollback()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        """
                        INSERT INTO memory_proposals
                        (id, root_proposal_id, previous_proposal_id, version,
                         owner_user_id, course_id, diagnosis_id, explanation_check_id,
                         content, concept_ids, confidence, status, created_at,
                         expires_at, request_id)
                        SELECT :bad_id, :bad_id, NULL, 2, owner_user_id, course_id,
                               diagnosis_id, NULL, content, concept_ids, confidence,
                               status, created_at, expires_at, request_id
                        FROM memory_proposals WHERE id=:source_id
                        """
                    ),
                    {"bad_id": f"bad-proposal-{seed.suffix}", "source_id": proposal.proposal_id},
                )
        finally:
            transaction.rollback()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        """
                        INSERT INTO learning_memories
                        (id, logical_memory_id, previous_version_id, version,
                         owner_user_id, course_id, memory_type, visibility, content,
                         concept_ids, source_diagnosis_id, source_proposal_id,
                         confidence, allowed_purposes, status, index_document_id,
                         created_at, updated_at, expires_at, request_id)
                        SELECT :bad_id, :bad_id, NULL, 2, owner_user_id, course_id,
                               memory_type, visibility, content, concept_ids,
                               source_diagnosis_id, NULL, confidence, allowed_purposes,
                               status, :index_id, created_at, updated_at, expires_at,
                               request_id
                        FROM learning_memories WHERE id=:source_id
                        """
                    ),
                    {
                        "bad_id": f"bad-memory-{seed.suffix}",
                        "index_id": f"bad-index-{seed.suffix}",
                        "source_id": memory.memory_id,
                    },
                )
        finally:
            transaction.rollback()


def test_two_repository_instances_concurrently_accept_only_one_memory():
    url = _postgres_url()
    repositories, seed = _seed(url)
    proposal = _service(repositories).create_proposal(
        seed.actor, seed.explanation_id, request_id=f"proposal-{seed.suffix}"
    )
    barrier = Barrier(2)

    def accept(index: int):
        current = create_sql_repositories(url)
        barrier.wait()
        return _service(current).accept_proposal(
            seed.actor,
            proposal.proposal_id,
            request_id=f"accept-{seed.suffix}-{index}",
            idempotency_key=f"accept-{seed.suffix}-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = tuple(pool.map(accept, (1, 2)))

    assert accepted[0].memory_id == accepted[1].memory_id
    assert len(create_sql_repositories(url).memories.all_memories()) >= 1
    matching = [
        item
        for item in create_sql_repositories(url).memories.all_memories()
        if item.source_proposal_id == proposal.proposal_id
    ]
    assert len(matching) == 1


def test_concurrent_corrections_leave_exactly_one_active_version():
    url = _postgres_url()
    repositories, seed = _seed(url)
    service = _service(repositories)
    proposal = service.create_proposal(
        seed.actor, seed.explanation_id, request_id=f"proposal-{seed.suffix}"
    )
    memory = service.accept_proposal(
        seed.actor,
        proposal.proposal_id,
        request_id=f"accept-{seed.suffix}",
        idempotency_key=f"accept-{seed.suffix}",
    )
    barrier = Barrier(2)

    def correct(index: int):
        current = create_sql_repositories(url)
        barrier.wait()
        try:
            return _service(current).correct_memory(
                seed.actor,
                memory.memory_id,
                f"Corrected content {index}",
                request_id=f"correct-{seed.suffix}-{index}",
                idempotency_key=f"correct-{seed.suffix}-{index}",
            )
        except MemoryConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(correct, (1, 2)))

    assert sum(item is not None for item in results) == 1
    lineage = create_sql_repositories(url).memories.memory_lineage(
        memory.logical_memory_id
    )
    assert len(lineage) == 2
    assert sum(item.status is LearningMemoryStatus.active for item in lineage) == 1


def test_concurrent_idempotency_key_reuse_is_a_domain_conflict():
    url = _postgres_url()
    repositories, seed = _seed(url)
    second_check = f"explanation-second-{seed.suffix}"
    _add_explanation(repositories, seed, second_check)
    service = _service(repositories)
    proposals = (
        service.create_proposal(
            seed.actor, seed.explanation_id, request_id=f"proposal-a-{seed.suffix}"
        ),
        service.create_proposal(
            seed.actor, second_check, request_id=f"proposal-b-{seed.suffix}"
        ),
    )
    barrier = Barrier(2)

    def accept(index: int):
        current = create_sql_repositories(url)
        original = current.memories.remember_idempotency_result

        def synchronized_remember(**kwargs):
            barrier.wait()
            return original(**kwargs)

        current.memories.remember_idempotency_result = synchronized_remember
        try:
            result = _service(current).accept_proposal(
                seed.actor,
                proposals[index].proposal_id,
                request_id=f"same-key-{seed.suffix}-{index}",
                idempotency_key=f"same-key-{seed.suffix}",
            )
            return "accepted", result.memory_id
        except IdempotencyConflict:
            return "conflict", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(accept, (0, 1)))

    assert sorted(item[0] for item in results) == ["accepted", "conflict"]


def test_audit_failure_rolls_back_memory_proposal_acceptance():
    url = _postgres_url()
    repositories, seed = _seed(url)
    proposal = _service(repositories).create_proposal(
        seed.actor, seed.explanation_id, request_id=f"proposal-{seed.suffix}"
    )

    class FailingAudit:
        def transaction(self):
            return repositories.audit.transaction()

        def record(self, **_kwargs):
            raise RuntimeError("injected audit failure")

    with pytest.raises(RuntimeError, match="injected audit failure"):
        _service(repositories, audit=FailingAudit()).accept_proposal(
            seed.actor,
            proposal.proposal_id,
            request_id=f"accept-{seed.suffix}",
            idempotency_key=f"accept-{seed.suffix}",
        )

    restarted = create_sql_repositories(url)
    assert restarted.memories.get_memory_for_proposal(proposal.proposal_id) is None
    assert (
        restarted.memories.get_proposal(proposal.proposal_id).status
        is MemoryProposalStatus.pending
    )


def test_live_student_and_teacher_authorization_revocation_is_immediate():
    url = _postgres_url()
    repositories, seed = _seed(url)
    service = _service(repositories)
    proposal = service.create_proposal(
        seed.actor, seed.explanation_id, request_id=f"proposal-{seed.suffix}"
    )
    grant = service.create_share_grant(
        seed.actor,
        seed.diagnosis_id,
        seed.reviewer_id,
        purpose="misconception_review",
        request_id=f"grant-{seed.suffix}",
        idempotency_key=f"grant-{seed.suffix}",
    )
    assert service.read_shared_diagnosis(seed.reviewer, grant.grant_id)

    sessions = repositories.memory_uow.sessions
    with sessions.begin() as session:
        teacher = session.get(
            CourseAuthorizedTeacherRow, (seed.course_id, seed.reviewer_id)
        )
        session.delete(teacher)
    with pytest.raises(ResourceNotAvailable):
        _service(create_sql_repositories(url)).read_shared_diagnosis(
            seed.reviewer, grant.grant_id
        )

    with sessions.begin() as session:
        enrollment = session.get(EnrollmentRow, (seed.course_id, seed.student_id))
        session.delete(enrollment)
    with pytest.raises(ResourceNotAvailable):
        _service(create_sql_repositories(url)).get_proposal(
            seed.actor, proposal.proposal_id
        )
