from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _GatewayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceContext(_GatewayModel):
    path: str


class CompilerDiagnosticContext(_GatewayModel):
    severity: str
    message: str
    code: str | None
    file: str | None
    start_line: int | None
    end_line: int | None


class ExecutionContext(_GatewayModel):
    status: str
    phase: str
    retryable: bool
    exit_code: int | None
    diagnostics: tuple[CompilerDiagnosticContext, ...]
    toolchain_cjc: str


class RuleMatchContext(_GatewayModel):
    misconception_id: str
    root_concept_id: str
    related_concept_ids: tuple[str, ...]
    diagnostic_indices: tuple[int, ...]
    evidence_summary: str
    source_references: tuple[str, ...]
    match_strength: str


class ApprovedKnowledgeContext(_GatewayModel):
    misconception_id: str
    root_concept_id: str
    related_concept_ids: tuple[str, ...]
    explanation: str
    source_references: tuple[str, ...]
    hint_outlines: tuple[str, ...]


class DiagnosisRequest(_GatewayModel):
    source_files: tuple[SourceContext, ...]
    execution: ExecutionContext
    rule_matches: tuple[RuleMatchContext, ...]
    knowledge: tuple[ApprovedKnowledgeContext, ...]
    exercise_context: str = ""


class HintRequest(_GatewayModel):
    category: str
    root_cause: str
    concept_ids: tuple[str, ...]
    level: int = Field(ge=1, le=4)
    previous_attempt_count: int = Field(ge=0)
    approved_outline: str
    low_information: bool = False


class ExplanationCheckRequest(_GatewayModel):
    category: str
    root_cause: str
    diagnosis_concept_ids: tuple[str, ...]
    approved_concept_ids: tuple[str, ...]
    explanation: str = Field(min_length=1)


class CompilerDiagnosticEvidence(_GatewayModel):
    kind: Literal["compiler_diagnostic"]
    summary: str = Field(min_length=1)
    diagnostic_index: int = Field(ge=0)


class RuleMatchEvidence(_GatewayModel):
    kind: Literal["rule_match"]
    summary: str = Field(min_length=1)
    misconception_id: str = Field(min_length=1)


class ApprovedKnowledgeEvidence(_GatewayModel):
    kind: Literal["approved_knowledge"]
    summary: str = Field(min_length=1)
    misconception_id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)


# Keep existing gateway imports and public OpenAPI component names stable.
CompilerDiagnosticEvidenceOutput = CompilerDiagnosticEvidence
RuleMatchEvidenceOutput = RuleMatchEvidence
ApprovedKnowledgeEvidenceOutput = ApprovedKnowledgeEvidence

EvidenceOutput = Annotated[
    CompilerDiagnosticEvidence
    | RuleMatchEvidence
    | ApprovedKnowledgeEvidence,
    Field(discriminator="kind"),
]


class DiagnosisCategory(StrEnum):
    conceptual = "conceptual"
    strategic = "strategic"
    procedural = "procedural"
    expression = "expression"


class DiagnosisLocation(_GatewayModel):
    file: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_line > self.end_line:
            raise ValueError("start_line must not exceed end_line")
        return self


class DiagnosisModelOutput(_GatewayModel):
    """Shared structural contract for the provider prompt and business validation."""

    category: DiagnosisCategory
    locations: tuple[DiagnosisLocation, ...] = Field(min_length=1)
    concept_ids: tuple[str, ...] = Field(min_length=1)
    root_cause: str = Field(min_length=1)
    evidence: tuple[EvidenceOutput, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    recommended_hint_level: int = Field(ge=1, le=4)

    @field_validator("concept_ids")
    @classmethod
    def concepts_are_unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("concept_ids must be unique")
        return value


class HintModelOutput(_GatewayModel):
    level: int = Field(ge=1, le=4)
    content: str = Field(min_length=1)


class ExplanationModelOutput(_GatewayModel):
    understands: bool
    concept_ids: tuple[str, ...]
    evidence_summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    feedback: str = Field(min_length=1)


class ProviderError(RuntimeError):
    """Base provider error. Its message must never be returned to a client."""


class ProviderTimeout(ProviderError):
    pass


class ProviderFailure(ProviderError):
    pass


class ModelProvider(Protocol):
    def generate_diagnosis(self, request: DiagnosisRequest) -> DiagnosisModelOutput: ...
    def generate_hint(self, request: HintRequest) -> HintModelOutput: ...
    def check_explanation(
        self, request: ExplanationCheckRequest
    ) -> ExplanationModelOutput: ...


@runtime_checkable
class UserScopedModelProvider(Protocol):
    """A provider that resolves the target per user.

    The services still receive one object, but a request from a student who
    configured a personal key must use that key, while everyone else keeps
    using the shared (teacher) configuration.
    """

    def for_user(self, user_id: str | None) -> ModelProvider: ...
