from __future__ import annotations

import os

from fastapi import FastAPI

from app.api.auth import Authenticator, TokenCodec, create_auth_router
from app.api.courses import create_courses_router
from app.api.diagnostics import create_diagnostics_router
from app.api.errors import install_error_handling
from app.api.knowledge import router as knowledge_router
from app.api.submissions import create_submissions_router
from app.auth.models import UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import CourseRepository, EnrollmentRepository, ProtectedAnswerLookup
from app.courses.service import CourseService
from app.diagnostics.hints import HintLadderService
from app.diagnostics.repository import DiagnosticRepository, InMemoryDiagnosticRepository
from app.diagnostics.service import DiagnosisService
from app.knowledge.repository import InMemoryKnowledgeRepository, KnowledgeRepository
from app.model_gateway.base import ModelProvider
from app.model_gateway.config import model_provider_from_config
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
    diagnosis_service: DiagnosisService,
) -> SubmissionService:
    return SubmissionService(
        repository=repository,
        access=CourseSubmissionAccess(
            courses, is_published=lambda exercise: exercise.is_published
        ),
        runner=_runner_client_from_config(),
        knowledge=knowledge,
        execution_completed=lambda submission_id, request_id: diagnosis_service.diagnose(
            submission_id, request_id=request_id
        ),
    )


def _default_dependencies() -> tuple[
    Authenticator,
    CourseService,
    KnowledgeRepository,
    SubmissionRepository,
    DiagnosticRepository,
    ProtectedAnswerLookup,
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
        diagnostics = repositories.diagnostics
        protected_answers = repositories.courses
    else:
        if environment not in {"development", "test"}:
            raise RuntimeError("DATABASE_URL must be set outside development and test")
        users = UserRepository()
        courses = CourseRepository()
        enrollments = EnrollmentRepository()
        knowledge = InMemoryKnowledgeRepository()
        submissions = InMemorySubmissionRepository()
        diagnostics = InMemoryDiagnosticRepository()
        protected_answers = courses
    authenticator = Authenticator(users, TokenCodec(secret))
    course_service = CourseService(users, courses, enrollments, AuthorizationPolicy())
    return (
        authenticator,
        course_service,
        knowledge,
        submissions,
        diagnostics,
        protected_answers,
    )


def create_app(
    *,
    authenticator: Authenticator | None = None,
    course_service: CourseService | None = None,
    knowledge_repository: KnowledgeRepository | None = None,
    submission_repository: SubmissionRepository | None = None,
    diagnostic_repository: DiagnosticRepository | None = None,
    protected_answer_lookup: ProtectedAnswerLookup | None = None,
    model_provider: ModelProvider | None = None,
    diagnosis_service: DiagnosisService | None = None,
    hint_service: HintLadderService | None = None,
    submission_service: SubmissionService | None = None,
) -> FastAPI:
    if (
        authenticator is None
        or course_service is None
        or knowledge_repository is None
        or submission_repository is None
        or diagnostic_repository is None
        or protected_answer_lookup is None
    ):
        defaults = _default_dependencies()
        authenticator = authenticator or defaults[0]
        course_service = course_service or defaults[1]
        knowledge_repository = knowledge_repository or defaults[2]
        submission_repository = submission_repository or defaults[3]
        diagnostic_repository = diagnostic_repository or defaults[4]
        protected_answer_lookup = protected_answer_lookup or defaults[5]
    provider = model_provider or model_provider_from_config()
    access = CourseSubmissionAccess(
        course_service, is_published=lambda exercise: exercise.is_published
    )
    try:
        confidence_threshold = float(os.environ.get("DIAGNOSIS_CONFIDENCE_THRESHOLD", "0.75"))
    except ValueError as exc:
        raise RuntimeError("DIAGNOSIS_CONFIDENCE_THRESHOLD must be in [0,1]") from exc
    if diagnosis_service is None:
        diagnosis_service = DiagnosisService(
            submissions=submission_repository,
            knowledge=knowledge_repository,
            repository=diagnostic_repository,
            provider=provider,
            access=access,
            confidence_threshold=confidence_threshold,
        )
    if hint_service is None:
        hint_service = HintLadderService(
            repository=diagnostic_repository,
            knowledge=knowledge_repository,
            provider=provider,
            submissions=submission_repository,
            access=access,
            protected_answer_lookup=protected_answer_lookup,
        )
    if submission_service is None:
        submission_service = _submission_service(
            repository=submission_repository,
            courses=course_service,
            knowledge=knowledge_repository,
            diagnosis_service=diagnosis_service,
        )

    application = FastAPI(title="KnowBound-CJ", version="0.2.0")
    application.state.authenticator = authenticator
    application.state.course_service = course_service
    application.state.knowledge_repository = knowledge_repository
    application.state.submission_repository = submission_repository
    application.state.submission_service = submission_service
    application.state.diagnostic_repository = diagnostic_repository
    application.state.diagnosis_service = diagnosis_service
    application.state.hint_service = hint_service
    install_error_handling(application)
    application.include_router(create_auth_router(authenticator))
    application.include_router(create_courses_router(course_service, authenticator))
    application.include_router(knowledge_router)
    application.include_router(
        create_submissions_router(submission_service, authenticator)
    )
    application.include_router(
        create_diagnostics_router(diagnosis_service, hint_service, authenticator)
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "knowbound-api"}

    return application


app = create_app()
