"""Official application, actual SQL audit commits and fail-closed teacher GETs."""
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.main import create_app
from app.model_gateway.mock import DeterministicMockProvider
from app.persistence.models import AuditEventRow
from app.persistence.repositories import create_sql_repositories
from tests.integration.wave3_support import Wave3PG, postgres_url, SECRET, PRIVATE


@pytest.fixture
def pg(monkeypatch):
    value = Wave3PG()
    monkeypatch.setenv('DATABASE_URL', postgres_url())
    monkeypatch.setenv('AUTH_TOKEN_SECRET', SECRET)
    monkeypatch.setenv('APP_ENV', 'test')
    yield value
    value.close()


def mount(pg, read):
    pg.seed_diagnoses(students=4 if read == 'suppressed' else 5)
    pg.application = create_app(model_provider=DeterministicMockProvider())
    return pg.application.state.teacher_analytics_repository.uow.sessions


def request(pg, read, **kwargs):
    return pg.request('GET', '/teacher/courses/course-a/' + ('review-queue' if read == 'queue' else 'analytics'),
        headers={'X-Request-ID': 'synthetic-read-audit-' + read}, **kwargs)


def read_events(sessions):
    with sessions() as session:
        return session.scalars(select(AuditEventRow).where(AuditEventRow.event_type.in_(
            ['teacher_review_queue_read', 'teacher_course_analytics_read']))).all()


@pytest.mark.parametrize('read', ['queue', 'available', 'suppressed'])
def test_teacher_get_audit_is_committed_metadata_and_visible_to_a_fresh_instance(pg, read, caplog):
    sessions = mount(pg, read)
    response = request(pg, read)
    assert response.status_code == 200
    expected = 'teacher_review_queue_read' if read == 'queue' else 'teacher_course_analytics_read'
    rows = read_events(sessions)
    assert len(rows) == 1
    row = rows[0]
    assert (row.event_type, row.actor_user_id, row.actor_role, row.target_type, row.target_id,
            row.owner_user_id, row.course_id, row.outcome, row.request_id) == (
        expected, 'teacher-a', 'teacher', 'course', 'course-a', '', 'course-a', 'success', 'synthetic-read-audit-' + read)
    fresh = create_sql_repositories(postgres_url())
    try:
        assert len([e for e in fresh.audit.events() if e.event_type == expected]) == 1
        rendered = fresh.audit.serialized_events()
        assert PRIVATE not in rendered + caplog.text
        assert not any(f.subject_key in rendered for f in pg.application.state.teacher_analytics_repository.list_facts('course-a'))
    finally:
        fresh.memory_uow.sessions.kw['bind'].dispose()
        sessions.kw['bind'].dispose()


@pytest.mark.parametrize('read', ['queue', 'available', 'suppressed'])
@pytest.mark.parametrize('failure', ['flush', 'commit'])
def test_teacher_get_returns_only_sanitized_503_if_audit_flush_or_commit_fails(pg, read, failure, caplog):
    sessions = mount(pg, read)
    def fail_flush(session, *_):
        if any(isinstance(row, AuditEventRow) for row in session.new):
            raise OperationalError('synthetic audit insert', {}, RuntimeError('PRIVATE_AUDIT_FAILURE'))
    def fail_commit(_session):
        raise OperationalError('synthetic audit commit', {}, RuntimeError('PRIVATE_AUDIT_FAILURE'))
    name, callback = ('before_flush', fail_flush) if failure == 'flush' else ('before_commit', fail_commit)
    event.listen(sessions, name, callback)
    try:
        response = request(pg, read)
    finally:
        event.remove(sessions, name, callback)
    assert response.status_code == 503
    assert set(response.json()) == {'code', 'message', 'request_id'}
    assert response.json()['code'] == 'STORAGE_UNAVAILABLE'
    assert response.json()['request_id'] == 'synthetic-read-audit-' + read
    assert PRIVATE not in response.text + caplog.text and 'PRIVATE_AUDIT_FAILURE' not in response.text + caplog.text
    assert not read_events(sessions)
    assert request(pg, read).status_code == 200
    assert len(read_events(sessions)) == 1
    sessions.kw['bind'].dispose()


@pytest.mark.parametrize('read', ['queue', 'available'])
def test_teacher_get_denial_is_audited_with_one_public_reason(pg, read):
    sessions = mount(pg, read)
    denied = request(pg, read, actor='synthetic-student-0')
    assert denied.status_code == 404
    rows = read_events(sessions)
    assert len(rows) == 1
    assert rows[0].outcome == 'denied' and rows[0].reason_code == 'resource_not_available'
    assert rows[0].owner_user_id == ''
    sessions.kw['bind'].dispose()


@pytest.mark.parametrize('read', ['queue', 'available'])
def test_nonexistent_course_keeps_uniform_404_without_a_fictitious_course_audit(pg, read):
    sessions = mount(pg, read)
    suffix = 'review-queue' if read == 'queue' else 'analytics'
    response = pg.request('GET', '/teacher/courses/unknown/' + suffix)
    assert response.status_code == 404
    assert response.json()['code'] == 'RESOURCE_NOT_AVAILABLE'
    assert not read_events(sessions)
    assert PRIVATE not in response.text
    # A subsequent real course read remains usable and must still be audited.
    assert request(pg, read).status_code == 200
    assert len(read_events(sessions)) == 1
    sessions.kw['bind'].dispose()
