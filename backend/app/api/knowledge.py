"""Teacher knowledge-management endpoints (contract: contracts/fragments/task-4-knowledge.yaml).

Not mounted on the shared app here. At Wave 1 Gate the coordinator includes ``router`` and
overrides two dependencies:

* ``authorize_course_teacher`` -> adapter over Task 2's course policy
* ``get_knowledge_repository`` -> the shared repository instance
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Annotated

from fastapi import APIRouter, Body, Depends, Header, Request, Security
from app.api.contract import BEARER, errors
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from app.knowledge.models import (
    Concept,
    ConceptEdge,
    HintStep,
    KnowledgeId,
    KnowledgeValidationError,
    MisconceptionPattern,
    NonEmpty,
    ReviewStatus,
    SourceMetadata,
    Topic,
    TriggerEvidence,
    Verification,
    parse_edge,
    require_review_status,
    require_source,
    validate_model,
)
from app.knowledge.repository import InMemoryKnowledgeRepository, KnowledgeRepository

router = APIRouter(prefix="/teacher/courses/{course_id}", tags=["knowledge"], dependencies=[Security(BEARER)])

NOT_AVAILABLE = "RESOURCE_NOT_AVAILABLE"
_STATUS_BY_CODE = {
    NOT_AVAILABLE: 404,
    "KNOWLEDGE_ID_CONFLICT": 409,
    "EDGE_CONFLICT": 409,
    "ROOT_CONCEPT_NOT_APPROVED": 409,
}


@dataclass(frozen=True)
class CourseAuthorization:
    """Outcome of 'is the caller a teacher who owns this course?'."""

    allowed: bool
    teacher_id: str | None = None
    course_id: str | None = None

    @classmethod
    def allow(cls, teacher_id: str, course_id: str) -> "CourseAuthorization":
        return cls(True, teacher_id, course_id)

    @classmethod
    def deny(cls) -> "CourseAuthorization":
        return cls(False)


def authorize_course_teacher(
    course_id: str,
    request: Request,
    authorization: str | None = Header(default=None, include_in_schema=False),
) -> CourseAuthorization:
    """Authenticate the bearer and enforce Task 2's server-side course policy."""

    authenticator = getattr(request.app.state, "authenticator", None)
    course_service = getattr(request.app.state, "course_service", None)
    if authenticator is None or course_service is None:
        return CourseAuthorization.deny()
    actor = authenticator.authenticate_header(authorization)
    course_service.require_teacher_access(actor, course_id)
    return CourseAuthorization.allow(actor.user_id, course_id)


_default_repository = InMemoryKnowledgeRepository()


def get_knowledge_repository(request: Request) -> KnowledgeRepository:
    return getattr(request.app.state, "knowledge_repository", _default_repository)


def _optional_schema(schema):
    for field in schema.get("properties", {}).values():
        if field.get("default", "absent") is None:
            field.pop("default")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=_optional_schema)


class ConceptCreate(_Body):
    id: KnowledgeId
    topic: Topic
    title: NonEmpty
    summary: NonEmpty
    source: SourceMetadata


class ConceptUpdate(_Body):
    model_config = ConfigDict(extra="forbid", json_schema_extra=lambda schema: (_optional_schema(schema), schema.update(minProperties=1)))
    topic: Topic = None
    title: NonEmpty = None
    summary: NonEmpty = None
    source: SourceMetadata = None


class MisconceptionCreate(_Body):
    id: KnowledgeId
    topic: Topic
    title: NonEmpty
    root_concept_id: KnowledgeId
    related_concept_ids: list[KnowledgeId] = Field(default_factory=list)
    trigger_evidence: list[TriggerEvidence] = Field(min_length=1)
    explanation: NonEmpty
    hint_ladder: list[HintStep] = Field(min_length=4, max_length=4)
    source: SourceMetadata
    verification: Verification


class MisconceptionUpdate(_Body):
    model_config = ConfigDict(extra="forbid", json_schema_extra=lambda schema: (_optional_schema(schema), schema.update(minProperties=1)))
    topic: Topic = None
    title: NonEmpty = None
    root_concept_id: KnowledgeId = None
    related_concept_ids: list[KnowledgeId] = None
    trigger_evidence: list[TriggerEvidence] = Field(default=None, min_length=1)
    explanation: NonEmpty = None
    hint_ladder: list[HintStep] = Field(default=None, min_length=4, max_length=4)
    source: SourceMetadata = None
    verification: Verification = None


class ReviewDecision(_Body):
    decision: Literal["approved", "rejected"]
    note: str | None = None


def _error(request: Request, code: str, message: str) -> JSONResponse:
    from app.api.errors import request_id_for

    request_id = request_id_for(request)
    status = _STATUS_BY_CODE.get(code, 422)
    return JSONResponse(status_code=status, content={"code": code, "message": message, "request_id": request_id})


def _not_available(request: Request) -> JSONResponse:
    return _error(request, NOT_AVAILABLE, "Resource is not available.")


def _dump(record: BaseModel, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=record.model_dump(mode="json"))


def _changes(model: type[_Body], payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise KnowledgeValidationError("VALIDATION_ERROR", "update must change at least one field")
    if "source" in payload:
        require_source(payload, "update")
    parsed = validate_model(model, payload, "update")
    return {k: getattr(parsed, k) for k in payload}


def _parse_review(payload: Any) -> ReviewDecision:
    decision = payload.get("decision") if isinstance(payload, dict) else None
    require_review_status(decision, "review")
    if decision not in ("approved", "rejected"):
        raise KnowledgeValidationError("UNKNOWN_REVIEW_STATUS", "decision must be approved or rejected")
    review = validate_model(ReviewDecision, payload, "review")
    if review.decision not in (ReviewStatus.approved, ReviewStatus.rejected):
        raise KnowledgeValidationError("UNKNOWN_REVIEW_STATUS", "decision must be approved or rejected")
    return review


_RESET_REVIEW = {"review_status": ReviewStatus.pending_review, "reviewed_by": None, "review_note": None}


# ---------------------------------------------------------------- concepts


@router.get("/concepts", operation_id="listCourseConcepts", response_model=list[Concept], responses=errors(401, 404))
def list_concepts(
    course_id: str,
    request: Request,
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    return JSONResponse([c.model_dump(mode="json") for c in repo.list_concepts(course_id)])


@router.post("/concepts", status_code=201, operation_id="createCourseConcept", response_model=Concept, responses=errors(401, 404, 409, 422))
def create_concept(
    course_id: str,
    request: Request,
    payload: Annotated[ConceptCreate, Body(...), SkipValidation()],
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    try:
        require_source(payload, "concept")
        body = validate_model(ConceptCreate, payload, "concept")
        concept = Concept(**body.model_dump(), review_status=ReviewStatus.pending_review)
        return _dump(repo.create_concept(course_id, concept), 201)
    except KnowledgeValidationError as exc:
        return _error(request, exc.code, exc.message)


@router.patch("/concepts/{concept_id}", operation_id="updateCourseConcept", response_model=Concept, responses=errors(401, 404, 422))
def update_concept(
    course_id: str,
    concept_id: KnowledgeId,
    request: Request,
    payload: Annotated[ConceptUpdate, Body(...), SkipValidation()],
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed or (current := repo.get_concept(course_id, concept_id)) is None:
        return _not_available(request)
    try:
        merged = {**current.model_dump(), **_changes(ConceptUpdate, payload), **_RESET_REVIEW}
        updated = validate_model(Concept, _plain(merged), concept_id)
        return _dump(repo.replace_concept(course_id, updated))
    except KnowledgeValidationError as exc:
        return _error(request, exc.code, exc.message)


@router.post("/concepts/{concept_id}/review", operation_id="reviewCourseConcept", response_model=Concept, responses=errors(401, 404, 422))
def review_concept(
    course_id: str,
    concept_id: KnowledgeId,
    request: Request,
    payload: Annotated[ReviewDecision, Body(...), SkipValidation()],
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed or (current := repo.get_concept(course_id, concept_id)) is None:
        return _not_available(request)
    try:
        review = _parse_review(payload)
    except KnowledgeValidationError as exc:
        return _error(request, exc.code, exc.message)
    updated = current.model_copy(
        update={"review_status": ReviewStatus(review.decision), "reviewed_by": auth.teacher_id, "review_note": review.note}
    )
    return _dump(repo.replace_concept(course_id, updated))


# ---------------------------------------------------------------- edges


@router.get("/concept-edges", operation_id="listCourseConceptEdges", response_model=list[ConceptEdge], responses=errors(401, 404))
def list_edges(
    course_id: str,
    request: Request,
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    return JSONResponse([e.model_dump(mode="json") for e in repo.list_edges(course_id)])


@router.post("/concept-edges", status_code=201, operation_id="createCourseConceptEdge", response_model=ConceptEdge, responses=errors(401, 404, 409, 422))
def create_edge(
    course_id: str,
    request: Request,
    payload: Annotated[ConceptEdge, Body(...), SkipValidation()],
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    try:
        edge = parse_edge(payload if isinstance(payload, dict) else {})
        return _dump(repo.add_edge(course_id, edge), 201)
    except KnowledgeValidationError as exc:
        return _error(request, exc.code, exc.message)


# ---------------------------------------------------------------- misconceptions


@router.get("/misconceptions", operation_id="listCourseMisconceptions", response_model=list[MisconceptionPattern], responses=errors(401, 404))
def list_misconceptions(
    course_id: str,
    request: Request,
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    return JSONResponse([m.model_dump(mode="json") for m in repo.list_misconceptions(course_id)])


@router.post("/misconceptions", status_code=201, operation_id="createCourseMisconception", response_model=MisconceptionPattern, responses=errors(401, 404, 409, 422))
def create_misconception(
    course_id: str,
    request: Request,
    payload: Annotated[MisconceptionCreate, Body(...), SkipValidation()],
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    try:
        require_source(payload, "misconception")
        body = validate_model(MisconceptionCreate, payload, "misconception")
        m = MisconceptionPattern(**body.model_dump(), review_status=ReviewStatus.pending_review)
        return _dump(repo.create_misconception(course_id, m), 201)
    except KnowledgeValidationError as exc:
        return _error(request, exc.code, exc.message)


@router.patch("/misconceptions/{misconception_id}", operation_id="updateCourseMisconception", response_model=MisconceptionPattern, responses=errors(401, 404, 422))
def update_misconception(
    course_id: str,
    misconception_id: KnowledgeId,
    request: Request,
    payload: Annotated[MisconceptionUpdate, Body(...), SkipValidation()],
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed or (current := repo.get_misconception(course_id, misconception_id)) is None:
        return _not_available(request)
    try:
        changes = _changes(MisconceptionUpdate, payload)
        merged = {**current.model_dump(), **changes, **_RESET_REVIEW}
        updated = validate_model(MisconceptionPattern, _plain(merged), misconception_id)
        return _dump(repo.replace_misconception(course_id, updated))
    except KnowledgeValidationError as exc:
        return _error(request, exc.code, exc.message)


@router.post("/misconceptions/{misconception_id}/review", operation_id="reviewCourseMisconception", response_model=MisconceptionPattern, responses=errors(401, 404, 409, 422))
def review_misconception(
    course_id: str,
    misconception_id: KnowledgeId,
    request: Request,
    payload: Annotated[ReviewDecision, Body(...), SkipValidation()],
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed or (current := repo.get_misconception(course_id, misconception_id)) is None:
        return _not_available(request)
    try:
        review = _parse_review(payload)
    except KnowledgeValidationError as exc:
        return _error(request, exc.code, exc.message)
    root = repo.get_concept(course_id, current.root_concept_id)
    if review.decision == "approved" and (root is None or root.review_status is not ReviewStatus.approved):
        return _error(request, "ROOT_CONCEPT_NOT_APPROVED", "approve the root concept first")
    updated = current.model_copy(
        update={"review_status": ReviewStatus(review.decision), "reviewed_by": auth.teacher_id, "review_note": review.note}
    )
    return _dump(repo.replace_misconception(course_id, updated))


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value
