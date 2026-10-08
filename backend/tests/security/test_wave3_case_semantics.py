"""Review regression: execute, then inspect actual attack preconditions."""
from . import test_wave3_case_execution as execution


def test_cross_course_006_executes_course_b_pending_owner_revocation(caplog, monkeypatch):
    case = next(case for case in execution.CASES if case['case_id'] == 'sec-cross-course-006')
    recorded = {}
    execution.test_planned_operation(case, caplog, monkeypatch, recorded.__setitem__)
    assert {key: recorded.get(key) for key in ('attack_course', 'attack_owner', 'proposal_status_before', 'revoked_course')} == {
        'attack_course': 'course-b', 'attack_owner': 'student-a',
        'proposal_status_before': 'pending', 'revoked_course': 'course-b',
    }
