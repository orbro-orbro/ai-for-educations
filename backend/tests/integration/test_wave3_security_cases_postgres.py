"""The three non-anonymity planned PG operations use real SQL authority."""
import pytest
from sqlalchemy import text, delete
from app.persistence.models import CourseAuthorizedTeacherRow
from app.main import create_app
from app.model_gateway.mock import DeterministicMockProvider
from tests.integration.wave3_support import Wave3PG, SECRET, postgres_url, upgrade
from tests.integration.test_task7_deletion_recovery import test_pending_deletion_survives_two_restarts_and_stays_redacted as restart_operation

@pytest.mark.parametrize('case_id',['sec-cross-role-002','sec-cross-role-008','sec-deletion-recovery-005'])
def test_concrete_postgres_operation(case_id,monkeypatch,record_property):
    record_property('case_id',case_id)
    if case_id=='sec-deletion-recovery-005':
        upgrade('wave3_task7')
        monkeypatch.setenv('TASK7_POSTGRES_URL',postgres_url('wave3_task7'))
        restart_operation()
        return
    pg=Wave3PG()
    try:
        pg.seed_diagnoses()
        monkeypatch.setenv('APP_ENV','test');monkeypatch.setenv('AUTH_TOKEN_SECRET',SECRET)
        monkeypatch.setenv('DATABASE_URL',postgres_url())
        pg.application=create_app(model_provider=DeterministicMockProvider())
        if case_id.endswith('002'):
            r=pg.post_review(actor='synthetic-student-0')
            with pg.sessions() as s:
                assert s.scalar(text('select count(*) from teacher_diagnosis_reviews'))==0
                assert s.scalar(text("select count(*) from audit_events where event_type='teacher_diagnosis_review'"))==0
        else:
            with pg.sessions.begin() as s:
                s.execute(delete(CourseAuthorizedTeacherRow).where(CourseAuthorizedTeacherRow.course_id=='course-a',CourseAuthorizedTeacherRow.teacher_id=='teacher-b'))
            r=pg.request('GET','/teacher/courses/course-a/analytics',actor='teacher-b')
        assert r.status_code==404 and r.json()['code']=='RESOURCE_NOT_AVAILABLE'
        assert set(r.json())=={'code','message','request_id'}
        record_property('actual_status',r.status_code)
    finally:
        pg.close()
        if pg.application:pg.application.state.memory_audit._uow.sessions.kw['bind'].dispose()
