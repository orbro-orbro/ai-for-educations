from __future__ import annotations

from threading import Lock
from typing import Iterable, Protocol

from app.submissions.runner_contract import SourceFile

from app.submissions.models import (
    ExecutionResult,
    Submission,
    SubmissionStatus,
    SubmissionTransition,
    utc_now,
)


class SubmissionPersistenceError(RuntimeError):
    pass


class SubmissionRepository(Protocol):
    def create(self, **kwargs) -> Submission: ...
    def get(self, submission_id: str) -> Submission | None: ...
    def transition(
        self,
        submission_id: str,
        to_status: SubmissionStatus,
        *,
        request_id: str,
        reason: str,
    ) -> Submission: ...
    def transitions(self, submission_id: str) -> tuple[SubmissionTransition, ...]: ...
    def execution_result(self, submission_id: str) -> ExecutionResult | None: ...
    def rule_matches(self, submission_id: str) -> tuple[object, ...]: ...
    def complete_execution(
        self,
        result: ExecutionResult,
        matches: Iterable[object],
        *,
        request_id: str,
        reason: str,
    ) -> Submission: ...


class InMemorySubmissionRepository:
    """Reference repository; production uses the SQL adapter in persistence.py."""

    def __init__(self) -> None:
        self._submissions: dict[str, Submission] = {}
        self._transitions: dict[str, list[SubmissionTransition]] = {}
        self._execution_results: dict[str, ExecutionResult] = {}
        self._rule_matches: dict[str, tuple[object, ...]] = {}
        self._lock = Lock()

    def create(
        self,
        *,
        submission_id: str,
        course_id: str,
        exercise_id: str,
        owner_user_id: str,
        source_files: Iterable[SourceFile | dict[str, str]],
        entrypoint: str,
        is_formal: bool,
        request_id: str,
    ) -> Submission:
        created_at = utc_now()
        submission = Submission(
            submission_id=submission_id,
            course_id=course_id,
            exercise_id=exercise_id,
            owner_user_id=owner_user_id,
            source_files=tuple(
                item if isinstance(item, SourceFile) else SourceFile.model_validate(item)
                for item in source_files
            ),
            entrypoint=entrypoint,
            is_formal=is_formal,
            status=SubmissionStatus.received,
            created_at=created_at,
            request_id=request_id,
        )
        transition = SubmissionTransition(
            submission_id=submission_id,
            from_status=None,
            to_status=SubmissionStatus.received,
            changed_at=created_at,
            request_id=request_id,
            reason="submission received",
        )
        with self._lock:
            if submission_id in self._submissions:
                raise ValueError("duplicate submission")
            self._submissions[submission_id] = submission
            self._transitions[submission_id] = [transition]
        return submission

    def get(self, submission_id: str) -> Submission | None:
        return self._submissions.get(submission_id)

    def transition(
        self,
        submission_id: str,
        to_status: SubmissionStatus,
        *,
        request_id: str,
        reason: str,
    ) -> Submission:
        with self._lock:
            current = self._submissions[submission_id]
            updated = current.transition_to(to_status)
            changed_at = utc_now()
            self._submissions[submission_id] = updated
            self._transitions[submission_id].append(
                SubmissionTransition(
                    submission_id=submission_id,
                    from_status=current.status,
                    to_status=updated.status,
                    changed_at=changed_at,
                    request_id=request_id,
                    reason=reason,
                )
            )
            return updated

    def transitions(self, submission_id: str) -> tuple[SubmissionTransition, ...]:
        return tuple(self._transitions.get(submission_id, ()))

    def execution_result(self, submission_id: str) -> ExecutionResult | None:
        return self._execution_results.get(submission_id)

    def rule_matches(self, submission_id: str) -> tuple[object, ...]:
        return self._rule_matches.get(submission_id, ())

    def complete_execution(
        self,
        result: ExecutionResult,
        matches: Iterable[object],
        *,
        request_id: str,
        reason: str,
    ) -> Submission:
        match_values = tuple(matches)
        with self._lock:
            current = self._submissions[result.submission_id]
            if current.course_id != result.course_id:
                raise ValueError("execution result course mismatch")
            if any(
                getattr(match, "course_id", None) != current.course_id
                for match in match_values
            ):
                raise ValueError("rule match course mismatch")
            if result.submission_id in self._execution_results:
                raise ValueError("execution result already exists")
            updated = current.transition_to(SubmissionStatus.executed)
            changed_at = utc_now()
            self._execution_results[result.submission_id] = result
            self._rule_matches[result.submission_id] = match_values
            self._submissions[result.submission_id] = updated
            self._transitions[result.submission_id].append(
                SubmissionTransition(
                    submission_id=result.submission_id,
                    from_status=current.status,
                    to_status=updated.status,
                    changed_at=changed_at,
                    request_id=request_id,
                    reason=reason,
                )
            )
            return updated
