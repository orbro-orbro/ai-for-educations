from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def _document():
    return yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))


def _schemas():
    return _document()["components"]["schemas"]


def test_wave3_paths_are_frozen_but_not_part_of_the_current_runtime():
    document = _document()
    expected = {
        ("/teacher/courses/{course_id}/analytics", "get"): "getTeacherCourseAnalytics",
        ("/teacher/courses/{course_id}/review-queue", "get"): "listTeacherReviewQueue",
        ("/teacher/diagnoses/{diagnosis_id}/review", "post"): "reviewTeacherDiagnosis",
    }
    for (path, method), operation_id in expected.items():
        operation = document["paths"][path][method]
        assert operation["operationId"] == operation_id
        assert operation["x-contract-status"] == "frozen-for-wave-3"
        assert operation["security"] == [{"bearerAuth": []}]
        assert {"401", "404", "409", "422", "503"} <= set(
            operation["responses"]
        )


def test_suppressed_analytics_has_no_exact_count_or_details():
    schema = _schemas()["TeacherAnalyticsSuppressed"]
    assert set(schema["properties"]) == {
        "status",
        "course_id",
        "filters",
        "minimum_sample_size",
    }
    assert schema["properties"]["status"]["const"] == "insufficient_sample"
    assert schema["properties"]["minimum_sample_size"]["const"] == 5
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False


def test_available_analytics_enforces_the_five_student_floor():
    schemas = _schemas()
    available = schemas["TeacherAnalyticsAvailable"]
    group = schemas["TeacherAnalyticsGroup"]
    assert available["properties"]["status"]["const"] == "available"
    assert available["properties"]["minimum_sample_size"]["const"] == 5
    assert available["properties"]["sample_size"]["minimum"] == 5
    assert group["properties"]["sample_size"]["minimum"] == 5
    assert set(group["properties"]) == {
        "concept_id",
        "exercise_id",
        "category",
        "sample_size",
        "diagnosis_count",
        "independent_repair_count",
    }


def test_teacher_dtos_exclude_private_and_identity_fields():
    schemas = _schemas()
    forbidden = {
        "owner_user_id",
        "student_user_id",
        "username",
        "email",
        "source_code",
        "submission",
        "conversation",
        "memory_content",
        "learning_memory",
    }
    for name in ("TeacherAnalyticsGroup", "TeacherReviewQueueItem"):
        assert forbidden.isdisjoint(schemas[name]["properties"])

    assert set(schemas["TeacherReviewQueueItem"]["properties"]) == {
        "queue_event_id",
        "diagnosis_id",
        "submission_id",
        "exercise_id",
        "category",
        "concept_ids",
        "root_cause",
        "evidence_summaries",
        "confidence",
        "review_reason",
        "queued_at",
    }


def test_teacher_review_is_strict_and_cannot_mutate_learning_memory():
    schemas = _schemas()
    request = schemas["TeacherDiagnosisReviewRequest"]
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"decision", "reason"}
    assert request["properties"]["decision"]["enum"] == [
        "confirmed",
        "overturned",
        "insufficient_evidence",
    ]
    assert request["properties"]["reason"]["minLength"] == 1
    assert request["properties"]["reason"]["maxLength"] == 2000
    assert all(value.get("writeOnly") is True for value in request["properties"].values())

    response = schemas["TeacherDiagnosisReview"]
    assert set(response["properties"]) == {
        "diagnosis_id",
        "course_id",
        "reviewer_user_id",
        "decision",
        "reason",
        "reviewed_at",
    }
    assert response["properties"]["reviewer_user_id"]["readOnly"] is True
    description = response["description"].lower()
    assert "learningmemory" in description
    assert "does not create, modify, or activate" in description
