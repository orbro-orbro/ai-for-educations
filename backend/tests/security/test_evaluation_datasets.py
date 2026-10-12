from pathlib import Path
import importlib.util
import json
from copy import deepcopy

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/evaluation"
CATEGORIES = {
    "idor", "cross_student", "cross_course", "cross_role", "prompt_injection",
    "memory_leakage", "deletion_recovery", "share_bypass", "sensitive_logging",
    "small_sample", "executor_abuse", "enumeration_idempotency",
}


def validator():
    path = DATA / "evaluate.py"
    assert path.exists(), "Task 10 needs a runnable dataset validator"
    spec = importlib.util.spec_from_file_location("task10_evaluate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dataset(name):
    path = DATA / name
    assert path.exists(), f"Missing planned evaluation artifact: {name}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_planned_datasets_have_unique_nonempty_attacks_and_honest_provenance():
    attacks = dataset("security_cases.yaml")
    diagnosis = dataset("diagnosis_cases.yaml")
    cases = attacks["cases"] + diagnosis["cases"]
    assert len(attacks["cases"]) >= 100
    assert len({c["case_id"] for c in cases}) == len(cases)
    assert {c["input"]["attack_category"] for c in attacks["cases"]} == CATEGORIES
    assert len({json.dumps(c["input"], sort_keys=True) for c in attacks["cases"]}) == len(attacks["cases"])
    assert all(c["annotation_status"] == "draft" and c["source_type"] == "synthetic" and c["teacher_annotators"] == [] for c in cases)
    assert len(diagnosis["cases"]) >= 3
    validator().validate_datasets(DATA)


def test_schema_describes_required_fields_and_verified_annotation_condition():
    path = DATA / "cases.schema.json"
    assert path.exists(), "Missing planned case schema"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert set(schema["required"]) >= {
        "case_id", "case_type", "course_version", "input", "expected_concept_ids",
        "evidence", "teacher_annotators", "annotation_status", "privacy_classification",
        "dataset_split", "source_type", "created_at", "notes",
    }
    assert schema["additionalProperties"] is False
    assert schema["properties"]["dataset_split"]["enum"] == ["train", "dev", "test"]
    assert schema["allOf"], "Verified cases must require real teacher annotation evidence"


@pytest.mark.parametrize("mutation", ["split", "verified", "identifier", "unknown", "empty_action", "timestamp", "duplicate"])
def test_validator_rejects_invalid_and_fabricated_cases(mutation):
    module = validator()
    case = deepcopy(dataset("security_cases.yaml")["cases"][0])
    cases = [case]
    if mutation == "split": case["dataset_split"] = "production"
    elif mutation == "verified": case["annotation_status"] = "verified"
    elif mutation == "identifier": case["input"]["student_email"] = "learner@example.invalid"
    elif mutation == "unknown": case["unexpected"] = True
    elif mutation == "empty_action": case["input"]["operation"] = ""
    elif mutation == "timestamp": case["created_at"] = "yesterday"
    elif mutation == "duplicate": cases.append(deepcopy(case))
    with pytest.raises(ValueError):
        module.validate_cases(cases, json.loads((DATA / "cases.schema.json").read_text(encoding="utf-8")))
