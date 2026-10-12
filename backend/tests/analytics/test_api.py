from __future__ import annotations

import base64
import hashlib
from functools import partial

import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.analytics.repository import InMemoryTeacherAnalyticsRepository
from app.analytics.service import TeacherAnalyticsService
from app.api.auth import Authenticator, TokenCodec
from app.api.errors import install_error_handling
from app.api.teacher import create_teacher_router
from app.audit.service import AuditService
from app.auth.models import Role, User, UserRepository

from .conftest import (
    BASE_TIME,
    COURSE_A,
    COURSE_B,
    OWNER,
    candidate,
    fact,
)


def _test_user(user_id: str, username: str, role: Role) -> User:
    salt = f"salt-{user_id}".encode()
    digest = hashlib.pbkdf2_hmac("sha256", b"password", salt, 1)
    password_hash = "pbkdf2_sha256$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )
    return User(user_id, username, password_hash, role)


@pytest.fixture
def api(course_service):
    users = UserRepository(
        [
            _test_user("teacher-owner", "owner", Role.TEACHER),
            _test_user("teacher-delegate", "delegate", Role.TEACHER),
            _test_user("teacher-other", "other", Role.TEACHER),
            _test_user("student-a", "student", Role.STUDENT),
        ]
    )
    authenticator = Authenticator(users, TokenCodec("task8-test-secret-at-least-16-bytes"))
    repository = InMemoryTeacherAnalyticsRepository(
        facts=[fact(number) for number in range(1, 6)],
        candidates=[candidate(1), candidate(2, course_id=COURSE_B)],
    )
    service = TeacherAnalyticsService(
        courses=course_service,
        repository=repository,
        audit=AuditService(clock=lambda: BASE_TIME),
        clock=lambda: BASE_TIME,
    )
    app = FastAPI()
    install_error_handling(app)
    app.include_router(create_teacher_router(service, authenticator))
    tokens = {
        username: authenticator.login(username, "password")[0]
        for username in ("owner", "delegate", "other", "student")
    }
    return app, repository, tokens


async def _request(app, method, path, *, token=None, request_id="request-api", json=None):
    headers = {"X-Request-ID": request_id}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=json)


def request(app, method, path, **kwargs):
    return anyio.run(partial(_request, app, method, path, **kwargs))


def test_teacher_api_requires_authentication_and_preserves_request_id(api) -> None:
    app, _repository, _tokens = api

    response = request(
        app,
        "GET",
        f"/teacher/courses/{COURSE_A}/analytics",
        request_id="request-unauthenticated",
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "AUTHENTICATION_FAILED",
        "message": "Authentication failed.",
        "request_id": "request-unauthenticated",
    }
    assert response.headers["X-Request-ID"] == "request-unauthenticated"


def test_teacher_analytics_api_matches_the_frozen_response(api) -> None:
    app, _repository, tokens = api

    response = request(
        app,
        "GET",
        f"/teacher/courses/{COURSE_A}/analytics",
        token=tokens["owner"],
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "status",
        "course_id",
        "filters",
        "minimum_sample_size",
        "sample_size",
        "groups",
    }
    assert set(response.json()["groups"][0]) == {
        "concept_id",
        "exercise_id",
        "category",
        "sample_size",
        "diagnosis_count",
        "independent_repair_count",
    }


def test_unknown_and_forbidden_courses_return_the_same_public_error(api) -> None:
    app, _repository, tokens = api

    forbidden = request(
        app,
        "GET",
        f"/teacher/courses/{COURSE_A}/review-queue",
        token=tokens["other"],
    )
    missing = request(
        app,
        "GET",
        "/teacher/courses/missing/review-queue",
        token=tokens["other"],
    )

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()
    assert forbidden.json()["code"] == "RESOURCE_NOT_AVAILABLE"


@pytest.mark.parametrize(
    "path",
    [
        f"/teacher/courses/{COURSE_A}/analytics?start_at=2026-10-01T02:00:00Z&end_at=2026-10-01T01:00:00Z",
        f"/teacher/courses/{COURSE_A}/analytics?start_at=2026-10-01T02:00:00",
        f"/teacher/courses/{COURSE_A}/review-queue?end_at=not-a-time",
    ],
)
def test_invalid_filters_use_the_uniform_validation_envelope(api, path) -> None:
    app, _repository, tokens = api

    response = request(
        app, "GET", path, token=tokens["owner"], request_id="request-filter"
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed.",
        "request_id": "request-filter",
    }


@pytest.mark.parametrize("query", ["concept_id=", f"exercise_id={'x' * 129}"])
def test_optional_string_filters_do_not_narrow_the_frozen_contract(api, query) -> None:
    app, _repository, tokens = api

    response = request(
        app,
        "GET",
        f"/teacher/courses/{COURSE_A}/analytics?{query}",
        token=tokens["owner"],
        request_id="request-unbounded-filter",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_sample"


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "invalid", "reason": "Reason"},
        {"decision": "confirmed", "reason": "   "},
        {"decision": "confirmed", "reason": "x" * 2001},
        {"decision": "confirmed", "reason": "Reason", "course_id": COURSE_B},
        {"decision": "confirmed", "reason": "Reason", "reviewer_user_id": "teacher-other"},
        {"decision": "confirmed", "reason": "Reason", "student_user_id": "student-a"},
    ],
)
def test_review_request_is_strict(api, payload) -> None:
    app, _repository, tokens = api

    response = request(
        app,
        "POST",
        "/teacher/diagnoses/review-diagnosis-course-a-1/review",
        token=tokens["owner"],
        request_id="request-strict",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["request_id"] == "request-strict"


def test_review_api_records_server_identity_and_returns_conflict_on_changed_replay(api) -> None:
    app, _repository, tokens = api
    path = "/teacher/diagnoses/review-diagnosis-course-a-1/review"

    first = request(
        app,
        "POST",
        path,
        token=tokens["delegate"],
        request_id="request-first",
        json={"decision": "confirmed", "reason": "  Confirmed by evidence.  "},
    )
    conflict = request(
        app,
        "POST",
        path,
        token=tokens["delegate"],
        request_id="request-conflict",
        json={"decision": "overturned", "reason": "Changed decision."},
    )

    assert first.status_code == 200
    assert first.json()["reviewer_user_id"] == "teacher-delegate"
    assert first.json()["course_id"] == COURSE_A
    assert first.json()["reason"] == "Confirmed by evidence."
    assert conflict.status_code == 409
    assert conflict.json() == {
        "code": "DIAGNOSIS_REVIEW_CONFLICT",
        "message": "The diagnosis already has a different authoritative review.",
        "request_id": "request-conflict",
    }


def test_storage_failure_is_sanitized_and_does_not_complete_queue_item(api) -> None:
    app, repository, tokens = api
    repository.fail_next_save()

    failed = request(
        app,
        "POST",
        "/teacher/diagnoses/review-diagnosis-course-a-1/review",
        token=tokens["owner"],
        request_id="request-storage",
        json={"decision": "confirmed", "reason": "Evidence is sufficient."},
    )
    queue = request(
        app,
        "GET",
        f"/teacher/courses/{COURSE_A}/review-queue",
        token=tokens["owner"],
    )

    assert failed.status_code == 503
    assert failed.json() == {
        "code": "STORAGE_UNAVAILABLE",
        "message": "Teacher analytics storage is temporarily unavailable.",
        "request_id": "request-storage",
    }
    assert [item["diagnosis_id"] for item in queue.json()["items"]] == [
        "review-diagnosis-course-a-1"
    ]


def test_analytics_read_failure_is_sanitized(api) -> None:
    app, repository, tokens = api
    repository.fail_next_read()

    response = request(
        app,
        "GET",
        f"/teacher/courses/{COURSE_A}/analytics",
        token=tokens["owner"],
        request_id="request-read-storage",
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "STORAGE_UNAVAILABLE",
        "message": "Teacher analytics storage is temporarily unavailable.",
        "request_id": "request-read-storage",
    }


def test_router_declares_the_three_frozen_operation_ids(api) -> None:
    app, _repository, _tokens = api
    document = app.openapi()

    assert document["paths"][f"/teacher/courses/{{course_id}}/analytics"]["get"][
        "operationId"
    ] == "getTeacherCourseAnalytics"
    assert document["paths"][f"/teacher/courses/{{course_id}}/review-queue"]["get"][
        "operationId"
    ] == "listTeacherReviewQueue"
    assert document["paths"]["/teacher/diagnoses/{diagnosis_id}/review"]["post"][
        "operationId"
    ] == "reviewTeacherDiagnosis"
