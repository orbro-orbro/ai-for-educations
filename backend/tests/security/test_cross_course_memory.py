from dataclasses import replace
import json
import pytest

from app.courses.service import ResourceNotAvailable
from app.memories.deletion import DeletionService
from app.memories.policy import CourseServiceMemoryAccess, MemoryPolicy
from .security_support import COURSE_A, COURSE_B, STUDENT_A, STUDENT_B, TEACHER, OTHER_TEACHER, PRIVATE_B, PRIVATE_OTHER_COURSE, public_denial


def test_index_cannot_expand_owner_course_or_pending_proposal_scope(security_app):
    h = security_app
    allowed = h.memories["a"]
    h.state.memory_index.inject_search_results(allowed.index_document_id, h.memories["b"].index_document_id,
        h.memories["a-other"].index_document_id, "unknown", allowed.index_document_id)
    result = h.state.memory_service.search_memories(STUDENT_A, COURSE_A, "MEMORY_SENTINEL", purpose="learning_support")
    assert result == (allowed,)
    call = h.state.memory_index.search_calls[-1]
    assert call.candidate_document_ids == frozenset({allowed.index_document_id})
    assert call.owner_user_id == STUDENT_A.user_id and call.course_id == COURSE_A
    assert PRIVATE_B not in json.dumps([m.content for m in result])
    assert PRIVATE_OTHER_COURSE not in json.dumps([m.content for m in result])
    for actor in (STUDENT_B, TEACHER):
        with pytest.raises(ResourceNotAvailable): h.state.memory_service.get_memory(actor, allowed.memory_id)


def test_revoked_enrollment_stops_memory_mutations_and_search(security_app):
    h = security_app
    h.revoke_enrollment(STUDENT_A, COURSE_A)
    for method, path, body in [("PATCH", f"/memories/{h.memories['a'].memory_id}", {"content": "replace"}),
        ("DELETE", f"/memories/{h.memories['a'].memory_id}", None),
        ("POST", f"/memory-proposals/{h.proposals['pending'].proposal_id}/accept", None)]:
        public_denial(h.request(method, path, body=body))
    public_denial(h.request("GET", f"/me/memories?course_id={COURSE_A}&query=MEMORY_SENTINEL"))


def test_share_grant_exposes_only_selected_summary_and_revocation_is_immediate(security_app):
    h = security_app
    grant = h.request("POST", "/diagnoses/diagnosis-a/share-grants", body={"grantee_user_id": TEACHER.user_id, "purpose": "synthetic-review"}).json()
    path = f"/share-grants/{grant['grant_id']}/diagnosis-summary"
    summary = h.request("GET", path, actor=TEACHER)
    assert summary.status_code == 200
    assert set(summary.json()) == {"diagnosis_id", "owner_user_id", "course_id", "category", "concept_ids", "root_cause", "confidence"}
    assert summary.json()["diagnosis_id"] == "diagnosis-a"
    assert h.memories["b"].content not in summary.text and h.memories["a-other"].content not in summary.text
    public_denial(h.request("GET", path, actor=OTHER_TEACHER))
    public_denial(h.request("GET", f"/me/memories?course_id={COURSE_A}", actor=TEACHER))
    public_denial(h.request("POST", "/diagnoses/diagnosis-a-other/share-grants", body={"grantee_user_id": TEACHER.user_id, "purpose": "cross-course"}))
    revoked = h.request("DELETE", f"/share-grants/{grant['grant_id']}")
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert public_denial(h.request("GET", path, actor=TEACHER)) == public_denial(h.request("GET", "/share-grants/unknown/diagnosis-summary", actor=TEACHER))


@pytest.mark.parametrize("failure", ["none", "index_delete", "reverse_verification"])
def test_delete_erases_lineage_and_original_query_even_when_cleanup_fails(security_app, failure):
    h = security_app
    original = h.memories["a"]
    corrected = h.state.memory_service.correct_memory(STUDENT_A, original.memory_id, "CORRECTED_PRIVATE_SENTINEL",
        request_id="correct", idempotency_key="correct")
    if failure == "index_delete": h.state.memory_index.fail_next_deletes(1)
    if failure == "reverse_verification": h.state.memory_index.fail_next_verifications(1)
    receipt = h.state.deletion_service.delete_memory(STUDENT_A, original.memory_id, request_id="delete", idempotency_key="delete")
    assert receipt.status.value == ("deleted" if failure == "none" else "deletion_pending")
    for version in h.state.memory_repository.memory_lineage(original.logical_memory_id):
        assert version.content is None
        assert version.status.value in {"deletion_pending", "deleted"}
    h.state.memory_index.inject_search_results(original.index_document_id, corrected.index_document_id)
    for query in (original.content, corrected.content):
        assert h.state.memory_service.search_memories(STUDENT_A, COURSE_A, query, purpose="learning_support") == ()
    # Construct a new service on the same authoritative store: domain recovery,
    # explicitly not PostgreSQL process persistence.
    recovered = DeletionService(repository=h.state.memory_repository, policy=MemoryPolicy(CourseServiceMemoryAccess(h.state.course_service)),
        retrieval_index=h.state.memory_index, audit=h.state.memory_audit)
    completed = recovered.retry(STUDENT_A, receipt.deletion_id, request_id="recover", idempotency_key="recover")
    assert completed.status.value == "deleted" and completed.reverse_lookup_absent
    assert not h.state.memory_index.contains(original.index_document_id)
    assert not h.state.memory_index.contains(corrected.index_document_id)
    assert original.content not in h.state.memory_audit.serialized_events()
    assert corrected.content not in h.state.memory_audit.serialized_events()


def test_late_upsert_cannot_restore_tombstoned_memory_to_retrieval(security_app):
    h = security_app
    old = h.memories["a"]
    h.state.deletion_service.delete_memory(STUDENT_A, old.memory_id, request_id="delete", idempotency_key="delete")
    h.state.memory_index.upsert(old)  # A delayed external writer has stale content.
    assert h.state.memory_service.search_memories(STUDENT_A, COURSE_A, old.content, purpose="learning_support") == ()
    assert h.state.memory_repository.get_memory(old.memory_id).content is None


def test_late_upsert_must_not_restore_physical_original_text(security_app):
    # Stronger than logical invisibility: current index has no tombstone guard.
    h = security_app
    old = h.memories["a"]
    h.state.deletion_service.delete_memory(STUDENT_A, old.memory_id, request_id="delete", idempotency_key="delete")
    h.state.memory_index.upsert(old)
    assert not h.state.memory_index.contains(old.index_document_id), "Late upsert restores a physical private-text copy after a completed deletion"


def test_retrieval_rechecks_authority_after_index_search(security_app, monkeypatch):
    h = security_app
    old = h.memories["a"]
    search = h.state.memory_index.search
    def delete_during_search(*args, **kwargs):
        found = search(*args, **kwargs)
        h.state.deletion_service.delete_memory(STUDENT_A, old.memory_id, request_id="concurrent-delete", idempotency_key="concurrent-delete")
        return found
    monkeypatch.setattr(h.state.memory_index, "search", delete_during_search)
    assert h.state.memory_service.search_memories(STUDENT_A, COURSE_A, old.content, purpose="learning_support") == ()
