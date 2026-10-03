from __future__ import annotations

from typing import Callable
from uuid import uuid4

from pydantic import ValidationError

from app.auth.models import Actor, Role
from app.courses.models import ProtectedAnswerLookup
from app.courses.service import ResourceNotAvailable
from app.diagnostics.leakage import contains_answer_leakage, safe_fallback
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.diagnostics.schema import HintEvent
from app.model_gateway.base import (
    HintModelOutput,
    HintRequest,
    ModelProvider,
    ProviderFailure,
    ProviderTimeout,
)
from app.submissions.models import utc_now


class HintLevelExhausted(RuntimeError):
    pass


class HintLadderService:
    def __init__(
        self,
        *,
        repository: InMemoryDiagnosticRepository,
        knowledge,
        provider: ModelProvider,
        submissions,
        access,
        max_regenerations: int = 1,
        min_attempts_for_level_four: int = 2,
        protected_answer_lookup: ProtectedAnswerLookup | None = None,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._repository = repository
        self._knowledge = knowledge
        self._provider = provider
        self._submissions = submissions
        self._access = access
        self._max_regenerations = max_regenerations
        self._min_attempts_for_level_four = min_attempts_for_level_four
        self._protected_answer_lookup = protected_answer_lookup
        self._id_factory = id_factory

    def next_hint(
        self,
        actor: Actor,
        diagnosis_id: str,
        *,
        reason: str,
        request_id: str,
    ) -> HintEvent:
        with self._repository.hint_claim(diagnosis_id):
            return self._next_hint_locked(
                actor,
                diagnosis_id,
                reason=reason,
                request_id=request_id,
            )

    def _next_hint_locked(
        self,
        actor: Actor,
        diagnosis_id: str,
        *,
        reason: str,
        request_id: str,
    ) -> HintEvent:
        diagnosis = self._repository.get(diagnosis_id)
        submission = (
            self._submissions.get(diagnosis.submission_id) if diagnosis is not None else None
        )
        if (
            diagnosis is None
            or submission is None
            or actor.role is not Role.STUDENT
            or actor.user_id != submission.owner_user_id
            or diagnosis.owner_user_id != submission.owner_user_id
            or diagnosis.course_id != submission.course_id
        ):
            raise ResourceNotAvailable()
        self._access.require_read(actor, submission)
        if diagnosis.requires_teacher_review:
            raise HintLevelExhausted("diagnosis requires review before hints")
        previous_events = self._repository.hint_events(diagnosis_id)
        if any(item.request_id == request_id for item in previous_events):
            return next(item for item in previous_events if item.request_id == request_id)
        previous_level = previous_events[-1].current_level if previous_events else 0
        if previous_level >= 4:
            raise HintLevelExhausted("maximum hint level already reached")
        level = previous_level + 1
        attempts = self._repository.attempt_count(diagnosis_id)
        if level == 4 and attempts < self._min_attempts_for_level_four:
            raise HintLevelExhausted("more student attempts are required for level four")

        approved = tuple(
            self._knowledge.approved_evidence(
                diagnosis.course_id, concept_ids=diagnosis.concept_ids
            )
        )
        outline = next(
            (
                item.hint_ladder[level - 1].outline
                for item in approved
                if len(item.hint_ladder) >= level
            ),
            safe_fallback(level),
        )
        protected_answer = (
            self._protected_answer_lookup.for_exercise(
                submission.course_id, submission.exercise_id
            )
            if self._protected_answer_lookup is not None
            else None
        )
        content = safe_fallback(level)
        used_fallback = True
        attempts_to_generate = self._max_regenerations + 1 if level <= 2 else 1
        for generation in range(attempts_to_generate):
            request = HintRequest(
                category=diagnosis.category.value,
                root_cause=diagnosis.root_cause,
                concept_ids=diagnosis.concept_ids,
                level=level,
                previous_attempt_count=attempts,
                approved_outline=outline,
                low_information=generation > 0,
            )
            try:
                raw = self._provider.generate_hint(request)
                output = (
                    raw
                    if isinstance(raw, HintModelOutput)
                    else HintModelOutput.model_validate(raw)
                )
            except (ProviderTimeout, ProviderFailure, ValidationError, ValueError, TypeError):
                continue
            if output.level != level or not output.content.strip():
                continue
            if contains_answer_leakage(
                output.content,
                level=level,
                protected_answers=(protected_answer,) if protected_answer else (),
            ):
                continue
            content = output.content
            used_fallback = False
            break
        event = HintEvent(
            hint_event_id=self._id_factory(),
            diagnosis_id=diagnosis_id,
            previous_level=previous_level,
            current_level=level,
            reason=reason,
            previous_attempt_count=attempts,
            content=content,
            used_safe_fallback=used_fallback,
            created_at=utc_now(),
            request_id=request_id,
        )
        return self._repository.add_hint_event(event)

    def record_submission_attempt(
        self, actor: Actor, diagnosis_id: str, submission_id: str
    ) -> int:
        diagnosis = self._repository.get(diagnosis_id)
        original = (
            self._submissions.get(diagnosis.submission_id) if diagnosis is not None else None
        )
        retry = self._submissions.get(submission_id)
        if (
            diagnosis is None
            or original is None
            or retry is None
            or submission_id == diagnosis.submission_id
            or actor.role is not Role.STUDENT
            or diagnosis.owner_user_id != original.owner_user_id
            or diagnosis.course_id != original.course_id
            or retry.owner_user_id != original.owner_user_id
            or retry.course_id != original.course_id
            or retry.exercise_id != original.exercise_id
            or self._submissions.execution_result(submission_id) is None
        ):
            raise ResourceNotAvailable()
        self._access.require_read(actor, original)
        self._access.require_read(actor, retry)
        return self._repository.record_attempt(diagnosis_id, submission_id)
