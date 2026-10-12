from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _response_schema(schema):
    schema["required"] = list(schema["properties"])
    for field in schema["properties"].values():
        field.pop("default", None)


class TeacherAnalyticsFilters(_StrictModel):
    model_config = ConfigDict(json_schema_extra=_response_schema)
    concept_id: str | None = None
    exercise_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None

    def normalized(self) -> "TeacherAnalyticsFilters":
        values = {}
        for name in ("start_at", "end_at"):
            value = getattr(self, name)
            if value is not None:
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware")
                values[name] = value.astimezone(UTC)
        return self.model_copy(update=values)


AnalyticsFilters = TeacherAnalyticsFilters


class TeacherAnalyticsGroup(_StrictModel):
    concept_id: str
    exercise_id: str | None
    category: str
    sample_size: int = Field(ge=5)
    diagnosis_count: int = Field(ge=0)
    independent_repair_count: int = Field(ge=0)


class TeacherAnalyticsAvailable(_StrictModel):
    model_config = ConfigDict(json_schema_extra=_response_schema)
    status: Literal["available"] = "available"
    course_id: str
    filters: AnalyticsFilters
    minimum_sample_size: Literal[5] = 5
    sample_size: int = Field(ge=5)
    groups: tuple[TeacherAnalyticsGroup, ...]


class TeacherAnalyticsSuppressed(_StrictModel):
    model_config = ConfigDict(json_schema_extra=_response_schema)
    status: Literal["insufficient_sample"] = "insufficient_sample"
    course_id: str
    filters: AnalyticsFilters
    minimum_sample_size: Literal[5] = 5


class TeacherReviewQueueItem(_StrictModel):
    queue_event_id: str
    diagnosis_id: str
    submission_id: str
    exercise_id: str
    category: str
    concept_ids: tuple[str, ...]
    root_cause: str
    evidence_summaries: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    review_reason: str
    queued_at: datetime


class TeacherReviewQueue(_StrictModel):
    course_id: str
    filters: AnalyticsFilters
    items: tuple[TeacherReviewQueueItem, ...]


class TeacherDiagnosisReviewRequest(_StrictModel):
    decision: Literal["confirmed", "overturned", "insufficient_evidence"] = Field(json_schema_extra={"writeOnly": True})
    reason: str = Field(min_length=1, max_length=2000, json_schema_extra={"writeOnly": True})

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class TeacherDiagnosisReview(_StrictModel):
    diagnosis_id: str = Field(json_schema_extra={"readOnly": True})
    course_id: str = Field(json_schema_extra={"readOnly": True})
    reviewer_user_id: str = Field(json_schema_extra={"readOnly": True})
    decision: Literal["confirmed", "overturned", "insufficient_evidence"]
    reason: str = Field(min_length=1, max_length=2000)
    reviewed_at: datetime = Field(json_schema_extra={"readOnly": True})
