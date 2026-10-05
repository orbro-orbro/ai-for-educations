from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.api.auth import Authenticator, TokenCodec
from app.auth.models import Actor, Role, User
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, Enrollment, Exercise
from app.courses.service import CourseService
from app.diagnostics.hints import HintLadderService
from app.diagnostics.service import DiagnosisService
from app.knowledge.models import Concept, MisconceptionPattern
from app.model_gateway.mock import DeterministicMockProvider
from app.model_gateway.config import DisabledModelProvider
from app.main import create_app
from app.persistence.repositories import create_sql_repositories
from app.submissions.models import SubmissionStatus
from app.submissions.runner_client import RunnerClient
from app.submissions.service import CourseSubmissionAccess, SubmissionService


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is required for the real-service closed loop")
    return value


def test_real_runner_mock_model_postgres_survives_recreation() -> None:
    database_url = _required("TASK6_POSTGRES_URL")
    runner_endpoint = _required("TASK6_RUNNER_ENDPOINT")
    suffix = uuid4().hex[:10]
    teacher_id = f"teacher-loop-{suffix}"
    student_id = f"student-loop-{suffix}"
    course_id = f"course-loop-{suffix}"
    exercise_id = f"exercise-loop-{suffix}"
    concept_id = f"cj.concept.loop-{suffix}"
    misconception_id = f"cj.misconception.loop-{suffix}"
    submission_id = f"sub-loop-{suffix}"
    diagnosis_id = f"diag-loop-{suffix}"
    reference = f"exp:loop:{suffix}"

    repositories = create_sql_repositories(database_url)
    repositories.users.add(
        User.with_password(teacher_id, teacher_id, "pw", Role.TEACHER)
    )
    repositories.users.add(
        User.with_password(student_id, student_id, "pw", Role.STUDENT)
    )
    repositories.courses.add(Course(course_id, "仓颉语言设计", teacher_id))
    repositories.enrollments.add(Enrollment(course_id, student_id, Role.STUDENT))
    repositories.courses.add_exercise(
        Exercise(exercise_id, course_id, "Entry point", is_published=True)
    )
    repositories.courses.set_protected_answer(
        course_id, exercise_id, "private reference answer"
    )
    source = {
        "kind": "toolchain_experiment",
        "references": [reference],
        "toolchain_version": "cjc 1.2.0 (cjnative)",
        "verification_status": "experiment_verified",
    }
    repositories.knowledge.load_course(
        course_id,
        [
            Concept.model_validate(
                {
                    "id": concept_id,
                    "topic": "basics_control_flow",
                    "title": "Program entry",
                    "summary": "A program has an entry point.",
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
                    "explanation": "Use a valid program entry point.",
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
                        "snippet": "main() {}",
                        "note": "real Runner Gate fixture",
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
                "root_cause": "The program entry concept is being checked.",
                "evidence": [
                    {
                        "kind": "approved_knowledge",
                        "summary": "approved evidence",
                        "misconception_id": misconception_id,
                        "source_reference": reference,
                    }
                ],
                "confidence": 0.92,
                "recommended_hint_level": 1,
            }
        ],
        hints=[{"level": 1, "content": "Check the declared program entry point."}],
        explanations=[
            {
                "understands": True,
                "concept_ids": [concept_id],
                "evidence_summary": "Connects the entry point to program execution.",
                "confidence": 0.91,
                "feedback": "The explanation is evidence-bound.",
            }
        ],
    )
    course_service = CourseService(
        repositories.users,
        repositories.courses,
        repositories.enrollments,
        AuthorizationPolicy(),
    )
    access = CourseSubmissionAccess(
        course_service, is_published=lambda exercise: exercise.is_published
    )
    ids = iter([diagnosis_id, f"hint-loop-{suffix}", f"check-loop-{suffix}"])
    diagnosis_service = DiagnosisService(
        submissions=repositories.submissions,
        knowledge=repositories.knowledge,
        repository=repositories.diagnostics,
        provider=provider,
        access=access,
        confidence_threshold=0.75,
        id_factory=ids.__next__,
    )
    hint_service = HintLadderService(
        repository=repositories.diagnostics,
        knowledge=repositories.knowledge,
        provider=provider,
        submissions=repositories.submissions,
        access=access,
        protected_answer_lookup=repositories.courses,
        id_factory=ids.__next__,
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
    actor = Actor(student_id, Role.STUDENT)

    submission = submission_service.submit(
        actor=actor,
        exercise_id=exercise_id,
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id=f"submit-loop-{suffix}",
        timeout_ms=10_000,
    )
    assert submission.status is SubmissionStatus.diagnosed
    execution = repositories.submissions.execution_result(submission_id)
    assert execution is not None
    assert execution.toolchain.cjc
    diagnosis = diagnosis_service.get_diagnosis(actor, submission_id)
    hint = hint_service.next_hint(
        actor,
        diagnosis.diagnosis_id,
        reason="closed loop",
        request_id=f"hint-request-loop-{suffix}",
    )
    explanation = diagnosis_service.check_explanation(
        actor,
        diagnosis.diagnosis_id,
        "A valid entry point is where program execution begins.",
        request_id=f"check-request-loop-{suffix}",
    )
    assert hint.current_level == 1
    assert explanation.memory_proposal_eligible is True

    restarted = create_sql_repositories(database_url)
    restarted_course_service = CourseService(
        restarted.users,
        restarted.courses,
        restarted.enrollments,
        AuthorizationPolicy(),
    )
    restarted_app = create_app(
        authenticator=Authenticator(
            restarted.users, TokenCodec("task6-restart-secret-at-least-16-bytes")
        ),
        course_service=restarted_course_service,
        knowledge_repository=restarted.knowledge,
        submission_repository=restarted.submissions,
        diagnostic_repository=restarted.diagnostics,
        protected_answer_lookup=restarted.courses,
        model_provider=DisabledModelProvider(),
    )
    assert restarted_app.state.diagnosis_service.get_diagnosis(
        actor, submission_id
    ) == diagnosis
    assert restarted.diagnostics.hint_events(diagnosis_id) == (hint,)
    assert restarted.diagnostics.get_explanation(
        diagnosis_id, f"check-request-loop-{suffix}"
    ) == explanation
    assert restarted.courses.for_exercise(course_id, exercise_id) == (
        "private reference answer"
    )

