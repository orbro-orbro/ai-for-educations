from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.knowledge.repository import ApprovedEvidence
from app.submissions.models import ExecutionResult, Submission


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiagnosisCategory(StrEnum):
    conceptual = "conceptual"
    strategic = "strategic"
    procedural = "procedural"
    expression = "expression"


class DiagnosisLocation(_StrictModel):
    file: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_line > self.end_line:
            raise ValueError("start_line must not exceed end_line")
        return self


class CompilerDiagnosticEvidence(_StrictModel):
    kind: Literal["compiler_diagnostic"]
    summary: str = Field(min_length=1)
    diagnostic_index: int = Field(ge=0)


class RuleMatchEvidence(_StrictModel):
    kind: Literal["rule_match"]
    summary: str = Field(min_length=1)
    misconception_id: str = Field(min_length=1)


class ApprovedKnowledgeEvidence(_StrictModel):
    kind: Literal["approved_knowledge"]
    summary: str = Field(min_length=1)
    misconception_id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)


EvidenceBinding = Annotated[
    CompilerDiagnosticEvidence | RuleMatchEvidence | ApprovedKnowledgeEvidence,
    Field(discriminator="kind"),
]


class DiagnosisCandidate(_StrictModel):
    category: DiagnosisCategory
    locations: tuple[DiagnosisLocation, ...] = Field(min_length=1)
    concept_ids: tuple[str, ...] = Field(min_length=1)
    root_cause: str = Field(min_length=1)
    evidence: tuple[EvidenceBinding, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    recommended_hint_level: int = Field(ge=1, le=4)

    @field_validator("concept_ids")
    @classmethod
    def concepts_are_unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("concept_ids must be unique")
        return value


class Diagnosis(_StrictModel):
    diagnosis_id: str
    submission_id: str
    course_id: str
    owner_user_id: str
    category: DiagnosisCategory
    locations: tuple[DiagnosisLocation, ...]
    concept_ids: tuple[str, ...]
    root_cause: str
    evidence: tuple[EvidenceBinding, ...]
    confidence: float = Field(ge=0, le=1)
    recommended_hint_level: int = Field(ge=1, le=4)
    requires_teacher_review: bool
    created_at: datetime
    request_id: str


class ReviewQueueEvent(_StrictModel):
    event_id: str
    submission_id: str
    diagnosis_id: str | None
    course_id: str
    owner_user_id: str
    reason: str
    summary: str
    created_at: datetime
    request_id: str


class HintEvent(_StrictModel):
    hint_event_id: str
    diagnosis_id: str
    previous_level: int = Field(ge=0, le=3)
    current_level: int = Field(ge=1, le=4)
    reason: str = Field(min_length=1)
    previous_attempt_count: int = Field(ge=0)
    content: str = Field(min_length=1)
    used_safe_fallback: bool
    created_at: datetime
    request_id: str


class ExplanationCheck(_StrictModel):
    explanation_check_id: str
    diagnosis_id: str
    understands: bool
    concept_ids: tuple[str, ...]
    evidence_summary: str
    confidence: float = Field(ge=0, le=1)
    feedback: str
    memory_proposal_eligible: bool
    created_at: datetime
    request_id: str


@dataclass(frozen=True, slots=True)
class DiagnosisValidationContext:
    source_files: tuple[object, ...]
    diagnostics: tuple[object, ...]
    rule_matches: tuple[object, ...]
    approved_evidence: tuple[ApprovedEvidence, ...]

    @classmethod
    def from_records(
        cls,
        *,
        submission: Submission,
        execution: ExecutionResult,
        rule_matches,
        approved_evidence,
    ) -> "DiagnosisValidationContext":
        return cls(
            source_files=tuple(submission.source_files),
            diagnostics=tuple(execution.diagnostics),
            rule_matches=tuple(rule_matches),
            approved_evidence=tuple(approved_evidence),
        )


def validate_diagnosis_output(raw, context: DiagnosisValidationContext) -> DiagnosisCandidate:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    candidate = DiagnosisCandidate.model_validate(raw)
    files = {item.path: item.content for item in context.source_files}
    for location in candidate.locations:
        if location.file not in files:
            raise ValueError("diagnosis location does not exist in submission")
        line_count = max(1, len(files[location.file].splitlines()))
        if location.end_line > line_count:
            raise ValueError("diagnosis location exceeds submitted source")

    approved_concepts = {
        concept_id
        for item in context.approved_evidence
        for concept_id in (item.root_concept_id, *item.related_concept_ids)
    }
    if any(concept_id not in approved_concepts for concept_id in candidate.concept_ids):
        raise ValueError("diagnosis references a concept without approved concept evidence")

    rules_by_id = {item.misconception_id: item for item in context.rule_matches}
    approved_by_id = {item.misconception_id: item for item in context.approved_evidence}
    cited_concepts: set[str] = set()
    trusted_evidence: list[EvidenceBinding] = []
    for evidence in candidate.evidence:
        if evidence.kind == "compiler_diagnostic":
            if evidence.diagnostic_index >= len(context.diagnostics):
                raise ValueError("diagnosis references an unknown compiler diagnostic")
            diagnostic = context.diagnostics[evidence.diagnostic_index]
            trusted_evidence.append(
                evidence.model_copy(update={"summary": diagnostic.message})
            )
        elif evidence.kind == "rule_match":
            rule = rules_by_id.get(evidence.misconception_id)
            if rule is None:
                raise ValueError("diagnosis references an unknown rule match")
            cited_concepts.update((rule.root_concept_id, *rule.related_concept_ids))
            trusted_evidence.append(
                evidence.model_copy(update={"summary": rule.evidence_summary})
            )
        else:
            approved = approved_by_id.get(evidence.misconception_id)
            if approved is None or evidence.source_reference not in approved.source.references:
                raise ValueError("diagnosis references unknown approved knowledge")
            cited_concepts.update(
                (approved.root_concept_id, *approved.related_concept_ids)
            )
            trusted_evidence.append(
                evidence.model_copy(update={"summary": approved.explanation})
            )
    if not set(candidate.concept_ids) <= cited_concepts:
        raise ValueError("diagnosis concepts are not covered by cited evidence")
    return candidate.model_copy(update={"evidence": tuple(trusted_evidence)})
