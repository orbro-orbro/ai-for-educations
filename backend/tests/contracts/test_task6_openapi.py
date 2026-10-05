from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def _document():
    return yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))


def test_shared_contract_contains_task6_routes_and_strict_requests():
    document = _document()

    expected = {
        "/submissions/{submission_id}/diagnosis": "getSubmissionDiagnosis",
        "/diagnoses/{diagnosis_id}/hints/next": "createNextDiagnosisHint",
        "/diagnoses/{diagnosis_id}/explanation-check": "checkDiagnosisExplanation",
    }
    for path, operation_id in expected.items():
        assert path in document["paths"]
        operation = next(
            value
            for method, value in document["paths"][path].items()
            if method in {"get", "post"}
        )
        assert operation["operationId"] == operation_id
        assert operation["security"] == [{"bearerAuth": []}]
        assert {"401", "404", "409", "422", "503"} <= set(operation["responses"])

    for name in ("NextHintRequest", "ExplanationCheckRequest"):
        assert document["components"]["schemas"][name]["additionalProperties"] is False


def test_evidence_binding_is_a_discriminated_strict_union():
    schemas = _document()["components"]["schemas"]
    evidence = schemas["EvidenceBinding"]

    assert evidence["discriminator"]["propertyName"] == "kind"
    assert len(evidence["oneOf"]) == 3
    assert {item["$ref"] for item in evidence["oneOf"]} == {
        "#/components/schemas/CompilerDiagnosticEvidence",
        "#/components/schemas/RuleMatchEvidence",
        "#/components/schemas/ApprovedKnowledgeEvidence",
    }
    expected_required = {
        "CompilerDiagnosticEvidence": {"kind", "summary", "diagnostic_index"},
        "RuleMatchEvidence": {"kind", "summary", "misconception_id"},
        "ApprovedKnowledgeEvidence": {
            "kind",
            "summary",
            "misconception_id",
            "source_reference",
        },
    }
    for name, required in expected_required.items():
        schema = schemas[name]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == required
        assert set(schema["properties"]) == required
