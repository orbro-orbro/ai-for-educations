"""Course knowledge graph records: concepts, edges and misconception patterns."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

KNOWLEDGE_ID_PATTERN = r"^cj(\.[a-z0-9]+(-[a-z0-9]+)*){2,}$"

KnowledgeId = Annotated[str, StringConstraints(pattern=KNOWLEDGE_ID_PATTERN)]
NonEmpty = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class KnowledgeValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Topic(str, Enum):
    basics_control_flow = "basics_control_flow"
    functions_lambdas_closures = "functions_lambdas_closures"
    class_struct_semantics = "class_struct_semantics"
    interface_extension = "interface_extension"
    generics_where = "generics_where"
    enum_match = "enum_match"
    option_exceptions = "option_exceptions"
    concurrency_spawn_future = "concurrency_spawn_future"
    packages_build_tools = "packages_build_tools"


class ReviewStatus(str, Enum):
    draft = "draft"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"


class EdgeType(str, Enum):
    prerequisite = "prerequisite"
    confusable_with = "confusable_with"
    used_by = "used_by"
    explains_error = "explains_error"


class SourceKind(str, Enum):
    cangjie_coding_kb = "cangjie_coding_kb"
    toolchain_experiment = "toolchain_experiment"
    teacher_authored = "teacher_authored"
    course_material = "course_material"


class VerificationStatus(str, Enum):
    experiment_verified = "experiment_verified"
    knowledge_base_summary = "knowledge_base_summary"
    teacher_asserted = "teacher_asserted"
    unverified = "unverified"


class TriggerKind(str, Enum):
    compiler_diagnostic = "compiler_diagnostic"
    runtime_exception = "runtime_exception"
    code_pattern = "code_pattern"
    answer_pattern = "answer_pattern"


class TriggerStrength(str, Enum):
    strong = "strong"
    weak = "weak"


class VerificationMethod(str, Enum):
    cjc_minimal_repro = "cjc_minimal_repro"
    cjpm_project_repro = "cjpm_project_repro"
    knowledge_base_summary = "knowledge_base_summary"
    teacher_assertion = "teacher_assertion"


class Outcome(str, Enum):
    compile_error = "compile_error"
    runtime_error = "runtime_error"
    run_ok = "run_ok"


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceMetadata(_Record):
    kind: SourceKind
    references: list[NonEmpty] = Field(min_length=1)
    toolchain_version: NonEmpty
    verification_status: VerificationStatus
    note: str | None = None


class Concept(_Record):
    id: KnowledgeId
    topic: Topic
    title: NonEmpty
    summary: NonEmpty
    review_status: ReviewStatus
    reviewed_by: str | None = None
    review_note: str | None = None
    source: SourceMetadata


class ConceptEdge(_Record):
    source_id: KnowledgeId
    target_id: KnowledgeId
    edge_type: EdgeType
    note: str | None = None


class TriggerEvidence(_Record):
    kind: TriggerKind
    pattern: NonEmpty
    strength: TriggerStrength


class HintStep(_Record):
    level: int = Field(ge=1, le=4)
    outline: NonEmpty


class Verification(_Record):
    method: VerificationMethod
    toolchain_version: NonEmpty
    expected_outcome: Outcome | None = None
    snippet: str | None = None
    project_files: dict[str, str] | None = None
    expected_output_contains: str | None = None
    observed: str | None = None
    note: NonEmpty


class MisconceptionPattern(_Record):
    id: KnowledgeId
    topic: Topic
    title: NonEmpty
    root_concept_id: KnowledgeId
    related_concept_ids: list[KnowledgeId] = Field(default_factory=list)
    trigger_evidence: list[TriggerEvidence] = Field(min_length=1)
    explanation: NonEmpty
    hint_ladder: list[HintStep] = Field(min_length=4, max_length=4)
    review_status: ReviewStatus
    reviewed_by: str | None = None
    review_note: str | None = None
    source: SourceMetadata
    verification: Verification

    @field_validator("hint_ladder")
    @classmethod
    def _levels_in_order(cls, steps: list[HintStep]) -> list[HintStep]:
        if [s.level for s in steps] != [1, 2, 3, 4]:
            raise ValueError("hint ladder must contain levels 1, 2, 3, 4 in order")
        return steps


_SOURCE_REQUIRED = ("kind", "references", "toolchain_version", "verification_status")
_REVIEW_VALUES = {s.value for s in ReviewStatus}
_EDGE_VALUES = {e.value for e in EdgeType}


def require_source(data: Any, record_id: str) -> None:
    source = data.get("source") if isinstance(data, dict) else None
    if not isinstance(source, dict):
        raise KnowledgeValidationError("MISSING_SOURCE", f"{record_id} has no source metadata")
    for key in _SOURCE_REQUIRED:
        if not source.get(key):
            raise KnowledgeValidationError("MISSING_SOURCE", f"{record_id} source lacks {key}")


def require_review_status(value: Any, record_id: str) -> None:
    if value not in _REVIEW_VALUES:
        raise KnowledgeValidationError(
            "UNKNOWN_REVIEW_STATUS", f"{record_id} has unknown review status {value!r}"
        )


def require_edge_type(value: Any, label: str) -> None:
    if value not in _EDGE_VALUES:
        raise KnowledgeValidationError("UNKNOWN_EDGE_TYPE", f"{label} has unknown edge type {value!r}")


def _record_id(data: Any) -> str:
    return str(data.get("id", "<no id>")) if isinstance(data, dict) else "<invalid record>"


def validate_model(model: type[BaseModel], data: Any, label: str) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise KnowledgeValidationError("VALIDATION_ERROR", f"{label}: {exc.errors()[0]['msg']}") from exc


def parse_concept(data: Any) -> Concept:
    rid = _record_id(data)
    require_source(data, rid)
    require_review_status(data.get("review_status"), rid)
    return validate_model(Concept, data, rid)


def parse_misconception(data: Any) -> MisconceptionPattern:
    rid = _record_id(data)
    require_source(data, rid)
    require_review_status(data.get("review_status"), rid)
    return validate_model(MisconceptionPattern, data, rid)


def parse_edge(data: Any) -> ConceptEdge:
    label = f"edge {data.get('source_id')}->{data.get('target_id')}" if isinstance(data, dict) else "edge"
    require_edge_type(data.get("edge_type") if isinstance(data, dict) else None, label)
    return validate_model(ConceptEdge, data, label)
