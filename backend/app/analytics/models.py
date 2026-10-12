from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AnalyticsDiagnosisFact:
    diagnosis_id: str
    course_id: str
    subject_key: str
    submission_id: str
    exercise_id: str | None
    category: str
    concept_ids: tuple[str, ...]
    diagnosed_at: datetime
    independent_repaired: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnosed_at", _utc(self.diagnosed_at))


@dataclass(frozen=True, slots=True)
class TeacherReviewCandidate:
    queue_event_id: str
    diagnosis_id: str
    course_id: str
    submission_id: str
    exercise_id: str
    category: str
    concept_ids: tuple[str, ...]
    root_cause: str
    evidence_summaries: tuple[str, ...]
    confidence: float
    review_reason: str
    queued_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "queued_at", _utc(self.queued_at))
