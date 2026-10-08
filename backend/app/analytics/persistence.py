"""Minimal course-scoped analytics projection; personal text is never selected."""
from contextlib import contextmanager
from datetime import UTC
import hashlib
import hmac
import json

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import aliased

from app.analytics.models import AnalyticsDiagnosisFact, TeacherReviewCandidate
from app.analytics.repository import AnalyticsPersistenceError
from app.analytics.schemas import TeacherDiagnosisReview
from app.memories.persistence import MemoryPersistenceError, SqlMemoryUnitOfWork
from app.persistence.models import (DiagnosisRow, DiagnosisConceptRow, SubmissionRow,
    ExplanationCheckRow, DiagnosisAttemptRow, ExecutionResultRow, HintEventRow, ReviewQueueEventRow, TeacherDiagnosisReviewRow)
from app.persistence.repositories import SqlKnowledgeRepository


def subject_key(owner: str, course: str, secret: str) -> str:
    payload = b"teacher-analytics\0" + json.dumps([course, owner], separators=(",", ":")).encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlTeacherAnalyticsRepository:
    def __init__(self, uow: SqlMemoryUnitOfWork, *, secret: str, confidence_threshold: float = .75):
        self.uow = uow
        self._secret = secret
        self._confidence_threshold = confidence_threshold
        self._knowledge = SqlKnowledgeRepository(uow.sessions)

    @contextmanager
    def _read(self):
        try:
            with self.uow.read_session() as session:
                yield session
        except MemoryPersistenceError as error:
            raise AnalyticsPersistenceError("analytics storage unavailable") from error

    def _concepts(self, session, course):
        rows = session.execute(select(DiagnosisConceptRow.diagnosis_id, DiagnosisConceptRow.concept_id)
            .where(DiagnosisConceptRow.course_id == course).order_by(DiagnosisConceptRow.ordinal)).all()
        result = {}
        for diagnosis, concept in rows:
            result.setdefault(diagnosis, []).append(concept)
        return {key:tuple(dict.fromkeys(values)) for key,values in result.items()}

    def list_facts(self, course_id):
        retry = aliased(SubmissionRow)
        understanding = exists(select(ExplanationCheckRow.id).where(
            ExplanationCheckRow.diagnosis_id == DiagnosisRow.id, ExplanationCheckRow.understands.is_(True),
            ExplanationCheckRow.confidence >= self._confidence_threshold,
            ExplanationCheckRow.created_at >= DiagnosisRow.created_at))
        full_hint = exists(select(HintEventRow.id).where(HintEventRow.diagnosis_id == DiagnosisRow.id,
            HintEventRow.current_level == 4, HintEventRow.created_at <= ExecutionResultRow.created_at).correlate(DiagnosisRow, ExecutionResultRow))
        successful_retry = exists(select(DiagnosisAttemptRow.attempt_key).select_from(DiagnosisAttemptRow)
            .join(retry, retry.id == DiagnosisAttemptRow.submission_id)
            .join(ExecutionResultRow, ExecutionResultRow.submission_id == retry.id)
            .where(DiagnosisAttemptRow.diagnosis_id == DiagnosisRow.id,
                retry.owner_user_id == SubmissionRow.owner_user_id, retry.course_id == SubmissionRow.course_id,
                retry.exercise_id == SubmissionRow.exercise_id, retry.created_at > SubmissionRow.created_at,
                ExecutionResultRow.status == "succeeded", ~full_hint).correlate(DiagnosisRow, SubmissionRow))
        query = select(DiagnosisRow.id, DiagnosisRow.course_id, SubmissionRow.owner_user_id,
            SubmissionRow.id, SubmissionRow.exercise_id, DiagnosisRow.category, DiagnosisRow.created_at,
            and_(understanding, successful_retry).label("repaired")).join(SubmissionRow,
                and_(SubmissionRow.id == DiagnosisRow.submission_id, SubmissionRow.course_id == DiagnosisRow.course_id,
                    SubmissionRow.owner_user_id == DiagnosisRow.owner_user_id)).where(DiagnosisRow.course_id == course_id)
        with self._read() as session:
            concepts = self._concepts(session, course_id)
            return tuple(AnalyticsDiagnosisFact(diagnosis_id=r.id, course_id=r.course_id,
                subject_key=subject_key(r.owner_user_id, r.course_id, self._secret), submission_id=r[3], exercise_id=r.exercise_id,
                category=r.category, concept_ids=concepts.get(r.id, ()), diagnosed_at=_aware(r.created_at), independent_repaired=bool(r.repaired))
                for r in session.execute(query).all())

    def _candidates(self, *, course_id=None, diagnosis_id=None):
        query = select(ReviewQueueEventRow.id, DiagnosisRow.id.label("diagnosis_id"), DiagnosisRow.course_id,
            SubmissionRow.id.label("submission_id"), SubmissionRow.exercise_id, DiagnosisRow.category,
            DiagnosisRow.confidence, ReviewQueueEventRow.created_at).select_from(ReviewQueueEventRow).join(DiagnosisRow,
                and_(DiagnosisRow.id == ReviewQueueEventRow.diagnosis_id,
                    DiagnosisRow.submission_id == ReviewQueueEventRow.submission_id,
                    DiagnosisRow.course_id == ReviewQueueEventRow.course_id,
                    DiagnosisRow.owner_user_id == ReviewQueueEventRow.owner_user_id)).join(SubmissionRow,
                and_(SubmissionRow.id == DiagnosisRow.submission_id, SubmissionRow.course_id == DiagnosisRow.course_id,
                    SubmissionRow.owner_user_id == DiagnosisRow.owner_user_id))
        if course_id is not None:
            query = query.where(DiagnosisRow.course_id == course_id)
        if diagnosis_id is not None:
            query = query.where(DiagnosisRow.id == diagnosis_id)
        with self._read() as session:
            rows = session.execute(query.order_by(ReviewQueueEventRow.created_at, ReviewQueueEventRow.id)).all()
            concepts = {course:self._concepts(session, course) for course in {r.course_id for r in rows}}
            result = []
            for r in rows:
                ids = concepts[r.course_id].get(r.diagnosis_id, ())
                evidence = self._knowledge.approved_evidence(r.course_id, ids)
                summaries = tuple(dict.fromkeys(item.explanation for item in evidence))
                result.append(TeacherReviewCandidate(queue_event_id=r.id, diagnosis_id=r.diagnosis_id, course_id=r.course_id,
                    submission_id=r.submission_id, exercise_id=r.exercise_id, category=r.category, concept_ids=ids,
                    root_cause="\n".join(summaries) if summaries else "证据不足，需教师复核。", evidence_summaries=summaries,
                    confidence=r.confidence, review_reason="evidence_requires_review", queued_at=_aware(r.created_at)))
            return tuple(result)

    def list_candidates(self, course_id):
        return self._candidates(course_id=course_id)

    def get_candidate(self, diagnosis_id):
        return next(iter(self._candidates(diagnosis_id=diagnosis_id)), None)

    def get_review(self, diagnosis_id):
        with self._read() as session:
            row = session.get(TeacherDiagnosisReviewRow, diagnosis_id)
            return TeacherDiagnosisReview(diagnosis_id=row.diagnosis_id, course_id=row.course_id,
                reviewer_user_id=row.reviewer_user_id, decision=row.decision, reason=row.reason,
                reviewed_at=_aware(row.reviewed_at)) if row is not None else None

    def save_review(self, review):
        session = self.uow.require_session()
        session.add(TeacherDiagnosisReviewRow(**review.model_dump()))
        session.flush()
        return review

    @contextmanager
    def transaction(self):
        try:
            with self.uow.transaction():
                yield
        except MemoryPersistenceError as error:
            raise AnalyticsPersistenceError("analytics storage unavailable") from error

    @contextmanager
    def review_claim(self, diagnosis_id):
        with self.transaction():
            self.uow.require_session().execute(select(DiagnosisRow.id).where(
                DiagnosisRow.id == diagnosis_id).with_for_update(key_share=True))
            yield
