from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import ContextManager, Iterable, Protocol

from app.analytics.models import AnalyticsDiagnosisFact, TeacherReviewCandidate
from app.analytics.schemas import TeacherDiagnosisReview


class AnalyticsPersistenceError(RuntimeError):
    pass


class TeacherAnalyticsRepository(Protocol):
    def list_facts(self, course_id: str) -> tuple[AnalyticsDiagnosisFact, ...]: ...
    def list_candidates(self, course_id: str) -> tuple[TeacherReviewCandidate, ...]: ...
    def get_candidate(self, diagnosis_id: str) -> TeacherReviewCandidate | None: ...
    def get_review(self, diagnosis_id: str) -> TeacherDiagnosisReview | None: ...
    def save_review(self, review: TeacherDiagnosisReview) -> TeacherDiagnosisReview: ...
    def transaction(self) -> ContextManager[None]: ...
    def review_claim(self, diagnosis_id: str) -> ContextManager[None]: ...


class InMemoryTeacherAnalyticsRepository:
    def __init__(
        self,
        facts: Iterable[AnalyticsDiagnosisFact] = (),
        candidates: Iterable[TeacherReviewCandidate] = (),
    ) -> None:
        self._facts = list(facts)
        self._candidates = {item.queue_event_id: item for item in candidates}
        self._reviews: dict[str, TeacherDiagnosisReview] = {}
        self._fail_save = False
        self._fail_read = False
        self._lock = RLock()
        self._claims: dict[str, RLock] = {}

    def add_fact(self, fact: AnalyticsDiagnosisFact) -> None:
        with self._lock:
            self._facts.append(fact)

    def add_facts(self, facts: Iterable[AnalyticsDiagnosisFact]) -> None:
        with self._lock:
            self._facts.extend(facts)

    def add_candidate(self, candidate: TeacherReviewCandidate) -> None:
        with self._lock:
            self._candidates[candidate.queue_event_id] = candidate

    def add_candidates(self, candidates: Iterable[TeacherReviewCandidate]) -> None:
        for candidate in candidates:
            self.add_candidate(candidate)

    def fail_next_save(self) -> None:
        self._fail_save = True

    def fail_next_read(self) -> None:
        self._fail_read = True

    def _check_read(self) -> None:
        if self._fail_read:
            self._fail_read = False
            raise AnalyticsPersistenceError("analytics read failed")

    def list_facts(self, course_id: str) -> tuple[AnalyticsDiagnosisFact, ...]:
        with self._lock:
            self._check_read()
            return tuple(item for item in self._facts if item.course_id == course_id)

    def list_candidates(self, course_id: str) -> tuple[TeacherReviewCandidate, ...]:
        with self._lock:
            self._check_read()
            return tuple(
                item for item in self._candidates.values() if item.course_id == course_id
            )

    def get_candidate(self, diagnosis_id: str) -> TeacherReviewCandidate | None:
        with self._lock:
            self._check_read()
            return next(
                (
                    item
                    for item in self._candidates.values()
                    if item.diagnosis_id == diagnosis_id
                ),
                None,
            )

    def get_review(self, diagnosis_id: str) -> TeacherDiagnosisReview | None:
        with self._lock:
            self._check_read()
            return self._reviews.get(diagnosis_id)

    def save_review(self, review: TeacherDiagnosisReview) -> TeacherDiagnosisReview:
        with self._lock:
            if self._fail_save:
                self._fail_save = False
                raise AnalyticsPersistenceError("analytics review write failed")
            existing = self._reviews.get(review.diagnosis_id)
            if existing is not None:
                return existing
            self._reviews[review.diagnosis_id] = review
            return review

    @contextmanager
    def transaction(self):
        with self._lock:
            original = dict(self._reviews)
            try:
                yield
            except BaseException:
                self._reviews = original
                raise

    @contextmanager
    def review_claim(self, diagnosis_id: str):
        with self._lock:
            claim = self._claims.setdefault(diagnosis_id, RLock())
        with claim:
            yield
