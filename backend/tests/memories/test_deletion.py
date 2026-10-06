from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from datetime import timedelta
from threading import Event, Lock

import pytest

from app.courses.service import ResourceNotAvailable
from app.memories.models import DeletionStatus, LearningMemoryStatus
from app.memories.retrieval import RetrievalDeletionError

from conftest import COURSE_A, PRIVATE_TEXT, STUDENT_A, TEACHER_A, create_memory


def test_index_delete_failure_is_immediately_invisible_and_retry_completes(memory_fixture):
    service = memory_fixture["service"]
    deletion = memory_fixture["deletion"]
    memory = create_memory(memory_fixture)
    memory_fixture["index"].fail_next_deletes(1)

    pending = deletion.delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete", idempotency_key="delete"
    )

    assert pending.status is DeletionStatus.deletion_pending
    assert memory_fixture["repository"].get_memory(memory.memory_id).status is LearningMemoryStatus.deletion_pending
    assert memory_fixture["repository"].get_memory(memory.memory_id).content is None
    assert service.search_memories(
        STUDENT_A, COURSE_A, PRIVATE_TEXT, purpose="learning_support"
    ) == ()

    completed = deletion.retry(
        STUDENT_A, pending.deletion_id, request_id="req-retry", idempotency_key="retry"
    )

    assert completed.status is DeletionStatus.deleted
    assert completed.reverse_lookup_absent is True
    assert memory_fixture["repository"].get_memory(memory.memory_id).status is LearningMemoryStatus.deleted
    assert memory_fixture["index"].contains(memory.index_document_id) is False


def test_reverse_lookup_verification_failure_is_audited_and_retryable(memory_fixture):
    memory = create_memory(memory_fixture)
    memory_fixture["index"].fail_next_verifications(1)

    pending = memory_fixture["deletion"].delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete-verify", idempotency_key="delete-verify"
    )

    assert pending.status is DeletionStatus.deletion_pending
    assert pending.error_code == "REVERSE_LOOKUP_NOT_EMPTY"
    assert memory_fixture["audit"].events()[-1].reason_code == "reverse_lookup_not_empty"

    completed = memory_fixture["deletion"].retry(
        STUDENT_A, pending.deletion_id, request_id="req-retry-verify", idempotency_key="retry-verify"
    )
    assert completed.status is DeletionStatus.deleted


def test_initial_cleanup_cannot_regress_a_completed_retry(memory_fixture, monkeypatch):
    memory = create_memory(memory_fixture)
    deletion = memory_fixture["deletion"]
    index = memory_fixture["index"]
    first_started = Event()
    release_first = Event()
    counter_lock = Lock()
    calls = 0
    original_delete = index.delete

    def racing_delete(document_id: str) -> None:
        nonlocal calls
        with counter_lock:
            calls += 1
            call = calls
        if call == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
            raise RetrievalDeletionError("first cleanup failed")
        original_delete(document_id)

    monkeypatch.setattr(index, "delete", racing_delete)

    with ThreadPoolExecutor(max_workers=2) as pool:
        initial = pool.submit(
            deletion.delete_memory,
            STUDENT_A,
            memory.memory_id,
            request_id="req-delete",
            idempotency_key="delete-race",
        )
        assert first_started.wait(timeout=2)
        receipt = memory_fixture["repository"].all_deletions()[0]
        retry = pool.submit(
            deletion.retry,
            STUDENT_A,
            receipt.deletion_id,
            request_id="req-retry",
            idempotency_key="retry-race",
        )
        try:
            retry.result(timeout=0.2)
        except TimeoutError:
            pass
        release_first.set()
        initial.result(timeout=2)
        retry.result(timeout=2)

    current = memory_fixture["repository"].get_deletion(receipt.deletion_id)
    assert current.status is DeletionStatus.deleted
    assert current.reverse_lookup_absent is True


def test_delayed_accept_index_write_cannot_restore_deleted_document(
    memory_fixture, monkeypatch
):
    service = memory_fixture["service"]
    proposal = service.create_proposal(STUDENT_A, "check-a", request_id="req-proposal")
    index = memory_fixture["index"]
    upsert_started = Event()
    release_upsert = Event()
    original_upsert = index.upsert

    def delayed_upsert(memory):
        upsert_started.set()
        assert release_upsert.wait(timeout=2)
        original_upsert(memory)

    monkeypatch.setattr(index, "upsert", delayed_upsert)

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(
            service.accept_proposal,
            STUDENT_A,
            proposal.proposal_id,
            request_id="req-accept",
            idempotency_key="accept-race",
        )
        assert upsert_started.wait(timeout=2)
        memory = memory_fixture["repository"].all_memories()[0]
        deleted = pool.submit(
            memory_fixture["deletion"].delete_memory,
            STUDENT_A,
            memory.memory_id,
            request_id="req-delete",
            idempotency_key="delete-delayed-accept",
        )
        try:
            deleted.result(timeout=0.2)
        except TimeoutError:
            pass
        release_upsert.set()
        accepted.result(timeout=2)
        receipt = deleted.result(timeout=2)

    assert receipt.status is DeletionStatus.deleted
    assert index.contains(memory.index_document_id) is False


def test_expiration_cannot_restore_a_deleted_stale_snapshot(memory_fixture, monkeypatch):
    memory = create_memory(memory_fixture)
    expiring = replace(
        memory,
        expires_at=memory_fixture["clock"]() + timedelta(minutes=1),
    )
    memory_fixture["repository"].save_memory(expiring)
    memory_fixture["clock"].advance(minutes=2)
    memory_fixture["deletion"].delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete", idempotency_key="delete-expired"
    )
    monkeypatch.setattr(
        memory_fixture["repository"],
        "list_memories",
        lambda _owner_user_id, _course_id: (expiring,),
    )

    assert memory_fixture["service"].list_memories(STUDENT_A, COURSE_A) == ()
    current = memory_fixture["repository"].get_memory(memory.memory_id)
    assert current.status is LearningMemoryStatus.deleted
    assert current.content is None


def test_repeated_delete_and_retry_are_idempotent(memory_fixture):
    memory = create_memory(memory_fixture)
    deletion = memory_fixture["deletion"]

    first = deletion.delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete", idempotency_key="delete-first"
    )
    repeated = deletion.delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete-again", idempotency_key="delete-again"
    )
    retried = deletion.retry(
        STUDENT_A, first.deletion_id, request_id="req-retry-after-complete", idempotency_key="retry-complete"
    )

    assert first.status is DeletionStatus.deleted
    assert repeated == first
    assert retried == first
    assert len(memory_fixture["repository"].all_deletions()) == 1


def test_pending_retries_keep_one_tombstone_and_never_restore_visibility(memory_fixture):
    service = memory_fixture["service"]
    memory = create_memory(memory_fixture)
    memory_fixture["index"].fail_next_deletes(2)

    first = memory_fixture["deletion"].delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete", idempotency_key="delete-pending"
    )
    second = memory_fixture["deletion"].retry(
        STUDENT_A, first.deletion_id, request_id="req-retry-pending", idempotency_key="retry-pending"
    )

    assert first.status is second.status is DeletionStatus.deletion_pending
    assert first.deletion_id == second.deletion_id
    assert second.attempts == 2
    assert len(memory_fixture["repository"].all_deletions()) == 1
    assert service.search_memories(
        STUDENT_A, COURSE_A, PRIVATE_TEXT, purpose="learning_support"
    ) == ()


def test_index_failure_cannot_restore_revoked_share_access(memory_fixture):
    service = memory_fixture["service"]
    memory = create_memory(memory_fixture)
    grant = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="review-before-delete",
        request_id="req-grant",
        idempotency_key="grant-before-delete",
    )
    memory_fixture["index"].fail_next_deletes(1)

    pending = memory_fixture["deletion"].delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete", idempotency_key="delete-granted"
    )

    assert pending.status is DeletionStatus.deletion_pending
    assert service.get_share_grant(STUDENT_A, grant.grant_id).status.value == "revoked"
    with pytest.raises(ResourceNotAvailable):
        service.read_shared_diagnosis(TEACHER_A, grant.grant_id)


def test_deletion_covers_all_versions_and_revokes_related_share(memory_fixture):
    service = memory_fixture["service"]
    original = create_memory(memory_fixture)
    corrected = service.correct_memory(
        STUDENT_A,
        original.memory_id,
        "Corrected private memory",
        request_id="req-correct",
        idempotency_key="correct-version",
    )
    grant = service.create_share_grant(
        STUDENT_A,
        "diagnosis-a",
        TEACHER_A.user_id,
        purpose="review",
        request_id="req-grant",
        idempotency_key="grant-review",
    )

    receipt = memory_fixture["deletion"].delete_memory(
        STUDENT_A, corrected.memory_id, request_id="req-delete", idempotency_key="delete-lineage"
    )

    assert receipt.status is DeletionStatus.deleted
    assert {
        memory_fixture["repository"].get_memory(original.memory_id).status,
        memory_fixture["repository"].get_memory(corrected.memory_id).status,
    } == {LearningMemoryStatus.deleted}
    assert service.list_memories(STUDENT_A, COURSE_A) == ()
    assert service.get_share_grant(STUDENT_A, grant.grant_id).status.value == "revoked"


def test_correction_replay_after_deletion_returns_only_redacted_state(memory_fixture):
    service = memory_fixture["service"]
    original = create_memory(memory_fixture)
    corrected = service.correct_memory(
        STUDENT_A,
        original.memory_id,
        "Corrected private memory",
        request_id="req-correct",
        idempotency_key="correct-before-delete",
    )
    memory_fixture["deletion"].delete_memory(
        STUDENT_A, corrected.memory_id, request_id="req-delete", idempotency_key="delete-corrected"
    )

    replayed = service.correct_memory(
        STUDENT_A,
        original.memory_id,
        "Corrected private memory",
        request_id="req-correct",
        idempotency_key="correct-before-delete",
    )

    assert replayed.memory_id == corrected.memory_id
    assert replayed.status is LearningMemoryStatus.deleted
    assert replayed.content is None


def test_receipt_and_audit_never_contain_private_content(memory_fixture):
    memory = create_memory(memory_fixture)

    receipt = memory_fixture["deletion"].delete_memory(
        STUDENT_A, memory.memory_id, request_id="req-delete", idempotency_key="delete-private"
    )
    serialized_receipt = json.dumps(receipt.public_dict(), ensure_ascii=False)
    serialized_audit = memory_fixture["audit"].serialized_events()

    for secret in (
        PRIVATE_TEXT,
        "main() {}",
        "embedding",
        "prompt",
        "Bearer",
        "api_key",
    ):
        assert secret not in serialized_receipt
        assert secret not in serialized_audit
    assert "content" not in receipt.public_dict()
    assert "index_document_id" not in receipt.public_dict()
