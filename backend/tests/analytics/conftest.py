from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.analytics.models import AnalyticsDiagnosisFact, TeacherReviewCandidate
from app.analytics.repository import InMemoryTeacherAnalyticsRepository
from app.analytics.service import TeacherAnalyticsService
from app.audit.service import AuditService
from app.auth.models import Actor, Role, User, UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, CourseRepository, EnrollmentRepository
from app.courses.service import CourseService


COURSE_A = "course-a"
COURSE_B = "course-b"
CONCEPT_A = "cj.concept.a"
CONCEPT_B = "cj.concept.b"
EXERCISE_A = "exercise-a"
EXERCISE_B = "exercise-b"
BASE_TIME = datetime(2026, 10, 1, tzinfo=UTC)

OWNER = Actor("teacher-owner", Role.TEACHER)
DELEGATE = Actor("teacher-delegate", Role.TEACHER)
OTHER_TEACHER = Actor("teacher-other", Role.TEACHER)
STUDENT = Actor("student-a", Role.STUDENT)


def fact(
    number: int,
    *,
    course_id: str = COURSE_A,
    subject_key: str | None = None,
    exercise_id: str = EXERCISE_A,
    concept_ids: tuple[str, ...] = (CONCEPT_A,),
    category: str = "conceptual",
    diagnosed_at: datetime | None = None,
    independent_repaired: bool = False,
) -> AnalyticsDiagnosisFact:
    return AnalyticsDiagnosisFact(
        diagnosis_id=f"diagnosis-{course_id}-{number}",
        course_id=course_id,
        subject_key=subject_key or f"subject-{number}",
        submission_id=f"submission-{course_id}-{number}",
        exercise_id=exercise_id,
        category=category,
        concept_ids=concept_ids,
        diagnosed_at=diagnosed_at or BASE_TIME + timedelta(hours=number),
        independent_repaired=independent_repaired,
    )


def candidate(
    number: int,
    *,
    course_id: str = COURSE_A,
    exercise_id: str = EXERCISE_A,
    concept_ids: tuple[str, ...] = (CONCEPT_A,),
    queued_at: datetime | None = None,
) -> TeacherReviewCandidate:
    return TeacherReviewCandidate(
        queue_event_id=f"queue-{course_id}-{number}",
        diagnosis_id=f"review-diagnosis-{course_id}-{number}",
        course_id=course_id,
        submission_id=f"review-submission-{course_id}-{number}",
        exercise_id=exercise_id,
        category="conceptual",
        concept_ids=concept_ids,
        root_cause="Evidence-bound root cause.",
        evidence_summaries=("Approved evidence summary.",),
        confidence=0.42,
        review_reason="low_confidence",
        queued_at=queued_at or BASE_TIME + timedelta(hours=number),
    )


@pytest.fixture
def course_service() -> CourseService:
    users = UserRepository(
        [
            User.with_password("teacher-owner", "owner", "password", Role.TEACHER),
            User.with_password("teacher-delegate", "delegate", "password", Role.TEACHER),
            User.with_password("teacher-other", "other", "password", Role.TEACHER),
            User.with_password("teacher-revoked", "revoked", "password", Role.TEACHER),
            User.with_password(
                "teacher-disabled", "disabled", "password", Role.TEACHER, active=False
            ),
            User.with_password("student-a", "student", "password", Role.STUDENT),
        ]
    )
    courses = CourseRepository(
        [
            Course(
                COURSE_A,
                "Course A",
                "teacher-owner",
                authorized_teacher_ids=frozenset({"teacher-delegate"}),
            ),
            Course(COURSE_B, "Course B", "teacher-other"),
        ]
    )
    return CourseService(users, courses, EnrollmentRepository(), AuthorizationPolicy())


@pytest.fixture
def repository() -> InMemoryTeacherAnalyticsRepository:
    return InMemoryTeacherAnalyticsRepository()


@pytest.fixture
def audit() -> AuditService:
    return AuditService(
        clock=lambda: BASE_TIME + timedelta(days=1),
        id_factory=lambda: "audit-teacher-review",
    )


@pytest.fixture
def service(course_service, repository, audit) -> TeacherAnalyticsService:
    return TeacherAnalyticsService(
        courses=course_service,
        repository=repository,
        audit=audit,
        clock=lambda: BASE_TIME + timedelta(days=1),
    )
