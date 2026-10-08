from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import timedelta

import pytest

from app.analytics.repository import AnalyticsPersistenceError
from app.analytics.schemas import AnalyticsFilters
from app.analytics.service import TeacherReviewConflict
from app.auth.models import Actor, Role
from app.courses.service import ResourceNotAvailable

from .conftest import (
    BASE_TIME,
    CONCEPT_A,
    CONCEPT_B,
    COURSE_A,
    COURSE_B,
    DELEGATE,
    EXERCISE_A,
    EXERCISE_B,
    OTHER_TEACHER,
    OWNER,
    STUDENT,
    candidate,
)


def test_owner_and_authorized_teacher_see_only_pending_items_for_the_course(
    service, repository
) -> None:
    first = candidate(1)
    repository.add_candidates([first, first, candidate(2), candidate(3, course_id=COURSE_B)])

    owner_items = service.review_queue(OWNER, COURSE_A, AnalyticsFilters()).items
    delegate_items = service.review_queue(DELEGATE, COURSE_A, AnalyticsFilters()).items

    assert [item.queue_event_id for item in owner_items] == [
        "queue-course-a-1",
        "queue-course-a-2",
    ]
    assert owner_items == delegate_items
    assert all("course-b" not in item.diagnosis_id for item in owner_items)


@pytest.mark.parametrize(
    "actor, course_id",
    [
        (STUDENT, COURSE_A),
        (OTHER_TEACHER, COURSE_A),
        (Actor("teacher-revoked", Role.TEACHER), COURSE_A),
        (Actor("teacher-disabled", Role.TEACHER), COURSE_A),
        (Actor("teacher-missing", Role.TEACHER), COURSE_A),
        (OWNER, "course-missing"),
    ],
)
def test_unknown_and_unauthorized_course_access_share_one_public_denial(
    service, actor, course_id
) -> None:
    with pytest.raises(ResourceNotAvailable) as error:
        service.review_queue(actor, course_id, AnalyticsFilters())

    assert error.value.public_error_code == "RESOURCE_NOT_AVAILABLE"
    assert str(error.value) == "Resource is not available."


@pytest.mark.parametrize(
    "filters, expected",
    [
        (AnalyticsFilters(concept_id=CONCEPT_A), [1, 3]),
        (AnalyticsFilters(exercise_id=EXERCISE_B), [2]),
        (AnalyticsFilters(start_at=BASE_TIME + timedelta(hours=2)), [2, 3]),
        (AnalyticsFilters(end_at=BASE_TIME + timedelta(hours=3)), [1, 2]),
        (
            AnalyticsFilters(
                concept_id=CONCEPT_A,
                exercise_id=EXERCISE_A,
                start_at=BASE_TIME + timedelta(hours=3),
                end_at=BASE_TIME + timedelta(hours=4),
            ),
            [3],
        ),
    ],
)
def test_review_queue_applies_frozen_filters(service, repository, filters, expected) -> None:
    repository.add_candidates(
        [
            candidate(1),
            candidate(2, exercise_id=EXERCISE_B, concept_ids=(CONCEPT_B,)),
            candidate(3),
        ]
    )

    result = service.review_queue(OWNER, COURSE_A, filters)

    assert [item.queue_event_id for item in result.items] == [
        f"queue-course-a-{number}" for number in expected
    ]


def test_queue_item_contains_only_the_frozen_public_fields(service, repository) -> None:
    repository.add_candidate(candidate(1))

    item = service.review_queue(OWNER, COURSE_A, AnalyticsFilters()).items[0]

    assert set(item.model_dump()) == {
        "queue_event_id",
        "diagnosis_id",
        "submission_id",
        "exercise_id",
        "category",
        "concept_ids",
        "root_cause",
        "evidence_summaries",
        "confidence",
        "review_reason",
        "queued_at",
    }


def test_first_review_is_authoritative_and_identical_replay_is_safe(
    service, repository
) -> None:
    item = candidate(1)
    repository.add_candidate(item)

    first = service.review_diagnosis(
        OWNER,
        item.diagnosis_id,
        decision="confirmed",
        reason="  Evidence is sufficient.  ",
        request_id="request-review-1",
    )
    replay = service.review_diagnosis(
        OWNER,
        item.diagnosis_id,
        decision="confirmed",
        reason="Evidence is sufficient.",
        request_id="request-review-2",
    )

    assert replay == first
    assert first.reviewer_user_id == OWNER.user_id
    assert first.reason == "Evidence is sufficient."
    assert service.review_queue(OWNER, COURSE_A, AnalyticsFilters()).items == ()


@pytest.mark.parametrize(
    "decision, reason",
    [
        ("overturned", "Evidence is sufficient."),
        ("confirmed", "Different reason."),
    ],
)
def test_changed_review_replay_returns_a_stable_conflict(
    service, repository, decision, reason
) -> None:
    item = candidate(1)
    repository.add_candidate(item)
    service.review_diagnosis(
        OWNER,
        item.diagnosis_id,
        decision="confirmed",
        reason="Evidence is sufficient.",
        request_id="request-review-1",
    )

    with pytest.raises(TeacherReviewConflict) as error:
        service.review_diagnosis(
            OWNER,
            item.diagnosis_id,
            decision=decision,
            reason=reason,
            request_id="request-review-2",
        )

    assert error.value.public_error_code == "DIAGNOSIS_REVIEW_CONFLICT"


def test_diagnosis_course_is_resolved_server_side_before_authorization(
    service, repository
) -> None:
    foreign = candidate(1, course_id=COURSE_B)
    repository.add_candidate(foreign)

    with pytest.raises(ResourceNotAvailable):
        service.review_diagnosis(
            OWNER,
            foreign.diagnosis_id,
            decision="confirmed",
            reason="Attempted cross-course review.",
            request_id="request-cross-course",
        )


def test_unknown_diagnosis_and_cross_course_diagnosis_have_same_public_denial(
    service, repository
) -> None:
    foreign = candidate(1, course_id=COURSE_B)
    repository.add_candidate(foreign)

    with pytest.raises(ResourceNotAvailable) as cross_course:
        service.review_diagnosis(
            OWNER,
            foreign.diagnosis_id,
            decision="confirmed",
            reason="No access.",
            request_id="request-cross-course",
        )
    with pytest.raises(ResourceNotAvailable) as unknown:
        service.review_diagnosis(
            OWNER,
            "missing-diagnosis",
            decision="confirmed",
            reason="No resource.",
            request_id="request-missing",
        )

    assert str(cross_course.value) == str(unknown.value)


def test_failed_review_write_keeps_the_item_pending(service, repository) -> None:
    item = candidate(1)
    repository.add_candidate(item)
    repository.fail_next_save()

    with pytest.raises(AnalyticsPersistenceError):
        service.review_diagnosis(
            OWNER,
            item.diagnosis_id,
            decision="confirmed",
            reason="Evidence is sufficient.",
            request_id="request-write-failure",
        )

    assert [
        queued.diagnosis_id
        for queued in service.review_queue(OWNER, COURSE_A, AnalyticsFilters()).items
    ] == [item.diagnosis_id]


def test_review_audit_is_metadata_only_and_does_not_touch_private_memory(
    service, repository, audit
) -> None:
    item = candidate(1)
    repository.add_candidate(item)
    private_memory = {"content": "student private memory", "status": "active"}

    service.review_diagnosis(
        OWNER,
        item.diagnosis_id,
        decision="insufficient_evidence",
        reason="Private explanation must not be read.",
        request_id="request-audit",
    )

    assert private_memory == {"content": "student private memory", "status": "active"}
    serialized = audit.serialized_events()
    assert item.diagnosis_id in serialized
    assert COURSE_A in serialized
    assert "request-audit" in serialized
    assert "student private memory" not in serialized
    assert "Private explanation" not in serialized
    assert json.loads(serialized)[0]["owner_user_id"] == ""


class FailingAudit:
    @contextmanager
    def transaction(self):
        yield

    def record(self, **_kwargs):
        raise RuntimeError("private content must not escape")


def test_audit_failure_rolls_back_review_and_keeps_queue_pending(
    course_service, repository
) -> None:
    from app.analytics.service import TeacherAnalyticsService

    item = candidate(1)
    repository.add_candidate(item)
    service = TeacherAnalyticsService(
        courses=course_service,
        repository=repository,
        audit=FailingAudit(),
        clock=lambda: BASE_TIME + timedelta(days=1),
    )

    with pytest.raises(AnalyticsPersistenceError, match="could not be persisted"):
        service.review_diagnosis(
            OWNER,
            item.diagnosis_id,
            decision="confirmed",
            reason="Evidence is sufficient.",
            request_id="request-audit-failure",
        )

    assert repository.get_review(item.diagnosis_id) is None
    with pytest.raises(AnalyticsPersistenceError, match="could not be audited"):
        service.review_queue(OWNER, COURSE_A, AnalyticsFilters())
    # A healthy reader must still see the pending item after the failed write.
    from app.audit.service import AuditService
    reader = TeacherAnalyticsService(courses=course_service, repository=repository,
        audit=AuditService(), clock=lambda: BASE_TIME)
    assert len(reader.review_queue(OWNER, COURSE_A, AnalyticsFilters()).items) == 1
