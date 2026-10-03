from __future__ import annotations

from contextlib import contextmanager
from threading import Lock, RLock

from app.diagnostics.schema import Diagnosis, ExplanationCheck, HintEvent, ReviewQueueEvent


class InMemoryDiagnosticRepository:
    """Task-private reference store; the Gate can later add SQL persistence."""

    def __init__(self) -> None:
        self._diagnoses_by_id: dict[str, Diagnosis] = {}
        self._diagnoses_by_submission: dict[str, Diagnosis] = {}
        self._review_events: dict[tuple[str, str], ReviewQueueEvent] = {}
        self._hint_events: dict[str, list[HintEvent]] = {}
        self._attempts: dict[str, set[str]] = {}
        self._explanations: list[ExplanationCheck] = []
        self._run_results: dict[tuple[str, str], object] = {}
        self._lock = Lock()
        self._diagnosis_locks: dict[str, RLock] = {}
        self._hint_locks: dict[str, RLock] = {}

    @contextmanager
    def diagnosis_claim(self, submission_id: str):
        with self._lock:
            claim = self._diagnosis_locks.setdefault(submission_id, RLock())
        with claim:
            yield

    @contextmanager
    def hint_claim(self, diagnosis_id: str):
        with self._lock:
            claim = self._hint_locks.setdefault(diagnosis_id, RLock())
        with claim:
            yield

    def save_diagnosis(self, diagnosis: Diagnosis) -> Diagnosis:
        with self._lock:
            existing = self._diagnoses_by_submission.get(diagnosis.submission_id)
            if existing is not None:
                return existing
            self._diagnoses_by_id[diagnosis.diagnosis_id] = diagnosis
            self._diagnoses_by_submission[diagnosis.submission_id] = diagnosis
            return diagnosis

    def get(self, diagnosis_id: str) -> Diagnosis | None:
        return self._diagnoses_by_id.get(diagnosis_id)

    def get_for_submission(self, submission_id: str) -> Diagnosis | None:
        return self._diagnoses_by_submission.get(submission_id)

    def diagnoses(self) -> tuple[Diagnosis, ...]:
        return tuple(self._diagnoses_by_id.values())

    def add_review_event(self, event: ReviewQueueEvent) -> ReviewQueueEvent:
        key = (event.submission_id, event.request_id)
        with self._lock:
            return self._review_events.setdefault(key, event)

    def review_events(self) -> tuple[ReviewQueueEvent, ...]:
        return tuple(self._review_events.values())

    def get_run_result(self, submission_id: str, request_id: str):
        return self._run_results.get((submission_id, request_id))

    def save_run_result(self, submission_id: str, request_id: str, result) -> None:
        self._run_results.setdefault((submission_id, request_id), result)

    def add_hint_event(self, event: HintEvent) -> HintEvent:
        with self._lock:
            events = self._hint_events.setdefault(event.diagnosis_id, [])
            if any(item.request_id == event.request_id for item in events):
                return next(item for item in events if item.request_id == event.request_id)
            events.append(event)
            return event

    def hint_events(self, diagnosis_id: str) -> tuple[HintEvent, ...]:
        return tuple(self._hint_events.get(diagnosis_id, ()))

    def record_attempt(self, diagnosis_id: str, attempt_key: str | None = None) -> int:
        with self._lock:
            attempts = self._attempts.setdefault(diagnosis_id, set())
            attempts.add(attempt_key or f"manual:{len(attempts) + 1}")
            return len(attempts)

    def attempt_count(self, diagnosis_id: str) -> int:
        return len(self._attempts.get(diagnosis_id, ()))

    def get_explanation(
        self, diagnosis_id: str, request_id: str
    ) -> ExplanationCheck | None:
        return next(
            (
                item
                for item in self._explanations
                if item.diagnosis_id == diagnosis_id and item.request_id == request_id
            ),
            None,
        )

    def add_explanation(self, result: ExplanationCheck) -> ExplanationCheck:
        with self._lock:
            existing = next(
                (
                    item
                    for item in self._explanations
                    if item.diagnosis_id == result.diagnosis_id
                    and item.request_id == result.request_id
                ),
                None,
            )
            if existing is not None:
                return existing
            self._explanations.append(result)
            return result

    def explanation_checks(self) -> tuple[ExplanationCheck, ...]:
        return tuple(self._explanations)
