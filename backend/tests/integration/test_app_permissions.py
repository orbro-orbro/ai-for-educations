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


def _request(app, method: str, path: str, token: str | None, *, request_id="req-integration", json=None):
    async def go():
        headers = {"X-Request-ID": request_id}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, headers=headers, json=json)

    return anyio.run(go)


SOURCE = {
    "kind": "teacher_authored",
    "references": ["course:integration"],
    "toolchain_version": "cjc 1.2.0 (cjnative) / cjpm 1.2.0",
    "verification_status": "teacher_asserted",
}
ROOT_ID = "cj.pattern-match.exhaustiveness"
RELATED_ID = "cj.pattern-match.wildcard"
EXPLAINER_ID = "cj.pattern-match.match-expression"
MISCONCEPTION_ID = "cj.misconception.match-non-exhaustive"


def _concept(concept_id):
    return {"id": concept_id, "topic": "enum_match", "title": concept_id, "summary": "summary", "source": SOURCE}


def _misconception():
    return {
        "id": MISCONCEPTION_ID,
        "topic": "enum_match",
        "title": "match without wildcard",
        "root_concept_id": ROOT_ID,
        "related_concept_ids": [RELATED_ID],
        "trigger_evidence": [{"kind": "compiler_diagnostic", "pattern": "non-exhaustive patterns", "strength": "strong"}],
        "explanation": "match must be exhaustive",
        "hint_ladder": [{"level": level, "outline": f"step {level}"} for level in (1, 2, 3, 4)],
        "source": SOURCE,
        "verification": {"method": "teacher_assertion", "toolchain_version": "cjc 1.2.0 (cjnative)", "note": "integration"},
    }


def _seed_graph(app, token):
    base = f"/teacher/courses/{COURSE}"
    for concept_id in (ROOT_ID, RELATED_ID, EXPLAINER_ID):
        assert _request(app, "POST", f"{base}/concepts", token, json=_concept(concept_id)).status_code == 201
    assert _request(app, "POST", f"{base}/misconceptions", token, json=_misconception()).status_code == 201
    edge = {"source_id": EXPLAINER_ID, "target_id": MISCONCEPTION_ID, "edge_type": "explains_error"}
    assert _request(app, "POST", f"{base}/concept-edges", token, json=edge).status_code == 201


def test_review_records_reviewer_from_verified_bearer_not_from_request():
    app, tokens = _fixture()
    _seed_graph(app, tokens["authorized"])
    path = f"/teacher/courses/{COURSE}/concepts/{ROOT_ID}/review"

    injected = _request(app, "POST", path, tokens["authorized"], json={"decision": "approved", "reviewed_by": "teacher-owner"})
    reviewed = _request(app, "POST", path, tokens["authorized"], json={"decision": "approved", "note": "checked"})

    assert injected.status_code == 422
    assert injected.json()["code"] == "VALIDATION_ERROR"
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewed_by"] == "teacher-authorized"


def test_review_is_denied_uniformly_for_student_foreign_teacher_and_unknown_course():
    app, tokens = _fixture()
    _seed_graph(app, tokens["owner"])
    cases = [
        (f"/teacher/courses/{COURSE}/concepts/{ROOT_ID}/review", tokens["student"]),
        (f"/teacher/courses/{COURSE}/concepts/{ROOT_ID}/review", tokens["other"]),
        (f"/teacher/courses/{COURSE}/misconceptions/{MISCONCEPTION_ID}/review", tokens["student"]),
        (f"/teacher/courses/{COURSE}/misconceptions/{MISCONCEPTION_ID}/review", tokens["other"]),
        (f"/teacher/courses/course-unknown/concepts/{ROOT_ID}/review", tokens["owner"]),
        (f"/teacher/courses/{COURSE}/concepts/cj.missing.node/review", tokens["owner"]),
    ]

    responses = [_request(app, "POST", path, token, json={"decision": "approved"}) for path, token in cases]

    assert {response.status_code for response in responses} == {404}
    assert {response.text for response in responses} == {
        '{"code":"RESOURCE_NOT_AVAILABLE","message":"Resource is not available.","request_id":"req-integration"}'
    }
    concept = app.state.knowledge_repository.get_concept(COURSE, ROOT_ID)
    assert concept.review_status.value == "pending_review"


def test_misconception_becomes_evidence_only_after_full_concept_closure_is_approved():
    app, tokens = _fixture()
    _seed_graph(app, tokens["owner"])
    repository = app.state.knowledge_repository
    base = f"/teacher/courses/{COURSE}"

    def review(kind, node_id):
        response = _request(app, "POST", f"{base}/{kind}/{node_id}/review", tokens["owner"], json={"decision": "approved"})
        assert response.status_code == 200

    review("concepts", ROOT_ID)
    review("misconceptions", MISCONCEPTION_ID)
    assert repository.approved_evidence(COURSE) == []
    review("concepts", RELATED_ID)
    assert repository.approved_evidence(COURSE) == []
    review("concepts", EXPLAINER_ID)
    assert [item.misconception_id for item in repository.approved_evidence(COURSE)] == [MISCONCEPTION_ID]

    edited = _request(app, "PATCH", f"{base}/concepts/{RELATED_ID}", tokens["owner"], json={"summary": "edited"})
    assert edited.json()["review_status"] == "pending_review"
    assert repository.approved_evidence(COURSE) == []


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
