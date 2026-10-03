from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.diagnostics.schema import (
    DiagnosisCandidate,
    DiagnosisValidationContext,
    validate_diagnosis_output,
)
from app.knowledge.repository import ApprovedEvidence

from conftest import CONCEPT_ID, diagnosis_output


def context(submissions, knowledge):
    return DiagnosisValidationContext.from_records(
        submission=submissions.get("sub-1"),
        execution=submissions.execution_result("sub-1"),
        rule_matches=submissions.rule_matches("sub-1"),
        approved_evidence=knowledge.approved_evidence("course-1"),
    )


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
