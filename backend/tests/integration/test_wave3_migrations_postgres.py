"""Disposable synthetic schemas in the dedicated Gate migration database."""
from datetime import UTC, datetime
from uuid import uuid4
import hashlib
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from app.api.auth import Authenticator, TokenCodec, AuthenticationFailed
from app.auth.models import Actor, Role
from app.persistence.repositories import create_sql_repositories
from app.memories.retrieval import InMemoryRetrievalIndex
from tests.integration.wave3_support import BACKEND, postgres_url
from tests.integration.test_task7_deletion_recovery import _seed, _create_memory, PRIVATE_MEMORY


@pytest.fixture
def migration():
    base = postgres_url("wave3_migration")
    admin = create_engine(base)
    schema = "wave3_synthetic_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base).update_query_dict({"options":f"-csearch_path={schema},public"}).render_as_string(hide_password=False)
    engine = create_engine(url)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    assert inspect(engine).get_table_names(schema=schema) == []
    yield url, config, engine, schema
    engine.dispose(); admin.dispose()


def revision(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def test_empty_full_chain_and_disposable_full_round_trip(migration, record_property):
    _, cfg, engine, schema = migration
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0007_teacher_analytics_reviews"]
    command.upgrade(cfg,"head")
    assert revision(engine) == "0007_teacher_analytics_reviews"
    command.current(cfg); command.check(cfg)
    assert {"token_revocations","teacher_diagnosis_reviews"} <= set(inspect(engine).get_table_names(schema=schema))
    with engine.connect() as connection:
        record_property("postgres",connection.scalar(text("SELECT version()")))
        record_property("pgvector",connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")))
    command.downgrade(cfg,"base")
    assert set(inspect(engine).get_table_names(schema=schema)) == {"alembic_version"}
    command.upgrade(cfg,"head"); command.check(cfg)
    assert revision(engine) == "0007_teacher_analytics_reviews"


@pytest.mark.parametrize("historical_status",["deleted","deletion_pending"])
def test_rollback_retains_non_target_data_requires_key_rotation_and_does_not_restore_text(migration,historical_status):
    url,cfg,engine,_ = migration
    command.upgrade(cfg,"0005_memories_audit")
    repos,actor,course,check = _seed(url)
    _,legacy,memory = _create_memory(repos,actor,check,InMemoryRetrievalIndex())
    legacy.delete_memory(actor,memory.memory_id,request_id="synthetic-legacy-delete",idempotency_key="synthetic-legacy-delete")
    assert PRIVATE_MEMORY in repos.diagnostics.get(memory.source_diagnosis_id).root_cause
    live, live_actor, live_course, live_check = _seed(url)
    live_diag = live.diagnostics.get(next(c.diagnosis_id for c in live.diagnostics.explanation_checks() if c.explanation_check_id == live_check))
    submission = live.submissions.get(live_diag.submission_id)
    with engine.begin() as connection:
        connection.execute(text("UPDATE learning_memories SET status=:status WHERE id=:id"),{"status":historical_status,"id":memory.memory_id})
        connection.execute(text("UPDATE evidence_bindings SET summary=:p WHERE diagnosis_id=:id"),{"p":PRIVATE_MEMORY,"id":memory.source_diagnosis_id})
        connection.execute(text("UPDATE explanation_checks SET evidence_summary=:p,feedback=:p WHERE diagnosis_id=:id"),{"p":PRIVATE_MEMORY,"id":memory.source_diagnosis_id})
        connection.execute(text("INSERT INTO hint_events VALUES ('synthetic-legacy-hint',:id,0,1,:p,0,:p,false,:at,'synthetic-legacy-hint')"),{"id":memory.source_diagnosis_id,"p":PRIVATE_MEMORY,"at":datetime.now(UTC)})
    command.upgrade(cfg,"head")
    with engine.connect() as connection:
        for table,key,fields in [("memory_proposals","diagnosis_id",["content"]),("diagnoses","id",["root_cause"]),("evidence_bindings","diagnosis_id",["summary"]),("hint_events","diagnosis_id",["reason","content"]),("explanation_checks","diagnosis_id",["evidence_summary","feedback"])]:
            rows=connection.execute(text(f"SELECT {','.join(fields)} FROM {table} WHERE {key}=:id"),{"id":memory.source_diagnosis_id}).all()
            assert rows and all(PRIVATE_MEMORY not in str(row) for row in rows),table
    fresh = create_sql_repositories(url)
    assert PRIVATE_MEMORY not in fresh.diagnostics.get(memory.source_diagnosis_id).model_dump_json()
    assert all(PRIVATE_MEMORY not in p.content for p in fresh.memories.list_proposals(actor.user_id,course))
    assert fresh.diagnostics.get(live_diag.diagnosis_id) == live_diag
    assert fresh.submissions.get(submission.submission_id) == submission
    assert fresh.courses.get(course) and fresh.courses.get(live_course)
    teacher = fresh.courses.get(course).owner_teacher_id
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO teacher_diagnosis_reviews VALUES (:d,:c,:t,'confirmed','synthetic reason',:at)"),{"d":memory.source_diagnosis_id,"c":course,"t":teacher,"at":datetime.now(UTC)})
    old_codec=TokenCodec("synthetic-before-rollback-key-16bytes")
    auth=Authenticator(fresh.users,old_codec,fresh.token_revocations)
    old_token,_=auth.login(actor.user_id,"pw")
    auth.logout("Bearer "+old_token)
    command.downgrade(cfg,"0006_token_revocations")
    with pytest.raises(AuthenticationFailed):auth.authenticate_token(old_token)
    command.upgrade(cfg,"head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM teacher_diagnosis_reviews")) == 0
    command.downgrade(cfg,"0005_memories_audit")
    command.upgrade(cfg,"head")
    restarted=create_sql_repositories(url)
    # Dropping revocations really loses them: key rotation is mandatory.
    assert Authenticator(restarted.users,old_codec,restarted.token_revocations).authenticate_token(old_token) == actor
    rotated=Authenticator(restarted.users,TokenCodec("synthetic-after-rollback-rotated-key"),restarted.token_revocations)
    with pytest.raises(AuthenticationFailed):rotated.authenticate_token(old_token)
    assert PRIVATE_MEMORY not in restarted.diagnostics.get(memory.source_diagnosis_id).model_dump_json()
    assert restarted.diagnostics.get(live_diag.diagnosis_id) == live_diag
    assert restarted.submissions.get(submission.submission_id) == submission
    command.check(cfg)


@pytest.mark.parametrize("failure",["short_digest","duplicate_digest","invalid_decision","blank_reason","long_reason","foreign_course","duplicate_review"])
def test_actual_migrated_constraints(migration,failure):
    url,cfg,engine,_=migration;command.upgrade(cfg,"head")
    repos,actor,course,check=_seed(url)
    teacher=repos.courses.get(course).owner_teacher_id
    values={"d":next(c.diagnosis_id for c in repos.diagnostics.explanation_checks() if c.explanation_check_id == check),"c":course,"t":teacher,"decision":"confirmed","reason":"synthetic reason","at":datetime.now(UTC)}
    review=text("INSERT INTO teacher_diagnosis_reviews VALUES (:d,:c,:t,:decision,:reason,:at)")
    digest=hashlib.sha256(b"synthetic-token-never-log").hexdigest()
    token=text("INSERT INTO token_revocations VALUES (:digest,2000000000)")
    if failure in {"duplicate_digest","duplicate_review"}:
        with engine.begin() as c:c.execute(token if failure=="duplicate_digest" else review,{"digest":digest} if failure=="duplicate_digest" else values)
    values.update({"invalid_decision":{"decision":"unknown"},"blank_reason":{"reason":" "},"long_reason":{"reason":"x"*2001},"foreign_course":{"c":"nonexistent-course"}}.get(failure,{}))
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(token,{"digest":"short" if failure=="short_digest" else digest}) if "digest" in failure else c.execute(review,values)
