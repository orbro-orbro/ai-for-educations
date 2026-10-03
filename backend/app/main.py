from __future__ import annotations

import os

from fastapi import FastAPI

from app.api.auth import Authenticator, TokenCodec, create_auth_router
from app.api.courses import create_courses_router
from app.api.errors import install_error_handling
from app.api.knowledge import router as knowledge_router
from app.api.submissions import create_submissions_router
from app.auth.models import UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import CourseRepository, EnrollmentRepository
from app.courses.service import CourseService
from app.knowledge.repository import InMemoryKnowledgeRepository, KnowledgeRepository
from app.submissions.repository import (
    InMemorySubmissionRepository,
    SubmissionRepository,
)
from app.submissions.runner_client import RunnerClient
from app.submissions.service import CourseSubmissionAccess, SubmissionService

_DEVELOPMENT_TOKEN_SECRET = "development-only-token-secret"


def _runner_client_from_config() -> RunnerClient:
    endpoint = os.environ.get("RUNNER_ENDPOINT", "http://runner-controller:8080")
    timeout_seconds = float(os.environ.get("RUNNER_TIMEOUT_SECONDS", "5"))
    return RunnerClient(endpoint, timeout_seconds=timeout_seconds)


def _submission_service(
    *,
    repository: SubmissionRepository,
    courses: CourseService,
    knowledge: KnowledgeRepository,
) -> SubmissionService:
    return SubmissionService(
        repository=repository,
        access=CourseSubmissionAccess(
            courses, is_published=lambda exercise: exercise.is_published
        ),
        runner=_runner_client_from_config(),
        knowledge=knowledge,
    )


def _default_dependencies() -> tuple[
    Authenticator,
    CourseService,
    KnowledgeRepository,
    SubmissionRepository,
]:
    environment = os.environ.get("APP_ENV", "development")
    secret = os.environ.get("AUTH_TOKEN_SECRET")
    if not secret:
        if environment not in {"development", "test"}:
            raise RuntimeError("AUTH_TOKEN_SECRET must be set outside development")
        secret = _DEVELOPMENT_TOKEN_SECRET
    if environment not in {"development", "test"} and secret == _DEVELOPMENT_TOKEN_SECRET:
        raise RuntimeError("AUTH_TOKEN_SECRET must not use the development value outside development")

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from app.persistence.repositories import create_sql_repositories

        repositories = create_sql_repositories(database_url)
        users = repositories.users
        courses = repositories.courses
        enrollments = repositories.enrollments
        knowledge = repositories.knowledge
        submissions = repositories.submissions
    else:
        if environment not in {"development", "test"}:
            raise RuntimeError("DATABASE_URL must be set outside development and test")
        users = UserRepository()
        courses = CourseRepository()
        enrollments = EnrollmentRepository()
        knowledge = InMemoryKnowledgeRepository()
        submissions = InMemorySubmissionRepository()
    authenticator = Authenticator(users, TokenCodec(secret))
    course_service = CourseService(users, courses, enrollments, AuthorizationPolicy())
    return authenticator, course_service, knowledge, submissions


def create_app(
    *,
    authenticator: Authenticator | None = None,
    course_service: CourseService | None = None,
    knowledge_repository: KnowledgeRepository | None = None,
    submission_repository: SubmissionRepository | None = None,
    submission_service: SubmissionService | None = None,
) -> FastAPI:
    if (
        authenticator is None
        or course_service is None
        or knowledge_repository is None
        or submission_repository is None
    ):
        defaults = _default_dependencies()
        authenticator = authenticator or defaults[0]
        course_service = course_service or defaults[1]
        knowledge_repository = knowledge_repository or defaults[2]
        submission_repository = submission_repository or defaults[3]
    if submission_service is None:
        submission_service = _submission_service(
            repository=submission_repository,
            courses=course_service,
            knowledge=knowledge_repository,
        )

    application = FastAPI(title="KnowBound-CJ", version="0.2.0")
    application.state.authenticator = authenticator
    application.state.course_service = course_service
    application.state.knowledge_repository = knowledge_repository
    application.state.submission_repository = submission_repository
    application.state.submission_service = submission_service
    install_error_handling(application)
    application.include_router(create_auth_router(authenticator))
    application.include_router(create_courses_router(course_service, authenticator))
    application.include_router(knowledge_router)
    application.include_router(
        create_submissions_router(submission_service, authenticator)
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "knowbound-api"}

    return application


app = create_app()
