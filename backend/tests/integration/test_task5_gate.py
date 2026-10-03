from __future__ import annotations

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.models import Actor, Role, User
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, Enrollment, Exercise
from app.courses.service import CourseService, ResourceNotAvailable
from app.main import create_app
from app.persistence.repositories import create_sql_repositories
from app.submissions.persistence import SqlSubmissionRepository
from app.submissions.service import CourseSubmissionAccess


TASK5_ROUTES = {
    ("/exercises/{exercise_id}/submissions", "POST"),
    ("/submissions/{submission_id}", "GET"),
    ("/submissions/{submission_id}/execution-result", "GET"),
}


def test_composed_application_mounts_all_task5_routes() -> None:
    application = create_app()

    async def request_all():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            return (
                await client.post(
                    "/exercises/exercise-1/submissions",
                    json={
                        "source_files": [{"path": "main.cj", "content": "main() {}"}],
                        "entrypoint": "main.cj",
                    },
                ),
                await client.get("/submissions/submission-1"),
                await client.get("/submissions/submission-1/execution-result"),
            )

    responses = anyio.run(request_all)

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert TASK5_ROUTES <= {
        (path, method.upper())
        for path, item in application.openapi()["paths"].items()
        for method in item
    }


def test_configured_database_uses_registered_sql_submission_repository(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'gate.db').as_posix()}")

    application = create_app()

    assert isinstance(application.state.submission_repository, SqlSubmissionRepository)


def test_production_refuses_to_fall_back_to_memory_without_database_url(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "production-token-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app()


def test_exercise_publication_is_loaded_from_server_storage(tmp_path) -> None:
    repositories = create_sql_repositories(
        f"sqlite:///{(tmp_path / 'publication.db').as_posix()}",
        create_schema=True,
    )
    repositories.users.add(
        User.with_password("teacher-1", "teacher", "pw", Role.TEACHER)
    )
    repositories.users.add(
        User.with_password("student-1", "student", "pw", Role.STUDENT)
    )
    repositories.courses.add(Course("course-1", "Course", "teacher-1"))
    repositories.enrollments.add(Enrollment("course-1", "student-1", Role.STUDENT))
    repositories.courses.add_exercise(
        Exercise("exercise-draft", "course-1", "Draft", is_published=False)
    )
    repositories.courses.add_exercise(
        Exercise("exercise-live", "course-1", "Live", is_published=True)
    )

    service = CourseService(
        repositories.users,
        repositories.courses,
        repositories.enrollments,
        AuthorizationPolicy(),
    )
    access = CourseSubmissionAccess(
        service, is_published=lambda exercise: exercise.is_published
    )
    actor = Actor("student-1", Role.STUDENT)

    assert access.resolve_student_exercise(actor, "exercise-live").is_published is True
    with pytest.raises(ResourceNotAvailable):
        access.resolve_student_exercise(actor, "exercise-draft")


def test_oversized_submission_path_id_matches_contract_validation() -> None:
    application = create_app()

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            return await client.get(f"/submissions/{'x' * 129}")

    response = anyio.run(request)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
