"""Real PostgreSQL only, with dedicated TASK10_POSTGRES_URL."""
import hashlib
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from datetime import UTC, datetime
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, inspect, event

from app.api.auth import Authenticator, TokenCodec, AuthenticationFailed
from app.persistence.models import TokenRevocationRow
from app.persistence.repositories import create_sql_repositories
from app.memories.deletion import DeletionService
from app.memories.retrieval import InMemoryRetrievalIndex
from test_task7_deletion_recovery import _seed, _services, _create_memory, PRIVATE_MEMORY


@pytest.fixture
def database():
    url = os.environ.get("TASK10_POSTGRES_URL")
    if not url: pytest.skip("Dedicated TASK10_POSTGRES_URL required; no SQLite substitute")
    assert url.startswith("postgresql")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url, config


def test_logout_is_persistent_across_instances_restart_and_concurrent_revocation(database):
    url, _ = database
    repositories, actor, _, _ = _seed(url)
    codec = TokenCodec("synthetic-repair-secret-at-least-16-bytes")
    auth = Authenticator(repositories.users, codec, repositories.token_revocations)
    token, _ = auth.login(actor.user_id, "pw")
    other, _ = auth.login(actor.user_id, "pw")
    header = "Bearer " + token
    # The store operation is idempotent even when two validated logout requests race.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: repositories.token_revocations.revoke(hashlib.sha256(token.encode()).hexdigest(), 2000000000), range(2)))
    for _ in range(2):
        restarted = create_sql_repositories(url)
        next_auth = Authenticator(restarted.users, codec, restarted.token_revocations)
        with pytest.raises(AuthenticationFailed): next_auth.authenticate_header(header)
        assert next_auth.authenticate_token(other) == actor
    auth.logout("Bearer " + other)
    after_logout = create_sql_repositories(url)
    with pytest.raises(AuthenticationFailed):
        Authenticator(after_logout.users, codec, after_logout.token_revocations).authenticate_token(other)
    with create_engine(url).connect() as connection:
        rows = connection.execute(select(TokenRevocationRow)).all()
        assert any(row.token_digest == hashlib.sha256(token.encode()).hexdigest() for row in rows)
        assert all(token not in repr(row) for row in rows)


def test_source_erasure_and_index_guard_survive_repository_restart(database):
    url, _ = database
    repositories, actor, course, explanation = _seed(url)
    index = InMemoryRetrievalIndex()
    _, _, memory = _create_memory(repositories, actor, explanation, index)
    from app.courses.service import CourseService
    from app.auth.policy import AuthorizationPolicy
    from app.memories.policy import CourseServiceMemoryAccess, MemoryPolicy
    policy = MemoryPolicy(CourseServiceMemoryAccess(CourseService(repositories.users, repositories.courses, repositories.enrollments, AuthorizationPolicy())))
    deletion = DeletionService(repository=repositories.memories, policy=policy, retrieval_index=index,
        audit=repositories.audit, source_context=repositories.memory_source)
    assert deletion.delete_memory(actor, memory.memory_id, request_id="delete", idempotency_key=uuid4().hex).status.value == "deleted"
    fresh = create_sql_repositories(url)
    assert PRIVATE_MEMORY not in fresh.diagnostics.get(memory.source_diagnosis_id).model_dump_json()
    assert all(PRIVATE_MEMORY not in p.content for p in fresh.memories.list_proposals(actor.user_id, course))
    rebuilt = InMemoryRetrievalIndex(repository=fresh.memories)
    rebuilt.upsert(memory)
    assert not rebuilt.contains(memory.index_document_id)


def test_upgrade_scrubs_legacy_deleted_source_and_round_trip_keeps_live_course(database):
    url, config = database
    command.downgrade(config, "0005_memories_audit")
    repositories, actor, course, explanation = _seed(url)
    index = InMemoryRetrievalIndex()
    _, legacy, memory = _create_memory(repositories, actor, explanation, index)
    legacy.delete_memory(actor, memory.memory_id, request_id="legacy-delete", idempotency_key=uuid4().hex)
    assert PRIVATE_MEMORY in repositories.diagnostics.get(memory.source_diagnosis_id).root_cause
    command.upgrade(config, "head")
    fresh = create_sql_repositories(url)
    assert PRIVATE_MEMORY not in fresh.diagnostics.get(memory.source_diagnosis_id).root_cause
    command.downgrade(config, "0005_memories_audit")
    assert "token_revocations" not in inspect(create_engine(url)).get_table_names()
    assert create_sql_repositories(url).courses.get(course) is not None
    command.upgrade(config, "head")


def test_source_erasure_rolls_back_with_failed_audit(database):
    url, _ = database
    repositories, actor, course, explanation = _seed(url)
    index = InMemoryRetrievalIndex()
    _, deletion, memory = _create_memory(repositories, actor, explanation, index)
    deletion._source_context = repositories.memory_source
    original = repositories.audit.record
    def fail(**_kwargs): raise RuntimeError("synthetic-audit-failure")
    repositories.audit.record = fail
    with pytest.raises(RuntimeError):
        deletion.delete_memory(actor, memory.memory_id, request_id="failed-delete", idempotency_key=uuid4().hex)
    repositories.audit.record = original
    fresh = create_sql_repositories(url)
    assert fresh.memories.get_memory(memory.memory_id).content == PRIVATE_MEMORY
    assert fresh.diagnostics.get(memory.source_diagnosis_id).root_cause == PRIVATE_MEMORY
    assert any(p.content == PRIVATE_MEMORY for p in fresh.memories.list_proposals(actor.user_id, course))


def test_restarted_writer_shares_index_without_self_blocking(database):
    url, _ = database
    repositories, actor, _, explanation = _seed(url)
    index = InMemoryRetrievalIndex()
    _, _, memory = _create_memory(repositories, actor, explanation, index)
    engine = repositories.memory_uow.sessions.kw["bind"]
    def bounded_lock(connection, _record, _proxy):
        cursor = connection.cursor()
        cursor.execute("SET lock_timeout = '1s'")
        cursor.close()
    event.listen(engine, "checkout", bounded_lock)
    try:
        restarted = create_sql_repositories(url)
        service, _ = _services(restarted, index)
        updated = service.correct_memory(actor, memory.memory_id, "Synthetic corrected context",
            request_id="restarted-correction", idempotency_key=uuid4().hex)
        assert index.contains(updated.index_document_id)
    finally:
        event.remove(engine, "checkout", bounded_lock)


@pytest.mark.parametrize("kind", ["explanation", "hint", "proposal"])
def test_late_source_writes_are_fenced_across_instances(database, kind, monkeypatch):
    from app.diagnostics.schema import HintEvent
    from app.memories.service import MemoryProposalNotEligible
    url, _ = database
    repositories, actor, course, explanation = _seed(url)
    index = InMemoryRetrievalIndex()
    _, deletion, memory = _create_memory(repositories, actor, explanation, index)
    deletion._source_context = repositories.memory_source
    writer = create_sql_repositories(url)
    stale = next(e for e in writer.diagnostics.explanation_checks() if e.explanation_check_id == explanation)
    late = stale.model_copy(update={"explanation_check_id": uuid4().hex, "request_id": uuid4().hex,
        "evidence_summary": PRIVATE_MEMORY, "feedback": PRIVATE_MEMORY})
    if kind == "proposal":
        writer.diagnostics.add_explanation(late)
        service, _ = _services(writer, index)
        read_done, deletion_done = Event(), Event()
        original = writer.memory_source.proposal_source
        def delayed_snapshot(check_id):
            snapshot = original(check_id)
            monkeypatch.setattr(writer.memory_source, "proposal_source", original)
            read_done.set()
            assert deletion_done.wait(5)
            return snapshot
        monkeypatch.setattr(writer.memory_source, "proposal_source", delayed_snapshot)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.create_proposal, actor, late.explanation_check_id, request_id="late")
            assert read_done.wait(5)
            try:
                deletion.delete_memory(actor, memory.memory_id, request_id="delete", idempotency_key=uuid4().hex)
            finally:
                deletion_done.set()
            with pytest.raises(MemoryProposalNotEligible): future.result(timeout=5)
        assert writer.memories.get_proposal_for_explanation(late.explanation_check_id) is None
    else:
        deletion.delete_memory(actor, memory.memory_id, request_id="delete", idempotency_key=uuid4().hex)
        # Use a restarted writer: the fence must be persisted, not instance-local.
        writer = create_sql_repositories(url)
        if kind == "explanation":
            persisted = writer.diagnostics.add_explanation(late)
            assert not persisted.memory_proposal_eligible
        else:
            persisted = writer.diagnostics.add_hint_event(HintEvent(hint_event_id=uuid4().hex,
                diagnosis_id=memory.source_diagnosis_id, previous_level=0, current_level=1,
                reason=PRIVATE_MEMORY, content=PRIVATE_MEMORY, previous_attempt_count=0,
                used_safe_fallback=False, created_at=datetime.now(UTC), request_id=uuid4().hex))
        assert PRIVATE_MEMORY not in persisted.model_dump_json()
        fresh = create_sql_repositories(url)
        assert all(PRIVATE_MEMORY not in e.model_dump_json() for e in fresh.diagnostics.explanation_checks()
            if e.diagnosis_id == memory.source_diagnosis_id)
        assert all(PRIVATE_MEMORY not in e.model_dump_json() for e in fresh.diagnostics.hint_events(memory.source_diagnosis_id))


@pytest.mark.parametrize("operation", ["accept", "correct"])
def test_deleting_source_serializes_pending_proposal_mutation(database, operation, monkeypatch):
    from app.memories.service import MemoryConflict
    url, _ = database
    repositories, actor, course, explanation = _seed(url)
    index = InMemoryRetrievalIndex()
    service, deletion, memory = _create_memory(repositories, actor, explanation, index)
    deletion._source_context = repositories.memory_source
    check = next(e for e in repositories.diagnostics.explanation_checks() if e.explanation_check_id == explanation)
    late = check.model_copy(update={"explanation_check_id": uuid4().hex, "request_id": uuid4().hex})
    repositories.diagnostics.add_explanation(late)
    pending = service.create_proposal(actor, late.explanation_check_id, request_id="second")
    writer = create_sql_repositories(url)
    writing_service, _ = _services(writer, index)
    parent_locked, proposal_read, release_delete = Event(), Event(), Event()
    erase = repositories.memory_source.erase_private_context
    read_proposal = writer.memories.get_proposal
    def pause_delete(*args):
        erase(*args)
        parent_locked.set()
        assert release_delete.wait(5)
    def observe_read(*args):
        result = read_proposal(*args)
        proposal_read.set()
        return result
    monkeypatch.setattr(repositories.memory_source, "erase_private_context", pause_delete)
    monkeypatch.setattr(writer.memories, "get_proposal", observe_read)
    def mutate():
        if operation == "accept":
            return writing_service.accept_proposal(actor, pending.proposal_id, request_id="late", idempotency_key=uuid4().hex)
        return writing_service.correct_proposal(actor, pending.proposal_id, PRIVATE_MEMORY, request_id="late", idempotency_key=uuid4().hex)
    with ThreadPoolExecutor(max_workers=2) as pool:
        deleting = pool.submit(deletion.delete_memory, actor, memory.memory_id, request_id="delete", idempotency_key=uuid4().hex)
        assert parent_locked.wait(5)
        writing = pool.submit(mutate)
        try:
            assert proposal_read.wait(5)
        finally:
            release_delete.set()
        assert deleting.result(timeout=8).status.value == "deleted"
        with pytest.raises(MemoryConflict): writing.result(timeout=8)
    fresh = create_sql_repositories(url)
    assert fresh.memories.get_memory_for_proposal(pending.proposal_id) is None
    assert fresh.memories.proposal_successor(pending.proposal_id) is None
    assert all(PRIVATE_MEMORY not in p.content for p in fresh.memories.list_proposals(actor.user_id, course))
