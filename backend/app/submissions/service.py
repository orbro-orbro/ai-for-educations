from __future__ import annotations

from typing import Callable, Iterable, Protocol
from uuid import uuid4

from pydantic import ValidationError

from app.auth.models import Actor, Role
from app.courses.models import Exercise
from app.courses.service import CourseService, ResourceNotAvailable
from app.diagnostics.rules import match_rules
from app.knowledge.repository import KnowledgeRepository
from app.submissions.models import ExecutionResult, Submission, SubmissionStatus
from app.submissions.repository import SubmissionRepository
from app.submissions.runner_client import RunnerUnavailable
from app.submissions.runner_contract import RunnerRequest, RunnerStatus, SourceFile


class ExerciseAccess(Protocol):
    def resolve_student_exercise(self, actor: Actor, exercise_id: str): ...
    def require_read(self, actor: Actor, submission: Submission) -> None: ...


class Runner(Protocol):
    def execute(self, request: RunnerRequest): ...


class ExecutionCompleted(Protocol):
    def __call__(self, submission_id: str, request_id: str) -> None: ...


class InvalidSubmissionInput(ValueError):
    pass


class CourseSubmissionAccess:
    def __init__(
        self,
        courses: CourseService,
        *,
        is_published: Callable[[Exercise], bool],
    ) -> None:
        self._courses = courses
        self._is_published = is_published

    def resolve_student_exercise(self, actor: Actor, exercise_id: str):
        if actor.role is not Role.STUDENT:
            raise ResourceNotAvailable()
        for course in self._courses.list_courses(actor):
            for exercise in self._courses.list_exercises(actor, course.course_id):
                if exercise.exercise_id == exercise_id and self._is_published(exercise):
                    return exercise
        raise ResourceNotAvailable()

    def require_read(self, actor: Actor, submission: Submission) -> None:
        self._courses.list_courses(actor)  # verifies the bearer-derived actor
        if actor.role is Role.STUDENT:
            if actor.user_id != submission.owner_user_id:
                raise ResourceNotAvailable()
            return
        if not submission.is_formal:
            raise ResourceNotAvailable()
        self._courses.require_teacher_access(actor, submission.course_id)


class SubmissionService:
    def __init__(
        self,
        *,
        repository: SubmissionRepository,
        access: ExerciseAccess,
        runner: Runner,
        knowledge: KnowledgeRepository,
        execution_completed: ExecutionCompleted | None = None,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._repository = repository
        self._access = access
        self._runner = runner
        self._knowledge = knowledge
        self._execution_completed = execution_completed
        self._id_factory = id_factory

    def get_submission(self, actor: Actor, submission_id: str) -> Submission:
        submission = self._repository.get(submission_id)
        if submission is None:
            raise ResourceNotAvailable()
        self._access.require_read(actor, submission)
        return submission

    def get_execution_result(self, actor: Actor, submission_id: str):
        self.get_submission(actor, submission_id)
        result = self._repository.execution_result(submission_id)
        if result is None:
            raise ExecutionResultNotAvailable()
        return result, self._repository.rule_matches(submission_id)

    def submit(
        self,
        *,
        actor: Actor,
        exercise_id: str,
        source_files: Iterable[SourceFile | dict[str, str]],
        entrypoint: str,
        is_formal: bool,
        request_id: str,
        timeout_ms: int = 5_000,
    ) -> Submission:
        exercise = self._access.resolve_student_exercise(actor, exercise_id)
        submission_id = self._id_factory()
        try:
            runner_request = RunnerRequest(
                submission_id=submission_id,
                source_files=list(source_files),
                entrypoint=entrypoint,
                timeout_ms=timeout_ms,
            )
        except ValidationError as exc:
            raise InvalidSubmissionInput("submission violates Runner v2 input bounds") from exc
        submission = self._repository.create(
            submission_id=submission_id,
            course_id=exercise.course_id,
            exercise_id=exercise.exercise_id,
            owner_user_id=actor.user_id,
            source_files=runner_request.source_files,
            entrypoint=entrypoint,
            is_formal=is_formal,
            request_id=request_id,
        )
        submission = self._repository.transition(
            submission_id,
            SubmissionStatus.executing,
            request_id=request_id,
            reason="runner request started",
        )
        try:
            runner_result = self._runner.execute(runner_request)
        except RunnerUnavailable:
            return self._repository.transition(
                submission_id,
                SubmissionStatus.execution_unavailable,
                request_id=request_id,
                reason="runner infrastructure unavailable",
            )
        if runner_result.status in {
            RunnerStatus.runner_unavailable,
            RunnerStatus.internal_error,
        }:
            return self._repository.transition(
                submission_id,
                SubmissionStatus.execution_unavailable,
                request_id=request_id,
                reason=f"runner reported {runner_result.status.value}",
            )
        execution = ExecutionResult.from_runner(
            course_id=exercise.course_id,
            result=runner_result,
            request_id=request_id,
        )
        matches = match_rules(
            course_id=exercise.course_id,
            diagnostics=execution.diagnostics,
            knowledge=self._knowledge,
        )
        completed = self._repository.complete_execution(
            execution,
            matches,
            request_id=request_id,
            reason=f"runner completed with {runner_result.status.value}",
        )
        if self._execution_completed is None:
            return completed
        self._execution_completed(submission_id, request_id)
        return self._repository.get(submission_id)


class ExecutionResultNotAvailable(LookupError):
    pass
