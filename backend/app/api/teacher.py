from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request

from app.analytics.repository import AnalyticsPersistenceError
from app.analytics.schemas import (
    AnalyticsFilters,
    TeacherAnalyticsAvailable,
    TeacherAnalyticsSuppressed,
    TeacherDiagnosisReview,
    TeacherDiagnosisReviewRequest,
    TeacherReviewQueue,
)
from app.analytics.service import (
    InvalidAnalyticsFilters,
    InvalidTeacherReview,
    TeacherAnalyticsService,
    TeacherReviewConflict,
)
from app.api.auth import Authenticator
from app.api.errors import ErrorResponse, error_response, request_id_for


BoundedPathId = Annotated[str, Path(min_length=1, max_length=128)]
OptionalStringQuery = Annotated[str | None, Query()]
OptionalTimestampQuery = Annotated[datetime | None, Query()]

_ERROR_RESPONSES = {
    status: {"model": ErrorResponse}
    for status in (401, 404, 409, 422, 503)
}


def _filters(
    concept_id: str | None,
    exercise_id: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> AnalyticsFilters:
    return AnalyticsFilters(
        concept_id=concept_id,
        exercise_id=exercise_id,
        start_at=start_at,
        end_at=end_at,
    )


def create_teacher_router(
    service: TeacherAnalyticsService, authenticator: Authenticator
) -> APIRouter:
    router = APIRouter(tags=["teacher"])

    @router.get(
        "/teacher/courses/{course_id}/analytics",
        response_model=TeacherAnalyticsAvailable | TeacherAnalyticsSuppressed,
        operation_id="getTeacherCourseAnalytics",
        responses=_ERROR_RESPONSES,
    )
    def course_analytics(
        request: Request,
        course_id: BoundedPathId,
        concept_id: OptionalStringQuery = None,
        exercise_id: OptionalStringQuery = None,
        start_at: OptionalTimestampQuery = None,
        end_at: OptionalTimestampQuery = None,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = authenticator.authenticate_header(authorization)
        try:
            return service.course_analytics(
                actor,
                course_id,
                _filters(concept_id, exercise_id, start_at, end_at),
            )
        except InvalidAnalyticsFilters:
            return error_response(
                request, 422, "VALIDATION_ERROR", "Request validation failed."
            )
        except AnalyticsPersistenceError:
            return _storage_error(request)

    @router.get(
        "/teacher/courses/{course_id}/review-queue",
        response_model=TeacherReviewQueue,
        operation_id="listTeacherReviewQueue",
        responses=_ERROR_RESPONSES,
    )
    def review_queue(
        request: Request,
        course_id: BoundedPathId,
        concept_id: OptionalStringQuery = None,
        exercise_id: OptionalStringQuery = None,
        start_at: OptionalTimestampQuery = None,
        end_at: OptionalTimestampQuery = None,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = authenticator.authenticate_header(authorization)
        try:
            return service.review_queue(
                actor,
                course_id,
                _filters(concept_id, exercise_id, start_at, end_at),
            )
        except InvalidAnalyticsFilters:
            return error_response(
                request, 422, "VALIDATION_ERROR", "Request validation failed."
            )
        except AnalyticsPersistenceError:
            return _storage_error(request)

    @router.post(
        "/teacher/diagnoses/{diagnosis_id}/review",
        response_model=TeacherDiagnosisReview,
        operation_id="reviewTeacherDiagnosis",
        responses=_ERROR_RESPONSES,
    )
    def review_diagnosis(
        request: Request,
        diagnosis_id: BoundedPathId,
        payload: TeacherDiagnosisReviewRequest,
        authorization: str | None = Header(default=None, include_in_schema=False),
    ):
        actor = authenticator.authenticate_header(authorization)
        try:
            return service.review_diagnosis(
                actor,
                diagnosis_id,
                decision=payload.decision,
                reason=payload.reason,
                request_id=request_id_for(request),
            )
        except (InvalidAnalyticsFilters, InvalidTeacherReview):
            return error_response(
                request, 422, "VALIDATION_ERROR", "Request validation failed."
            )
        except TeacherReviewConflict as exc:
            return error_response(
                request, 409, exc.public_error_code, exc.public_message
            )
        except AnalyticsPersistenceError:
            return _storage_error(request)

    return router


def _storage_error(request: Request):
    return error_response(
        request,
        503,
        "STORAGE_UNAVAILABLE",
        "Teacher analytics storage is temporarily unavailable.",
    )
