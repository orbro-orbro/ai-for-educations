from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from app.courses.service import ResourceNotAvailable
from app.memories.models import LearningMemoryStatus, MemoryProposalStatus
from app.memories.repository import IdempotencyConflict
from app.memories.service import MemoryConflict, MemoryProposalNotEligible

from conftest import (
    COURSE_A,
    PRIVATE_TEXT,
    STUDENT_A,
    STUDENT_B,
    TEACHER_A,
    seed_task6_source,
)


def test_verified_task6_result_creates_only_a_pending_proposal(memory_fixture):
    service = memory_fixture["service"]

    proposal = service.create_proposal(
        STUDENT_A, "check-a", request_id="req-proposal"
    )

    assert proposal.status is MemoryProposalStatus.pending
    assert proposal.owner_user_id == STUDENT_A.user_id
    assert proposal.course_id == COURSE_A
    assert proposal.content == PRIVATE_TEXT
    assert service.list_memories(STUDENT_A, COURSE_A) == ()
    assert service.create_proposal(
        STUDENT_A, "check-a", request_id="req-proposal-retry"
    ) == proposal


def test_ineligible_or_unverified_task6_result_cannot_create_proposal(memory_fixture):
    seed_task6_source(
        memory_fixture["diagnostics"],
        memory_fixture["submissions"],
        explanation_id="check-ineligible",
        diagnosis_id="diagnosis-ineligible",
        submission_id="submission-ineligible",
        owner_id=STUDENT_A.user_id,
        course_id=COURSE_A,
        eligible=False,
    )
    seed_task6_source(
        memory_fixture["diagnostics"],
        memory_fixture["submissions"],
        explanation_id="check-low-confidence",
        diagnosis_id="diagnosis-low-confidence",
        submission_id="submission-low-confidence",
        owner_id=STUDENT_A.user_id,
        course_id=COURSE_A,
        diagnosis_confidence=0.5,
    )
    seed_task6_source(
        memory_fixture["diagnostics"],
        memory_fixture["submissions"],
        explanation_id="check-needs-review",
        diagnosis_id="diagnosis-needs-review",
        submission_id="submission-needs-review",
        owner_id=STUDENT_A.user_id,
        course_id=COURSE_A,
        requires_teacher_review=True,
    )

    for check_id in (
        "check-ineligible",
        "check-low-confidence",
        "check-needs-review",
    ):
        with pytest.raises(MemoryProposalNotEligible):
            memory_fixture["service"].create_proposal(
                STUDENT_A, check_id, request_id=f"req-{check_id}"
            )

    assert memory_fixture["service"].list_proposals(STUDENT_A, COURSE_A) == ()


def test_other_roles_cannot_reject_correct_or_delete_student_memory(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")

    for actor in (TEACHER_A, STUDENT_B):
        with pytest.raises(ResourceNotAvailable):
            service.reject_proposal(
                actor,
                proposal.proposal_id,
                request_id="req-denied",
                idempotency_key=f"reject-denied-{actor.user_id}",
            )
        with pytest.raises(ResourceNotAvailable):
            service.correct_proposal(
                actor,
                proposal.proposal_id,
                "unauthorized replacement",
                request_id="req-denied",
                idempotency_key=f"correct-denied-{actor.user_id}",
            )

    memory = service.accept_proposal(
        STUDENT_A, proposal.proposal_id, request_id="req-accept", idempotency_key="accept-owner"
    )
    for actor in (TEACHER_A, STUDENT_B):
        with pytest.raises(ResourceNotAvailable):
            memory_fixture["deletion"].delete_memory(
                actor,
                memory.memory_id,
                request_id="req-denied",
                idempotency_key=f"delete-denied-{actor.user_id}",
            )


def test_only_owner_student_can_accept_and_acceptance_is_idempotent(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")

    for actor in (TEACHER_A, STUDENT_B):
        with pytest.raises(ResourceNotAvailable):
            service.accept_proposal(
                actor,
                proposal.proposal_id,
                request_id="req-denied",
                idempotency_key=f"accept-denied-{actor.user_id}",
            )

    memory = service.accept_proposal(
        STUDENT_A, proposal.proposal_id, request_id="req-accept", idempotency_key="accept-first"
    )
    repeated = service.accept_proposal(
        STUDENT_A, proposal.proposal_id, request_id="req-accept-again", idempotency_key="accept-again"
    )

    assert memory.status is LearningMemoryStatus.active
    assert repeated == memory
    assert service.get_proposal(STUDENT_A, proposal.proposal_id).status is MemoryProposalStatus.accepted
    assert service.list_memories(STUDENT_A, COURSE_A) == (memory,)


def test_student_can_reject_and_repeated_rejection_is_safe(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")

    rejected = service.reject_proposal(
        STUDENT_A, proposal.proposal_id, request_id="req-reject", idempotency_key="reject-first"
    )
    repeated = service.reject_proposal(
        STUDENT_A, proposal.proposal_id, request_id="req-reject-again", idempotency_key="reject-again"
    )

    assert rejected.status is MemoryProposalStatus.rejected
    assert repeated == rejected
    assert service.list_memories(STUDENT_A, COURSE_A) == ()
    with pytest.raises(MemoryConflict):
        service.accept_proposal(
            STUDENT_A,
            proposal.proposal_id,
            request_id="req-accept-after-reject",
            idempotency_key="accept-after-reject",
        )


def test_proposal_correction_creates_audited_immutable_version(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")

    corrected = service.correct_proposal(
        STUDENT_A,
        proposal.proposal_id,
        "I now distinguish reference and value semantics.",
        request_id="req-correct",
        idempotency_key="correct-proposal",
    )
    repeated = service.correct_proposal(
        STUDENT_A,
        proposal.proposal_id,
        "I now distinguish reference and value semantics.",
        request_id="req-correct",
        idempotency_key="correct-proposal",
    )

    assert service.get_proposal(STUDENT_A, proposal.proposal_id).status is MemoryProposalStatus.superseded
    assert corrected.status is MemoryProposalStatus.pending
    assert corrected.previous_proposal_id == proposal.proposal_id
    assert corrected.root_proposal_id == proposal.root_proposal_id
    assert corrected.version == 2
    assert repeated == corrected
    audit_text = memory_fixture["audit"].serialized_events()
    assert PRIVATE_TEXT not in audit_text
    assert corrected.content not in audit_text

    with pytest.raises(IdempotencyConflict):
        service.correct_proposal(
            STUDENT_A,
            proposal.proposal_id,
            "different content with the same key",
            request_id="req-correct-reused",
            idempotency_key="correct-proposal",
        )

    with pytest.raises(MemoryConflict):
        service.correct_proposal(
            STUDENT_A,
            proposal.proposal_id,
            "a distinct edit must not be discarded",
            request_id="req-correct-distinct",
            idempotency_key="correct-proposal-distinct",
        )


def test_expired_proposal_cannot_be_accepted(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(
        STUDENT_A,
        "check-a",
        expires_at=memory_fixture["clock"]() + timedelta(minutes=1),
        request_id="req-proposal",
    )
    memory_fixture["clock"].advance(minutes=2)

    with pytest.raises(MemoryConflict):
        service.accept_proposal(
            STUDENT_A,
            proposal.proposal_id,
            request_id="req-late-accept",
            idempotency_key="late-accept",
        )

    assert service.get_proposal(STUDENT_A, proposal.proposal_id).status is MemoryProposalStatus.expired
    assert service.list_memories(STUDENT_A, COURSE_A) == ()


def test_concurrent_accept_creates_one_active_memory(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda request_id: service.accept_proposal(
                    STUDENT_A,
                    proposal.proposal_id,
                    request_id=request_id,
                    idempotency_key=request_id,
                ),
                ("req-accept-a", "req-accept-b"),
            )
        )

    assert results[0] == results[1]
    assert len(memory_fixture["repository"].all_memories()) == 1


def test_memory_correction_creates_new_active_version(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")
    original = service.accept_proposal(
        STUDENT_A,
        proposal.proposal_id,
        request_id="req-accept",
        idempotency_key="accept-for-correction",
    )

    corrected = service.correct_memory(
        STUDENT_A,
        original.memory_id,
        "Classes are references; structs have value semantics.",
        request_id="req-memory-correct",
        idempotency_key="correct-memory",
    )

    assert service.get_memory(STUDENT_A, original.memory_id).status is LearningMemoryStatus.superseded
    assert corrected.status is LearningMemoryStatus.active
    assert corrected.logical_memory_id == original.logical_memory_id
    assert corrected.previous_version_id == original.memory_id
    assert corrected.version == 2
    assert service.list_memories(STUDENT_A, COURSE_A) == (corrected,)

    replayed = service.correct_memory(
        STUDENT_A,
        original.memory_id,
        "Classes are references; structs have value semantics.",
        request_id="req-memory-correct",
        idempotency_key="correct-memory",
    )
    assert replayed == corrected
    with pytest.raises(IdempotencyConflict):
        service.correct_memory(
            STUDENT_A,
            original.memory_id,
            "a distinct edit with the same key must conflict",
            request_id="req-memory-correct-reused",
            idempotency_key="correct-memory",
        )


def test_accept_replay_returns_original_memory_current_state(memory_fixture):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")
    original = service.accept_proposal(
        STUDENT_A, proposal.proposal_id, request_id="req-accept", idempotency_key="accept-original"
    )
    service.correct_memory(
        STUDENT_A,
        original.memory_id,
        "A corrected active version.",
        request_id="req-correct",
        idempotency_key="correct-after-accept",
    )

    replayed = service.accept_proposal(
        STUDENT_A,
        proposal.proposal_id,
        request_id="req-accept-replay",
        idempotency_key="accept-replay",
    )

    assert replayed.memory_id == original.memory_id
    assert replayed.status is LearningMemoryStatus.superseded


def test_audit_failure_rolls_back_acceptance(memory_fixture, monkeypatch):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")

    def fail_audit(**_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(memory_fixture["audit"], "record", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.accept_proposal(
            STUDENT_A,
            proposal.proposal_id,
            request_id="req-accept",
            idempotency_key="accept-audit-failure",
        )

    assert memory_fixture["repository"].get_proposal(proposal.proposal_id).status is MemoryProposalStatus.pending
    assert memory_fixture["repository"].all_memories() == ()
    assert memory_fixture["index"].contains("memory-index:id-3") is False
