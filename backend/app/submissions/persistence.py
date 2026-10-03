from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
from typing import Iterable

from sqlalchemy import (
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.models import (
    Base,
    ExecutionResultRow,
    ExerciseRow,
    RuleMatchRelatedConceptRow,
    RuleMatchRow,
    SubmissionRow,
    SubmissionTransitionRow,
)
from app.submissions.models import (
    ExecutionResult,
    Submission,
    SubmissionStatus,
    SubmissionTransition,
    utc_now,
)
from app.submissions.repository import SubmissionPersistenceError
from app.diagnostics.rules import RuleMatch
from app.submissions.runner_contract import (
    CompilerDiagnostic,
    CommandSummary,
    RunnerLimits,
    RunnerPhase,
    RunnerStatus,
    SourceFile,
    ToolchainInfo,
)


def _translate_storage_errors(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except SubmissionPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise SubmissionPersistenceError("submission storage operation failed") from exc

    return wrapped


class SqlSubmissionRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    @_translate_storage_errors
    def create(
        self,
        *,
        submission_id: str,
        course_id: str,
        exercise_id: str,
        owner_user_id: str,
        source_files: Iterable[SourceFile | dict[str, str]],
        entrypoint: str,
        is_formal: bool,
        request_id: str,
    ) -> Submission:
        sources = tuple(
            item if isinstance(item, SourceFile) else SourceFile.model_validate(item)
            for item in source_files
        )
        created_at = utc_now()
        try:
            with self._sessions.begin() as session:
                exercise = session.get(ExerciseRow, exercise_id)
                if exercise is None or exercise.course_id != course_id:
                    raise ValueError("exercise does not belong to course")
                session.add(
                    SubmissionRow(
                        id=submission_id,
                        course_id=course_id,
                        exercise_id=exercise_id,
                        owner_user_id=owner_user_id,
                        source_files=[item.model_dump(mode="json") for item in sources],
                        entrypoint=entrypoint,
                        is_formal=is_formal,
                        status=SubmissionStatus.received.value,
                        created_at=created_at,
                        request_id=request_id,
                    )
                )
                session.add(
                    SubmissionTransitionRow(
                        submission_id=submission_id,
                        sequence=0,
                        from_status=None,
                        to_status=SubmissionStatus.received.value,
                        changed_at=created_at,
                        request_id=request_id,
                        reason="submission received",
                    )
                )
        except IntegrityError as exc:
            raise SubmissionPersistenceError("submission write failed") from exc
        return Submission(
            submission_id=submission_id,
            course_id=course_id,
            exercise_id=exercise_id,
            owner_user_id=owner_user_id,
            source_files=sources,
            entrypoint=entrypoint,
            is_formal=is_formal,
            status=SubmissionStatus.received,
            created_at=created_at,
            request_id=request_id,
        )

    @_translate_storage_errors
    def get(self, submission_id: str) -> Submission | None:
        with self._sessions() as session:
            row = session.get(SubmissionRow, submission_id)
            if row is None:
                return None
            return _submission(row)

    @_translate_storage_errors
    def transition(
        self,
        submission_id: str,
        to_status: SubmissionStatus,
        *,
        request_id: str,
        reason: str,
    ) -> Submission:
        with self._sessions.begin() as session:
            row = session.get(SubmissionRow, submission_id)
            if row is None:
                raise KeyError(submission_id)
            current = _submission(row)
            updated = current.transition_to(to_status)
            sequence = session.scalar(
                select(func.max(SubmissionTransitionRow.sequence)).where(
                    SubmissionTransitionRow.submission_id == submission_id
                )
            )
            changed_at = utc_now()
            row.status = updated.status.value
            session.add(
                SubmissionTransitionRow(
                    submission_id=submission_id,
                    sequence=int(sequence or 0) + 1,
                    from_status=current.status.value,
                    to_status=updated.status.value,
                    changed_at=changed_at,
                    request_id=request_id,
                    reason=reason,
                )
            )
        return updated

    @_translate_storage_errors
    def transitions(self, submission_id: str) -> tuple[SubmissionTransition, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(SubmissionTransitionRow)
                .where(SubmissionTransitionRow.submission_id == submission_id)
                .order_by(SubmissionTransitionRow.sequence)
            ).all()
            return tuple(
                SubmissionTransition(
                    submission_id=row.submission_id,
                    from_status=SubmissionStatus(row.from_status) if row.from_status else None,
                    to_status=SubmissionStatus(row.to_status),
                    changed_at=_aware_utc(row.changed_at),
                    request_id=row.request_id,
                    reason=row.reason,
                )
                for row in rows
            )

    @_translate_storage_errors
    def execution_result(self, submission_id: str) -> ExecutionResult | None:
        with self._sessions() as session:
            row = session.get(ExecutionResultRow, submission_id)
            if row is None:
                return None
            submission = session.get(SubmissionRow, submission_id)
            return ExecutionResult(
                submission_id=row.submission_id,
                course_id=submission.course_id,
                protocol_version=row.protocol_version,
                status=RunnerStatus(row.status),
                phase=RunnerPhase(row.phase),
                retryable=row.retryable,
                exit_code=row.exit_code,
                signal=row.signal,
                stdout=row.stdout,
                stderr=row.stderr,
                stdout_truncated=row.stdout_truncated,
                stderr_truncated=row.stderr_truncated,
                diagnostics=tuple(CompilerDiagnostic.model_validate(item) for item in row.diagnostics),
                command_summary=CommandSummary.model_validate(row.command_summary),
                limits=RunnerLimits.model_validate(row.limits),
                toolchain=ToolchainInfo.model_validate(row.toolchain),
                created_at=_aware_utc(row.created_at),
                request_id=row.request_id,
            )

    @_translate_storage_errors
    def rule_matches(self, submission_id: str) -> tuple[RuleMatch, ...]:
        submission = self.get(submission_id)
        if submission is None:
            return ()
        with self._sessions() as session:
            rows = session.scalars(
                select(RuleMatchRow)
                .where(RuleMatchRow.submission_id == submission_id)
                .order_by(RuleMatchRow.misconception_id)
            ).all()
            related_rows = session.scalars(
                select(RuleMatchRelatedConceptRow)
                .where(RuleMatchRelatedConceptRow.submission_id == submission_id)
                .order_by(
                    RuleMatchRelatedConceptRow.misconception_id,
                    RuleMatchRelatedConceptRow.ordinal,
                )
            ).all()
            related_by_misconception: dict[str, list[str]] = {}
            for related in related_rows:
                related_by_misconception.setdefault(
                    related.misconception_id, []
                ).append(related.concept_id)
            return tuple(
                RuleMatch(
                    course_id=row.course_id,
                    misconception_id=row.misconception_id,
                    root_concept_id=row.root_concept_id,
                    related_concept_ids=tuple(
                        related_by_misconception.get(row.misconception_id, ())
                    ),
                    diagnostic_indices=tuple(row.diagnostic_indices),
                    evidence_kind=row.evidence_kind,
                    evidence_summary=row.evidence_summary,
                    source_references=tuple(row.source_references),
                    match_strength=row.match_strength,
                )
                for row in rows
            )

    @_translate_storage_errors
    def complete_execution(
        self,
        result: ExecutionResult,
        matches: Iterable[RuleMatch],
        *,
        request_id: str,
        reason: str,
    ) -> Submission:
        match_values = tuple(matches)
        with self._sessions.begin() as session:
            submission_row = session.get(SubmissionRow, result.submission_id)
            if submission_row is None:
                raise KeyError(result.submission_id)
            current = _submission(submission_row)
            if current.course_id != result.course_id:
                raise ValueError("execution result course mismatch")
            if any(match.course_id != current.course_id for match in match_values):
                raise ValueError("rule match course mismatch")
            updated = current.transition_to(SubmissionStatus.executed)
            sequence = session.scalar(
                select(func.max(SubmissionTransitionRow.sequence)).where(
                    SubmissionTransitionRow.submission_id == result.submission_id
                )
            )
            changed_at = utc_now()
            session.add(
                ExecutionResultRow(
                    submission_id=result.submission_id,
                    protocol_version=result.protocol_version,
                    status=result.status.value,
                    phase=result.phase.value,
                    retryable=result.retryable,
                    exit_code=result.exit_code,
                    signal=result.signal,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    stdout_truncated=result.stdout_truncated,
                    stderr_truncated=result.stderr_truncated,
                    diagnostics=[item.model_dump(mode="json") for item in result.diagnostics],
                    command_summary=result.command_summary.model_dump(mode="json"),
                    limits=result.limits.model_dump(mode="json"),
                    toolchain=result.toolchain.model_dump(mode="json"),
                    created_at=result.created_at,
                    request_id=result.request_id,
                )
            )
            session.add_all(
                RuleMatchRow(
                    submission_id=result.submission_id,
                    course_id=match.course_id,
                    misconception_id=match.misconception_id,
                    root_concept_id=match.root_concept_id,
                    diagnostic_indices=list(match.diagnostic_indices),
                    evidence_kind=match.evidence_kind,
                    evidence_summary=match.evidence_summary,
                    source_references=list(match.source_references),
                    match_strength=match.match_strength,
                )
                for match in match_values
            )
            session.add_all(
                RuleMatchRelatedConceptRow(
                    submission_id=result.submission_id,
                    misconception_id=match.misconception_id,
                    ordinal=ordinal,
                    course_id=match.course_id,
                    concept_id=concept_id,
                )
                for match in match_values
                for ordinal, concept_id in enumerate(match.related_concept_ids)
            )
            submission_row.status = updated.status.value
            session.add(
                SubmissionTransitionRow(
                    submission_id=result.submission_id,
                    sequence=int(sequence or 0) + 1,
                    from_status=current.status.value,
                    to_status=updated.status.value,
                    changed_at=changed_at,
                    request_id=request_id,
                    reason=reason,
                )
            )
            session.flush()
        return updated


def create_sql_submission_repository(
    database_url: str, *, create_schema: bool = False
) -> SqlSubmissionRepository:
    engine = create_engine(database_url, pool_pre_ping=True)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    if create_schema:
        Base.metadata.create_all(engine)
    return SqlSubmissionRepository(sessionmaker(engine, expire_on_commit=False))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _submission(row: SubmissionRow) -> Submission:
    return Submission(
        submission_id=row.id,
        course_id=row.course_id,
        exercise_id=row.exercise_id,
        owner_user_id=row.owner_user_id,
        source_files=tuple(SourceFile.model_validate(item) for item in row.source_files),
        entrypoint=row.entrypoint,
        is_formal=row.is_formal,
        status=SubmissionStatus(row.status),
        created_at=_aware_utc(row.created_at),
        request_id=row.request_id,
    )
