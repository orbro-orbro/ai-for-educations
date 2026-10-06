from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.courses.service import ResourceNotAvailable
from app.memories.models import ShareGrantStatus

from conftest import (
    COURSE_A,
    COURSE_B,
    PRIVATE_TEXT,
    STUDENT_A,
    STUDENT_B,
    TEACHER_A,
    TEACHER_B,
    create_memory,
)


def test_search_filters_owner_and_course_before_index_and_rechecks_results(memory_fixture):
    service = memory_fixture["service"]
    memory_a = create_memory(memory_fixture)
    foreign = create_memory(memory_fixture, actor=STUDENT_B, check_id="check-b")
    other_course = create_memory(
        memory_fixture, actor=STUDENT_A, check_id="check-course-b"
    )
    memory_fixture["index"].inject_search_results(
        memory_a.index_document_id,
        foreign.index_document_id,
        other_course.index_document_id,
        "unknown-index-id",
    )

    results = service.search_memories(
        STUDENT_A, COURSE_A, "value semantics", purpose="learning_support"
    )

    assert results == (memory_a,)
    call = memory_fixture["index"].search_calls[-1]
    assert call.owner_user_id == STUDENT_A.user_id
    assert call.course_id == COURSE_A
    assert call.candidate_document_ids == frozenset({memory_a.index_document_id})


def test_students_cannot_read_other_students_or_cross_course_memories(memory_fixture):
    service = memory_fixture["service"]
    memory_a = create_memory(memory_fixture)
    course_b_memory = create_memory(
        memory_fixture, actor=STUDENT_A, check_id="check-course-b"
    )

    with pytest.raises(ResourceNotAvailable):
        service.get_memory(STUDENT_B, memory_a.memory_id)
    assert service.search_memories(
        STUDENT_A, COURSE_A, "semantics", purpose="learning_support"
    ) == (memory_a,)
    assert course_b_memory not in service.list_memories(STUDENT_A, COURSE_A)


def test_teacher_cannot_read_private_memory_even_with_course_control(memory_fixture):
    memory = create_memory(memory_fixture)

    with pytest.raises(ResourceNotAvailable):
        memory_fixture["service"].get_memory(TEACHER_A, memory.memory_id)
    with pytest.raises(ResourceNotAvailable):
        memory_fixture["service"].search_memories(
            TEACHER_A, COURSE_A, "semantics", purpose="learning_support"
        )


def test_share_grant_is_exact_revocable_and_does_not_expose_memory(memory_fixture):
    service = memory_fixture["service"]
    memory = create_memory(memory_fixture)
    grant = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="student_requested_review",
        request_id="req-grant",
        idempotency_key="grant-exact",
    )

    summary = service.read_shared_diagnosis(TEACHER_A, grant.grant_id)

    assert summary.diagnosis_id == "diagnosis-a"
    assert summary.course_id == COURSE_A
    assert summary.owner_user_id == STUDENT_A.user_id
    with pytest.raises(ResourceNotAvailable):
        service.get_memory(TEACHER_A, memory.memory_id)
    with pytest.raises(ResourceNotAvailable):
        service.read_shared_diagnosis(TEACHER_B, grant.grant_id)

    revoked = service.revoke_share_grant(
        STUDENT_A, grant.grant_id, request_id="req-revoke", idempotency_key="revoke"
    )
    assert revoked.status is ShareGrantStatus.revoked
    assert service.revoke_share_grant(
        STUDENT_A, grant.grant_id, request_id="req-revoke-again", idempotency_key="revoke-again"
    ) == revoked
    with pytest.raises(ResourceNotAvailable):
        service.read_shared_diagnosis(TEACHER_A, grant.grant_id)


def test_revoked_scope_can_be_granted_again_with_a_new_record(memory_fixture):
    service = memory_fixture["service"]
    first = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="teacher_support",
        request_id="req-grant-first",
        idempotency_key="grant-first",
    )
    service.revoke_share_grant(
        STUDENT_A,
        first.grant_id,
        request_id="req-revoke-first",
        idempotency_key="revoke-first",
    )

    second = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="teacher_support",
        request_id="req-grant-second",
        idempotency_key="grant-second",
    )

    assert second.grant_id != first.grant_id
    assert second.status is ShareGrantStatus.active
    assert service.read_shared_diagnosis(TEACHER_A, second.grant_id).diagnosis_id == "diagnosis-a"


def test_share_grant_cannot_expand_to_another_course_or_diagnosis(memory_fixture):
    service = memory_fixture["service"]

    with pytest.raises(ResourceNotAvailable):
        service.create_share_grant(
            STUDENT_A,
            "diagnosis-course-b",
            TEACHER_A.user_id,
            purpose="wrong-course-teacher",
            request_id="req-wrong-course",
            idempotency_key="wrong-course",
        )

    grant = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="one-summary",
        request_id="req-grant",
        idempotency_key="grant-summary",
    )
    assert service.read_shared_diagnosis(TEACHER_A, grant.grant_id).diagnosis_id == "diagnosis-a"
    with pytest.raises(ResourceNotAvailable):
        service.read_diagnosis_for_teacher(TEACHER_A, "diagnosis-b")


def test_expired_share_grant_stops_access_immediately(memory_fixture):
    service = memory_fixture["service"]
    grant = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="short-review",
        expires_at=memory_fixture["clock"]() + timedelta(minutes=1),
        request_id="req-grant",
        idempotency_key="grant-expiring",
    )
    memory_fixture["clock"].advance(minutes=2)

    with pytest.raises(ResourceNotAvailable):
        service.read_shared_diagnosis(TEACHER_A, grant.grant_id)

    assert service.get_share_grant(STUDENT_A, grant.grant_id).status is ShareGrantStatus.expired


def test_share_grant_rejects_timezone_free_expiry(memory_fixture):
    with pytest.raises(ValueError, match="timezone-aware"):
        memory_fixture["service"].create_share_grant(
            STUDENT_A,
            "diagnosis-a",
            TEACHER_A.user_id,
            purpose="invalid-expiry",
            expires_at=datetime(2026, 10, 7, 8, 0),
            request_id="req-naive-expiry",
            idempotency_key="grant-naive-expiry",
        )

    assert memory_fixture["repository"].list_grants(STUDENT_A.user_id, COURSE_A) == ()


def test_current_course_membership_is_rechecked_for_owner_and_grantee(memory_fixture):
    service = memory_fixture["service"]
    memory = create_memory(memory_fixture)
    grant = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="membership-sensitive-review",
        request_id="req-grant",
        idempotency_key="grant-membership",
    )

    memory_fixture["course_access"].students.remove((COURSE_A, STUDENT_A.user_id))
    with pytest.raises(ResourceNotAvailable):
        service.get_memory(STUDENT_A, memory.memory_id)

    memory_fixture["course_access"].teachers.remove((COURSE_A, TEACHER_A.user_id))
    with pytest.raises(ResourceNotAvailable):
        service.read_shared_diagnosis(TEACHER_A, grant.grant_id)


def test_sensitive_reads_are_metadata_only_audited(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")
    service.list_proposals(STUDENT_A, COURSE_A, request_id="req-list-proposals")
    service.get_proposal(STUDENT_A, proposal.proposal_id, request_id="req-get-proposal")
    memory = service.accept_proposal(
        STUDENT_A,
        proposal.proposal_id,
        request_id="req-accept",
        idempotency_key="accept-audited",
    )
    service.get_memory(STUDENT_A, memory.memory_id, request_id="req-get-memory")
    service.list_memories(STUDENT_A, COURSE_A, request_id="req-list-memories")
    service.search_memories(
        STUDENT_A,
        COURSE_A,
        "semantics",
        purpose="learning_support",
        request_id="req-search-memories",
    )
    grant = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="audited-review",
        request_id="req-grant",
        idempotency_key="grant-audited",
    )
    service.list_share_grants(STUDENT_A, COURSE_A, request_id="req-list-grants")
    service.get_share_grant(STUDENT_A, grant.grant_id, request_id="req-get-grant")
    service.read_shared_diagnosis(
        TEACHER_A, grant.grant_id, request_id="req-shared-read"
    )

    read_events = {
        event.event_type: event.request_id for event in memory_fixture["audit"].events()
    }
    assert read_events.items() >= {
        "memory_proposals_listed": "req-list-proposals",
        "memory_proposal_read": "req-get-proposal",
        "learning_memory_read": "req-get-memory",
        "learning_memories_listed": "req-list-memories",
        "learning_memories_searched": "req-search-memories",
        "share_grants_listed": "req-list-grants",
        "share_grant_read": "req-get-grant",
        "shared_diagnosis_read": "req-shared-read",
    }.items()
    serialized = memory_fixture["audit"].serialized_events()
    assert PRIVATE_TEXT not in serialized
    assert memory.content not in serialized


def test_missing_and_unauthorized_resources_have_same_public_denial(memory_fixture):
    service = memory_fixture["service"]
    memory = create_memory(memory_fixture)

    errors = []
    for memory_id in (memory.memory_id, "missing-memory"):
        with pytest.raises(ResourceNotAvailable) as error:
            service.get_memory(STUDENT_B, memory_id)
        errors.append(error.value)

    assert [item.public_error_code for item in errors] == [
        "RESOURCE_NOT_AVAILABLE",
        "RESOURCE_NOT_AVAILABLE",
    ]
    assert str(errors[0]) == str(errors[1])
