from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.auth.models import Role, User
from app.courses.models import Course, Exercise
from app.diagnostics.repository import DiagnosticPersistenceError
from app.diagnostics.schema import (
    CompilerDiagnosticEvidence,
    Diagnosis,
    DiagnosisCategory,
    DiagnosisLocation,
    ExplanationCheck,
    HintEvent,
    ReviewQueueEvent,
)
from app.knowledge.models import (
    Concept,
    ReviewStatus,
    SourceKind,
    SourceMetadata,
    Topic,
    VerificationStatus,
)
from app.persistence.repositories import create_sql_repositories


NOW = datetime(2026, 10, 3, tzinfo=UTC)


def _seed(database_url: str, *, create_schema: bool):
    repositories = create_sql_repositories(database_url, create_schema=create_schema)
    if create_schema:
        repositories.users.add(
            User.with_password("teacher-1", "teacher", "pw", Role.TEACHER)
        )
        repositories.users.add(
            User.with_password("student-1", "student", "pw", Role.STUDENT)
        )
        repositories.courses.add(Course("course-1", "Course", "teacher-1"))
        repositories.courses.add_exercise(
            Exercise("exercise-1", "course-1", "Exercise", True)
        )
        repositories.knowledge.create_concept(
            "course-1",
            Concept(
                id="cj.enum.match",
                topic=Topic.enum_match,
                title="Match",
                summary="Exhaustiveness",
                review_status=ReviewStatus.approved,
                source=SourceMetadata(
                    kind=SourceKind.teacher_authored,
                    references=["course"],
                    toolchain_version="cjc 1.2.0 (cjnative)",
                    verification_status=VerificationStatus.teacher_asserted,
                ),
            ),
        )
        repositories.submissions.create(
            submission_id="sub-1",
            course_id="course-1",
            exercise_id="exercise-1",
            owner_user_id="student-1",
            source_files=[{"path": "main.cj", "content": "main() {}"}],
            entrypoint="main.cj",
            is_formal=True,
            request_id="req-submit",
        )
    return repositories


def _diagnosis(*, concept_id="cj.enum.match"):
    return Diagnosis(
        diagnosis_id="diag-1",
        submission_id="sub-1",
        course_id="course-1",
        owner_user_id="student-1",
        category=DiagnosisCategory.conceptual,
        locations=(DiagnosisLocation(file="main.cj", start_line=1, end_line=1),),
        concept_ids=(concept_id,),
        root_cause="A concept was misunderstood.",
        evidence=(
            CompilerDiagnosticEvidence(
                kind="compiler_diagnostic", summary="compiler", diagnostic_index=0
            ),
        ),
        confidence=0.9,
        recommended_hint_level=1,
        requires_teacher_review=False,
        created_at=NOW,
        request_id="req-diag",
    )


def test_sql_diagnostic_state_survives_repository_recreation(tmp_path):
    url = f"sqlite:///{(tmp_path / 'diagnostics.db').as_posix()}"
    first = _seed(url, create_schema=True)
    first.diagnostics.save_diagnosis(_diagnosis())
    first.diagnostics.add_hint_event(
        HintEvent(
            hint_event_id="hint-1",
            diagnosis_id="diag-1",
            previous_level=0,
            current_level=1,
            reason="help",
            previous_attempt_count=0,
            content="Think about the cases.",
            used_safe_fallback=False,
            created_at=NOW,
            request_id="req-hint",
        )
    )
    first.diagnostics.add_explanation(
        ExplanationCheck(
            explanation_check_id="check-1",
            diagnosis_id="diag-1",
            understands=True,
            concept_ids=("cj.enum.match",),
            evidence_summary="bounded",
            confidence=0.9,
            feedback="ok",
            memory_proposal_eligible=True,
            created_at=NOW,
            request_id="req-check",
        )
    )
    first.diagnostics.add_review_event(
        ReviewQueueEvent(
            event_id="review-1",
            submission_id="sub-1",
            diagnosis_id="diag-1",
            course_id="course-1",
            owner_user_id="student-1",
            reason="manual",
            summary="review",
            created_at=NOW,
            request_id="req-review",
        )
    )

    second = _seed(url, create_schema=False)

    assert second.diagnostics.get_for_submission("sub-1").diagnosis_id == "diag-1"
    assert second.diagnostics.hint_events("diag-1")[0].current_level == 1
    assert second.diagnostics.explanation_checks()[0].memory_proposal_eligible is True
    assert second.diagnostics.review_events()[0].event_id == "review-1"


def test_sql_diagnostic_request_keys_are_idempotent(tmp_path):
    url = f"sqlite:///{(tmp_path / 'idempotent.db').as_posix()}"
    repositories = _seed(url, create_schema=True)
    repositories.diagnostics.save_diagnosis(_diagnosis())
    event = HintEvent(
        hint_event_id="hint-1",
        diagnosis_id="diag-1",
        previous_level=0,
        current_level=1,
        reason="help",
        previous_attempt_count=0,
        content="hint",
        used_safe_fallback=False,
        created_at=NOW,
        request_id="same-request",
    )

    first = repositories.diagnostics.add_hint_event(event)
    second = repositories.diagnostics.add_hint_event(
        event.model_copy(update={"hint_event_id": "hint-2", "content": "different"})
    )

    assert second == first
    assert len(repositories.diagnostics.hint_events("diag-1")) == 1


def test_sql_diagnosis_rejects_cross_course_concept(tmp_path):
    url = f"sqlite:///{(tmp_path / 'course-scope.db').as_posix()}"
    repositories = _seed(url, create_schema=True)

    with pytest.raises(DiagnosticPersistenceError):
        repositories.diagnostics.save_diagnosis(
            _diagnosis(concept_id="cj.other.course")
        )

    assert repositories.diagnostics.get_for_submission("sub-1") is None
