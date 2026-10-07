"""Reusable Wave 3 Gate assertions; this module contains no analytics reducer."""


def assert_analytics(vector, payload):
    expected = vector["expected_response"]
    assert payload == expected, "Runtime analytics differs from the hand-specified privacy vector"
    if payload["status"] == "insufficient_sample":
        assert set(payload) == {"status", "course_id", "filters", "minimum_sample_size"}
    else:
        assert payload["sample_size"] >= 5
        assert all(g["sample_size"] >= 5 for g in payload["groups"])
        assert all(set(g) == {"concept_id", "exercise_id", "category", "sample_size", "diagnosis_count", "independent_repair_count"} for g in payload["groups"])
