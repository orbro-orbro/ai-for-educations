from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from app.analytics.models import AnalyticsDiagnosisFact, TeacherReviewCandidate
from app.analytics.repository import AnalyticsPersistenceError, TeacherAnalyticsRepository
from app.analytics.schemas import (
    AnalyticsFilters,
    TeacherAnalyticsAvailable,
    TeacherAnalyticsGroup,
    TeacherAnalyticsSuppressed,
    TeacherDiagnosisReview,
    TeacherReviewQueue,
    TeacherReviewQueueItem,
)
from app.audit.service import AuditLog
from app.auth.models import Actor
from app.courses.service import CourseService, ResourceNotAvailable


MINIMUM_SAMPLE_SIZE = 5


class InvalidAnalyticsFilters(ValueError):
    pass


class TeacherReviewConflict(RuntimeError):
    public_error_code = "DIAGNOSIS_REVIEW_CONFLICT"
    public_message = "The diagnosis already has a different authoritative review."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class InvalidTeacherReview(ValueError):
    pass


@dataclass(slots=True)
class _GroupAccumulator:
    subject_keys: set[str] = field(default_factory=set)
    diagnosis_ids: set[str] = field(default_factory=set)
    independent_repair_ids: set[str] = field(default_factory=set)


class TeacherAnalyticsService:
    def __init__(
        self,
        *,
        courses: CourseService,
        repository: TeacherAnalyticsRepository,
        audit: AuditLog,
        clock: Callable[[], datetime],
    ) -> None:
        self._courses = courses
        self._repository = repository
        self._audit = audit
        self._clock = clock

    def course_analytics(
        self, actor: Actor, course_id: str, filters: AnalyticsFilters
    ) -> TeacherAnalyticsAvailable | TeacherAnalyticsSuppressed:
        filters = _validated_filters(filters)
        self._courses.require_teacher_access(actor, course_id)
        facts = tuple(
            item
            for item in self._repository.list_facts(course_id)
            if _fact_matches(item, filters)
        )
        subject_keys = {item.subject_key for item in facts}
        if len(subject_keys) < MINIMUM_SAMPLE_SIZE:
            return TeacherAnalyticsSuppressed(course_id=course_id, filters=filters)

        grouped: dict[tuple[str, str | None, str], _GroupAccumulator] = {}
        for item in facts:
            for concept_id in set(item.concept_ids):
                key = (concept_id, item.exercise_id, item.category)
                accumulator = grouped.setdefault(key, _GroupAccumulator())
                accumulator.subject_keys.add(item.subject_key)
                accumulator.diagnosis_ids.add(item.diagnosis_id)
                if item.independent_repaired:
                    accumulator.independent_repair_ids.add(item.diagnosis_id)

        groups = tuple(
            TeacherAnalyticsGroup(
                concept_id=concept_id,
                exercise_id=exercise_id,
                category=category,
                sample_size=len(accumulator.subject_keys),
                diagnosis_count=len(accumulator.diagnosis_ids),
                independent_repair_count=len(accumulator.independent_repair_ids),
            )
            for (concept_id, exercise_id, category), accumulator in sorted(
                grouped.items(), key=lambda item: (item[0][0], item[0][1] or "", item[0][2])
            )
            if len(accumulator.subject_keys) >= MINIMUM_SAMPLE_SIZE
        )
        return TeacherAnalyticsAvailable(
            course_id=course_id,
            filters=filters,
            sample_size=len(subject_keys),
            groups=groups,
        )

    def review_queue(
        self, actor: Actor, course_id: str, filters: AnalyticsFilters
    ) -> TeacherReviewQueue:
        filters = _validated_filters(filters)
        self._courses.require_teacher_access(actor, course_id)
        candidates = []
        for item in self._repository.list_candidates(course_id):
            if not _candidate_matches(item, filters):
                continue
            if self._repository.get_review(item.diagnosis_id) is not None:
                continue
            candidates.append(item)
        candidates.sort(key=lambda item: (item.queued_at, item.queue_event_id))
        return TeacherReviewQueue(
            course_id=course_id,
            filters=filters,
            items=tuple(_queue_item(item) for item in candidates),
        )

    def review_diagnosis(
        self,
        actor: Actor,
        diagnosis_id: str,
        *,
        decision: str,
        reason: str,
        request_id: str,
    ) -> TeacherDiagnosisReview:
        reason = reason.strip()
        if decision not in {"confirmed", "overturned", "insufficient_evidence"}:
            raise InvalidTeacherReview("unsupported review decision")
        if not reason or len(reason) > 2000:
            raise InvalidTeacherReview("review reason is invalid")

        candidate = self._repository.get_candidate(diagnosis_id)
        if candidate is None:
            raise ResourceNotAvailable()
        self._courses.require_teacher_access(actor, candidate.course_id)

        with self._repository.review_claim(diagnosis_id):
            candidate = self._repository.get_candidate(diagnosis_id)
            if candidate is None:
                raise ResourceNotAvailable()
            self._courses.require_teacher_access(actor, candidate.course_id)
            existing = self._repository.get_review(diagnosis_id)
            if existing is not None:
                if existing.decision == decision and existing.reason == reason:
                    return existing
                raise TeacherReviewConflict()

            review = TeacherDiagnosisReview(
                diagnosis_id=diagnosis_id,
                course_id=candidate.course_id,
                reviewer_user_id=actor.user_id,
                decision=decision,
                reason=reason,
                reviewed_at=_utc(self._clock()),
            )
            try:
                with ExitStack() as stack:
                    stack.enter_context(self._repository.transaction())
                    stack.enter_context(self._audit.transaction())
                    saved = self._repository.save_review(review)
                    self._audit.record(
                        event_type="teacher_diagnosis_review",
                        actor=actor,
                        target_type="diagnosis",
                        target_id=diagnosis_id,
                        owner_user_id="",
                        course_id=candidate.course_id,
                        outcome="success",
                        reason_code=f"teacher_review_{decision}",
                        request_id=request_id,
                    )
                return saved
            except AnalyticsPersistenceError:
                raise
            except RuntimeError as exc:
                raise AnalyticsPersistenceError(
                    "teacher review could not be persisted safely"
                ) from exc


def _validated_filters(filters: AnalyticsFilters) -> AnalyticsFilters:
    try:
        normalized = filters.normalized()
    except ValueError as exc:
        raise InvalidAnalyticsFilters("timestamps must include a UTC offset") from exc
    if (
        normalized.start_at is not None
        and normalized.end_at is not None
        and normalized.start_at >= normalized.end_at
    ):
        raise InvalidAnalyticsFilters("start_at must precede end_at")
    return normalized


def _time_matches(value: datetime, filters: AnalyticsFilters) -> bool:
    value = _utc(value)
    return not (
        (filters.start_at is not None and value < filters.start_at)
        or (filters.end_at is not None and value >= filters.end_at)
    )


def _fact_matches(item: AnalyticsDiagnosisFact, filters: AnalyticsFilters) -> bool:
    return (
        (filters.concept_id is None or filters.concept_id in item.concept_ids)
        and (filters.exercise_id is None or filters.exercise_id == item.exercise_id)
        and _time_matches(item.diagnosed_at, filters)
    )


def _candidate_matches(item: TeacherReviewCandidate, filters: AnalyticsFilters) -> bool:
    return (
        (filters.concept_id is None or filters.concept_id in item.concept_ids)
        and (filters.exercise_id is None or filters.exercise_id == item.exercise_id)
        and _time_matches(item.queued_at, filters)
    )


def _queue_item(item: TeacherReviewCandidate) -> TeacherReviewQueueItem:
    return TeacherReviewQueueItem(
        queue_event_id=item.queue_event_id,
        diagnosis_id=item.diagnosis_id,
        submission_id=item.submission_id,
        exercise_id=item.exercise_id,
        category=item.category,
        concept_ids=item.concept_ids,
        root_cause=item.root_cause,
        evidence_summaries=item.evidence_summaries,
        confidence=item.confidence,
        review_reason=item.review_reason,
        queued_at=item.queued_at,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
