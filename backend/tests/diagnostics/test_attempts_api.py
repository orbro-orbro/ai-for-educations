"""ADR 0008: the HTTP boundary calls the existing checked retry service."""
import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.api.auth import Authenticator, TokenCodec
from app.api.diagnostics import create_diagnostics_router
from app.api.errors import install_error_handling
from app.auth.models import Role, User, UserRepository
from conftest import seed_executed_submission
from test_hints import setup_services


@pytest.fixture
def attempts(submissions, knowledge):
    diagnosis, service, repository, _ = setup_services(submissions, knowledge, [])
    seed_executed_submission(submissions, submission_id="sub-retry")
    users = UserRepository([User.with_password(uid, uid, "synthetic-password", role)
        for uid, role in [("student-1", Role.STUDENT), ("student-2", Role.STUDENT), ("teacher-1", Role.TEACHER)]])
    auth = Authenticator(users, TokenCodec("synthetic-attempt-api-secret-at-least-16"))
    app = FastAPI()
    install_error_handling(app)
    app.include_router(create_diagnostics_router(None, service, auth))
    def request(*, actor="student-1", submission="sub-retry", body=None):
        async def run():
            headers = {} if actor is None else {"Authorization": "Bearer " + auth.login(actor, "synthetic-password")[0]}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic") as client:
                return await client.post(f"/diagnoses/{diagnosis.diagnosis_id}/attempts", headers=headers,
                    json=body if body is not None else {"submission_id": submission})
        return anyio.run(run)
    return request, repository, diagnosis, submissions


def test_authorized_retry_association_is_idempotent(attempts):
    request, repository, diagnosis, _ = attempts
    for _ in range(2):
        response = request()
        assert response.status_code == 204 and not response.content
    assert repository.attempt_count(diagnosis.diagnosis_id) == 1


@pytest.mark.parametrize("actor,submission,status", [(None,"sub-retry",401), ("student-2","sub-retry",404),
    ("teacher-1","sub-retry",404), ("student-1","sub-1",404), ("student-1","missing",404)])
def test_denied_association_never_registers_an_attempt(attempts, actor, submission, status):
    request, repository, diagnosis, _ = attempts
    assert request(actor=actor, submission=submission).status_code == status
    assert repository.attempt_count(diagnosis.diagnosis_id) == 0


@pytest.mark.parametrize("body", [{}, {"submission_id":""}, {"submission_id":"x"*129},
    {"submission_id":"sub-retry", "owner_user_id":"student-2"}])
def test_attempt_body_rejects_missing_invalid_or_identity_fields(attempts, body):
    request, repository, diagnosis, _ = attempts
    assert request(body=body).status_code == 422
    assert repository.attempt_count(diagnosis.diagnosis_id) == 0
