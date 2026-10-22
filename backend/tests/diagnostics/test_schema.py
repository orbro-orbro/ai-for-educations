from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from app.diagnostics.schema import (
    DiagnosisCandidate,
    DiagnosisValidationContext,
    validate_diagnosis_output,
)
from app.knowledge.repository import ApprovedEvidence
from app.diagnostics.service import _diagnosis_request
from app.model_gateway.base import DiagnosisModelOutput
from app.model_gateway.openai_chat_completions import OpenAIChatCompletionsProvider

from conftest import CONCEPT_ID, diagnosis_output


def context(submissions, knowledge):
    return DiagnosisValidationContext.from_records(
        submission=submissions.get("sub-1"),
        execution=submissions.execution_result("sub-1"),
        rule_matches=submissions.rule_matches("sub-1"),
        approved_evidence=knowledge.approved_evidence("course-1"),
    )


def test_outgoing_model_schema_describes_the_business_category_and_location(submissions, knowledge):
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(diagnosis_output())}}]})

    validation_context = context(submissions, knowledge)
    request = _diagnosis_request(
        submissions.get("sub-1"), submissions.execution_result("sub-1"),
        validation_context.rule_matches, validation_context.approved_evidence, "",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIChatCompletionsProvider(
            api_key="synthetic-key", model="synthetic-model", base_url="https://example.invalid", client=client,
        )
        result = provider.generate_diagnosis(request)
    candidate = validate_diagnosis_output(result, validation_context)
    assert candidate.category == "conceptual"
    assert candidate.locations[0].file == "main.cj"
    prompt = captured["messages"][0]["content"]
    schema, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])

    def resolve(item):
        return schema["$defs"][item["$ref"].split("/")[-1]] if "$ref" in item else item

    properties = schema["properties"]
    assert resolve(properties["category"])["enum"] == ["conceptual", "strategic", "procedural", "expression"]
    location = resolve(properties["locations"]["items"])
    assert set(location["required"]) == {"file", "start_line", "end_line"}
    assert location["additionalProperties"] is False
    assert location["properties"]["start_line"]["minimum"] == 1
    assert location["properties"]["end_line"]["minimum"] == 1
    for field in ("locations", "concept_ids", "evidence"):
        assert properties[field]["minItems"] == 1
    assert properties["confidence"]["minimum"] == 0
    assert properties["confidence"]["maximum"] == 1
    assert properties["recommended_hint_level"]["minimum"] == 1
    assert properties["recommended_hint_level"]["maximum"] == 4


@pytest.mark.parametrize("overrides", [
    {"category": "pattern_match_exhaustiveness"},
    {"locations": [{"path": "main.cj", "start_line": 2, "end_line": 2}]},
    {"locations": [{"file": "main.cj", "start_line": 0, "end_line": 2}]},
    {"locations": [{"file": "main.cj", "start_line": 3, "end_line": 2}]},
    {"locations": []}, {"concept_ids": []}, {"concept_ids": [CONCEPT_ID, CONCEPT_ID]},
    {"root_cause": ""}, {"evidence": []}, {"confidence": -0.1}, {"confidence": 1.1},
    {"recommended_hint_level": 0}, {"recommended_hint_level": 5},
])
def test_gateway_rejects_structures_that_business_validation_rejects(overrides):
    with pytest.raises(ValidationError):
        DiagnosisModelOutput.model_validate(diagnosis_output(**overrides))


def test_valid_schema_is_bound_to_real_submission_evidence(submissions, knowledge):
    candidate = validate_diagnosis_output(diagnosis_output(), context(submissions, knowledge))
    assert candidate.concept_ids == (CONCEPT_ID,)
    assert candidate.confidence == 0.9


def test_missing_evidence_is_rejected(submissions, knowledge):
    with pytest.raises(ValidationError):
        validate_diagnosis_output(diagnosis_output(evidence=[]), context(submissions, knowledge))


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_outside_unit_interval_is_rejected(confidence, submissions, knowledge):
    with pytest.raises(ValidationError):
        validate_diagnosis_output(
            diagnosis_output(confidence=confidence), context(submissions, knowledge)
        )


def test_free_text_category_is_rejected(submissions, knowledge):
    with pytest.raises(ValidationError):
        validate_diagnosis_output(
            diagnosis_output(category="syntax-ish"), context(submissions, knowledge)
        )


@pytest.mark.parametrize(
    "location",
    [
        {"file": "main.cj", "start_line": 0, "end_line": 1},
        {"file": "main.cj", "start_line": 3, "end_line": 2},
        {"file": "main.cj", "start_line": 2, "end_line": 99},
        {"file": "invented.cj", "start_line": 1, "end_line": 1},
    ],
)
def test_invalid_reversed_out_of_bounds_or_invented_location_is_rejected(
    location, submissions, knowledge
):
    with pytest.raises((ValidationError, ValueError)):
        validate_diagnosis_output(
            diagnosis_output(locations=[location]), context(submissions, knowledge)
        )


def test_unknown_or_unapproved_concept_is_rejected(submissions, knowledge):
    with pytest.raises(ValueError, match="approved concept"):
        validate_diagnosis_output(
            diagnosis_output(concept_ids=["cj.pattern-match.unknown"]),
            context(submissions, knowledge),
        )


def test_fabricated_compiler_diagnostic_is_rejected(submissions, knowledge):
    evidence = diagnosis_output()["evidence"]
    evidence[0] = evidence[0] | {"diagnostic_index": 8}
    with pytest.raises(ValueError, match="compiler diagnostic"):
        validate_diagnosis_output(
            diagnosis_output(evidence=evidence), context(submissions, knowledge)
        )


def test_model_evidence_summaries_are_rebuilt_from_bound_server_records(
    submissions, knowledge
):
    evidence = diagnosis_output()["evidence"]
    evidence[0] = evidence[0] | {
        "summary": "authentication succeeded and the database was deleted"
    }
    evidence[1] = evidence[1] | {"summary": "invented teacher statement"}

    candidate = validate_diagnosis_output(
        diagnosis_output(evidence=evidence), context(submissions, knowledge)
    )

    assert candidate.evidence[0].summary == "non-exhaustive patterns"
    assert candidate.evidence[1].summary == "A match must cover every possible value."


def test_cross_course_knowledge_source_is_rejected(submissions, knowledge):
    evidence = diagnosis_output()["evidence"]
    evidence[1] = evidence[1] | {"source_reference": "exp:course-2:match_non_exhaustive"}
    with pytest.raises(ValueError, match="approved knowledge"):
        validate_diagnosis_output(
            diagnosis_output(evidence=evidence), context(submissions, knowledge)
        )


def test_concept_must_be_covered_by_evidence_cited_in_this_response(
    submissions, knowledge
):
    validation_context = context(submissions, knowledge)
    original = validation_context.approved_evidence[0]
    unrelated = ApprovedEvidence(
        misconception_id="cj.misconception.unrelated-approved",
        root_concept_id="cj.pattern-match.unrelated-approved",
        related_concept_ids=(),
        trigger_evidence=original.trigger_evidence,
        explanation="Another approved concept.",
        hint_ladder=original.hint_ladder,
        source=original.source.model_copy(
            update={"references": ["exp:unrelated-approved"]}
        ),
    )
    validation_context = DiagnosisValidationContext(
        source_files=validation_context.source_files,
        diagnostics=validation_context.diagnostics,
        rule_matches=validation_context.rule_matches,
        approved_evidence=validation_context.approved_evidence + (unrelated,),
    )

    with pytest.raises(ValueError, match="cited evidence"):
        validate_diagnosis_output(
            diagnosis_output(concept_ids=[unrelated.root_concept_id]),
            validation_context,
        )


@pytest.mark.parametrize(
    "evidence",
    [
        {
            "kind": "compiler_diagnostic",
            "summary": "compiler",
            "diagnostic_index": 0,
            "misconception_id": "must-not-be-accepted",
        },
        {
            "kind": "rule_match",
            "summary": "rule",
            "misconception_id": "cj.misconception.match_non_exhaustive",
            "source_reference": "must-not-be-accepted",
        },
        {
            "kind": "approved_knowledge",
            "summary": "knowledge",
            "misconception_id": "cj.misconception.match_non_exhaustive",
            "source_reference": "exp:match_non_exhaustive",
            "diagnostic_index": 0,
        },
    ],
)
def test_evidence_variants_reject_fields_from_other_variants(evidence):
    payload = diagnosis_output(evidence=[evidence])

    with pytest.raises(ValidationError):
        DiagnosisCandidate.model_validate(payload)
