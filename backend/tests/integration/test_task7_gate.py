from __future__ import annotations

from datetime import UTC, datetime

import anyio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec
from app.api.diagnostics import create_diagnostics_router
from app.api.errors import install_error_handling
from app.audit.persistence import SqlAuditLog
from app.audit.service import AuditService
from app.auth.models import Role, User, UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, CourseRepository, Enrollment, EnrollmentRepository
from app.courses.service import CourseService
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.diagnostics.schema import (
    ApprovedKnowledgeEvidence,
    Diagnosis,
    DiagnosisCategory,
    DiagnosisLocation,
    ExplanationCheck,
)
from app.knowledge.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.memories.persistence import MemoryPersistenceError, SqlMemoryRepository
from app.memories.repository import IdempotencyConflict, InMemoryMemoryRepository
from app.memories.retrieval import InMemoryRetrievalIndex
from app.memories.service import DiagnosticMemorySource
from app.model_gateway.config import DisabledModelProvider
from app.submissions.repository import InMemorySubmissionRepository


TASK7_ROUTES = {
    ("/me/memory-proposals", "GET"),
    ("/memory-proposals/{proposal_id}/accept", "POST"),
    ("/memory-proposals/{proposal_id}/reject", "POST"),
    ("/memory-proposals/{proposal_id}", "PATCH"),
    ("/me/memories", "GET"),
    ("/memories/{memory_id}", "PATCH"),
    ("/memories/{memory_id}", "DELETE"),
    ("/memory-deletions/{deletion_id}", "GET"),
    ("/memory-deletions/{deletion_id}/retry", "POST"),
    ("/diagnoses/{diagnosis_id}/share-grants", "POST"),
    ("/me/share-grants", "GET"),
    ("/share-grants/{grant_id}", "GET"),
    ("/share-grants/{grant_id}", "DELETE"),
    ("/share-grants/{grant_id}/diagnosis-summary", "GET"),
}


def _runtime_operations(application: FastAPI) -> set[tuple[str, str]]:
    return {
        (path, method.upper())
        for path, item in application.openapi()["paths"].items()
        for method in item
    }


def test_composed_application_mounts_task7_with_in_memory_defaults(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = create_app()

    assert TASK7_ROUTES <= _runtime_operations(application)
    assert isinstance(application.state.memory_repository, InMemoryMemoryRepository)
    assert isinstance(application.state.memory_audit, AuditService)
    assert application.state.memory_service is not None
    assert application.state.deletion_service is not None


def test_composed_application_uses_shared_sql_memory_dependencies(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'gate.db').as_posix()}")
    application = create_app()

    assert TASK7_ROUTES <= _runtime_operations(application)
    assert isinstance(application.state.memory_repository, SqlMemoryRepository)
    assert isinstance(application.state.memory_audit, SqlAuditLog)
    assert application.state.memory_repository.uow is application.state.memory_audit._uow


def test_explanation_check_calls_server_side_proposal_hook_once():
    users = UserRepository(
        [User.with_password("student-1", "student", "pw", Role.STUDENT)]
    )
    authenticator = Authenticator(users, TokenCodec("task7-hook-secret-at-least-16"))
    token = authenticator.login("student", "pw")[0]
    check = ExplanationCheck(
        explanation_check_id="check-1",
        diagnosis_id="diagnosis-1",
        understands=True,
        concept_ids=("cj.class-struct",),
        evidence_summary="Evidence-bound.",
        confidence=0.91,
        feedback="Correct.",
        memory_proposal_eligible=True,
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        request_id="req-hook",
    )

    class DiagnosisStub:
        def check_explanation(self, *_args, **_kwargs):
            return check

    calls = []
    application = FastAPI()
    install_error_handling(application)
    application.include_router(
        create_diagnostics_router(
            DiagnosisStub(),
            None,
            authenticator,
            proposal_hook=lambda actor, result, request_id: calls.append(
                (actor.user_id, result.explanation_check_id, request_id)
            ),
        )
    )

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            return await client.post(
                "/diagnoses/diagnosis-1/explanation-check",
                json={"explanation": "Classes are references."},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": "req-hook",
                },
            )

    response = anyio.run(request)
    assert response.status_code == 200
    assert calls == [("student-1", "check-1", "req-hook")]


def test_composed_explanation_route_creates_one_proposal_and_skips_ineligible():
    users = UserRepository(
        [
            User.with_password("teacher-1", "teacher", "pw", Role.TEACHER),
            User.with_password("student-1", "student", "pw", Role.STUDENT),
        ]
    )
    authenticator = Authenticator(users, TokenCodec("task7-gate-secret-at-least-16"))
    token = authenticator.login("student", "pw")[0]
    courses = CourseRepository([Course("course-1", "仓颉语言设计", "teacher-1")])
    enrollments = EnrollmentRepository(
        [Enrollment("course-1", "student-1", Role.STUDENT)]
    )
    course_service = CourseService(users, courses, enrollments, AuthorizationPolicy())
    submissions = InMemorySubmissionRepository()
    submissions.create(
        submission_id="submission-1",
        course_id="course-1",
        exercise_id="exercise-1",
        owner_user_id="student-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-submission",
    )
    diagnostics = InMemoryDiagnosticRepository()
    diagnostics.save_diagnosis(
        Diagnosis(
            diagnosis_id="diagnosis-1",
            submission_id="submission-1",
            course_id="course-1",
            owner_user_id="student-1",
            category=DiagnosisCategory.conceptual,
            locations=(DiagnosisLocation(file="main.cj", start_line=1, end_line=1),),
            concept_ids=("cj.class-struct",),
            root_cause="Classes use reference semantics.",
            evidence=(
                ApprovedKnowledgeEvidence(
                    kind="approved_knowledge",
                    summary="Reviewed course evidence.",
                    misconception_id="cj.misconception.class-struct",
                    source_reference="course:class-struct",
                ),
            ),
            confidence=0.91,
            recommended_hint_level=1,
            requires_teacher_review=False,
            created_at=datetime(2026, 10, 6, tzinfo=UTC),
            request_id="req-diagnosis",
        )
    )
    eligible = ExplanationCheck(
        explanation_check_id="check-eligible",
        diagnosis_id="diagnosis-1",
        understands=True,
        concept_ids=("cj.class-struct",),
        evidence_summary="Evidence-bound.",
        confidence=0.91,
        feedback="Correct.",
        memory_proposal_eligible=True,
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        request_id="req-check",
    )
    ineligible = eligible.model_copy(
        update={
            "explanation_check_id": "check-ineligible",
            "understands": False,
            "concept_ids": (),
            "confidence": 0.2,
            "memory_proposal_eligible": False,
        }
    )
    diagnostics.add_explanation(eligible)

    class DiagnosisStub:
        def check_explanation(self, _actor, diagnosis_id, *_args, **_kwargs):
            return eligible if diagnosis_id == "diagnosis-1" else ineligible

    memories = InMemoryMemoryRepository()
    audit = AuditService()
    application = create_app(
        authenticator=authenticator,
        course_service=course_service,
        knowledge_repository=InMemoryKnowledgeRepository(),
        submission_repository=submissions,
        diagnostic_repository=diagnostics,
        protected_answer_lookup=courses,
        model_provider=DisabledModelProvider(),
        diagnosis_service=DiagnosisStub(),
        memory_repository=memories,
        memory_source=DiagnosticMemorySource(
            diagnostics=diagnostics,
            submissions=submissions,
            confidence_threshold=0.75,
        ),
        memory_index=InMemoryRetrievalIndex(),
        memory_audit=audit,
    )

    async def requests():
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": "req-check",
        }
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            first = await client.post(
                "/diagnoses/diagnosis-1/explanation-check",
                json={"explanation": "Classes use reference semantics."},
                headers=headers,
            )
            repeated = await client.post(
                "/diagnoses/diagnosis-1/explanation-check",
                json={"explanation": "Classes use reference semantics."},
                headers=headers,
            )
            skipped = await client.post(
                "/diagnoses/diagnosis-ineligible/explanation-check",
                json={"explanation": "I am not sure."},
                headers=headers,
            )
            proposals = await client.get(
                "/me/memory-proposals",
                params={"course_id": "course-1"},
                headers=headers,
            )
            return first, repeated, skipped, proposals

    first, repeated, skipped, proposals = anyio.run(requests)
    assert (first.status_code, repeated.status_code, skipped.status_code) == (200, 200, 200)
    assert len(proposals.json()) == 1
    assert proposals.json()[0]["explanation_check_id"] == "check-eligible"


def test_memory_errors_are_stable_redacted_and_keep_request_id():
    application = FastAPI()
    install_error_handling(application)

    @application.get("/storage-error")
    def storage_error():
        raise MemoryPersistenceError("private SQL and content must not escape")

    @application.get("/idempotency-error")
    def idempotency_error():
        raise IdempotencyConflict("private fingerprint must not escape")

    async def requests():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            return (
                await client.get(
                    "/storage-error", headers={"X-Request-ID": "req-storage"}
                ),
                await client.get(
                    "/idempotency-error",
                    headers={"X-Request-ID": "req-idempotency"},
                ),
            )

    storage, idempotency = anyio.run(requests)
    assert storage.status_code == 503
    assert storage.json() == {
        "code": "STORAGE_UNAVAILABLE",
        "message": "The request could not be persisted safely.",
        "request_id": "req-storage",
    }
    assert idempotency.status_code == 409
    assert idempotency.json() == {
        "code": "IDEMPOTENCY_KEY_REUSED",
        "message": "The idempotency key was already used for another request.",
        "request_id": "req-idempotency",
    }
    assert storage.headers["X-Request-ID"] == "req-storage"
    assert idempotency.headers["X-Request-ID"] == "req-idempotency"
