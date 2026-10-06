from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from threading import Lock

import pytest

from app.audit.service import AuditService
from app.auth.models import Actor, Role
from app.courses.service import ResourceNotAvailable
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.diagnostics.schema import (
    ApprovedKnowledgeEvidence,
    Diagnosis,
    DiagnosisCategory,
    DiagnosisLocation,
    ExplanationCheck,
)
from app.memories.deletion import DeletionService
from app.memories.policy import MemoryPolicy
from app.memories.repository import InMemoryMemoryRepository
from app.memories.retrieval import InMemoryRetrievalIndex
from app.memories.service import DiagnosticMemorySource, MemoryService
from app.submissions.models import SubmissionStatus
from app.submissions.repository import InMemorySubmissionRepository


COURSE_A = "course-a"
COURSE_B = "course-b"
STUDENT_A = Actor("student-a", Role.STUDENT)
STUDENT_B = Actor("student-b", Role.STUDENT)
TEACHER_A = Actor("teacher-a", Role.TEACHER)
TEACHER_B = Actor("teacher-b", Role.TEACHER)
PRIVATE_TEXT = "I confuse class reference semantics with struct value semantics."


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


class ThreadSafeIds:
    def __init__(self) -> None:
        self._values = count(1)
        self._lock = Lock()

    def __call__(self) -> str:
        with self._lock:
            return f"id-{next(self._values)}"


class CourseAccess:
    def __init__(self) -> None:
        self.students = {
            (COURSE_A, STUDENT_A.user_id),
            (COURSE_A, STUDENT_B.user_id),
            (COURSE_B, STUDENT_A.user_id),
        }
        self.teachers = {
            (COURSE_A, TEACHER_A.user_id),
            (COURSE_B, TEACHER_B.user_id),
        }

    def require_student(self, actor: Actor, course_id: str) -> None:
        if actor.role is not Role.STUDENT or (course_id, actor.user_id) not in self.students:
            raise ResourceNotAvailable()

    def require_teacher(self, actor: Actor, course_id: str) -> None:
        if actor.role is not Role.TEACHER or (course_id, actor.user_id) not in self.teachers:
            raise ResourceNotAvailable()


def seed_task6_source(
    diagnostics: InMemoryDiagnosticRepository,
    submissions: InMemorySubmissionRepository,
    *,
    explanation_id: str,
    diagnosis_id: str,
    submission_id: str,
    owner_id: str,
    course_id: str,
    eligible: bool = True,
    diagnosis_confidence: float = 0.93,
    requires_teacher_review: bool = False,
) -> None:
    submissions.create(
        submission_id=submission_id,
        course_id=course_id,
        exercise_id=f"exercise-{course_id}",
        owner_user_id=owner_id,
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id=f"req-{submission_id}",
    )
    current = submissions.get(submission_id)
    for status in (
        SubmissionStatus.executing,
        SubmissionStatus.executed,
        SubmissionStatus.diagnosing,
        SubmissionStatus.diagnosed,
    ):
        current = submissions.transition(
            submission_id,
            status,
            request_id=f"req-{submission_id}",
            reason="task7 fixture",
        )
    diagnosis = Diagnosis(
        diagnosis_id=diagnosis_id,
        submission_id=submission_id,
        course_id=course_id,
        owner_user_id=owner_id,
        category=DiagnosisCategory.conceptual,
        locations=(DiagnosisLocation(file="main.cj", start_line=1, end_line=1),),
        concept_ids=("cj.class-struct.semantics",),
        root_cause=PRIVATE_TEXT,
        evidence=(
            ApprovedKnowledgeEvidence(
                kind="approved_knowledge",
                summary="Reviewed course evidence distinguishes value and reference semantics.",
                misconception_id="cj.misconception.class-struct",
                source_reference="course:class-struct",
            ),
        ),
        confidence=diagnosis_confidence,
        recommended_hint_level=1,
        requires_teacher_review=requires_teacher_review,
        created_at=datetime(2026, 10, 5, 7, 0, tzinfo=UTC),
        request_id=f"req-{diagnosis_id}",
    )
    diagnostics.save_diagnosis(diagnosis)
    diagnostics.add_explanation(
        ExplanationCheck(
            explanation_check_id=explanation_id,
            diagnosis_id=diagnosis_id,
            understands=eligible,
            concept_ids=("cj.class-struct.semantics",) if eligible else (),
            evidence_summary="The student explained the semantic distinction.",
            confidence=0.91 if eligible else 0.2,
            feedback="Evidence-bound explanation check.",
            memory_proposal_eligible=eligible,
            created_at=datetime(2026, 10, 5, 7, 30, tzinfo=UTC),
            request_id=f"req-{explanation_id}",
        )
    )


@pytest.fixture
def memory_fixture():
    clock = MutableClock()
    ids = ThreadSafeIds()
    diagnostics = InMemoryDiagnosticRepository()
    submissions = InMemorySubmissionRepository()
    seed_task6_source(
        diagnostics,
        submissions,
        explanation_id="check-a",
        diagnosis_id="diagnosis-a",
        submission_id="submission-a",
        owner_id=STUDENT_A.user_id,
        course_id=COURSE_A,
    )
    seed_task6_source(
        diagnostics,
        submissions,
        explanation_id="check-b",
        diagnosis_id="diagnosis-b",
        submission_id="submission-b",
        owner_id=STUDENT_B.user_id,
        course_id=COURSE_A,
    )
    seed_task6_source(
        diagnostics,
        submissions,
        explanation_id="check-course-b",
        diagnosis_id="diagnosis-course-b",
        submission_id="submission-course-b",
        owner_id=STUDENT_A.user_id,
        course_id=COURSE_B,
    )
    repository = InMemoryMemoryRepository()
    index = InMemoryRetrievalIndex()
    audit = AuditService(clock=clock, id_factory=ids)
    source = DiagnosticMemorySource(
        diagnostics=diagnostics,
        submissions=submissions,
        confidence_threshold=0.75,
    )
    course_access = CourseAccess()
    policy = MemoryPolicy(course_access)
    service = MemoryService(
        repository=repository,
        source=source,
        policy=policy,
        retrieval_index=index,
        audit=audit,
        clock=clock,
        id_factory=ids,
    )
    deletion = DeletionService(
        repository=repository,
        policy=policy,
        retrieval_index=index,
        audit=audit,
        clock=clock,
        id_factory=ids,
    )
    return {
        "clock": clock,
        "diagnostics": diagnostics,
        "submissions": submissions,
        "repository": repository,
        "index": index,
        "audit": audit,
        "source": source,
        "course_access": course_access,
        "policy": policy,
        "service": service,
        "deletion": deletion,
    }


def create_memory(memory_fixture, *, actor=STUDENT_A, check_id="check-a"):
    proposal = memory_fixture["service"].create_proposal(
        actor,
        check_id,
        request_id=f"proposal-{check_id}",
    )
    return memory_fixture["service"].accept_proposal(
        actor,
        proposal.proposal_id,
        request_id=f"accept-{check_id}",
        idempotency_key=f"accept-{check_id}",
    )
