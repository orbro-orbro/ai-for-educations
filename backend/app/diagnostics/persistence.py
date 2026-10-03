from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from threading import Lock, RLock

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.diagnostics.repository import DiagnosticPersistenceError
from app.diagnostics.schema import (
    ApprovedKnowledgeEvidence,
    CompilerDiagnosticEvidence,
    Diagnosis,
    DiagnosisCategory,
    DiagnosisLocation,
    ExplanationCheck,
    HintEvent,
    ReviewQueueEvent,
    RuleMatchEvidence,
)
from app.persistence.models import (
    DiagnosisAttemptRow,
    DiagnosisConceptRow,
    DiagnosisRow,
    DiagnosisRunResultRow,
    EvidenceBindingRow,
    ExplanationCheckRow,
    HintEventRow,
    MisconceptionRow,
    ReviewQueueEventRow,
)
from app.submissions.models import utc_now


class SqlDiagnosticRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._active_session: ContextVar[Session | None] = ContextVar(
            "diagnostic_session", default=None
        )
        self._lock = Lock()
        self._diagnosis_locks: dict[str, RLock] = {}
        self._hint_locks: dict[str, RLock] = {}

    def _named_lock(self, collection: dict[str, RLock], key: str) -> RLock:
        with self._lock:
            return collection.setdefault(key, RLock())

    @contextmanager
    def diagnosis_claim(self, submission_id: str):
        with self._named_lock(self._diagnosis_locks, submission_id):
            yield

    @contextmanager
    def hint_claim(self, diagnosis_id: str):
        with self._named_lock(self._hint_locks, diagnosis_id):
            try:
                with self._sessions.begin() as session:
                    row = session.scalar(
                        select(DiagnosisRow)
                        .where(DiagnosisRow.id == diagnosis_id)
                        .with_for_update()
                    )
                    if row is None:
                        yield
                        return
                    token = self._active_session.set(session)
                    try:
                        yield
                    finally:
                        self._active_session.reset(token)
            except DiagnosticPersistenceError:
                raise
            except SQLAlchemyError as exc:
                raise DiagnosticPersistenceError(
                    "diagnostic storage operation failed"
                ) from exc

    @contextmanager
    def _read(self):
        active = self._active_session.get()
        if active is not None:
            yield active
        else:
            with self._sessions() as session:
                yield session

    @contextmanager
    def _write(self):
        active = self._active_session.get()
        if active is not None:
            yield active
        else:
            with self._sessions.begin() as session:
                yield session

    def save_diagnosis(self, diagnosis: Diagnosis) -> Diagnosis:
        existing = self.get_for_submission(diagnosis.submission_id)
        if existing is not None:
            return existing
        try:
            with self._write() as session:
                session.add(
                    DiagnosisRow(
                        id=diagnosis.diagnosis_id,
                        submission_id=diagnosis.submission_id,
                        course_id=diagnosis.course_id,
                        owner_user_id=diagnosis.owner_user_id,
                        category=diagnosis.category.value,
                        locations=[item.model_dump(mode="json") for item in diagnosis.locations],
                        root_cause=diagnosis.root_cause,
                        confidence=diagnosis.confidence,
                        recommended_hint_level=diagnosis.recommended_hint_level,
                        requires_teacher_review=diagnosis.requires_teacher_review,
                        created_at=diagnosis.created_at,
                        request_id=diagnosis.request_id,
                    )
                )
                session.flush()
                session.add_all(
                    DiagnosisConceptRow(
                        diagnosis_id=diagnosis.diagnosis_id,
                        course_id=diagnosis.course_id,
                        concept_id=concept_id,
                        ordinal=ordinal,
                    )
                    for ordinal, concept_id in enumerate(diagnosis.concept_ids)
                )
                for ordinal, evidence in enumerate(diagnosis.evidence):
                    if isinstance(evidence, ApprovedKnowledgeEvidence):
                        approved = session.scalar(
                            select(MisconceptionRow).where(
                                MisconceptionRow.course_id == diagnosis.course_id,
                                MisconceptionRow.id == evidence.misconception_id,
                                MisconceptionRow.review_status == "approved",
                            )
                        )
                        if approved is None:
                            raise DiagnosticPersistenceError(
                                "diagnostic storage operation failed"
                            )
                    session.add(_evidence_row(diagnosis, evidence, ordinal))
                session.flush()
        except DiagnosticPersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            raise DiagnosticPersistenceError(
                "diagnostic storage operation failed"
            ) from exc
        return diagnosis

    def get(self, diagnosis_id: str) -> Diagnosis | None:
        try:
            with self._read() as session:
                row = session.get(DiagnosisRow, diagnosis_id)
                return self._load_diagnosis(session, row) if row else None
        except SQLAlchemyError as exc:
            raise DiagnosticPersistenceError("diagnostic storage operation failed") from exc

    def get_for_submission(self, submission_id: str) -> Diagnosis | None:
        try:
            with self._read() as session:
                row = session.scalar(
                    select(DiagnosisRow).where(DiagnosisRow.submission_id == submission_id)
                )
                return self._load_diagnosis(session, row) if row else None
        except SQLAlchemyError as exc:
            raise DiagnosticPersistenceError("diagnostic storage operation failed") from exc

    def diagnoses(self) -> tuple[Diagnosis, ...]:
        with self._read() as session:
            rows = session.scalars(select(DiagnosisRow).order_by(DiagnosisRow.id)).all()
            return tuple(self._load_diagnosis(session, row) for row in rows)

    def _load_diagnosis(self, session: Session, row: DiagnosisRow) -> Diagnosis:
        concepts = session.scalars(
            select(DiagnosisConceptRow)
            .where(DiagnosisConceptRow.diagnosis_id == row.id)
            .order_by(DiagnosisConceptRow.ordinal)
        ).all()
        evidence_rows = session.scalars(
            select(EvidenceBindingRow)
            .where(EvidenceBindingRow.diagnosis_id == row.id)
            .order_by(EvidenceBindingRow.ordinal)
        ).all()
        return Diagnosis(
            diagnosis_id=row.id,
            submission_id=row.submission_id,
            course_id=row.course_id,
            owner_user_id=row.owner_user_id,
            category=DiagnosisCategory(row.category),
            locations=tuple(DiagnosisLocation.model_validate(item) for item in row.locations),
            concept_ids=tuple(item.concept_id for item in concepts),
            root_cause=row.root_cause,
            evidence=tuple(_evidence(item) for item in evidence_rows),
            confidence=row.confidence,
            recommended_hint_level=row.recommended_hint_level,
            requires_teacher_review=row.requires_teacher_review,
            created_at=_utc(row.created_at),
            request_id=row.request_id,
        )

    def add_review_event(self, event: ReviewQueueEvent) -> ReviewQueueEvent:
        existing = self._review_event(event.submission_id, event.request_id)
        if existing is not None:
            return existing
        try:
            with self._write() as session:
                session.add(
                    ReviewQueueEventRow(
                        id=event.event_id,
                        submission_id=event.submission_id,
                        diagnosis_id=event.diagnosis_id,
                        course_id=event.course_id,
                        owner_user_id=event.owner_user_id,
                        reason=event.reason,
                        summary=event.summary,
                        created_at=event.created_at,
                        request_id=event.request_id,
                    )
                )
                session.flush()
        except SQLAlchemyError as exc:
            raise DiagnosticPersistenceError("diagnostic storage operation failed") from exc
        return event

    def _review_event(self, submission_id: str, request_id: str):
        with self._read() as session:
            row = session.scalar(
                select(ReviewQueueEventRow).where(
                    ReviewQueueEventRow.submission_id == submission_id,
                    ReviewQueueEventRow.request_id == request_id,
                )
            )
            return _review(row) if row else None

    def review_events(self) -> tuple[ReviewQueueEvent, ...]:
        with self._read() as session:
            rows = session.scalars(
                select(ReviewQueueEventRow).order_by(ReviewQueueEventRow.created_at)
            ).all()
            return tuple(_review(row) for row in rows)

    def add_hint_event(self, event: HintEvent) -> HintEvent:
        existing = next(
            (item for item in self.hint_events(event.diagnosis_id) if item.request_id == event.request_id),
            None,
        )
        if existing is not None:
            return existing
        try:
            with self._write() as session:
                session.add(
                    HintEventRow(
                        id=event.hint_event_id,
                        diagnosis_id=event.diagnosis_id,
                        previous_level=event.previous_level,
                        current_level=event.current_level,
                        reason=event.reason,
                        previous_attempt_count=event.previous_attempt_count,
                        content=event.content,
                        used_safe_fallback=event.used_safe_fallback,
                        created_at=event.created_at,
                        request_id=event.request_id,
                    )
                )
                session.flush()
        except SQLAlchemyError as exc:
            raise DiagnosticPersistenceError("diagnostic storage operation failed") from exc
        return event

    def hint_events(self, diagnosis_id: str) -> tuple[HintEvent, ...]:
        with self._read() as session:
            rows = session.scalars(
                select(HintEventRow)
                .where(HintEventRow.diagnosis_id == diagnosis_id)
                .order_by(HintEventRow.current_level)
            ).all()
            return tuple(_hint(row) for row in rows)

    def record_attempt(self, diagnosis_id: str, attempt_key: str | None = None) -> int:
        key = attempt_key or f"manual:{self.attempt_count(diagnosis_id) + 1}"
        try:
            with self._write() as session:
                existing = session.get(DiagnosisAttemptRow, (diagnosis_id, key))
                if existing is None:
                    session.add(
                        DiagnosisAttemptRow(
                            diagnosis_id=diagnosis_id,
                            attempt_key=key,
                            submission_id=attempt_key if attempt_key and not attempt_key.startswith("manual:") else None,
                            created_at=utc_now(),
                        )
                    )
                    session.flush()
                return int(
                    session.scalar(
                        select(func.count()).select_from(DiagnosisAttemptRow).where(
                            DiagnosisAttemptRow.diagnosis_id == diagnosis_id
                        )
                    )
                    or 0
                )
        except SQLAlchemyError as exc:
            raise DiagnosticPersistenceError("diagnostic storage operation failed") from exc

    def attempt_count(self, diagnosis_id: str) -> int:
        with self._read() as session:
            return int(
                session.scalar(
                    select(func.count()).select_from(DiagnosisAttemptRow).where(
                        DiagnosisAttemptRow.diagnosis_id == diagnosis_id
                    )
                )
                or 0
            )

    def get_explanation(self, diagnosis_id: str, request_id: str) -> ExplanationCheck | None:
        with self._read() as session:
            row = session.scalar(
                select(ExplanationCheckRow).where(
                    ExplanationCheckRow.diagnosis_id == diagnosis_id,
                    ExplanationCheckRow.request_id == request_id,
                )
            )
            return _explanation(row) if row else None

    def add_explanation(self, result: ExplanationCheck) -> ExplanationCheck:
        existing = self.get_explanation(result.diagnosis_id, result.request_id)
        if existing is not None:
            return existing
        try:
            with self._write() as session:
                session.add(
                    ExplanationCheckRow(
                        id=result.explanation_check_id,
                        diagnosis_id=result.diagnosis_id,
                        understands=result.understands,
                        concept_ids=list(result.concept_ids),
                        evidence_summary=result.evidence_summary,
                        confidence=result.confidence,
                        feedback=result.feedback,
                        memory_proposal_eligible=result.memory_proposal_eligible,
                        created_at=result.created_at,
                        request_id=result.request_id,
                    )
                )
                session.flush()
        except SQLAlchemyError as exc:
            raise DiagnosticPersistenceError("diagnostic storage operation failed") from exc
        return result

    def explanation_checks(self) -> tuple[ExplanationCheck, ...]:
        with self._read() as session:
            rows = session.scalars(
                select(ExplanationCheckRow).order_by(ExplanationCheckRow.created_at)
            ).all()
            return tuple(_explanation(row) for row in rows)

    def get_run_result(self, submission_id: str, request_id: str):
        with self._read() as session:
            row = session.get(DiagnosisRunResultRow, (submission_id, request_id))
            if row is None:
                return None
            if row.result_kind == "evidence_unavailable":
                from app.diagnostics.service import ExecutionEvidenceUnavailable

                return ExecutionEvidenceUnavailable(row.error_message or "evidence unavailable")
            from app.diagnostics.service import DiagnosisRunResult

            diagnosis = self.get(row.diagnosis_id) if row.diagnosis_id else None
            review = (
                session.get(ReviewQueueEventRow, row.review_event_id)
                if row.review_event_id
                else None
            )
            return DiagnosisRunResult(diagnosis, _review(review) if review else None)

    def save_run_result(self, submission_id: str, request_id: str, result) -> None:
        if self.get_run_result(submission_id, request_id) is not None:
            return
        from app.diagnostics.service import DiagnosisRunResult, ExecutionEvidenceUnavailable

        if isinstance(result, ExecutionEvidenceUnavailable):
            kind, diagnosis_id, review_id, message = "evidence_unavailable", None, None, str(result)
        elif isinstance(result, DiagnosisRunResult):
            kind = "diagnosis" if result.diagnosis and not result.review_event else "review"
            diagnosis_id = result.diagnosis.diagnosis_id if result.diagnosis else None
            review_id = result.review_event.event_id if result.review_event else None
            message = None
        else:
            raise TypeError("unsupported diagnosis run result")
        try:
            with self._write() as session:
                session.add(
                    DiagnosisRunResultRow(
                        submission_id=submission_id,
                        request_id=request_id,
                        result_kind=kind,
                        diagnosis_id=diagnosis_id,
                        review_event_id=review_id,
                        error_message=message,
                        created_at=utc_now(),
                    )
                )
                session.flush()
        except SQLAlchemyError as exc:
            raise DiagnosticPersistenceError("diagnostic storage operation failed") from exc


def _evidence_row(diagnosis: Diagnosis, evidence, ordinal: int) -> EvidenceBindingRow:
    return EvidenceBindingRow(
        diagnosis_id=diagnosis.diagnosis_id,
        ordinal=ordinal,
        course_id=diagnosis.course_id,
        kind=evidence.kind,
        summary=evidence.summary,
        diagnostic_index=(evidence.diagnostic_index if isinstance(evidence, CompilerDiagnosticEvidence) else None),
        rule_submission_id=(diagnosis.submission_id if isinstance(evidence, RuleMatchEvidence) else None),
        misconception_id=(evidence.misconception_id if isinstance(evidence, (RuleMatchEvidence, ApprovedKnowledgeEvidence)) else None),
        source_reference=(evidence.source_reference if isinstance(evidence, ApprovedKnowledgeEvidence) else None),
    )


def _evidence(row: EvidenceBindingRow):
    data = {"kind": row.kind, "summary": row.summary}
    if row.kind == "compiler_diagnostic":
        data["diagnostic_index"] = row.diagnostic_index
        return CompilerDiagnosticEvidence.model_validate(data)
    data["misconception_id"] = row.misconception_id
    if row.kind == "approved_knowledge":
        data["source_reference"] = row.source_reference
        return ApprovedKnowledgeEvidence.model_validate(data)
    return RuleMatchEvidence.model_validate(data)


def _review(row: ReviewQueueEventRow) -> ReviewQueueEvent:
    return ReviewQueueEvent(
        event_id=row.id,
        submission_id=row.submission_id,
        diagnosis_id=row.diagnosis_id,
        course_id=row.course_id,
        owner_user_id=row.owner_user_id,
        reason=row.reason,
        summary=row.summary,
        created_at=_utc(row.created_at),
        request_id=row.request_id,
    )


def _hint(row: HintEventRow) -> HintEvent:
    return HintEvent(
        hint_event_id=row.id,
        diagnosis_id=row.diagnosis_id,
        previous_level=row.previous_level,
        current_level=row.current_level,
        reason=row.reason,
        previous_attempt_count=row.previous_attempt_count,
        content=row.content,
        used_safe_fallback=row.used_safe_fallback,
        created_at=_utc(row.created_at),
        request_id=row.request_id,
    )


def _explanation(row: ExplanationCheckRow) -> ExplanationCheck:
    return ExplanationCheck(
        explanation_check_id=row.id,
        diagnosis_id=row.diagnosis_id,
        understands=row.understands,
        concept_ids=tuple(row.concept_ids),
        evidence_summary=row.evidence_summary,
        confidence=row.confidence,
        feedback=row.feedback,
        memory_proposal_eligible=row.memory_proposal_eligible,
        created_at=_utc(row.created_at),
        request_id=row.request_id,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
