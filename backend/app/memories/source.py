from __future__ import annotations

from sqlalchemy import select

from app.memories.models import DiagnosisSummary, MemoryProposalSource
from app.memories.persistence import SqlMemoryUnitOfWork
from app.persistence.models import (
    DiagnosisConceptRow,
    DiagnosisRow,
    EnrollmentRow,
    ExplanationCheckRow,
    SubmissionRow,
    UserRow,
)


class SqlDiagnosticMemorySource:
    """Server-side Task 6 source adapter; client claims never enter this join."""

    def __init__(
        self, uow: SqlMemoryUnitOfWork, *, confidence_threshold: float
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence threshold must be in [0,1]")
        self._uow = uow
        self._threshold = confidence_threshold

    def proposal_source(
        self, explanation_check_id: str
    ) -> MemoryProposalSource | None:
        with self._uow.read_session() as session:
            row = session.execute(
                select(
                    ExplanationCheckRow,
                    DiagnosisRow,
                    SubmissionRow,
                    UserRow,
                    EnrollmentRow,
                )
                .join(
                    DiagnosisRow,
                    ExplanationCheckRow.diagnosis_id == DiagnosisRow.id,
                )
                .join(SubmissionRow, DiagnosisRow.submission_id == SubmissionRow.id)
                .join(UserRow, DiagnosisRow.owner_user_id == UserRow.id)
                .join(
                    EnrollmentRow,
                    (EnrollmentRow.course_id == DiagnosisRow.course_id)
                    & (EnrollmentRow.user_id == DiagnosisRow.owner_user_id),
                )
                .where(ExplanationCheckRow.id == explanation_check_id)
            ).one_or_none()
            if row is None:
                return None
            check, diagnosis, submission, user, enrollment = row
            concepts = tuple(
                session.scalars(
                    select(DiagnosisConceptRow.concept_id)
                    .where(DiagnosisConceptRow.diagnosis_id == diagnosis.id)
                    .order_by(DiagnosisConceptRow.ordinal)
                ).all()
            )
            check_concepts = tuple(check.concept_ids)
            relationships_match = (
                check.diagnosis_id == diagnosis.id
                and diagnosis.submission_id == submission.id
                and diagnosis.owner_user_id == submission.owner_user_id
                and diagnosis.course_id == submission.course_id
                and enrollment.role == "student"
                and user.role == "student"
                and user.active
            )
            eligible = (
                relationships_match
                and check.memory_proposal_eligible
                and check.understands
                and check.confidence >= self._threshold
                and diagnosis.confidence >= self._threshold
                and not diagnosis.requires_teacher_review
                and bool(check_concepts)
                and set(check_concepts) <= set(concepts)
            )
            return MemoryProposalSource(
                explanation_check_id=check.id,
                diagnosis_id=diagnosis.id,
                owner_user_id=diagnosis.owner_user_id,
                course_id=diagnosis.course_id,
                content=diagnosis.root_cause,
                concept_ids=check_concepts,
                confidence=min(check.confidence, diagnosis.confidence),
                eligible=eligible,
            )

    def diagnosis_summary(self, diagnosis_id: str) -> DiagnosisSummary | None:
        with self._uow.read_session() as session:
            row = session.execute(
                select(DiagnosisRow, SubmissionRow)
                .join(SubmissionRow, DiagnosisRow.submission_id == SubmissionRow.id)
                .where(DiagnosisRow.id == diagnosis_id)
            ).one_or_none()
            if row is None:
                return None
            diagnosis, submission = row
            if (
                diagnosis.owner_user_id != submission.owner_user_id
                or diagnosis.course_id != submission.course_id
            ):
                return None
            concepts = tuple(
                session.scalars(
                    select(DiagnosisConceptRow.concept_id)
                    .where(DiagnosisConceptRow.diagnosis_id == diagnosis.id)
                    .order_by(DiagnosisConceptRow.ordinal)
                ).all()
            )
            return DiagnosisSummary(
                diagnosis_id=diagnosis.id,
                owner_user_id=diagnosis.owner_user_id,
                course_id=diagnosis.course_id,
                category=diagnosis.category,
                concept_ids=concepts,
                root_cause=diagnosis.root_cause,
                confidence=diagnosis.confidence,
            )
