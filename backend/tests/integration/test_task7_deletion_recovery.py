from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event, Lock
from uuid import uuid4

import pytest
import anyio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.errors import install_error_handling
from app.auth.models import Actor, Role, User
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, Enrollment, Exercise
from app.courses.service import CourseService
from app.diagnostics.schema import (
    CompilerDiagnosticEvidence,
    Diagnosis,
    DiagnosisCategory,
    DiagnosisLocation,
    ExplanationCheck,
)
from app.knowledge.models import Concept
from app.memories.deletion import DeletionService
from app.memories.models import DeletionStatus, LearningMemoryStatus
from app.memories.persistence import MemoryPersistenceError
from app.memories.policy import CourseServiceMemoryAccess, MemoryPolicy
from app.memories.retrieval import InMemoryRetrievalIndex
from app.memories.repository import IdempotencyConflict
from app.memories.service import MemoryService
from app.persistence.models import (
    AuditEventRow,
    MemoryDeletionRow,
    MemoryIdempotencyResultRow,
    MemoryTombstoneRow,
)
from app.persistence.repositories import create_sql_repositories


PRIVATE_MEMORY = "I confuse class reference semantics with struct value semantics."
PRIVATE_CODE = "main() { let privateStudentCode = 7 }"


def _postgres_url() -> str:
    value = os.environ.get("TASK7_POSTGRES_URL")
    if not value:
        pytest.skip("TASK7_POSTGRES_URL is required for deletion recovery")
    assert value.startswith("postgresql")
    return value


@pytest.fixture(autouse=True)
def _ensure_head():
    backend = __file__.replace("\\", "/").rsplit("/tests/", 1)[0]
    config = Config(f"{backend}/alembic.ini")
    config.set_main_option("script_location", f"{backend}/migrations")
    config.set_main_option("sqlalchemy.url", _postgres_url())
    command.upgrade(config, "0005_memories_audit")


def _seed(url: str):
    suffix = uuid4().hex[:10]
    teacher_id = f"teacher-delete-{suffix}"
    student_id = f"student-delete-{suffix}"
    course_id = f"course-delete-{suffix}"
    exercise_id = f"exercise-delete-{suffix}"
    submission_id = f"submission-delete-{suffix}"
    diagnosis_id = f"diagnosis-delete-{suffix}"
    explanation_id = f"explanation-delete-{suffix}"
    concept_id = f"cj.concept.delete.{suffix}"
    repositories = create_sql_repositories(url)
    repositories.users.add(
        User.with_password(teacher_id, teacher_id, "pw", Role.TEACHER)
    )
    repositories.users.add(
        User.with_password(student_id, student_id, "pw", Role.STUDENT)
    )
    repositories.courses.add(Course(course_id, "仓颉语言设计", teacher_id))
    repositories.enrollments.add(Enrollment(course_id, student_id, Role.STUDENT))
    repositories.courses.add_exercise(
        Exercise(exercise_id, course_id, "Class semantics", True)
    )
    repositories.knowledge.load_course(
        course_id,
        [
            Concept.model_validate(
                {
                    "id": concept_id,
                    "topic": "class_struct_semantics",
                    "title": "Class and struct semantics",
                    "summary": "Classes use reference semantics.",
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
        submission_id=submission_id,
        course_id=course_id,
        exercise_id=exercise_id,
        owner_user_id=student_id,
        source_files=[{"path": "main.cj", "content": PRIVATE_CODE}],
        entrypoint="main.cj",
        is_formal=True,
        request_id=f"submission-{suffix}",
    )
    repositories.diagnostics.save_diagnosis(
        Diagnosis(
            diagnosis_id=diagnosis_id,
            submission_id=submission_id,
            course_id=course_id,
            owner_user_id=student_id,
            category=DiagnosisCategory.conceptual,
            locations=(DiagnosisLocation(file="main.cj", start_line=1, end_line=1),),
            concept_ids=(concept_id,),
            root_cause=PRIVATE_MEMORY,
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
            request_id=f"diagnosis-{suffix}",
        )
    )
    repositories.diagnostics.add_explanation(
        ExplanationCheck(
            explanation_check_id=explanation_id,
            diagnosis_id=diagnosis_id,
            understands=True,
            concept_ids=(concept_id,),
            evidence_summary="Evidence-bound explanation.",
            confidence=0.91,
            feedback="Correct.",
            memory_proposal_eligible=True,
            created_at=datetime.now(UTC),
            request_id=f"explanation-{suffix}",
        )
    )
    return repositories, Actor(student_id, Role.STUDENT), course_id, explanation_id


def _services(repositories, index):
    courses = CourseService(
        repositories.users,
        repositories.courses,
        repositories.enrollments,
        AuthorizationPolicy(),
    )
    policy = MemoryPolicy(CourseServiceMemoryAccess(courses))
    return (
        MemoryService(
            repository=repositories.memories,
            source=repositories.memory_source,
            policy=policy,
            retrieval_index=index,
            audit=repositories.audit,
        ),
        DeletionService(
            repository=repositories.memories,
            policy=policy,
            retrieval_index=index,
            audit=repositories.audit,
        ),
    )


def _create_memory(repositories, actor, explanation_id, index):
    service, deletion = _services(repositories, index)
    proposal = service.create_proposal(
        actor, explanation_id, request_id=f"proposal-{uuid4().hex}"
    )
    memory = service.accept_proposal(
        actor,
        proposal.proposal_id,
        request_id=f"accept-{uuid4().hex}",
        idempotency_key=f"accept-{uuid4().hex}",
    )
    return service, deletion, memory


def test_pending_deletion_survives_two_restarts_and_stays_redacted():
    url = _postgres_url()
    repositories, actor, course_id, explanation_id = _seed(url)
    index = InMemoryRetrievalIndex()
    service, deletion, memory = _create_memory(
        repositories, actor, explanation_id, index
    )
    assert index.contains(memory.index_document_id)
    index.fail_next_deletes(1)

    pending = deletion.delete_memory(
        actor,
        memory.memory_id,
        request_id="delete-initial",
        idempotency_key=f"delete-{uuid4().hex}",
    )
    assert pending.status is DeletionStatus.deletion_pending
    persisted = repositories.memories.get_memory(memory.memory_id)
    assert persisted.status is LearningMemoryStatus.deletion_pending
    assert persisted.content is None
    assert service.search_memories(
        actor, course_id, PRIVATE_MEMORY, purpose="learning_support"
    ) == ()

    restarted = create_sql_repositories(url)
    restarted_service, restarted_deletion = _services(restarted, index)
    assert pending.deletion_id in {
        item.deletion_id for item in restarted.memories.pending_deletions()
    }
    completed = restarted_deletion.retry(
        actor,
        pending.deletion_id,
        request_id="delete-retry-after-restart",
        idempotency_key=f"retry-{uuid4().hex}",
    )
    assert completed.status is DeletionStatus.deleted
    assert index.contains(memory.index_document_id) is False
    assert restarted_service.search_memories(
        actor, course_id, PRIVATE_MEMORY, purpose="learning_support"
    ) == ()

    restarted_again = create_sql_repositories(url)
    _, deletion_again = _services(restarted_again, index)
    assert deletion_again.get_status(actor, pending.deletion_id).status is DeletionStatus.deleted
    assert deletion_again.delete_memory(
        actor,
        memory.memory_id,
        request_id="delete-repeat",
        idempotency_key=f"delete-repeat-{uuid4().hex}",
    ).status is DeletionStatus.deleted
    assert deletion_again.retry(
        actor,
        pending.deletion_id,
        request_id="retry-repeat",
        idempotency_key=f"retry-repeat-{uuid4().hex}",
    ).status is DeletionStatus.deleted
    assert len(
        [
            item
            for item in restarted_again.memories.all_deletions()
            if item.memory_id == memory.logical_memory_id
        ]
    ) == 1

    sessions = restarted_again.memory_uow.sessions
    with sessions() as session:
        metadata = {
            "deletions": [
                row._mapping
                for row in session.execute(select(MemoryDeletionRow.__table__))
            ],
            "tombstones": [
                row._mapping
                for row in session.execute(select(MemoryTombstoneRow.__table__))
            ],
            "audit": [
                row._mapping for row in session.execute(select(AuditEventRow.__table__))
            ],
            "idempotency": [
                row._mapping
                for row in session.execute(select(MemoryIdempotencyResultRow.__table__))
            ],
        }
    serialized = json.dumps(metadata, default=str, ensure_ascii=False)
    serialized_receipt = json.dumps(completed.public_dict(), ensure_ascii=False)
    for secret in (
        PRIVATE_MEMORY,
        PRIVATE_CODE,
        memory.index_document_id,
        "embedding",
        "prompt",
        "Bearer",
        "api_key",
    ):
        assert secret not in serialized
        assert secret not in serialized_receipt
    assert PRIVATE_MEMORY not in restarted_again.audit.serialized_events()


def test_failure_bodies_and_logs_never_expose_deletion_secrets(caplog):
    application = FastAPI()
    install_error_handling(application)
    secrets = (
        PRIVATE_MEMORY,
        PRIVATE_CODE,
        "memory-index:private-document",
        "Bearer private-token",
    )
    injected = " | ".join(secrets)

    @application.get("/storage")
    def storage_failure():
        raise MemoryPersistenceError(injected)

    @application.get("/conflict")
    def conflict_failure():
        raise IdempotencyConflict(injected)

    async def requests():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            return (
                await client.get("/storage", headers={"X-Request-ID": "redact-503"}),
                await client.get("/conflict", headers={"X-Request-ID": "redact-409"}),
            )

    storage, conflict = anyio.run(requests)
    assert storage.status_code == 503
    assert conflict.status_code == 409
    serialized = json.dumps(
        [storage.json(), conflict.json(), caplog.text], ensure_ascii=False
    )
    for secret in secrets:
        assert secret not in serialized


def test_late_index_publish_and_stale_snapshots_cannot_restore_deletion():
    url = _postgres_url()
    repositories, actor, _course_id, explanation_id = _seed(url)

    class BlockingIndex(InMemoryRetrievalIndex):
        def __init__(self):
            super().__init__()
            self.upsert_started = Event()
            self.release_upsert = Event()

        def upsert(self, memory):
            self.upsert_started.set()
            assert self.release_upsert.wait(timeout=5)
            super().upsert(memory)

    index = BlockingIndex()
    service, _ = _services(repositories, index)
    proposal = service.create_proposal(
        actor, explanation_id, request_id=f"proposal-{uuid4().hex}"
    )
    restarted = create_sql_repositories(url)
    _, deletion = _services(restarted, index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(
            service.accept_proposal,
            actor,
            proposal.proposal_id,
            request_id="accept-delayed-index",
            idempotency_key=f"accept-{uuid4().hex}",
        )
        assert index.upsert_started.wait(timeout=5)
        stale = next(
            item
            for item in create_sql_repositories(url).memories.all_memories()
            if item.owner_user_id == actor.user_id
        )
        deleting = pool.submit(
            deletion.delete_memory,
            actor,
            stale.memory_id,
            request_id="delete-during-upsert",
            idempotency_key=f"delete-{uuid4().hex}",
        )
        with pytest.raises(TimeoutError):
            deleting.result(timeout=0.2)
        index.release_upsert.set()
        accepted.result(timeout=5)
        completed = deleting.result(timeout=5)

    assert completed.status is DeletionStatus.deleted
    assert index.contains(stale.index_document_id) is False
    stale_repository = create_sql_repositories(url).memories
    with stale_repository.transaction():
        stale_repository.save_memory(replace(stale, status=LearningMemoryStatus.active))
    current = create_sql_repositories(url).memories.get_memory(stale.memory_id)
    assert current.status is LearningMemoryStatus.deleted
    assert current.content is None

    stale_receipt = replace(
        completed,
        status=DeletionStatus.deletion_pending,
        completed_at=None,
        reverse_lookup_absent=False,
    )
    with stale_repository.transaction():
        stale_repository.save_deletion(stale_receipt)
    assert (
        create_sql_repositories(url).memories.get_deletion(completed.deletion_id).status
        is DeletionStatus.deleted
    )


def test_retry_resumes_after_verified_index_delete_without_deleting_twice():
    url = _postgres_url()
    repositories, actor, _course_id, explanation_id = _seed(url)

    class CountingIndex(InMemoryRetrievalIndex):
        def __init__(self):
            super().__init__()
            self.deleted_ids = []
            self._count_lock = Lock()

        def delete(self, index_document_id):
            with self._count_lock:
                self.deleted_ids.append(index_document_id)
            super().delete(index_document_id)

    index = CountingIndex()
    _, deletion, memory = _create_memory(repositories, actor, explanation_id, index)
    index.fail_next_verifications(1)
    pending = deletion.delete_memory(
        actor,
        memory.memory_id,
        request_id="delete-verify-failed",
        idempotency_key=f"delete-{uuid4().hex}",
    )
    assert pending.status is DeletionStatus.deletion_pending
    assert pending.index_cleared is True
    assert len(index.deleted_ids) == 1

    restarted = create_sql_repositories(url)
    _, restarted_deletion = _services(restarted, index)
    completed = restarted_deletion.retry(
        actor,
        pending.deletion_id,
        request_id="retry-verification-only",
        idempotency_key=f"retry-{uuid4().hex}",
    )
    assert completed.status is DeletionStatus.deleted
    assert len(index.deleted_ids) == 1
