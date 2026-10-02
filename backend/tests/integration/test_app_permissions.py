from __future__ import annotations

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec
from app.auth.models import Actor, Role, User, UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, CourseRepository, EnrollmentRepository
from app.courses.service import CourseService
from app.knowledge.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app import main as main_module


SECRET = "integration-secret-at-least-16-bytes"
COURSE = "course-owner"


def _fixture():
    users = UserRepository(
        [
            User.with_password("teacher-owner", "owner", "pw", Role.TEACHER),
            User.with_password("teacher-other", "other", "pw", Role.TEACHER),
            User.with_password("teacher-authorized", "authorized", "pw", Role.TEACHER),
            User.with_password("student-1", "student", "pw", Role.STUDENT),
        ]
    )
    codec = TokenCodec(SECRET)
    authenticator = Authenticator(users, codec)
    courses = CourseRepository(
        [
            Course(
                COURSE,
                "仓颉语言设计",
                "teacher-owner",
                authorized_teacher_ids=frozenset({"teacher-authorized"}),
            )
        ]
    )
    service = CourseService(users, courses, EnrollmentRepository(), AuthorizationPolicy())
    app = create_app(
        authenticator=authenticator,
        course_service=service,
        knowledge_repository=InMemoryKnowledgeRepository(),
    )
    tokens = {
        role: codec.issue(Actor(user_id, actor_role))
        for role, user_id, actor_role in (
            ("owner", "teacher-owner", Role.TEACHER),
            ("other", "teacher-other", Role.TEACHER),
            ("authorized", "teacher-authorized", Role.TEACHER),
            ("student", "student-1", Role.STUDENT),
        )
    }
    return app, tokens


def _request(app, method: str, path: str, token: str | None, *, request_id="req-integration"):
    async def go():
        headers = {"X-Request-ID": request_id}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, headers=headers)

    return anyio.run(go)


def test_real_bearer_owner_can_reach_knowledge_api():
    app, tokens = _fixture()

    response = _request(app, "GET", f"/teacher/courses/{COURSE}/concepts", tokens["owner"])

    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Request-ID"] == "req-integration"


def test_explicitly_authorized_teacher_can_reach_knowledge_api():
    app, tokens = _fixture()
    response = _request(app, "GET", f"/teacher/courses/{COURSE}/concepts", tokens["authorized"])
    assert response.status_code == 200


def test_missing_bearer_is_uniform_authentication_error():
    app, _ = _fixture()

    response = _request(app, "GET", f"/teacher/courses/{COURSE}/concepts", None)

    assert response.status_code == 401
    assert response.json() == {
        "code": "AUTHENTICATION_FAILED",
        "message": "Authentication failed.",
        "request_id": "req-integration",
    }


def test_student_other_teacher_and_unknown_course_do_not_leak_existence():
    app, tokens = _fixture()
    cases = [
        (COURSE, tokens["student"]),
        (COURSE, tokens["other"]),
        ("course-unknown", tokens["owner"]),
    ]

    responses = [
        _request(app, "GET", f"/teacher/courses/{course_id}/concepts", token)
        for course_id, token in cases
    ]

    assert {response.status_code for response in responses} == {404}
    assert {response.text for response in responses} == {
        '{"code":"RESOURCE_NOT_AVAILABLE","message":"Resource is not available.","request_id":"req-integration"}'
    }


def test_request_models_reject_unknown_fields_with_shared_error_shape():
    app, _ = _fixture()

    async def go():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/auth/login",
                headers={"X-Request-ID": "req-validation"},
                json={"username": "owner", "password": "pw", "admin": True},
            )

    response = anyio.run(go)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["request_id"] == "req-validation"


def test_production_rejects_the_development_token_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "development-only-token-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_TOKEN_SECRET"):
        main_module._default_dependencies()
