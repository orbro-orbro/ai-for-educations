"""Synthetic observations test the calculator, never a pilot result."""
import hashlib
import importlib.util
from copy import deepcopy
import pytest
from .test_evaluation_datasets import DATA


def calculator():
    path = DATA / "recompute.py"
    assert path.exists(), "Need an executable future-observation recomputation tool"
    spec = importlib.util.spec_from_file_location("task10_recompute", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observations(metric="autonomous_repair"):
    return {"experiment_status": "executed", "dataset_sha256": hashlib.sha256((DATA / "diagnosis_cases.yaml").read_bytes()).hexdigest(),
        "system_commit": "a" * 40, "observations": [
            {"group": "knowbound", "metric": metric, "unit_id": "synthetic-unit-1", "outcome": True, "evidence_ref": "synthetic-evidence/1"},
            {"group": "knowbound", "metric": metric, "unit_id": "synthetic-unit-2", "outcome": None, "evidence_ref": "synthetic-evidence/2"}]}


def test_assigned_missing_repair_is_in_denominator_and_wilson_is_nonzero():
    result = calculator().recompute(observations(), DATA / "diagnosis_cases.yaml")
    row = result["metrics"][0]
    assert (row["numerator"], row["denominator"], row["missing"], row["rate"]) == (1, 2, 1, 0.5)
    assert 0 < row["wilson95"][0] < 0.5 < row["wilson95"][1] < 1


@pytest.mark.parametrize("metric", ["attack_success", "deletion_recovery", "answer_leakage", "teacher_agreement"])
def test_unexecuted_probe_is_reported_missing_not_passed(metric):
    row = calculator().recompute(observations(metric), DATA / "diagnosis_cases.yaml")["metrics"][0]
    assert (row["numerator"], row["denominator"], row["missing"]) == (1, 1, 1)


def test_missing_recurrence_reports_complete_case_and_conservative_bound():
    row = calculator().recompute(observations("recurrence"), DATA / "diagnosis_cases.yaml")["metrics"][0]
    assert row["denominator"] == 1 and row["missing_as_failure_rate"] == 1


@pytest.mark.parametrize("mutation", ["duplicate", "no_evidence", "draft_gold", "unknown_group", "not_executed", "hash", "identity"])
def test_invalid_or_unverified_observations_are_rejected(mutation):
    data = deepcopy(observations())
    if mutation == "duplicate": data["observations"].append(deepcopy(data["observations"][0]))
    if mutation == "no_evidence": data["observations"][0]["evidence_ref"] = ""
    if mutation == "draft_gold":
        for row in data["observations"]:
            row["metric"] = "root_accuracy"
            row["case_id"] = "diag-exhaustive-control"
    if mutation == "unknown_group": data["observations"][0]["group"] = "assistant"
    if mutation == "not_executed": data["experiment_status"] = "not_executed"
    if mutation == "hash": data["dataset_sha256"] = "0" * 64
    if mutation == "identity": data["observations"][0]["email"] = "synthetic@example.invalid"
    with pytest.raises(ValueError): calculator().recompute(data, DATA / "diagnosis_cases.yaml")
