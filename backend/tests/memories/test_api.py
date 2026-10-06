from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import anyio
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec
from app.api.errors import install_error_handling
from app.api.memories import create_memories_router
from app.auth.models import Role, User, UserRepository

from conftest import COURSE_A, STUDENT_A


ROOT = Path(__file__).resolve().parents[3]


def _test_user(user_id: str, role: Role) -> User:
    salt = f"salt-{user_id}".encode()
    digest = hashlib.pbkdf2_hmac("sha256", b"password", salt, 1)
    password_hash = "pbkdf2_sha256$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )
    return User(user_id, user_id, password_hash, role)


def _app(memory_fixture):
    users = UserRepository(
        [
            _test_user("student-a", Role.STUDENT),
            _test_user("student-b", Role.STUDENT),
            _test_user("teacher-a", Role.TEACHER),
        ]
    )
    authenticator = Authenticator(users, TokenCodec("task7-test-secret-at-least-16-bytes"))
    application = FastAPI()
    install_error_handling(application)
    application.include_router(
        create_memories_router(
            memory_fixture["service"], memory_fixture["deletion"], authenticator
        )
    )
    return application, authenticator


def test_memory_api_requires_authentication_and_uses_uniform_resource_denial(memory_fixture):
    proposal = memory_fixture["service"].create_proposal(
        STUDENT_A, "check-a", request_id="req-proposal"
    )
    app, authenticator = _app(memory_fixture)
    student_b = authenticator.login("student-b", "password")[0]

    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unauthenticated = await client.get(
                "/me/memory-proposals", params={"course_id": COURSE_A}
            )
            headers = {
                "Authorization": f"Bearer {student_b}",
                "X-Request-ID": "req-api-denied",
                "Idempotency-Key": "deny-accept",
            }
            foreign = await client.post(
                f"/memory-proposals/{proposal.proposal_id}/accept", headers=headers
            )
            missing = await client.post(
                "/memory-proposals/missing/accept", headers=headers
            )
            return unauthenticated, foreign, missing

    unauthenticated, foreign, missing = anyio.run(requests)

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "AUTHENTICATION_FAILED"
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["request_id"] == "req-api-denied"


def test_owner_can_accept_list_correct_and_delete_through_api(memory_fixture):
    proposal = memory_fixture["service"].create_proposal(
        STUDENT_A, "check-a", request_id="req-proposal"
    )
    app, authenticator = _app(memory_fixture)
    token = authenticator.login("student-a", "password")[0]

    async def requests():
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": "req-api",
            "Idempotency-Key": "owner-lifecycle",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            accepted = await client.post(
                f"/memory-proposals/{proposal.proposal_id}/accept", headers=headers
            )
            memory_id = accepted.json()["memory_id"]
            listed = await client.get(
                "/me/memories", params={"course_id": COURSE_A}, headers=headers
            )
            corrected = await client.patch(
                f"/memories/{memory_id}",
                json={"content": "Corrected through API"},
                headers=headers,
            )
            acceptance_replay = await client.post(
                f"/memory-proposals/{proposal.proposal_id}/accept", headers=headers
            )
            deleted = await client.delete(
                f"/memories/{corrected.json()['memory_id']}", headers=headers
            )
            deleted_replay = await client.post(
                f"/memory-proposals/{proposal.proposal_id}/accept", headers=headers
            )
            status = await client.get(
                f"/memory-deletions/{deleted.json()['deletion_id']}", headers=headers
            )
            return (
                accepted,
                listed,
                corrected,
                acceptance_replay,
                deleted,
                deleted_replay,
                status,
            )

    accepted, listed, corrected, acceptance_replay, deleted, deleted_replay, status = anyio.run(requests)

    assert accepted.status_code == 200
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert corrected.status_code == 200 and corrected.json()["version"] == 2
    assert acceptance_replay.status_code == 200
    assert acceptance_replay.json()["status"] == "superseded"
    assert deleted.status_code == 202
    assert deleted_replay.status_code == 200
    assert deleted_replay.json()["status"] == "deleted"
    assert deleted_replay.json()["content"] is None
    assert status.status_code == 200
    assert "content" not in deleted.json()


def test_share_grant_and_deletion_retry_routes_enforce_exact_actors(memory_fixture):
    proposal = memory_fixture["service"].create_proposal(
        STUDENT_A, "check-a", request_id="req-proposal"
    )
    app, authenticator = _app(memory_fixture)
    student_token = authenticator.login("student-a", "password")[0]
    teacher_token = authenticator.login("teacher-a", "password")[0]

    async def requests():
        student_headers = {
            "Authorization": f"Bearer {student_token}",
            "X-Request-ID": "req-student-api",
            "Idempotency-Key": "student-lifecycle",
        }
        teacher_headers = {
            "Authorization": f"Bearer {teacher_token}",
            "X-Request-ID": "req-teacher-api",
            "Idempotency-Key": "teacher-lifecycle",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            accepted = await client.post(
                f"/memory-proposals/{proposal.proposal_id}/accept",
                headers=student_headers,
            )
            grant = await client.post(
                "/diagnoses/diagnosis-a/share-grants",
                json={
                    "grantee_user_id": "teacher-a",
                    "purpose": "student_requested_review",
                },
                headers=student_headers,
            )
            grant_id = grant.json()["grant_id"]
            listed = await client.get(
                "/me/share-grants",
                params={"course_id": COURSE_A},
                headers=student_headers,
            )
            shared = await client.get(
                f"/share-grants/{grant_id}/diagnosis-summary",
                headers=teacher_headers,
            )
            teacher_cannot_revoke = await client.delete(
                f"/share-grants/{grant_id}", headers=teacher_headers
            )
            revoked = await client.delete(
                f"/share-grants/{grant_id}", headers=student_headers
            )
            memory_fixture["index"].fail_next_deletes(1)
            deleted = await client.delete(
                f"/memories/{accepted.json()['memory_id']}", headers=student_headers
            )
            retried = await client.post(
                f"/memory-deletions/{deleted.json()['deletion_id']}/retry",
                headers=student_headers,
            )
            return (
                grant,
                listed,
                shared,
                teacher_cannot_revoke,
                revoked,
                deleted,
                retried,
            )

    grant, listed, shared, denied, revoked, deleted, retried = anyio.run(requests)

    assert grant.status_code == 201
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert shared.status_code == 200 and shared.json()["diagnosis_id"] == "diagnosis-a"
    assert denied.status_code == 404 and denied.json()["code"] == "RESOURCE_NOT_AVAILABLE"
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert deleted.status_code == 202 and deleted.json()["status"] == "deletion_pending"
    assert retried.status_code == 200 and retried.json()["status"] == "deleted"


def test_whitespace_correction_uses_uniform_validation_error(memory_fixture):
    proposal = memory_fixture["service"].create_proposal(
        STUDENT_A, "check-a", request_id="req-proposal"
    )
    app, authenticator = _app(memory_fixture)
    token = authenticator.login("student-a", "password")[0]

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(
                f"/memory-proposals/{proposal.proposal_id}",
                json={"content": "   "},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": "req-whitespace",
                    "Idempotency-Key": "whitespace-correction",
                },
            )

    response = anyio.run(request)

    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed.",
        "request_id": "req-whitespace",
    }


def test_timezone_free_share_expiry_uses_uniform_validation_error(memory_fixture):
    app, authenticator = _app(memory_fixture)
    token = authenticator.login("student-a", "password")[0]

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/diagnoses/diagnosis-a/share-grants",
                json={
                    "grantee_user_id": "teacher-a",
                    "purpose": "invalid-expiry",
                    "expires_at": "2026-10-07T08:00:00",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": "req-naive-expiry",
                    "Idempotency-Key": "naive-expiry",
                },
            )

    response = anyio.run(request)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["request_id"] == "req-naive-expiry"


def test_task7_contract_is_strict_scoped_and_has_no_direct_memory_create():
    contract = yaml.safe_load(
        (ROOT / "contracts/fragments/task-7-memories.yaml").read_text(encoding="utf-8")
    )

    expected_paths = {
        "/me/memory-proposals",
        "/memory-proposals/{proposal_id}/accept",
        "/memory-proposals/{proposal_id}/reject",
        "/memory-proposals/{proposal_id}",
        "/me/memories",
        "/memories/{memory_id}",
        "/memory-deletions/{deletion_id}",
        "/memory-deletions/{deletion_id}/retry",
        "/diagnoses/{diagnosis_id}/share-grants",
        "/me/share-grants",
        "/share-grants/{grant_id}",
        "/share-grants/{grant_id}/diagnosis-summary",
    }
    assert set(contract["paths"]) == expected_paths
    assert "/memories" not in contract["paths"]
    operations = [
        operation
        for path in contract["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "patch", "delete"}
    ]
    assert all(item["security"] == [{"bearerAuth": []}] for item in operations)
    assert all({"401", "404"} <= set(item["responses"]) for item in operations)
    for name in (
        "MemoryProposal",
        "LearningMemory",
        "ShareGrant",
        "DeletionReceipt",
        "ProposalCorrectionRequest",
        "MemoryCorrectionRequest",
        "ShareGrantCreateRequest",
    ):
        assert contract["components"]["schemas"][name]["additionalProperties"] is False
    assert "CourseIdQuery" in contract["components"]["parameters"]
    assert contract["components"]["schemas"]["LearningMemory"]["properties"]["content"]["type"] == ["string", "null"]
