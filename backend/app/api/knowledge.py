"""Teacher knowledge-management endpoints (contract: contracts/fragments/task-4-knowledge.yaml).

Not mounted on the shared app here. At Wave 1 Gate the coordinator includes ``router`` and
overrides two dependencies:

* ``authorize_course_teacher`` -> adapter over Task 2's course policy
* ``get_knowledge_repository`` -> the shared repository instance
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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

router = APIRouter(prefix="/teacher/courses/{course_id}", tags=["knowledge"])

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


def authorize_course_teacher(course_id: str) -> CourseAuthorization:
    """Deny-by-default placeholder until Task 2's policy is wired in via dependency override."""
    return CourseAuthorization.deny()


_default_repository = InMemoryKnowledgeRepository()


def get_knowledge_repository() -> KnowledgeRepository:
    return _default_repository


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConceptCreate(_Body):
    id: KnowledgeId
    topic: Topic
    title: NonEmpty
    summary: NonEmpty
    source: SourceMetadata


class ConceptUpdate(_Body):
    topic: Topic | None = None
    title: NonEmpty | None = None
    summary: NonEmpty | None = None
    source: SourceMetadata | None = None


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
    topic: Topic | None = None
    title: NonEmpty | None = None
    root_concept_id: KnowledgeId | None = None
    related_concept_ids: list[KnowledgeId] | None = None
    trigger_evidence: list[TriggerEvidence] | None = Field(default=None, min_length=1)
    explanation: NonEmpty | None = None
    hint_ladder: list[HintStep] | None = Field(default=None, min_length=4, max_length=4)
    source: SourceMetadata | None = None
    verification: Verification | None = None


class ReviewDecision(_Body):
    decision: ReviewStatus
    note: str | None = None


def _error(request: Request, code: str, message: str) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
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
    review = validate_model(ReviewDecision, payload, "review")
    if review.decision not in (ReviewStatus.approved, ReviewStatus.rejected):
        raise KnowledgeValidationError("UNKNOWN_REVIEW_STATUS", "decision must be approved or rejected")
    return review


_RESET_REVIEW = {"review_status": ReviewStatus.pending_review, "reviewed_by": None, "review_note": None}


# ---------------------------------------------------------------- concepts


@router.get("/concepts")
def list_concepts(
    course_id: str,
    request: Request,
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    return JSONResponse([c.model_dump(mode="json") for c in repo.list_concepts(course_id)])


@router.post("/concepts", status_code=201)
def create_concept(
    course_id: str,
    request: Request,
    payload: Any = Body(...),
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


@router.patch("/concepts/{concept_id}")
def update_concept(
    course_id: str,
    concept_id: str,
    request: Request,
    payload: Any = Body(...),
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


@router.post("/concepts/{concept_id}/review")
def review_concept(
    course_id: str,
    concept_id: str,
    request: Request,
    payload: Any = Body(...),
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
        update={"review_status": review.decision, "reviewed_by": auth.teacher_id, "review_note": review.note}
    )
    return _dump(repo.replace_concept(course_id, updated))


# ---------------------------------------------------------------- edges


@router.get("/concept-edges")
def list_edges(
    course_id: str,
    request: Request,
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    return JSONResponse([e.model_dump(mode="json") for e in repo.list_edges(course_id)])


@router.post("/concept-edges", status_code=201)
def create_edge(
    course_id: str,
    request: Request,
    payload: Any = Body(...),
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


@router.get("/misconceptions")
def list_misconceptions(
    course_id: str,
    request: Request,
    auth: CourseAuthorization = Depends(authorize_course_teacher),
    repo: KnowledgeRepository = Depends(get_knowledge_repository),
):
    if not auth.allowed:
        return _not_available(request)
    return JSONResponse([m.model_dump(mode="json") for m in repo.list_misconceptions(course_id)])


@router.post("/misconceptions", status_code=201)
def create_misconception(
    course_id: str,
    request: Request,
    payload: Any = Body(...),
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


@router.patch("/misconceptions/{misconception_id}")
def update_misconception(
    course_id: str,
    misconception_id: str,
    request: Request,
    payload: Any = Body(...),
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


@router.post("/misconceptions/{misconception_id}/review")
def review_misconception(
    course_id: str,
    misconception_id: str,
    request: Request,
    payload: Any = Body(...),
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
    if review.decision is ReviewStatus.approved and (root is None or root.review_status is not ReviewStatus.approved):
        return _error(request, "ROOT_CONCEPT_NOT_APPROVED", "approve the root concept first")
    updated = current.model_copy(
        update={"review_status": review.decision, "reviewed_by": auth.teacher_id, "review_note": review.note}
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
