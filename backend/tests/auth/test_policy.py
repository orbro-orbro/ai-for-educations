import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import (
    AuthenticationFailed,
    Authenticator,
    TokenCodec,
    create_auth_router,
)
from app.auth.models import Actor, Role, User, UserRepository
from app.auth.policy import AuthorizationPolicy, AuthorizationResource


def resource(
    *,
    resource_type: str = "submission",
    owner_user_id: str | None = "student-b",
    member_user_ids: frozenset[str] = frozenset(
        {"student-a", "student-b", "teacher-a"}
    ),
    course_owner_user_id: str = "teacher-a",
    authorized_teacher_user_ids: frozenset[str] = frozenset(),
    granted_teacher_user_ids: frozenset[str] = frozenset(),
    is_formal_submission: bool | None = None,
) -> AuthorizationResource:
    values = dict(
        resource_id="resource-1",
        resource_type=resource_type,
        course_id="course-1",
        owner_user_id=owner_user_id,
        member_user_ids=member_user_ids,
        course_owner_user_id=course_owner_user_id,
        authorized_teacher_user_ids=authorized_teacher_user_ids,
        granted_teacher_user_ids=granted_teacher_user_ids,
    )
    if is_formal_submission is not None:
        values["is_formal_submission"] = is_formal_submission
    return AuthorizationResource(**values)


def test_student_cannot_read_another_students_resource() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("student-a", Role.STUDENT), "read", resource()
    )

    assert decision.allowed is False
    assert decision.public_error_code == "RESOURCE_NOT_AVAILABLE"


def test_teacher_cannot_read_private_memory_without_grant() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("teacher-a", Role.TEACHER),
        "read_private_memory",
        resource(resource_type="private_memory"),
    )

    assert decision.allowed is False
    assert decision.public_error_code == "RESOURCE_NOT_AVAILABLE"


def test_teacher_can_read_private_memory_only_with_explicit_grant() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("teacher-a", Role.TEACHER),
        "read_private_memory",
        resource(
            resource_type="private_memory",
            granted_teacher_user_ids=frozenset({"teacher-a"}),
        ),
    )

    assert decision.allowed is True
    assert decision.public_error_code is None


def test_teacher_cannot_read_unshared_diagnosis_summary() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("teacher-a", Role.TEACHER),
        "read",
        resource(resource_type="diagnosis_summary"),
    )

    assert decision.allowed is False
    assert decision.public_error_code == "RESOURCE_NOT_AVAILABLE"


def test_teacher_can_read_diagnosis_summary_with_explicit_grant() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("teacher-a", Role.TEACHER),
        "read",
        resource(
            resource_type="diagnosis_summary",
            granted_teacher_user_ids=frozenset({"teacher-a"}),
        ),
    )

    assert decision.allowed is True


def test_teacher_cannot_read_student_draft_submission() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("teacher-a", Role.TEACHER),
        "read",
        resource(resource_type="submission"),
    )

    assert decision.allowed is False


def test_teacher_can_read_formal_student_submission() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("teacher-a", Role.TEACHER),
        "read",
        resource(resource_type="submission", is_formal_submission=True),
    )

    assert decision.allowed is True


def test_non_member_cannot_read_course_resource() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("student-outsider", Role.STUDENT), "read", resource()
    )

    assert decision.allowed is False
    assert decision.public_error_code == "RESOURCE_NOT_AVAILABLE"


def test_student_cannot_execute_teacher_action() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("student-a", Role.STUDENT), "manage_course", resource()
    )

    assert decision.allowed is False
    assert decision.public_error_code == "RESOURCE_NOT_AVAILABLE"


@pytest.mark.parametrize(
    ("teacher_id", "allowed"),
    [
        ("teacher-owner", True),
        ("teacher-authorized", True),
        ("teacher-outsider", False),
    ],
)
def test_teacher_manages_only_owned_or_explicitly_authorized_courses(
    teacher_id: str, allowed: bool
) -> None:
    decision = AuthorizationPolicy().authorize(
        Actor(teacher_id, Role.TEACHER),
        "manage_course",
        resource(
            resource_type="course",
            owner_user_id="teacher-owner",
            course_owner_user_id="teacher-owner",
            member_user_ids=frozenset(
                {"teacher-owner", "teacher-authorized", "teacher-outsider"}
            ),
            authorized_teacher_user_ids=frozenset({"teacher-authorized"}),
        ),
    )

    assert decision.allowed is allowed


def test_unknown_action_is_denied_by_default() -> None:
    decision = AuthorizationPolicy().authorize(
        Actor("teacher-a", Role.TEACHER), "export_everything", resource()
    )

    assert decision.allowed is False
    assert decision.public_error_code == "RESOURCE_NOT_AVAILABLE"


def test_password_is_stored_as_a_salted_hash() -> None:
    user = User.with_password(
        user_id="student-a",
        username="student-a",
        password="correct horse battery staple",
        role=Role.STUDENT,
    )

    assert user.password_hash != "correct horse battery staple"
    assert "correct horse battery staple" not in user.password_hash
    assert user.verify_password("correct horse battery staple") is True
    assert user.verify_password("wrong") is False


def test_token_secret_must_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="AUTH_TOKEN_SECRET"):
        TokenCodec.from_environment()


def test_tampered_signed_token_is_rejected() -> None:
    codec = TokenCodec("test-secret-that-is-long-enough")
    token = codec.issue(Actor("student-a", Role.STUDENT))

    with pytest.raises(AuthenticationFailed):
        codec.verify(token + "tampered")


def test_server_rechecks_role_instead_of_trusting_token_claim() -> None:
    users = UserRepository(
        [
            User.with_password(
                user_id="user-a",
                username="user-a",
                password="password",
                role=Role.TEACHER,
            )
        ]
    )
    codec = TokenCodec("test-secret-that-is-long-enough")
    authenticator = Authenticator(users, codec)
    forged_role_token = codec.issue(Actor("user-a", Role.STUDENT))

    with pytest.raises(AuthenticationFailed):
        authenticator.authenticate_token(forged_role_token)


def test_login_route_returns_token_for_server_verified_actor() -> None:
    users = UserRepository(
        [User.with_password("student-a", "student-a", "password", Role.STUDENT)]
    )
    authenticator = Authenticator(
        users, TokenCodec("test-secret-that-is-long-enough")
    )
    app = FastAPI()
    app.include_router(create_auth_router(authenticator))

    async def post_login():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                "/auth/login",
                json={"username": "student-a", "password": "password"},
            )

    response = anyio.run(post_login)

    assert response.status_code == 200
    payload = response.json()
    assert payload["actor"] == {"user_id": "student-a", "role": "student"}
    assert authenticator.authenticate_token(payload["access_token"]) == Actor(
        "student-a", Role.STUDENT
    )


def test_login_route_does_not_reveal_which_credential_was_wrong() -> None:
    users = UserRepository(
        [User.with_password("student-a", "student-a", "password", Role.STUDENT)]
    )
    authenticator = Authenticator(
        users, TokenCodec("test-secret-that-is-long-enough")
    )
    app = FastAPI()
    app.include_router(create_auth_router(authenticator))

    async def post_login(username: str, password: str):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                "/auth/login", json={"username": username, "password": password}
            )

    wrong_password = anyio.run(post_login, "student-a", "wrong")
    unknown_user = anyio.run(post_login, "unknown", "wrong")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["code"] == "AUTHENTICATION_FAILED"
