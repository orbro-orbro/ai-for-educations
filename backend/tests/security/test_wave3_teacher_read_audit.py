"""Unfixed review finding: sensitive teacher reads must audit or fail closed.

Only synthetic in-process facts are used. These RED tests deliberately remain
unfixed while the user's Important-security stop condition is active.
"""
import pytest

from app.analytics.repository import AnalyticsPersistenceError, InMemoryTeacherAnalyticsRepository
from app.analytics.schemas import AnalyticsFilters
from app.analytics.service import TeacherAnalyticsService
from app.audit.service import AuditService
from tests.analytics.conftest import BASE_TIME, COURSE_A, OWNER, candidate, course_service, fact


def make_service(audit, read):
    repository = InMemoryTeacherAnalyticsRepository()
    repository.add_candidates([candidate(1)])
    if read == "available_analytics":
        repository.add_facts([fact(number) for number in range(1, 6)])
    return TeacherAnalyticsService(
        courses=course_service.__wrapped__(), repository=repository,
        audit=audit, clock=lambda: BASE_TIME,
    )


def sensitive_read(service, read):
    if read == "queue":
        result = service.review_queue(OWNER, COURSE_A, AnalyticsFilters())
        assert len(result.items) == 1
    else:
        result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())
        assert result.status == ("available" if read == "available_analytics" else "insufficient_sample")
    return result


@pytest.mark.parametrize("read", ["queue", "available_analytics", "suppressed_analytics"])
def test_sensitive_teacher_read_records_metadata_audit(read):
    audit = AuditService(clock=lambda: BASE_TIME)
    service = make_service(audit, read)
    sensitive_read(service, read)
    events = audit.events()
    assert len(events) >= 1, "Sensitive teacher GET returned without an audit event"
    assert all(event.actor_user_id == OWNER.user_id and event.course_id == COURSE_A for event in events)


class UnavailableAudit(AuditService):
    def record(self, **kwargs):
        raise RuntimeError("synthetic audit storage unavailable")


@pytest.mark.parametrize("read", ["queue", "available_analytics", "suppressed_analytics"])
def test_sensitive_teacher_read_fails_closed_when_audit_is_unavailable(read):
    service = make_service(UnavailableAudit(), read)
    with pytest.raises(AnalyticsPersistenceError):
        sensitive_read(service, read)
