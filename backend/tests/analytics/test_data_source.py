from tests.security.security_support import build_harness, PRIVATE_B, PRIVATE_OTHER_COURSE, NOW
from app.diagnostics.schema import ReviewQueueEvent


def test_development_projection_reads_current_diagnoses_and_safe_course_evidence():
    from app.analytics.data_source import InMemoryTeacherAnalyticsDataSource
    h = build_harness()
    source = InMemoryTeacherAnalyticsDataSource(h.state.submission_repository, h.state.diagnostic_repository, h.state.knowledge_repository, secret="test-secret")
    before = source.list_facts("course-a")
    assert before
    d = h.state.diagnostic_repository.get("diagnosis-a")
    h.state.diagnostic_repository.add_review_event(ReviewQueueEvent(event_id="new-queue", diagnosis_id=d.diagnosis_id, submission_id=d.submission_id,
        course_id=d.course_id, owner_user_id=d.owner_user_id, reason="PRIVATE_REASON", summary="PRIVATE_SUMMARY", created_at=NOW, request_id="new-queue"))
    candidates = source.list_candidates("course-a")
    assert len(candidates) == 1
    assert candidates[0].root_cause == "A match must cover all possible cases."
    assert "PRIVATE" not in repr(candidates)
    assert not source.list_candidates("course-b")
    assert all(f.course_id == "course-a" for f in before)
    assert PRIVATE_B not in repr(before) and PRIVATE_OTHER_COURSE not in repr(before)


def test_development_repair_requires_an_explicit_link_to_the_successful_retry():
    from dataclasses import replace
    from datetime import timedelta
    from app.analytics.data_source import InMemoryTeacherAnalyticsDataSource
    from app.submissions.models import SubmissionStatus
    from app.submissions.runner_contract import RunnerStatus
    h = build_harness()
    repo = h.state.submission_repository
    source = InMemoryTeacherAnalyticsDataSource(repo, h.state.diagnostic_repository, h.state.knowledge_repository, secret="test-secret")
    original = repo.get("submission-a")
    repo.create(submission_id="retry-a", course_id="course-a", exercise_id="exercise-a", owner_user_id="student-a",
        source_files=original.source_files, entrypoint="main.cj", is_formal=True, request_id="retry-a")
    repo.transition("retry-a", SubmissionStatus.executing, request_id="retry-a", reason="synthetic execution")
    result = replace(repo.execution_result("submission-a"), submission_id="retry-a", status=RunnerStatus.succeeded, created_at=original.created_at+timedelta(minutes=1))
    repo.complete_execution(result, (), request_id="retry-a", reason="synthetic success")
    assert not next(f for f in source.list_facts("course-a") if f.diagnosis_id == "diagnosis-a").independent_repaired
    h.state.diagnostic_repository.record_attempt("diagnosis-a", "retry-a")
    assert next(f for f in source.list_facts("course-a") if f.diagnosis_id == "diagnosis-a").independent_repaired
