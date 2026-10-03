from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from pydantic import ValidationError

from app.auth.models import Actor, Role
from app.courses.service import ResourceNotAvailable
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.diagnostics.schema import (
    Diagnosis,
    DiagnosisValidationContext,
    ExplanationCheck,
    ReviewQueueEvent,
    validate_diagnosis_output,
)
from app.model_gateway.base import (
    ApprovedKnowledgeContext,
    CompilerDiagnosticContext,
    DiagnosisRequest,
    ExecutionContext,
    ExplanationCheckRequest,
    ExplanationModelOutput,
    ModelProvider,
    ProviderFailure,
    ProviderTimeout,
    RuleMatchContext,
    SourceContext,
)
from app.submissions.models import SubmissionStatus, utc_now


class ExecutionEvidenceUnavailable(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class DiagnosisRunResult:
    diagnosis: Diagnosis | None
    review_event: ReviewQueueEvent | None


class DiagnosisService:
    def __init__(
        self,
        *,
        submissions,
        knowledge,
        repository: InMemoryDiagnosticRepository,
        provider: ModelProvider,
        access,
        confidence_threshold: float,
        max_provider_retries: int = 1,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence threshold must be in [0,1]")
        if max_provider_retries < 0:
            raise ValueError("max_provider_retries must not be negative")
        self._submissions = submissions
        self._knowledge = knowledge
        self._repository = repository
        self._provider = provider
        self._access = access
        self._threshold = confidence_threshold
        self._max_provider_retries = max_provider_retries
        self._id_factory = id_factory

    def diagnose(
        self,
        submission_id: str,
        *,
        request_id: str,
        exercise_context: str = "",
    ) -> DiagnosisRunResult:
        with self._repository.diagnosis_claim(submission_id):
            return self._diagnose_locked(
                submission_id,
                request_id=request_id,
                exercise_context=exercise_context,
            )

    def _diagnose_locked(
        self,
        submission_id: str,
        *,
        request_id: str,
        exercise_context: str,
    ) -> DiagnosisRunResult:
        prior_run = self._repository.get_run_result(submission_id, request_id)
        if isinstance(prior_run, ExecutionEvidenceUnavailable):
            raise ExecutionEvidenceUnavailable(str(prior_run))
        if prior_run is not None:
            return prior_run
        existing = self._repository.get_for_submission(submission_id)
        if existing is not None:
            return DiagnosisRunResult(existing, None)

        submission = self._submissions.get(submission_id)
        execution = self._submissions.execution_result(submission_id)
        if (
            submission is None
            or execution is None
            or submission.status is SubmissionStatus.execution_unavailable
        ):
            failure = ExecutionEvidenceUnavailable(
                "real execution evidence is unavailable"
            )
            if submission is not None:
                event = self._review_event(
                    submission=submission,
                    request_id=request_id,
                    reason="execution_evidence_unavailable",
                    diagnosis_id=None,
                )
            self._repository.save_run_result(submission_id, request_id, failure)
            raise failure
        if submission.status not in {SubmissionStatus.executed, SubmissionStatus.needs_review}:
            raise ExecutionEvidenceUnavailable("submission is not ready for diagnosis")

        self._submissions.transition(
            submission_id,
            SubmissionStatus.diagnosing,
            request_id=request_id,
            reason="evidence-bound diagnosis started",
        )
        approved = tuple(self._knowledge.approved_evidence(submission.course_id))
        if not approved:
            return self._finish_review(
                submission=submission,
                request_id=request_id,
                reason="no_approved_evidence",
                diagnosis=None,
            )

        rule_matches = tuple(self._submissions.rule_matches(submission_id))
        request = _diagnosis_request(
            submission, execution, rule_matches, approved, exercise_context
        )
        context = DiagnosisValidationContext.from_records(
            submission=submission,
            execution=execution,
            rule_matches=rule_matches,
            approved_evidence=approved,
        )
        candidate = None
        failure_reason = "invalid_provider_response"
        for _attempt in range(self._max_provider_retries + 1):
            try:
                raw = self._provider.generate_diagnosis(request)
                candidate = validate_diagnosis_output(raw, context)
                break
            except ProviderTimeout:
                failure_reason = "provider_timeout"
            except ProviderFailure:
                failure_reason = "provider_failure"
            except (ValidationError, ValueError, TypeError):
                failure_reason = "invalid_provider_response"
        if candidate is None:
            return self._finish_review(
                submission=submission,
                request_id=request_id,
                reason=failure_reason,
                diagnosis=None,
            )

        requires_review = candidate.confidence < self._threshold
        diagnosis = Diagnosis(
            diagnosis_id=self._id_factory(),
            submission_id=submission.submission_id,
            course_id=submission.course_id,
            owner_user_id=submission.owner_user_id,
            **candidate.model_dump(),
            requires_teacher_review=requires_review,
            created_at=utc_now(),
            request_id=request_id,
        )
        diagnosis = self._repository.save_diagnosis(diagnosis)
        if requires_review:
            return self._finish_review(
                submission=submission,
                request_id=request_id,
                reason="low_confidence",
                diagnosis=diagnosis,
            )
        self._submissions.transition(
            submission_id,
            SubmissionStatus.diagnosed,
            request_id=request_id,
            reason="validated evidence-bound diagnosis completed",
        )
        result = DiagnosisRunResult(diagnosis, None)
        self._repository.save_run_result(submission_id, request_id, result)
        return result

    def get_diagnosis(self, actor: Actor, submission_id: str) -> Diagnosis:
        submission = self._submissions.get(submission_id)
        diagnosis = self._repository.get_for_submission(submission_id)
        if (
            submission is None
            or diagnosis is None
            or actor.role is not Role.STUDENT
            or actor.user_id != submission.owner_user_id
            or diagnosis.course_id != submission.course_id
            or diagnosis.owner_user_id != submission.owner_user_id
        ):
            raise ResourceNotAvailable()
        self._access.require_read(actor, submission)
        return diagnosis

    def check_explanation(
        self,
        actor: Actor,
        diagnosis_id: str,
        explanation: str,
        *,
        request_id: str,
    ) -> ExplanationCheck:
        diagnosis = self._owned_diagnosis(actor, diagnosis_id)
        existing = self._repository.get_explanation(diagnosis_id, request_id)
        if existing is not None:
            return existing
        if diagnosis.requires_teacher_review or diagnosis.confidence < self._threshold:
            return self._save_ineligible_explanation(
                diagnosis,
                request_id,
                "Diagnosis needs review before an explanation can qualify.",
            )
        approved = tuple(
            self._knowledge.approved_evidence(
                diagnosis.course_id, concept_ids=diagnosis.concept_ids
            )
        )
        approved_concepts = {
            concept_id
            for item in approved
            for concept_id in (item.root_concept_id, *item.related_concept_ids)
        }
        if not approved or not set(diagnosis.concept_ids) <= approved_concepts:
            return self._save_ineligible_explanation(
                diagnosis, request_id, "Approved diagnosis evidence is unavailable."
            )
        request = ExplanationCheckRequest(
            category=diagnosis.category.value,
            root_cause=diagnosis.root_cause,
            diagnosis_concept_ids=diagnosis.concept_ids,
            approved_concept_ids=tuple(sorted(approved_concepts)),
            explanation=explanation,
        )
        try:
            raw = self._provider.check_explanation(request)
            output = (
                raw
                if isinstance(raw, ExplanationModelOutput)
                else ExplanationModelOutput.model_validate(raw)
            )
        except (ProviderTimeout, ProviderFailure, ValidationError, ValueError, TypeError):
            return self._save_ineligible_explanation(
                diagnosis, request_id, "The explanation could not be verified safely."
            )
        concepts_valid = bool(output.concept_ids) and set(output.concept_ids) <= (
            set(diagnosis.concept_ids) & approved_concepts
        )
        understands = output.understands and concepts_valid
        eligible = understands and output.confidence >= self._threshold
        result = ExplanationCheck(
            explanation_check_id=self._id_factory(),
            diagnosis_id=diagnosis_id,
            understands=understands,
            concept_ids=output.concept_ids if concepts_valid else (),
            evidence_summary=output.evidence_summary,
            confidence=output.confidence,
            feedback=output.feedback,
            memory_proposal_eligible=eligible,
            created_at=utc_now(),
            request_id=request_id,
        )
        return self._repository.add_explanation(result)

    def _owned_diagnosis(self, actor: Actor, diagnosis_id: str) -> Diagnosis:
        diagnosis = self._repository.get(diagnosis_id)
        submission = (
            self._submissions.get(diagnosis.submission_id) if diagnosis is not None else None
        )
        if (
            diagnosis is None
            or submission is None
            or actor.role is not Role.STUDENT
            or actor.user_id != submission.owner_user_id
            or diagnosis.owner_user_id != submission.owner_user_id
            or diagnosis.course_id != submission.course_id
        ):
            raise ResourceNotAvailable()
        self._access.require_read(actor, submission)
        return diagnosis

    def _save_ineligible_explanation(
        self, diagnosis: Diagnosis, request_id: str, feedback: str
    ) -> ExplanationCheck:
        return self._repository.add_explanation(
            ExplanationCheck(
                explanation_check_id=self._id_factory(),
                diagnosis_id=diagnosis.diagnosis_id,
                understands=False,
                concept_ids=(),
                evidence_summary="No qualifying evidence-bound understanding was verified.",
                confidence=0,
                feedback=feedback,
                memory_proposal_eligible=False,
                created_at=utc_now(),
                request_id=request_id,
            )
        )

    def _finish_review(
        self, *, submission, request_id: str, reason: str, diagnosis: Diagnosis | None
    ) -> DiagnosisRunResult:
        event = self._review_event(
            submission=submission,
            request_id=request_id,
            reason=reason,
            diagnosis_id=diagnosis.diagnosis_id if diagnosis else None,
        )
        self._submissions.transition(
            submission.submission_id,
            SubmissionStatus.needs_review,
            request_id=request_id,
            reason=f"diagnosis requires review: {reason}",
        )
        result = DiagnosisRunResult(diagnosis, event)
        self._repository.save_run_result(submission.submission_id, request_id, result)
        return result

    def _review_event(
        self, *, submission, request_id: str, reason: str, diagnosis_id: str | None
    ) -> ReviewQueueEvent:
        return self._repository.add_review_event(
            ReviewQueueEvent(
                event_id=self._id_factory(),
                submission_id=submission.submission_id,
                diagnosis_id=diagnosis_id,
                course_id=submission.course_id,
                owner_user_id=submission.owner_user_id,
                reason=reason,
                summary="Diagnosis requires authorized review; private source is omitted.",
                created_at=utc_now(),
                request_id=request_id,
            )
        )


def _diagnosis_request(submission, execution, rule_matches, approved, exercise_context):
    return DiagnosisRequest(
        source_files=tuple(
            SourceContext(path=item.path, content=item.content)
            for item in submission.source_files
        ),
        execution=ExecutionContext(
            status=execution.status.value,
            phase=execution.phase.value,
            retryable=execution.retryable,
            exit_code=execution.exit_code,
            diagnostics=tuple(
                CompilerDiagnosticContext(
                    severity=item.severity,
                    message=item.message,
                    code=item.code,
                    file=item.file,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
                for item in execution.diagnostics
            ),
            toolchain_cjc=execution.toolchain.cjc,
        ),
        rule_matches=tuple(
            RuleMatchContext(
                misconception_id=item.misconception_id,
                root_concept_id=item.root_concept_id,
                related_concept_ids=item.related_concept_ids,
                diagnostic_indices=item.diagnostic_indices,
                evidence_summary=item.evidence_summary,
                source_references=item.source_references,
                match_strength=item.match_strength,
            )
            for item in rule_matches
        ),
        knowledge=tuple(
            ApprovedKnowledgeContext(
                misconception_id=item.misconception_id,
                root_concept_id=item.root_concept_id,
                related_concept_ids=item.related_concept_ids,
                explanation=item.explanation,
                source_references=tuple(item.source.references),
                hint_outlines=tuple(step.outline for step in item.hint_ladder),
            )
            for item in approved
        ),
        exercise_context=exercise_context,
    )
