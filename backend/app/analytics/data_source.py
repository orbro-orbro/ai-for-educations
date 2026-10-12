"""Development-only live projection over the existing domain repositories."""
from app.analytics.models import AnalyticsDiagnosisFact, TeacherReviewCandidate
from app.analytics.persistence import subject_key
from app.analytics.repository import InMemoryTeacherAnalyticsRepository


class InMemoryTeacherAnalyticsDataSource(InMemoryTeacherAnalyticsRepository):
    def __init__(self, submissions, diagnostics, knowledge, *, secret, confidence_threshold=.75):
        super().__init__()
        self._submissions = submissions
        self._diagnostics = diagnostics
        self._knowledge = knowledge
        self._secret = secret
        self._confidence_threshold = confidence_threshold

    def _submission(self, diagnosis):
        submission = self._submissions.get(diagnosis.submission_id)
        if submission is None or submission.course_id != diagnosis.course_id or submission.owner_user_id != diagnosis.owner_user_id:
            return None
        return submission

    def _repaired(self, diagnosis, original):
        checks = self._diagnostics.explanation_checks()
        if not any(c.diagnosis_id == diagnosis.diagnosis_id and c.understands and c.confidence >= self._confidence_threshold
                   and c.created_at >= diagnosis.created_at for c in checks):
            return False
        for sid in self._diagnostics.attempt_submission_ids(diagnosis.diagnosis_id):
            retry = self._submissions.get(sid)
            if retry is None or (retry.owner_user_id, retry.course_id, retry.exercise_id) != (original.owner_user_id, original.course_id, original.exercise_id) or retry.created_at <= original.created_at:
                continue
            result = self._submissions.execution_result(sid)
            if result is not None and result.status.value == "succeeded" and not any(h.current_level == 4 and h.created_at <= result.created_at for h in self._diagnostics.hint_events(diagnosis.diagnosis_id)):
                return True
        return False

    def list_facts(self, course_id):
        result = []
        for diagnosis in self._diagnostics.diagnoses():
            if diagnosis.course_id != course_id:
                continue
            submission = self._submission(diagnosis)
            if submission is None:
                continue
            result.append(AnalyticsDiagnosisFact(diagnosis_id=diagnosis.diagnosis_id, course_id=course_id,
                subject_key=subject_key(submission.owner_user_id, course_id, self._secret), submission_id=submission.submission_id,
                exercise_id=submission.exercise_id, category=diagnosis.category.value, concept_ids=diagnosis.concept_ids,
                diagnosed_at=diagnosis.created_at, independent_repaired=self._repaired(diagnosis, submission)))
        return tuple(result)

    def list_candidates(self, course_id):
        result = []
        for item in self._diagnostics.review_events():
            if item.course_id != course_id or item.diagnosis_id is None:
                continue
            diagnosis = self._diagnostics.get(item.diagnosis_id)
            if diagnosis is None or diagnosis.course_id != item.course_id or diagnosis.submission_id != item.submission_id or diagnosis.owner_user_id != item.owner_user_id:
                continue
            submission = self._submission(diagnosis)
            if submission is None:
                continue
            evidence = self._knowledge.approved_evidence(course_id, diagnosis.concept_ids)
            summaries = tuple(dict.fromkeys(e.explanation for e in evidence))
            result.append(TeacherReviewCandidate(queue_event_id=item.event_id, diagnosis_id=diagnosis.diagnosis_id,
                course_id=course_id, submission_id=submission.submission_id, exercise_id=submission.exercise_id,
                category=diagnosis.category.value, concept_ids=diagnosis.concept_ids,
                root_cause="\n".join(summaries) if summaries else "证据不足，需教师复核。", evidence_summaries=summaries,
                confidence=diagnosis.confidence, review_reason="evidence_requires_review", queued_at=item.created_at))
        return tuple(result)

    def get_candidate(self, diagnosis_id):
        diagnosis = self._diagnostics.get(diagnosis_id)
        if diagnosis is None:
            return None
        return next((item for item in self.list_candidates(diagnosis.course_id) if item.diagnosis_id == diagnosis_id), None)
