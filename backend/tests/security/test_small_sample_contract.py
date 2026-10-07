"""Contract/vector checks only. Task 8 Router and SQL run at Wave 3 Gate."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import pytest
import yaml

from .analytics_assertions import assert_analytics
from .test_evaluation_datasets import validator

ROOT = Path(__file__).resolve().parents[3]


def vectors():
    path = ROOT / "data/evaluation/analytics_vectors.yaml"
    assert path.exists(), "Analytics vectors must be delivered"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["vectors"]


def test_all_nine_filter_combinations_have_six_attack_scenarios():
    data = vectors()
    assert len(data) == 54 and len({v["vector_id"] for v in data}) == 54
    assert {v["filter_combination"] for v in data} == {"none", "concept", "exercise", "start", "end", "concept-exercise", "concept-time", "exercise-time", "all"}
    for name in {v["filter_combination"] for v in data}:
        assert {v["scenario"] for v in data if v["filter_combination"] == name} == {
            "four-distinct", "five-distinct", "duplicate-student", "foreign-course", "small-group", "suppressed-fields"}


@pytest.mark.parametrize("index", range(54))
def test_vector_expected_payload_satisfies_frozen_contract(index):
    vector = vectors()[index]
    schemas = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))["components"]["schemas"]
    schema_name = "TeacherAnalyticsSuppressed" if vector["expected_response"]["status"] == "insufficient_sample" else "TeacherAnalyticsAvailable"
    # Resolve the only referenced DTOs without introducing a JSON Schema package.
    def resolve(schema):
        if isinstance(schema, dict):
            if "$ref" in schema: return resolve(schemas[schema["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in schema.items()}
        if isinstance(schema, list): return [resolve(s) for s in schema]
        return schema
    validator().check_schema(vector["expected_response"], resolve(schemas[schema_name]))
    assert_analytics(vector, vector["expected_response"])


@pytest.mark.parametrize("field,value", [("sample_size", 4), ("groups", []), ("owner_user_id", "student-a"), ("subject_key", "synthetic-subject-1")])
def test_gate_assertion_rejects_every_sensitive_suppression_field(field, value):
    for vector in vectors():
        if vector["expected_response"]["status"] == "insufficient_sample":
            corrupted = {**vector["expected_response"], field: value}
            with pytest.raises(AssertionError): assert_analytics(vector, corrupted)


def test_gate_assertion_rejects_a_four_student_group_in_available_response():
    vector = next(v for v in vectors() if v["scenario"] == "small-group")
    leaked = deepcopy(vector["expected_response"])
    leaked["groups"].append({**leaked["groups"][0], "sample_size": 4, "concept_id": "cj.pattern-match.other"})
    with pytest.raises(AssertionError): assert_analytics(vector, leaked)


def test_vectors_use_distinct_subjects_without_real_identity_fields():
    validator().check_identity(vectors())
    for vector in vectors():
        if vector["scenario"] in {"four-distinct", "duplicate-student", "foreign-course", "suppressed-fields"}:
            matching = [f for f in vector["facts"] if f["course_id"] == "course-a" and not f.get("excluded_by")]
            assert len({f["subject_key"] for f in matching}) == 4


def test_every_active_filter_has_an_out_of_scope_fifth_subject():
    # Vector-integrity check, not a replacement analytics reducer. Ignoring any
    # one supplied filter must have a fact that changes four into five subjects.
    for vector in vectors():
        if vector["scenario"] != "four-distinct": continue
        filters = vector["expected_response"]["filters"]
        for key, value in filters.items():
            if value is None: continue
            candidates = [f for f in vector["facts"] if f.get("excluded_by") == key]
            assert candidates, f"{vector['vector_id']} lacks a counterexample for {key}"
            assert all(f["course_id"] == "course-a" and f["subject_key"] == "synthetic-filter-outsider" for f in candidates)
            for fact in candidates:
                if key in {"concept_id", "exercise_id"}: assert fact[key] != value
                if key == "start_at": assert datetime.fromisoformat(fact["created_at"]) < datetime.fromisoformat(value)
                if key == "end_at": assert datetime.fromisoformat(fact["created_at"]) > datetime.fromisoformat(value)
