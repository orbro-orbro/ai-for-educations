from __future__ import annotations

from contextlib import contextmanager
from threading import Lock, RLock
from copy import deepcopy
from dataclasses import replace
from typing import ContextManager, Protocol

from app.diagnostics.schema import Diagnosis, ExplanationCheck, HintEvent, ReviewQueueEvent
from app.submissions.models import SubmissionStatus


class DiagnosticPersistenceError(RuntimeError):
    pass


class DiagnosticRepository(Protocol):
    def diagnosis_claim(self, submission_id: str) -> ContextManager[None]: ...
    def hint_claim(self, diagnosis_id: str) -> ContextManager[None]: ...
    def save_diagnosis(self, diagnosis: Diagnosis) -> Diagnosis: ...
    def get(self, diagnosis_id: str) -> Diagnosis | None: ...
    def get_for_submission(self, submission_id: str) -> Diagnosis | None: ...
    def diagnoses(self) -> tuple[Diagnosis, ...]: ...
    def add_review_event(self, event: ReviewQueueEvent) -> ReviewQueueEvent: ...
    def review_events(self) -> tuple[ReviewQueueEvent, ...]: ...
    def get_run_result(self, submission_id: str, request_id: str): ...
    def save_run_result(self, submission_id: str, request_id: str, result) -> None: ...
    def add_hint_event(self, event: HintEvent) -> HintEvent: ...
    def hint_events(self, diagnosis_id: str) -> tuple[HintEvent, ...]: ...
    def record_attempt(self, diagnosis_id: str, attempt_key: str | None = None) -> int: ...
    def attempt_count(self, diagnosis_id: str) -> int: ...
    def attempt_submission_ids(self, diagnosis_id: str) -> tuple[str, ...]: ...
    def get_explanation(self, diagnosis_id: str, request_id: str) -> ExplanationCheck | None: ...
    def add_explanation(self, result: ExplanationCheck) -> ExplanationCheck: ...
    def explanation_checks(self) -> tuple[ExplanationCheck, ...]: ...


class AtomicDiagnosticRepository(DiagnosticRepository, Protocol):
    def finalize_run(
        self,
        *,
        submission_id: str,
        request_id: str,
        result,
        terminal_status: SubmissionStatus,
        reason: str,
    ): ...


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
        self._deleted_context_ids: set[str] = set()
        self._lock = RLock()
        self._diagnosis_locks: dict[str, RLock] = {}
        self._hint_locks: dict[str, RLock] = {}

    @contextmanager
    def private_context_transaction(self):
        keys = ("_diagnoses_by_id", "_diagnoses_by_submission", "_run_results", "_hint_events", "_explanations", "_deleted_context_ids")
        with self._lock:
            snapshot = {key: deepcopy(getattr(self, key)) for key in keys}
            try: yield
            except BaseException:
                for key, value in snapshot.items(): setattr(self, key, value)
                raise

    def erase_private_context(self, owner_user_id: str, course_id: str, diagnosis_ids: frozenset[str]) -> None:
        marker = "[Deleted by student]"
        with self._lock:
            for diagnosis_id in diagnosis_ids:
                original = self.get(diagnosis_id)
                if original is None or original.owner_user_id != owner_user_id or original.course_id != course_id: continue
                self._deleted_context_ids.add(diagnosis_id)
                redacted = original.model_copy(update={"root_cause": marker,
                    "evidence": tuple(e.model_copy(update={"summary": marker}) for e in original.evidence)})
                self._diagnoses_by_id[diagnosis_id] = redacted
                self._diagnoses_by_submission[original.submission_id] = redacted
                for key, result in tuple(self._run_results.items()):
                    cached_diagnosis = getattr(result, "diagnosis", None)
                    if cached_diagnosis is not None and cached_diagnosis.diagnosis_id == diagnosis_id:
                        self._run_results[key] = replace(result, diagnosis=redacted)
                self._hint_events[diagnosis_id] = [h.model_copy(update={"reason": marker, "content": marker}) for h in self._hint_events.get(diagnosis_id, [])]
                self._explanations = [e.model_copy(update={"evidence_summary": marker, "feedback": marker,
                    "memory_proposal_eligible": False}) if e.diagnosis_id == diagnosis_id else e for e in self._explanations]

    def context_deleted(self, diagnosis_id: str) -> bool:
        with self._lock:
            return diagnosis_id in self._deleted_context_ids

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
        with self._lock:
            diagnosis = getattr(result, "diagnosis", None)
            if diagnosis is not None and diagnosis.diagnosis_id in self._deleted_context_ids:
                result = replace(result, diagnosis=self._diagnoses_by_id[diagnosis.diagnosis_id])
            self._run_results.setdefault((submission_id, request_id), result)

    def add_hint_event(self, event: HintEvent) -> HintEvent:
        with self._lock:
            events = self._hint_events.setdefault(event.diagnosis_id, [])
            if any(item.request_id == event.request_id for item in events):
                return next(item for item in events if item.request_id == event.request_id)
            if event.diagnosis_id in self._deleted_context_ids:
                event = event.model_copy(update={"reason": "[Deleted by student]", "content": "[Deleted by student]"})
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

    def attempt_submission_ids(self, diagnosis_id: str) -> tuple[str, ...]:
        with self._lock:
            return tuple(key for key in self._attempts.get(diagnosis_id, ()) if not key.startswith("manual:"))

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
            if result.diagnosis_id in self._deleted_context_ids:
                result = result.model_copy(update={"evidence_summary": "[Deleted by student]",
                    "feedback": "[Deleted by student]", "memory_proposal_eligible": False})
            self._explanations.append(result)
            return result

    def explanation_checks(self) -> tuple[ExplanationCheck, ...]:
        return tuple(self._explanations)
