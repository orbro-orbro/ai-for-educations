from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class _GatewayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceContext(_GatewayModel):
    path: str
    content: str


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


class CompilerDiagnosticEvidenceOutput(_GatewayModel):
    kind: Literal["compiler_diagnostic"]
    summary: str = Field(min_length=1)
    diagnostic_index: int = Field(ge=0)


class RuleMatchEvidenceOutput(_GatewayModel):
    kind: Literal["rule_match"]
    summary: str = Field(min_length=1)
    misconception_id: str = Field(min_length=1)


class ApprovedKnowledgeEvidenceOutput(_GatewayModel):
    kind: Literal["approved_knowledge"]
    summary: str = Field(min_length=1)
    misconception_id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)


EvidenceOutput = Annotated[
    CompilerDiagnosticEvidenceOutput
    | RuleMatchEvidenceOutput
    | ApprovedKnowledgeEvidenceOutput,
    Field(discriminator="kind"),
]


class DiagnosisModelOutput(_GatewayModel):
    category: str
    locations: tuple[dict[str, object], ...]
    concept_ids: tuple[str, ...]
    root_cause: str
    evidence: tuple[EvidenceOutput, ...]
    confidence: float
    recommended_hint_level: int


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
