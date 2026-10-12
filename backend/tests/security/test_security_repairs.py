from dataclasses import replace
import pytest
from pydantic import ValidationError

from app.api.auth import AuthenticationFailed
from app.auth.revocations import AuthenticationStorageError
from app.memories.retrieval import InMemoryRetrievalIndex
from app.model_gateway.base import SourceContext
from app.model_gateway.mock import DeterministicMockProvider
from .security_support import build_harness, SyntheticRunner, model_output, STUDENT_A
from app.diagnostics.service import ExecutionEvidenceUnavailable


def test_logout_only_revokes_this_login_and_requires_authentication(security_app):
    h = security_app
    first, actor = h.state.authenticator.login("student-a", "synthetic-password")
    second, _ = h.state.authenticator.login("student-a", "synthetic-password")
    assert first != second, "Distinct logins need distinct token IDs"
    h.tokens[actor.user_id] = first
    assert h.request("POST", "/auth/logout").status_code == 204
    with pytest.raises(AuthenticationFailed): h.state.authenticator.authenticate_token(first)
    assert h.state.authenticator.authenticate_token(second) == actor
    assert h.request("POST", "/auth/logout", actor=None).status_code == 401


def test_gateway_schema_rejects_source_content():
    with pytest.raises(ValidationError): SourceContext(path="main.cj", content="RAW_SOURCE_SENTINEL")


def test_compiler_and_rule_echoes_do_not_smuggle_raw_source_to_provider():
    class EchoingRunner(SyntheticRunner):
        def execute(self, request):
            result = super().execute(request)
            diagnostic = result.diagnostics[0].model_copy(update={"message": "non-exhaustive patterns RAW_SOURCE_ECHO_SENTINEL main() { secret() }"})
            return result.model_copy(update={"diagnostics": [diagnostic]})
    h = build_harness(runner=EchoingRunner(), provider=DeterministicMockProvider(diagnoses=[model_output()]))
    response = h.request("POST", "/exercises/exercise-a/submissions", body={
        "source_files": [{"path": "main.cj", "content": "main() {}"}], "entrypoint": "main.cj"})
    assert response.status_code == 201
    assert h.provider.diagnosis_requests
    assert "RAW_SOURCE_ECHO_SENTINEL" not in h.provider.diagnosis_requests[0].model_dump_json()
    assert "RAW_SOURCE_ECHO_SENTINEL" in h.state.submission_repository.execution_result(response.json()["submission_id"]).diagnostics[0].message


def test_rebuilt_index_rejects_tombstone_and_forged_current_content(security_app):
    h = security_app
    old = h.memories["a"]
    h.state.deletion_service.delete_memory(STUDENT_A, old.memory_id, request_id="delete", idempotency_key="delete")
    rebuilt = InMemoryRetrievalIndex(repository=h.state.memory_repository)
    rebuilt.upsert(old)
    assert not rebuilt.contains(old.index_document_id)
    current = h.memories["b"]
    rebuilt.upsert(replace(current, content="FORGED_CONTENT"))
    assert not rebuilt.contains(current.index_document_id)


def test_deleted_original_absent_from_source_proposals_and_future_explanation_context():
    h = build_harness(provider=DeterministicMockProvider(explanations=[{
        "understands": False, "concept_ids": [], "evidence_summary": "No evidence", "confidence": 0,
        "feedback": "Reflect."}]))
    old = h.memories["a"]
    h.state.deletion_service.delete_memory(STUDENT_A, old.memory_id, request_id="delete", idempotency_key="delete")
    proposals = h.state.memory_repository.list_proposals(STUDENT_A.user_id, old.course_id)
    assert all(old.content not in p.content for p in proposals)
    assert old.content not in h.state.diagnostic_repository.get(old.source_diagnosis_id).model_dump_json()
    response = h.request("POST", "/diagnoses/diagnosis-a/explanation-check", body={"explanation": "A fresh explanation."})
    assert response.status_code == 200
    assert old.content not in h.provider.explanation_requests[0].model_dump_json()


@pytest.mark.parametrize("failure", ["read", "write"])
def test_revocation_storage_failure_is_closed_and_sanitized(security_app, caplog, failure):
    secret = "SYNTHETIC_REVOCATION_DB_SECRET"
    class FailedStore:
        def contains(self, _digest):
            if failure == "read": raise AuthenticationStorageError(secret)
            return False
        def revoke(self, _digest, _expires): raise AuthenticationStorageError(secret)
    security_app.state.authenticator._revocations = FailedStore()
    response = security_app.request("POST", "/auth/logout")
    assert response.status_code == 503
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"
    assert secret not in response.text + caplog.text


@pytest.mark.parametrize("variant", ["padding", "unused_bits"])
def test_equivalent_signature_encoding_cannot_bypass_logout(security_app, variant):
    h = security_app
    token = h.tokens[STUDENT_A.user_id]
    assert h.request("POST", "/auth/logout").status_code == 204
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    altered = token + "=" if variant == "padding" else token[:-1] + alphabet[alphabet.index(token[-1]) + 1]
    with pytest.raises(AuthenticationFailed): h.state.authenticator.authenticate_token(altered)


def test_failed_run_cache_does_not_block_erasure(security_app):
    h = security_app
    h.state.diagnostic_repository.save_run_result("unrelated-missing", "failed", ExecutionEvidenceUnavailable())
    response = h.request("DELETE", f"/memories/{h.memories['a'].memory_id}")
    assert response.status_code == 202
    assert response.json()["status"] == "deleted"


def test_late_source_snapshot_cannot_recreate_deleted_proposal(security_app, monkeypatch):
    h = security_app
    old_check = next(e for e in h.state.diagnostic_repository.explanation_checks() if e.diagnosis_id == "diagnosis-a")
    later = old_check.model_copy(update={"explanation_check_id": "late-check", "request_id": "late-check"})
    h.state.diagnostic_repository.add_explanation(later)
    original = h.state.memory_source.proposal_source
    def snapshot_then_delete(check_id):
        source = original(check_id)
        monkeypatch.setattr(h.state.memory_source, "proposal_source", original)
        h.state.deletion_service.delete_memory(STUDENT_A, h.memories["a"].memory_id, request_id="delete", idempotency_key="delete")
        return source
    monkeypatch.setattr(h.state.memory_source, "proposal_source", snapshot_then_delete)
    from app.memories.service import MemoryProposalNotEligible
    with pytest.raises(MemoryProposalNotEligible):
        h.state.memory_service.create_proposal(STUDENT_A, later.explanation_check_id, request_id="late")
    assert h.state.memory_repository.get_proposal_for_explanation(later.explanation_check_id) is None


def test_late_explanation_output_is_redacted_after_delete():
    old_text = "PRIVATE_A_MEMORY_SENTINEL_c387"
    h = build_harness()
    def delete_then_reply(_request):
        h.state.deletion_service.delete_memory(STUDENT_A, h.memories["a"].memory_id, request_id="delete", idempotency_key="delete")
        return {"understands": True, "concept_ids": ["cj.pattern-match.exhaustiveness"],
            "evidence_summary": old_text, "feedback": old_text, "confidence": 1}
    h.provider.check_explanation = delete_then_reply
    response = h.request("POST", "/diagnoses/diagnosis-a/explanation-check", body={"explanation": "fresh explanation"})
    assert response.status_code == 200
    assert old_text not in response.text
    assert response.json()["memory_proposal_eligible"] is False
    assert all(old_text not in result.model_dump_json() for result in h.state.diagnostic_repository.explanation_checks())


def test_late_hint_and_run_cache_cannot_restore_erased_context(security_app):
    from datetime import UTC, datetime
    from app.diagnostics.schema import HintEvent
    from app.diagnostics.service import DiagnosisRunResult
    h = security_app
    stale = h.state.diagnostic_repository.get("diagnosis-a")
    h.state.deletion_service.delete_memory(STUDENT_A, h.memories["a"].memory_id, request_id="delete", idempotency_key="delete")
    hint = h.state.diagnostic_repository.add_hint_event(HintEvent(
        hint_event_id="late-hint", diagnosis_id="diagnosis-a", previous_level=0, current_level=1,
        reason=stale.root_cause, content=stale.root_cause, previous_attempt_count=0,
        used_safe_fallback=False, created_at=datetime.now(UTC), request_id="late-hint"))
    assert stale.root_cause not in hint.model_dump_json()
    h.state.diagnostic_repository.save_run_result(stale.submission_id, "late-run", DiagnosisRunResult(stale, None))
    assert stale.root_cause not in h.state.diagnostic_repository.get_run_result(stale.submission_id, "late-run").diagnosis.model_dump_json()


@pytest.mark.parametrize("operation", ["accept", "correct"])
def test_deleted_source_pending_proposal_cannot_create_new_memory(security_app, operation):
    from app.memories.service import MemoryConflict
    h = security_app
    check = next(e for e in h.state.diagnostic_repository.explanation_checks() if e.diagnosis_id == "diagnosis-a")
    late = check.model_copy(update={"explanation_check_id": "second-check", "request_id": "second-check"})
    h.state.diagnostic_repository.add_explanation(late)
    pending = h.state.memory_service.create_proposal(STUDENT_A, late.explanation_check_id, request_id="second")
    h.state.deletion_service.delete_memory(STUDENT_A, h.memories["a"].memory_id, request_id="delete", idempotency_key="delete")
    with pytest.raises(MemoryConflict):
        if operation == "accept":
            h.state.memory_service.accept_proposal(STUDENT_A, pending.proposal_id, request_id="late", idempotency_key="late")
        else:
            h.state.memory_service.correct_proposal(STUDENT_A, pending.proposal_id, h.memories["a"].content, request_id="late", idempotency_key="late")
