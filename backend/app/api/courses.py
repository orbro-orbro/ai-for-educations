from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.auth import AuthenticationFailed, Authenticator, authentication_error
from app.courses.models import Course, Enrollment, Exercise
from app.courses.service import CourseService, ResourceNotAvailable


class CourseResponse(BaseModel):
    course_id: str
    title: str


class ExerciseResponse(BaseModel):
    exercise_id: str
    course_id: str
    title: str


class CreateCourseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str


class EnrollmentResponse(BaseModel):
    course_id: str
    user_id: str
    role: str


def _course_response(course: Course) -> CourseResponse:
    return CourseResponse(course_id=course.course_id, title=course.title)


def _exercise_response(exercise: Exercise) -> ExerciseResponse:
    return ExerciseResponse(
        exercise_id=exercise.exercise_id,
        course_id=exercise.course_id,
        title=exercise.title,
    )


def _enrollment_response(enrollment: Enrollment) -> EnrollmentResponse:
    return EnrollmentResponse(
        course_id=enrollment.course_id,
        user_id=enrollment.user_id,
        role=enrollment.role.value,
    )


def resource_not_available(request: Request) -> JSONResponse:
    from app.api.errors import error_response

    return error_response(request, 404, "RESOURCE_NOT_AVAILABLE", "Resource is not available.")


def create_courses_router(
    service: CourseService, authenticator: Authenticator
) -> APIRouter:
    router = APIRouter()

    @router.get("/courses", response_model=list[CourseResponse])
    def list_courses(
        request: Request, authorization: str | None = Header(default=None)
    ):
        try:
            actor = authenticator.authenticate_header(authorization)
            return [_course_response(item) for item in service.list_courses(actor)]
        except AuthenticationFailed:
            return authentication_error(request)

    @router.get(
        "/courses/{course_id}/exercises", response_model=list[ExerciseResponse]
    )
    def list_exercises(
        course_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            actor = authenticator.authenticate_header(authorization)
            return [
                _exercise_response(item)
                for item in service.list_exercises(actor, course_id)
            ]
        except AuthenticationFailed:
            return authentication_error(request)
        except ResourceNotAvailable:
            return resource_not_available(request)

    @router.post("/teacher/courses", response_model=CourseResponse, status_code=201)
    def create_course(
        payload: CreateCourseRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            actor = authenticator.authenticate_header(authorization)
            course = service.create_course(actor, str(uuid4()), payload.title)
            return _course_response(course)
        except AuthenticationFailed:
            return authentication_error(request)
        except ResourceNotAvailable:
            return resource_not_available(request)

    @router.post(
        "/courses/{course_id}/enrollments",
        response_model=EnrollmentResponse,
        status_code=201,
    )
    def enroll_current_student(
        course_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            actor = authenticator.authenticate_header(authorization)
            return _enrollment_response(
                service.enroll_current_student(actor, course_id)
            )
        except AuthenticationFailed:
            return authentication_error(request)
        except ResourceNotAvailable:
            return resource_not_available(request)

    return router
