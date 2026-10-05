from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app.auth.models import Role, User
from app.courses.models import Course, Exercise
from app.diagnostics.repository import DiagnosticPersistenceError
from app.diagnostics.schema import (
    CompilerDiagnosticEvidence,
    Diagnosis,
    DiagnosisCategory,
    DiagnosisLocation,
    HintEvent,
)
from app.knowledge.models import Concept, MisconceptionPattern
from app.persistence.repositories import create_sql_repositories
from app.submissions.models import utc_now


def _postgres_url() -> str:
    value = os.environ.get("TASK6_POSTGRES_URL")
    if not value:
        pytest.skip("TASK6_POSTGRES_URL is required for real PostgreSQL tests")
    return value


def _seed(url: str, suffix: str):
    repositories = create_sql_repositories(url)
    teacher = f"teacher-{suffix}"
    student = f"student-{suffix}"
    course = f"course-{suffix}"
    exercise = f"exercise-{suffix}"
    concept = f"cj.concept.{suffix}"
    misconception = f"cj.misconception.{suffix}"
    repositories.users.add(User.with_password(teacher, teacher, "pw", Role.TEACHER))
    repositories.users.add(User.with_password(student, student, "pw", Role.STUDENT))
    repositories.courses.add(Course(course, "Course", teacher))
    repositories.courses.add_exercise(Exercise(exercise, course, "Exercise", True))
    repositories.knowledge.load_course(
        course,
        [
            Concept.model_validate(
                {
                    "id": concept,
                    "topic": "basics_control_flow",
                    "title": "Program entry",
                    "summary": "A program has an entry point.",
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
        [
            MisconceptionPattern.model_validate(
                {
                    "id": misconception,
                    "topic": "basics_control_flow",
                    "title": "Program entry",
                    "root_concept_id": concept,
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
                    "source": {
                        "kind": "toolchain_experiment",
                        "references": [f"exp:{suffix}"],
                        "toolchain_version": "cjc 1.2.0 (cjnative)",
                        "verification_status": "experiment_verified",
                    },
                    "verification": {
                        "method": "cjc_minimal_repro",
                        "toolchain_version": "cjc 1.2.0 (cjnative)",
                        "expected_outcome": "run_ok",
                        "snippet": "main() {}",
                        "note": "real PostgreSQL Gate fixture",
                    },
                }
            )
        ],
    )
    return repositories, teacher, student, course, exercise, concept, misconception


def _diagnosis(*, suffix, submission, course, student, concept):
    return Diagnosis(
        diagnosis_id=f"diag-{suffix}",
        submission_id=submission,
        course_id=course,
        owner_user_id=student,
        category=DiagnosisCategory.conceptual,
        locations=(DiagnosisLocation(file="main.cj", start_line=1, end_line=1),),
        concept_ids=(concept,),
        root_cause="The program needs a valid entry point.",
        evidence=(
            CompilerDiagnosticEvidence(
                kind="compiler_diagnostic",
                summary="compiler evidence",
                diagnostic_index=0,
            ),
        ),
        confidence=0.9,
        recommended_hint_level=1,
        requires_teacher_review=False,
        created_at=utc_now(),
        request_id=f"req-{suffix}",
    )


def test_postgres_rejects_cross_course_diagnosis_concept() -> None:
    url = _postgres_url()
    suffix = uuid4().hex[:10]
    repos_a, _, student, course_a, exercise_a, _, _ = _seed(url, f"a{suffix}")
    repos_b, _, _, course_b, _, concept_b, _ = _seed(url, f"b{suffix}")
    submission = f"sub-{suffix}"
    repos_a.submissions.create(
        submission_id=submission,
        course_id=course_a,
        exercise_id=exercise_a,
        owner_user_id=student,
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id=f"create-{suffix}",
    )

    with pytest.raises(DiagnosticPersistenceError):
        repos_b.diagnostics.save_diagnosis(
            _diagnosis(
                suffix=suffix,
                submission=submission,
                course=course_a,
                student=student,
                concept=concept_b,
            )
        )

    assert repos_a.diagnostics.get_for_submission(submission) is None
    assert course_a != course_b


def test_two_repository_instances_serialize_postgres_hint_levels() -> None:
    url = _postgres_url()
    suffix = uuid4().hex[:10]
    repos, _, student, course, exercise, concept, _ = _seed(url, suffix)
    submission = f"sub-{suffix}"
    repos.submissions.create(
        submission_id=submission,
        course_id=course,
        exercise_id=exercise,
        owner_user_id=student,
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id=f"create-{suffix}",
    )
    diagnosis = repos.diagnostics.save_diagnosis(
        _diagnosis(
            suffix=suffix,
            submission=submission,
            course=course,
            student=student,
            concept=concept,
        )
    )
    barrier = Barrier(2)

    def insert_next(index: int) -> int:
        repository = create_sql_repositories(url).diagnostics
        barrier.wait()
        with repository.hint_claim(diagnosis.diagnosis_id):
            prior = repository.hint_events(diagnosis.diagnosis_id)
            level = len(prior) + 1
            repository.add_hint_event(
                HintEvent(
                    hint_event_id=f"hint-{suffix}-{index}",
                    diagnosis_id=diagnosis.diagnosis_id,
                    previous_level=level - 1,
                    current_level=level,
                    reason="concurrency Gate",
                    previous_attempt_count=0,
                    content=f"Hint level {level}",
                    used_safe_fallback=False,
                    created_at=utc_now(),
                    request_id=f"hint-request-{suffix}-{index}",
                )
            )
            return level

    with ThreadPoolExecutor(max_workers=2) as pool:
        levels = sorted(pool.map(insert_next, (1, 2)))

    assert levels == [1, 2]
    assert [
        item.current_level
        for item in create_sql_repositories(url).diagnostics.hint_events(
            diagnosis.diagnosis_id
        )
    ] == [1, 2]
