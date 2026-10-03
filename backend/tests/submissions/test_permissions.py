import anyio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec
from app.api.errors import install_error_handling
from app.api.submissions import create_submissions_router
from app.auth.models import Role, User, UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import (
    Course,
    CourseRepository,
    Enrollment,
    EnrollmentRepository,
    Exercise,
)
from app.courses.service import CourseService
from app.submissions.repository import InMemorySubmissionRepository, SubmissionPersistenceError
from app.submissions.service import CourseSubmissionAccess, SubmissionService
from app.submissions.runner_contract import RunnerResult


class UnusedRunner:
    def execute(self, _request):
        raise AssertionError("runner must not be called by a read")


class EmptyKnowledge:
    def approved_evidence(self, course_id, concept_ids=None, misconception_ids=None):
        return []


class SuccessfulRunner:
    def execute(self, request):
        return RunnerResult.model_validate(
            {
                "submission_id": request.submission_id,
                "status": "succeeded",
                "phase": "run",
                "retryable": False,
                "exit_code": 0,
                "signal": None,
                "stdout": "ok",
                "stderr": "",
                "diagnostics": [],
                "command_summary": {
                    "source_count": 1,
                    "entrypoint": "main.cj",
                },
                "limits": {"timeout_ms": 5000},
                "toolchain": {},
            }
        )


def fixture(runner=None, repository=None, *, seed=True, is_published=lambda _exercise: True):
    users = UserRepository(
        [
            User.with_password("student-a", "student-a", "password", Role.STUDENT),
            User.with_password("student-b", "student-b", "password", Role.STUDENT),
            User.with_password("teacher-a", "teacher-a", "password", Role.TEACHER),
            User.with_password("teacher-b", "teacher-b", "password", Role.TEACHER),
        ]
    )
    courses = CourseRepository(
        [
            Course("course-a", "Course A", "teacher-a"),
            Course("course-b", "Course B", "teacher-b"),
        ],
        [
            Exercise("exercise-a", "course-a", "Exercise A"),
            Exercise("exercise-b", "course-b", "Exercise B"),
        ],
    )
    enrollments = EnrollmentRepository(
        [
            Enrollment("course-a", "student-a", Role.STUDENT),
            Enrollment("course-b", "student-b", Role.STUDENT),
        ]
    )
    course_service = CourseService(users, courses, enrollments, AuthorizationPolicy())
    authenticator = Authenticator(users, TokenCodec("permission-test-secret-long"))
    repository = repository or InMemorySubmissionRepository()
    if seed:
        repository.create(
            submission_id="sub-a",
            course_id="course-a",
            exercise_id="exercise-a",
            owner_user_id="student-a",
            source_files=[{"path": "main.cj", "content": "main() {}"}],
            entrypoint="main.cj",
            is_formal=True,
            request_id="req-create",
        )
    service = SubmissionService(
        repository=repository,
        access=CourseSubmissionAccess(course_service, is_published=is_published),
        runner=runner or UnusedRunner(),
        knowledge=EmptyKnowledge(),
        id_factory=lambda: "sub-new",
    )
    app = FastAPI()
    install_error_handling(app)
    app.include_router(create_submissions_router(service, authenticator))
    tokens = {
        username: authenticator.login(username, "password")[0]
        for username in ("student-a", "student-b", "teacher-a", "teacher-b")
    }
    return app, tokens, repository


def get(app, path, token=None, request_id="req-read"):
    async def go():
        headers = {"X-Request-ID": request_id}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path, headers=headers)

    return anyio.run(go)


def post(app, path, token, body, request_id="req-submit"):
    async def go():
        headers = {"X-Request-ID": request_id, "Authorization": f"Bearer {token}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(path, headers=headers, json=body)

    return anyio.run(go)


def test_foreign_student_and_unknown_submission_share_non_enumerating_404():
    app, tokens, _ = fixture()

    foreign = get(app, "/submissions/sub-a", tokens["student-b"])
    missing = get(app, "/submissions/sub-missing", tokens["student-b"])

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {
        "code": "RESOURCE_NOT_AVAILABLE",
        "message": "Resource is not available.",
        "request_id": "req-read",
    }


def test_student_submit_derives_owner_and_course_from_bearer_and_exercise():
    app, tokens, repository = fixture(SuccessfulRunner())

    response = post(
        app,
        "/exercises/exercise-a/submissions",
        tokens["student-a"],
        {
            "source_files": [{"path": "main.cj", "content": "main() {}"}],
            "entrypoint": "main.cj",
            "is_formal": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["submission_id"] == "sub-new"
    assert response.json()["owner_user_id"] == "student-a"
    assert response.json()["course_id"] == "course-a"
    assert response.json()["status"] == "executed"
    assert repository.get("sub-new").owner_user_id == "student-a"

    execution = get(
        app,
        "/submissions/sub-new/execution-result",
        tokens["student-a"],
        request_id="req-execution",
    )
    assert execution.status_code == 200
    assert execution.json()["status"] == "succeeded"
    assert execution.json()["stdout"] == "ok"
    assert execution.json()["rule_matches"] == []
    assert execution.json()["request_id"] == "req-execution"


def test_teacher_reads_only_formal_submission_in_owned_course():
    app, tokens, repository = fixture()
    repository.create(
        submission_id="sub-draft",
        course_id="course-a",
        exercise_id="exercise-a",
        owner_user_id="student-a",
        source_files=[{"path": "main.cj", "content": "draft"}],
        entrypoint="main.cj",
        is_formal=False,
        request_id="req-draft",
    )

    owner = get(app, "/submissions/sub-a", tokens["teacher-a"])
    other_teacher = get(app, "/submissions/sub-a", tokens["teacher-b"])
    draft = get(app, "/submissions/sub-draft", tokens["teacher-a"])

    assert owner.status_code == 200
    assert owner.json()["source_files"][0]["content"] == "main() {}"
    assert other_teacher.status_code == draft.status_code == 404
    assert other_teacher.json()["code"] == draft.json()["code"] == "RESOURCE_NOT_AVAILABLE"


def test_submission_api_rejects_missing_auth_cross_course_and_client_control_fields():
    app, tokens, _ = fixture(SuccessfulRunner())
    body = {
        "source_files": [{"path": "main.cj", "content": "main() {}"}],
        "entrypoint": "main.cj",
        "is_formal": True,
    }

    missing_auth = post(app, "/exercises/exercise-a/submissions", "", body)
    cross_course = post(app, "/exercises/exercise-b/submissions", tokens["student-a"], body)
    controlled = post(
        app,
        "/exercises/exercise-a/submissions",
        tokens["student-a"],
        body
        | {
            "owner_user_id": "student-b",
            "course_id": "course-b",
            "runner_url": "http://attacker",
            "image": "attacker/image",
            "command": ["sh"],
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["request_id"] == "req-submit"
    assert cross_course.status_code == 404
    assert cross_course.json()["code"] == "RESOURCE_NOT_AVAILABLE"
    assert controlled.status_code == 422
    assert controlled.json()["code"] == "VALIDATION_ERROR"


def test_student_cannot_submit_unpublished_exercise():
    app, tokens, repository = fixture(
        SuccessfulRunner(),
        seed=False,
        is_published=lambda _exercise: False,
    )

    response = post(
        app,
        "/exercises/exercise-a/submissions",
        tokens["student-a"],
        {
            "source_files": [{"path": "main.cj", "content": "main() {}"}],
            "entrypoint": "main.cj",
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_AVAILABLE"
    assert repository.get("sub-new") is None


def test_database_write_failure_returns_source_safe_retryable_error():
    class FailingRepository(InMemorySubmissionRepository):
        def create(self, **_kwargs):
            raise SubmissionPersistenceError("database secret and private student source")

    app, tokens, _ = fixture(
        SuccessfulRunner(), FailingRepository(), seed=False
    )

    response = post(
        app,
        "/exercises/exercise-a/submissions",
        tokens["student-a"],
        {
            "source_files": [{"path": "main.cj", "content": "private student source"}],
            "entrypoint": "main.cj",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "PERSISTENCE_UNAVAILABLE",
        "message": "Submission storage is temporarily unavailable.",
        "request_id": "req-submit",
    }
    assert "private student source" not in response.text
    assert "database secret" not in response.text


def test_runner_v2_source_validation_happens_before_submission_persistence():
    app, tokens, repository = fixture(SuccessfulRunner(), seed=False)

    response = post(
        app,
        "/exercises/exercise-a/submissions",
        tokens["student-a"],
        {
            "source_files": [{"path": "payload.txt", "content": "not cangjie"}],
            "entrypoint": "payload.txt",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed.",
        "request_id": "req-submit",
    }
    assert repository.get("sub-new") is None


def test_submission_read_failure_uses_same_safe_persistence_error_shape():
    class FailingReadRepository(InMemorySubmissionRepository):
        def get(self, _submission_id):
            raise SubmissionPersistenceError("postgres://secret private source")

    app, tokens, _ = fixture(repository=FailingReadRepository(), seed=False)

    response = get(app, "/submissions/sub-any", tokens["student-a"])

    assert response.status_code == 503
    assert response.json() == {
        "code": "PERSISTENCE_UNAVAILABLE",
        "message": "Submission storage is temporarily unavailable.",
        "request_id": "req-read",
    }
    assert "secret" not in response.text
