"""Synthetic seed repeatability on real Task 11 PostgreSQL, no SQL facts doubles."""
import uuid
import pytest
from sqlalchemy import func, select
from app.persistence.models import UserRow, SubmissionRow
from scripts.delivery_demo import validate_demo_target, seed, DeliveryMockProvider
from tests.integration.wave3_support import postgres_url, upgrade


@pytest.mark.parametrize("url,environment,enabled", [
    ("postgresql+psycopg://x:x@postgres:5432/knowbound", "development", "1"),
    ("postgresql+psycopg://x:x@postgres:5432/wave4_demo", "production", "1"),
    ("postgresql+psycopg://x:x@postgres:5432/wave4_demo", "development", "0"),
    ("sqlite:///demo.db", "development", "1"),
    ("postgresql+psycopg://x:x@127.0.0.1:55430/wave3_browser", "test", "1"),
])
def test_demo_refuses_foreign_or_production_targets(url, environment, enabled):
    with pytest.raises(ValueError): validate_demo_target(url, environment, enabled)


def test_demo_seed_is_repeatable_and_preserves_existing_state():
    import os
    assert os.environ.get("WAVE4_TEST_MODE") == "1", "Dedicated Task 11 resources must be selected"
    upgrade("wave3_browser")
    url = postgres_url("wave3_browser")
    repos = seed(url, environment="test", enabled="1", password="synthetic-demo-password")
    sid = "synthetic-preserved-" + uuid.uuid4().hex
    repos.submissions.create(submission_id=sid, course_id="cangjie-language-design", exercise_id="demo-match",
        owner_user_id="demo-student-1", source_files=[{"path":"main.cj","content":"synthetic-preserved-source"}],
        entrypoint="main.cj", is_formal=True, request_id="synthetic-seed-test")
    with repos.memory_uow.sessions() as session:
        before = (session.scalar(select(func.count()).select_from(UserRow)), session.scalar(select(func.count()).select_from(SubmissionRow)))
    again = seed(url, environment="test", enabled="1", password="different-password-must-not-reset-actors")
    try:
        with again.memory_uow.sessions() as session:
            after = (session.scalar(select(func.count()).select_from(UserRow)), session.scalar(select(func.count()).select_from(SubmissionRow)))
        assert after == before
        assert again.submissions.get(sid).source_files[0].content == "synthetic-preserved-source"
        actor = again.users.find_by_username("demo-student-1")
        assert actor.verify_password("synthetic-demo-password")
        assert again.courses.get("cangjie-language-design").title == "仓颉语言设计"
        assert next(item for item in again.courses.list_exercises("cangjie-language-design") if item.exercise_id == "demo-match").is_published
        assert len(again.knowledge.graph("cangjie-language-design").approved_evidence()) == 1
    finally:
        repos.memory_uow.sessions.kw["bind"].dispose()
        again.memory_uow.sessions.kw["bind"].dispose()


def test_mock_hints_are_repeatable_without_queue_exhaustion():
    from app.model_gateway.base import HintRequest
    mock = DeliveryMockProvider()
    request = HintRequest(category="conceptual", root_cause="synthetic", concept_ids=("cj.pattern-match.exhaustiveness",),
        level=2, previous_attempt_count=1, approved_outline="逐项检查枚举构造器。")
    for _ in range(50):
        hint = mock.generate_hint(request)
        assert hint.level == 2 and "合成" in hint.content
