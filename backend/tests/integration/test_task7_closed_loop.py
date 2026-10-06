from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec
from app.auth.models import Role, User
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, Enrollment, Exercise
from app.courses.service import CourseService
from app.diagnostics.service import DiagnosisService
from app.knowledge.models import Concept, MisconceptionPattern
from app.main import create_app
from app.memories.retrieval import InMemoryRetrievalIndex
from app.model_gateway.config import DisabledModelProvider
from app.model_gateway.mock import DeterministicMockProvider
from app.persistence.repositories import create_sql_repositories
from app.submissions.runner_client import RunnerClient
from app.submissions.service import CourseSubmissionAccess, SubmissionService


BACKEND = Path(__file__).resolve().parents[2]
CANGJIE_SOURCE = 'main() {\n    println("task7 real runner")\n}\n'


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is required for the Task 7 real-service closed loop")
    return value


def _upgrade(url: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0005_memories_audit")


def _course_service(repositories) -> CourseService:
    return CourseService(
        repositories.users,
        repositories.courses,
        repositories.enrollments,
        AuthorizationPolicy(),
    )


def _headers(token: str, request_id: str, *, idempotency_key: str | None = None):
    values = {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": request_id,
    }
    if idempotency_key is not None:
        values["Idempotency-Key"] = idempotency_key
    return values


def test_real_runner_mock_model_postgres_memory_closed_loop() -> None:
    database_url = _required("TASK7_POSTGRES_URL")
    runner_endpoint = _required("TASK7_RUNNER_ENDPOINT")
    _upgrade(database_url)
    suffix = uuid4().hex[:10]
    teacher_a = f"teacher-a-{suffix}"
    teacher_b = f"teacher-b-{suffix}"
    student_a = f"student-a-{suffix}"
    student_b = f"student-b-{suffix}"
    course_a = f"course-a-{suffix}"
    course_b = f"course-b-{suffix}"
    exercise_id = f"exercise-{suffix}"
    concept_id = f"cj.concept.loop.{suffix}"
    misconception_id = f"cj.misconception.loop.{suffix}"
    submission_id = f"submission-{suffix}"
    diagnosis_id = f"diagnosis-{suffix}"
    explanation_id = f"explanation-{suffix}"
    reference = f"exp:task7:{suffix}"
    token_secret = "task7-closed-loop-secret-at-least-16-bytes"

    repositories = create_sql_repositories(database_url)
    for user_id, role in (
        (teacher_a, Role.TEACHER),
        (teacher_b, Role.TEACHER),
        (student_a, Role.STUDENT),
        (student_b, Role.STUDENT),
    ):
        repositories.users.add(User.with_password(user_id, user_id, "pw", role))
    repositories.courses.add(Course(course_a, "仓颉语言设计", teacher_a))
    repositories.courses.add(Course(course_b, "Other course", teacher_b))
    for enrollment in (
        Enrollment(course_a, student_a, Role.STUDENT),
        Enrollment(course_a, student_b, Role.STUDENT),
        Enrollment(course_b, student_a, Role.STUDENT),
    ):
        repositories.enrollments.add(enrollment)
    repositories.courses.add_exercise(
        Exercise(exercise_id, course_a, "Program entry", is_published=True)
    )
    source = {
        "kind": "toolchain_experiment",
        "references": [reference],
        "toolchain_version": "cjc 1.2.0 (cjnative)",
        "verification_status": "experiment_verified",
    }
    repositories.knowledge.load_course(
        course_a,
        [
            Concept.model_validate(
                {
                    "id": concept_id,
                    "topic": "basics_control_flow",
                    "title": "Program entry",
                    "summary": "A Cangjie program has a valid entry point.",
                    "review_status": "approved",
                    "source": source,
                }
            )
        ],
        [],
        [
            MisconceptionPattern.model_validate(
                {
                    "id": misconception_id,
                    "topic": "basics_control_flow",
                    "title": "Program entry",
                    "root_concept_id": concept_id,
                    "related_concept_ids": [],
                    "trigger_evidence": [
                        {
                            "kind": "compiler_diagnostic",
                            "pattern": "entry",
                            "strength": "weak",
                        }
                    ],
                    "explanation": "Use a valid Cangjie program entry point.",
                    "hint_ladder": [
                        {"level": level, "outline": f"outline {level}"}
                        for level in (1, 2, 3, 4)
                    ],
                    "review_status": "approved",
                    "source": source,
                    "verification": {
                        "method": "cjc_minimal_repro",
                        "toolchain_version": "cjc 1.2.0 (cjnative)",
                        "expected_outcome": "run_ok",
                        "snippet": CANGJIE_SOURCE,
                        "note": "Task 7 real Runner Gate fixture",
                    },
                }
            )
        ],
    )
    provider = DeterministicMockProvider(
        diagnoses=[
            {
                "category": "conceptual",
                "locations": [{"file": "main.cj", "start_line": 1, "end_line": 1}],
                "concept_ids": [concept_id],
                "root_cause": "The program entry concept is understood through execution.",
                "evidence": [
                    {
                        "kind": "approved_knowledge",
                        "summary": "Approved course evidence describes the entry point.",
                        "misconception_id": misconception_id,
                        "source_reference": reference,
                    }
                ],
                "confidence": 0.92,
                "recommended_hint_level": 1,
            }
        ],
        explanations=[
            {
                "understands": True,
                "concept_ids": [concept_id],
                "evidence_summary": "Connects main to program execution.",
                "confidence": 0.91,
                "feedback": "The explanation is evidence-bound.",
            }
        ],
    )
    courses = _course_service(repositories)
    access = CourseSubmissionAccess(
        courses, is_published=lambda exercise: exercise.is_published
    )
    generated_ids = iter((diagnosis_id, explanation_id))
    diagnosis_service = DiagnosisService(
        submissions=repositories.submissions,
        knowledge=repositories.knowledge,
        repository=repositories.diagnostics,
        provider=provider,
        access=access,
        confidence_threshold=0.75,
        id_factory=generated_ids.__next__,
    )
    submission_service = SubmissionService(
        repository=repositories.submissions,
        access=access,
        runner=RunnerClient(runner_endpoint, timeout_seconds=20),
        knowledge=repositories.knowledge,
        execution_completed=lambda current_id, request_id: diagnosis_service.diagnose(
            current_id, request_id=request_id
        ),
        id_factory=lambda: submission_id,
    )
    authenticator = Authenticator(repositories.users, TokenCodec(token_secret))
    tokens = {
        user_id: authenticator.login(user_id, "pw")[0]
        for user_id in (student_a, student_b, teacher_a, teacher_b)
    }
    index = InMemoryRetrievalIndex()
    application = create_app(
        authenticator=authenticator,
        course_service=courses,
        knowledge_repository=repositories.knowledge,
        submission_repository=repositories.submissions,
        diagnostic_repository=repositories.diagnostics,
        protected_answer_lookup=repositories.courses,
        model_provider=provider,
        diagnosis_service=diagnosis_service,
        submission_service=submission_service,
        memory_repository=repositories.memories,
        memory_source=repositories.memory_source,
        memory_index=index,
        memory_audit=repositories.audit,
    )

    async def create_and_accept():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            submitted = await client.post(
                f"/exercises/{exercise_id}/submissions",
                json={
                    "source_files": [{"path": "main.cj", "content": CANGJIE_SOURCE}],
                    "entrypoint": "main.cj",
                    "is_formal": True,
                },
                headers=_headers(tokens[student_a], "submit-loop"),
            )
            execution = await client.get(
                f"/submissions/{submission_id}/execution-result",
                headers=_headers(tokens[student_a], "execution-loop"),
            )
            diagnosis = await client.get(
                f"/submissions/{submission_id}/diagnosis",
                headers=_headers(tokens[student_a], "diagnosis-loop"),
            )
            checked = await client.post(
                f"/diagnoses/{diagnosis_id}/explanation-check",
                json={"explanation": "main is where program execution begins."},
                headers=_headers(tokens[student_a], "explanation-loop"),
            )
            proposals = await client.get(
                "/me/memory-proposals",
                params={"course_id": course_a},
                headers=_headers(tokens[student_a], "proposal-list-loop"),
            )
            proposal_id = proposals.json()[0]["proposal_id"]
            accepted = await client.post(
                f"/memory-proposals/{proposal_id}/accept",
                headers=_headers(
                    tokens[student_a],
                    "accept-loop",
                    idempotency_key="accept-loop",
                ),
            )
            return submitted, execution, diagnosis, checked, proposals, accepted

    submitted, execution, diagnosis, checked, proposals, accepted = anyio.run(
        create_and_accept
    )
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "diagnosed"
    assert execution.status_code == 200
    assert execution.json()["status"] == "succeeded"
    assert execution.json()["toolchain"]["cjc"] == "1.2.0"
    assert diagnosis.status_code == 200
    assert checked.status_code == 200
    assert checked.json()["memory_proposal_eligible"] is True
    assert proposals.status_code == 200 and len(proposals.json()) == 1
    assert accepted.status_code == 200
    memory_id = accepted.json()["memory_id"]

    restarted = create_sql_repositories(database_url)
    restarted_auth = Authenticator(restarted.users, TokenCodec(token_secret))
    restarted_app = create_app(
        authenticator=restarted_auth,
        course_service=_course_service(restarted),
        knowledge_repository=restarted.knowledge,
        submission_repository=restarted.submissions,
        diagnostic_repository=restarted.diagnostics,
        protected_answer_lookup=restarted.courses,
        model_provider=DisabledModelProvider(),
        memory_repository=restarted.memories,
        memory_source=restarted.memory_source,
        memory_index=index,
        memory_audit=restarted.audit,
    )

    async def verify_restart_share_and_delete():
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app), base_url="http://test"
        ) as client:
            owner_memories = await client.get(
                "/me/memories",
                params={"course_id": course_a},
                headers=_headers(tokens[student_a], "owner-memory-list"),
            )
            other_course = await client.get(
                "/me/memories",
                params={"course_id": course_b},
                headers=_headers(tokens[student_a], "other-course-list"),
            )
            foreign_student = await client.patch(
                f"/memories/{memory_id}",
                json={"content": "forged"},
                headers=_headers(
                    tokens[student_b],
                    "foreign-memory",
                    idempotency_key="foreign-memory",
                ),
            )
            teacher_private = await client.get(
                "/me/memories",
                params={"course_id": course_a},
                headers=_headers(tokens[teacher_a], "teacher-private"),
            )
            grant = await client.post(
                f"/diagnoses/{diagnosis_id}/share-grants",
                json={
                    "grantee_user_id": teacher_a,
                    "purpose": "misconception_review",
                },
                headers=_headers(
                    tokens[student_a], "grant-loop", idempotency_key="grant-loop"
                ),
            )
            grant_id = grant.json()["grant_id"]
            teacher_summary = await client.get(
                f"/share-grants/{grant_id}/diagnosis-summary",
                headers=_headers(tokens[teacher_a], "teacher-summary"),
            )
            other_teacher = await client.get(
                f"/share-grants/{grant_id}/diagnosis-summary",
                headers=_headers(tokens[teacher_b], "other-teacher-summary"),
            )
            index.fail_next_deletes(1)
            pending = await client.delete(
                f"/memories/{memory_id}",
                headers=_headers(
                    tokens[student_a], "delete-loop", idempotency_key="delete-loop"
                ),
            )
            after_delete = await client.get(
                "/me/memories",
                params={"course_id": course_a},
                headers=_headers(tokens[student_a], "after-delete-list"),
            )
            deletion_id = pending.json()["deletion_id"]
            completed = await client.post(
                f"/memory-deletions/{deletion_id}/retry",
                headers=_headers(
                    tokens[student_a], "retry-loop", idempotency_key="retry-loop"
                ),
            )
            return (
                owner_memories,
                other_course,
                foreign_student,
                teacher_private,
                grant,
                teacher_summary,
                other_teacher,
                pending,
                after_delete,
                completed,
            )

    (
        owner_memories,
        other_course,
        foreign_student,
        teacher_private,
        grant,
        teacher_summary,
        other_teacher,
        pending,
        after_delete,
        completed,
    ) = anyio.run(verify_restart_share_and_delete)
    assert owner_memories.status_code == 200
    assert [item["memory_id"] for item in owner_memories.json()] == [memory_id]
    assert other_course.status_code == 200 and other_course.json() == []
    assert foreign_student.status_code == 404
    assert teacher_private.status_code == 404
    assert grant.status_code == 201
    assert teacher_summary.status_code == 200
    assert teacher_summary.json()["diagnosis_id"] == diagnosis_id
    assert "memory_id" not in teacher_summary.json()
    assert other_teacher.status_code == 404
    assert pending.status_code == 202
    assert pending.json()["status"] == "deletion_pending"
    assert after_delete.status_code == 200 and after_delete.json() == []
    assert completed.status_code == 200
    assert completed.json()["status"] == "deleted"
    persisted = create_sql_repositories(database_url).memories.get_memory(memory_id)
    assert persisted.status.value == "deleted"
    assert persisted.content is None
    assert len(provider.diagnosis_requests) == 1
    assert len(provider.explanation_requests) == 1
