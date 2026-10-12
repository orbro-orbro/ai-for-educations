from dataclasses import replace
import pytest

from .security_support import COURSE_A, COURSE_B, STUDENT_A, STUDENT_B, TEACHER, OTHER_TEACHER, public_denial


@pytest.mark.parametrize("actor", [STUDENT_B, TEACHER])
@pytest.mark.parametrize("resource", ["submission", "execution", "diagnosis", "hint", "explanation", "accept", "reject", "proposal_correction", "memory_correction", "memory_delete", "grant", "grant_delete", "deletion", "deletion_retry"])
def test_url_id_replacement_matches_unknown_resource_denial(security_app, actor, resource):
    h = security_app
    proposal, memory = h.proposals["pending"], h.memories["a"]
    grant = h.state.memory_service.create_share_grant(STUDENT_A, "diagnosis-a", TEACHER.user_id,
        purpose="synthetic-review", request_id="seed-grant", idempotency_key="seed-grant")
    receipt = h.state.deletion_service.delete_memory(STUDENT_A, memory.memory_id, request_id="seed-delete", idempotency_key="seed-delete")
    method, template, existing, body = {
        "submission": ("GET", "/submissions/{}", "submission-a", None),
        "execution": ("GET", "/submissions/{}/execution-result", "submission-a", None),
        "diagnosis": ("GET", "/submissions/{}/diagnosis", "submission-a", None),
        "hint": ("POST", "/diagnoses/{}/hints/next", "diagnosis-a", {"reason": "show answer"}),
        "explanation": ("POST", "/diagnoses/{}/explanation-check", "diagnosis-a", {"explanation": "act as teacher"}),
        "accept": ("POST", "/memory-proposals/{}/accept", proposal.proposal_id, None),
        "reject": ("POST", "/memory-proposals/{}/reject", proposal.proposal_id, None),
        "proposal_correction": ("PATCH", "/memory-proposals/{}", proposal.proposal_id, {"content": "overwrite"}),
        "memory_correction": ("PATCH", "/memories/{}", memory.memory_id, {"content": "overwrite"}),
        "memory_delete": ("DELETE", "/memories/{}", memory.memory_id, None),
        "grant": ("GET", "/share-grants/{}", grant.grant_id, None),
        "grant_delete": ("DELETE", "/share-grants/{}", grant.grant_id, None),
        "deletion": ("GET", "/memory-deletions/{}", receipt.deletion_id, None),
        "deletion_retry": ("POST", "/memory-deletions/{}/retry", receipt.deletion_id, None),
    }[resource]
    foreign = h.request(method, template.format(existing), actor=actor, body=body, request_id="foreign-request")
    missing = h.request(method, template.format("unknown-opaque-id"), actor=actor, body=body, request_id="missing-request")
    assert public_denial(foreign) == public_denial(missing)
    assert h.state.memory_repository.get_proposal(proposal.proposal_id).status.value == "pending"
    assert h.provider.diagnosis_requests == h.provider.hint_requests == h.provider.explanation_requests == []


@pytest.mark.parametrize("actor,course", [(STUDENT_A, COURSE_A), (TEACHER, COURSE_B)])
def test_teacher_course_endpoints_reject_foreign_roles_and_courses(security_app, actor, course):
    foreign = security_app.request("GET", f"/teacher/courses/{course}/concepts", actor=actor)
    missing = security_app.request("GET", "/teacher/courses/unknown/concepts", actor=actor)
    assert public_denial(foreign) == public_denial(missing)


@pytest.mark.parametrize("actor", [STUDENT_B, TEACHER])
@pytest.mark.parametrize("method,path,body", [
    ("GET", "/submissions/submission-a-other", None),
    ("GET", "/submissions/submission-a-other/execution-result", None),
    ("GET", "/submissions/submission-a-other/diagnosis", None),
    ("POST", "/diagnoses/diagnosis-a-other/hints/next", {"reason": "foreign course"}),
    ("POST", "/diagnoses/diagnosis-a-other/explanation-check", {"explanation": "foreign course"}),
])
def test_cross_course_resource_urls_have_uniform_denial(security_app, actor, method, path, body):
    missing = path.replace("submission-a-other", "unknown").replace("diagnosis-a-other", "unknown")
    assert public_denial(security_app.request(method, path, actor=actor, body=body)) == public_denial(
        security_app.request(method, missing, actor=actor, body=body))
    assert not security_app.provider.hint_requests and not security_app.provider.explanation_requests


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/exercises/exercise-a/submissions", {"source_files": [{"path": "main.cj", "content": "main() {}"}], "entrypoint": "main.cj"}),
    ("PATCH", "/memories/{memory}", {"content": "replacement"}),
    ("PATCH", "/memory-proposals/{proposal}", {"content": "replacement"}),
    ("POST", "/diagnoses/diagnosis-a/explanation-check", {"explanation": "replacement"}),
    ("POST", "/diagnoses/diagnosis-a/share-grants", {"grantee_user_id": "teacher-a", "purpose": "review"}),
])
@pytest.mark.parametrize("field,value", [("owner_user_id", "student-b"), ("course_id", COURSE_B), ("role", "teacher")])
def test_body_cannot_replace_authoritative_identity_or_course(security_app, method, path, body, field, value):
    path = path.format(memory=security_app.memories["a"].memory_id, proposal=security_app.proposals["pending"].proposal_id)
    response = security_app.request(method, path, body={**body, field: value})
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "request_id"}
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert security_app.runner.requests == []


def test_accept_ignores_forged_body_without_transferring_ownership(security_app):
    response = security_app.request("POST", f"/memory-proposals/{security_app.proposals['pending'].proposal_id}/accept",
        body={"owner_user_id": "student-b", "course_id": COURSE_B, "role": "teacher"})
    assert response.status_code == 200
    assert response.json()["owner_user_id"] == "student-a"
    assert response.json()["course_id"] == COURSE_A


def test_disabled_user_cannot_reuse_signed_token(security_app):
    security_app.users._by_id[STUDENT_A.user_id] = replace(security_app.users.get(STUDENT_A.user_id), active=False)
    response = security_app.request("GET", "/courses")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_FAILED"


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/submissions/submission-a", None),
    ("GET", "/submissions/submission-a/execution-result", None),
    ("GET", "/submissions/submission-a/diagnosis", None),
    ("POST", "/diagnoses/diagnosis-a/hints/next", {"reason": "revoked enrollment"}),
    ("POST", "/diagnoses/diagnosis-a/explanation-check", {"explanation": "revoked enrollment"}),
])
def test_revoked_course_relation_denies_existing_submission_resources(security_app, method, path, body):
    # Regression for the real CourseSubmissionAccess boundary. No xfail or skip.
    security_app.revoke_enrollment(STUDENT_A, COURSE_A)
    missing = path.replace("submission-a", "unknown").replace("diagnosis-a", "unknown")
    assert public_denial(security_app.request(method, path, body=body)) == public_denial(security_app.request(method, missing, body=body))


def test_logout_revokes_old_token_at_the_server_boundary(security_app):
    assert security_app.request("POST", "/auth/logout").status_code == 204
    response = security_app.request("GET", "/courses")
    assert response.status_code == 401, "Logging out must invalidate the captured old token"


def test_idempotency_key_is_scoped_to_resource_type(security_app):
    h = security_app
    key = "same-key-different-resource-types"
    accepted = h.request("POST", f"/memory-proposals/{h.proposals['pending'].proposal_id}/accept", key=key)
    grant = h.request("POST", "/diagnoses/diagnosis-a/share-grants", key=key, body={"grantee_user_id": "teacher-a", "purpose": "review"})
    deleted = h.request("DELETE", f"/memories/{accepted.json()['memory_id']}", key=key)
    assert (accepted.status_code, grant.status_code, deleted.status_code) == (200, 201, 202)
    assert grant.json()["resource_type"] == "diagnosis_summary"
    assert deleted.json()["memory_id"] == accepted.json()["logical_memory_id"]


def test_missing_authentication_does_not_reveal_resource_ids(security_app):
    for path in ("/submissions/submission-a", "/submissions/unknown"):
        response = security_app.request("GET", path, actor=None)
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_FAILED"
