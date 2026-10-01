import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec, create_auth_router
from app.api.courses import create_courses_router
from app.auth.models import Actor, Role, User, UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, CourseRepository, Enrollment, EnrollmentRepository, Exercise
from app.courses.service import CourseService, ResourceNotAvailable


@pytest.fixture
def course_service() -> CourseService:
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
    return CourseService(users, courses, enrollments, AuthorizationPolicy())


def test_student_lists_only_enrolled_courses(course_service: CourseService) -> None:
    courses = course_service.list_courses(Actor("student-a", Role.STUDENT))

    assert [course.course_id for course in courses] == ["course-a"]


def test_course_member_can_list_only_that_courses_exercises(
    course_service: CourseService,
) -> None:
    exercises = course_service.list_exercises(
        Actor("student-a", Role.STUDENT), "course-a"
    )

    assert [exercise.exercise_id for exercise in exercises] == ["exercise-a"]


def test_non_member_and_unknown_course_return_same_public_error(
    course_service: CourseService,
) -> None:
    actor = Actor("student-a", Role.STUDENT)

    with pytest.raises(ResourceNotAvailable) as forbidden:
        course_service.list_exercises(actor, "course-b")
    with pytest.raises(ResourceNotAvailable) as missing:
        course_service.list_exercises(actor, "course-missing")

    assert forbidden.value.public_error_code == "RESOURCE_NOT_AVAILABLE"
    assert missing.value.public_error_code == "RESOURCE_NOT_AVAILABLE"
    assert str(forbidden.value) == str(missing.value)


def test_server_rejects_actor_role_that_disagrees_with_user_record(
    course_service: CourseService,
) -> None:
    with pytest.raises(ResourceNotAvailable) as error:
        course_service.list_courses(Actor("student-a", Role.TEACHER))

    assert error.value.public_error_code == "RESOURCE_NOT_AVAILABLE"


def test_student_cannot_create_course(course_service: CourseService) -> None:
    with pytest.raises(ResourceNotAvailable):
        course_service.create_course(
            Actor("student-a", Role.STUDENT), "course-new", "New Course"
        )


def test_teacher_creates_course_owned_by_server_verified_identity(
    course_service: CourseService,
) -> None:
    course = course_service.create_course(
        Actor("teacher-a", Role.TEACHER), "course-new", "New Course"
    )

    assert course.owner_teacher_id == "teacher-a"
    assert course_service.list_courses(Actor("teacher-a", Role.TEACHER))[-1] == course


def test_student_enrolls_self_without_client_supplied_user_id(
    course_service: CourseService,
) -> None:
    enrollment = course_service.enroll_current_student(
        Actor("student-a", Role.STUDENT), "course-b"
    )

    assert enrollment.user_id == "student-a"
    assert [
        exercise.exercise_id
        for exercise in course_service.list_exercises(
            Actor("student-a", Role.STUDENT), "course-b"
        )
    ] == ["exercise-b"]


def test_unknown_course_cannot_be_enrolled(course_service: CourseService) -> None:
    with pytest.raises(ResourceNotAvailable) as error:
        course_service.enroll_current_student(
            Actor("student-a", Role.STUDENT), "course-missing"
        )

    assert error.value.public_error_code == "RESOURCE_NOT_AVAILABLE"


def test_teacher_lists_only_owned_or_authorized_courses() -> None:
    users = UserRepository(
        [User.with_password("teacher-a", "teacher-a", "password", Role.TEACHER)]
    )
    courses = CourseRepository(
        [
            Course("owned", "Owned", "teacher-a"),
            Course(
                "authorized",
                "Authorized",
                "teacher-b",
                authorized_teacher_ids=frozenset({"teacher-a"}),
            ),
            Course("unrelated", "Unrelated", "teacher-b"),
        ]
    )
    service = CourseService(
        users, courses, EnrollmentRepository(), AuthorizationPolicy()
    )

    visible = service.list_courses(Actor("teacher-a", Role.TEACHER))

    assert [course.course_id for course in visible] == ["authorized", "owned"]


def build_api() -> FastAPI:
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
    authenticator = Authenticator(
        users, TokenCodec("test-secret-that-is-long-enough")
    )
    service = CourseService(users, courses, enrollments, AuthorizationPolicy())
    app = FastAPI()
    app.include_router(create_auth_router(authenticator))
    app.include_router(create_courses_router(service, authenticator))
    return app


async def api_request(
    app: FastAPI,
    method: str,
    path: str,
    token: str | None = None,
    json: dict[str, str] | None = None,
):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.request(method, path, headers=headers, json=json)


def login_token(app: FastAPI, username: str) -> str:
    response = anyio.run(
        api_request,
        app,
        "POST",
        "/auth/login",
        None,
        {"username": username, "password": "password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_course_routes_use_bearer_identity_for_visibility() -> None:
    app = build_api()
    token = login_token(app, "student-a")

    response = anyio.run(api_request, app, "GET", "/courses", token)

    assert response.status_code == 200
    assert response.json() == [{"course_id": "course-a", "title": "Course A"}]


def test_course_routes_hide_unknown_and_forbidden_ids_the_same_way() -> None:
    app = build_api()
    token = login_token(app, "student-a")

    forbidden = anyio.run(
        api_request,
        app,
        "GET",
        "/courses/course-b/exercises",
        token,
    )
    missing = anyio.run(
        api_request,
        app,
        "GET",
        "/courses/course-missing/exercises",
        token,
    )

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()
    assert forbidden.json()["code"] == "RESOURCE_NOT_AVAILABLE"


def test_enrollment_route_ignores_client_supplied_identity() -> None:
    app = build_api()
    token = login_token(app, "student-a")

    response = anyio.run(
        api_request,
        app,
        "POST",
        "/courses/course-b/enrollments",
        token,
        {"user_id": "student-b", "role": "teacher"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "course_id": "course-b",
        "user_id": "student-a",
        "role": "student",
    }


def test_student_receives_non_enumerating_error_for_teacher_course_route() -> None:
    app = build_api()
    token = login_token(app, "student-a")

    response = anyio.run(
        api_request,
        app,
        "POST",
        "/teacher/courses",
        token,
        {"title": "Not Allowed"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_AVAILABLE"
