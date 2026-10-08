from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import event, select, text, delete
from app.persistence.models import AuditEventRow, LearningMemoryRow, CourseAuthorizedTeacherRow
from app.persistence.repositories import create_sql_repositories
from tests.integration.wave3_support import Wave3PG, postgres_url, PRIVATE, SECRET


@pytest.fixture
def pg():
    value = Wave3PG()
    value.seed_diagnoses()
    value.mount()
    yield value
    value.close()


def reviews(pg):
    from app.persistence.models import TeacherDiagnosisReviewRow
    with pg.sessions() as session:
        return session.scalars(select(TeacherDiagnosisReviewRow)).all()


def success_audits(pg):
    with pg.sessions() as session:
        return session.scalars(select(AuditEventRow).where(AuditEventRow.event_type == "teacher_diagnosis_review", AuditEventRow.outcome == "success")).all()


def memory_snapshot(pg):
    with pg.sessions() as session:
        return [dict(row) for row in session.execute(select(LearningMemoryRow.__table__).order_by(LearningMemoryRow.id)).mappings()]


def test_review_replays_only_identical_trimmed_decision_and_never_changes_private_memory(pg, caplog):
    pg.seed_private_memory()
    before = memory_snapshot(pg)
    assert len(before) == 1 and before[0]["version"] == 1 and before[0]["status"] == "active"
    first = pg.post_review(reason="  Teacher reasoning  ")
    assert first.status_code == 200
    same = pg.post_review(reason="Teacher reasoning", actor="teacher-b")
    assert same.status_code == 200 and same.json() == first.json()
    assert pg.post_review(decision="overturned", reason="Teacher reasoning").status_code == 409
    assert pg.post_review(reason="Different reasoning").status_code == 409
    assert len(reviews(pg)) == len(success_audits(pg)) == 1
    assert memory_snapshot(pg) == before
    assert "Teacher reasoning" not in pg.repos.audit.serialized_events() + caplog.text
    assert PRIVATE not in first.text + caplog.text
    queue = pg.request("GET", "/teacher/courses/course-a/review-queue").json()
    assert "diag-0" not in {item["diagnosis_id"] for item in queue["items"]}


def test_sql_factory_shares_uow_and_successful_review_has_one_commit(pg):
    assert pg.repos.analytics.uow is pg.repos.memory_uow
    assert pg.repos.audit._uow is pg.repos.memory_uow
    commits = []
    def committed(_session):
        commits.append(True)
    event.listen(pg.sessions, "after_commit", committed)
    try:
        response = pg.post_review()
        assert response.status_code == 200
    finally:
        event.remove(pg.sessions, "after_commit", committed)
    assert len(commits) == 1
    assert len(reviews(pg)) == len(success_audits(pg)) == 1


@pytest.mark.parametrize("failure", ["review", "audit"])
def test_review_and_audit_rollback_together_when_either_flush_fails(pg, failure, caplog):
    def fail_flush(session, _context, _instances):
        from app.persistence.models import TeacherDiagnosisReviewRow
        target = TeacherDiagnosisReviewRow if failure == "review" else AuditEventRow
        if any(isinstance(row,target) for row in session.new):
            raise RuntimeError("PRIVATE_STORAGE_ERROR_SENTINEL")
    event.listen(pg.sessions, "before_flush", fail_flush)
    try:
        response = pg.post_review(reason="PRIVATE_REVIEW_REASON_SENTINEL")
    finally:
        event.remove(pg.sessions, "before_flush", fail_flush)
    assert response.status_code == 503
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"
    assert len(reviews(pg)) == len(success_audits(pg)) == 0
    assert "PRIVATE" not in response.text + caplog.text + pg.repos.audit.serialized_events()


@pytest.mark.parametrize("same", [True,False])
def test_two_independent_sql_instances_produce_one_authoritative_review_and_audit(pg, same):
    from app.analytics.persistence import SqlTeacherAnalyticsRepository
    first = pg.application
    other = create_sql_repositories(postgres_url())
    pg.mount(SqlTeacherAnalyticsRepository(other.memory_uow, secret=SECRET))
    second = pg.application
    barrier = Barrier(2)
    def request(app, actor, reason):
        barrier.wait(timeout=5)
        return pg.request("POST", "/teacher/diagnoses/diag-0/review", body={"decision":"confirmed", "reason":reason}, actor=actor, application=app)
    def timeout(_session, _transaction, connection):
        connection.execute(text("SET LOCAL lock_timeout = '5000ms'"))
    event.listen(pg.sessions, "after_begin", timeout)
    event.listen(other.memory_uow.sessions, "after_begin", timeout)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(request, first, "teacher-a", "same")
            b = pool.submit(request, second, "teacher-b", "same" if same else "different")
            results = [a.result(timeout=10), b.result(timeout=10)]
        assert sorted(r.status_code for r in results) == ([200,200] if same else [200,409])
        if same:
            assert results[0].json() == results[1].json()
        assert len(reviews(pg)) == len(success_audits(pg)) == 1
    finally:
        event.remove(pg.sessions, "after_begin", timeout)
        event.remove(other.memory_uow.sessions, "after_begin", timeout)
        other.memory_uow.sessions.kw["bind"].dispose()


def test_teacher_relationship_is_rechecked_after_waiting_for_diagnosis_lock(pg):
    engine = pg.sessions.kw["bind"]
    waiting = Event()
    def observe(_conn, _cursor, statement, _params, _context, _many):
        if "FOR NO KEY UPDATE" in statement:
            waiting.set()
    with pg.sessions() as blocker:
        blocker.begin()
        blocker.execute(text("SELECT id FROM diagnoses WHERE id='diag-0' FOR NO KEY UPDATE"))
        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(pg.post_review, actor="teacher-b")
                assert waiting.wait(timeout=5)
                with pg.sessions.begin() as session:
                    session.execute(delete(CourseAuthorizedTeacherRow).where(CourseAuthorizedTeacherRow.course_id == "course-a", CourseAuthorizedTeacherRow.teacher_id == "teacher-b"))
                blocker.rollback()
                response = future.result(timeout=10)
            assert response.status_code == 404
            missing = pg.post_review(diagnosis="missing", actor="teacher-b")
            assert (response.status_code, response.json()["code"], response.json()["message"]) == (missing.status_code, missing.json()["code"], missing.json()["message"])
            assert len(reviews(pg)) == len(success_audits(pg)) == 0
        finally:
            blocker.rollback()
            event.remove(engine, "before_cursor_execute", observe)
