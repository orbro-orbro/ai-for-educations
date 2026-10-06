from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import DateTime, UniqueConstraint


BACKEND = Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "migrations/versions"
TASK7_TABLES = (
    "memory_proposals",
    "learning_memories",
    "share_grants",
    "memory_deletions",
    "memory_tombstones",
    "memory_idempotency_results",
    "audit_events",
)


def _load_migration(name: str):
    path = VERSIONS / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraint_names(table) -> set[str]:
    return {constraint.name for constraint in table.constraints if constraint.name}


def _foreign_key_columns(table) -> set[tuple[str, ...]]:
    return {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }


def test_task7_migration_extends_the_real_head_once():
    migrations = sorted(VERSIONS.glob("*.py"))
    task7 = [path for path in migrations if "memories_audit" in path.name]
    assert [path.name for path in task7] == ["0005_memories_audit.py"]

    migration = _load_migration("0005_memories_audit.py")
    assert migration.revision == "0005_memories_audit"
    assert migration.down_revision == "0004_diagnostics_hints"
    assert migration._TABLES == TASK7_TABLES


def test_task7_metadata_declares_all_tables_and_timezone_aware_dates():
    from app.persistence.models import Base

    tables = Base.metadata.tables
    assert set(TASK7_TABLES) <= set(tables)
    for table_name in TASK7_TABLES:
        for column in tables[table_name].columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone is True, f"{table_name}.{column.name}"


def test_task6_composite_keys_support_task7_foreign_keys():
    from app.persistence.models import Base

    diagnoses = Base.metadata.tables["diagnoses"]
    checks = Base.metadata.tables["explanation_checks"]
    diagnosis_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in diagnoses.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in checks.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("id", "course_id", "owner_user_id") in diagnosis_unique
    assert ("id", "diagnosis_id") in check_unique


def test_proposal_and_memory_lineages_are_bound_to_owner_and_course():
    from app.persistence.models import Base

    proposal = Base.metadata.tables["memory_proposals"]
    memory = Base.metadata.tables["learning_memories"]

    assert {
        "uq_memory_proposals_explanation_check",
        "uq_memory_proposals_root_version",
        "uq_memory_proposals_previous",
        "uq_memory_proposals_id_owner_course",
    } <= _constraint_names(proposal)
    assert {
        ("diagnosis_id", "course_id", "owner_user_id"),
        ("explanation_check_id", "diagnosis_id"),
        ("root_proposal_id", "owner_user_id", "course_id"),
        ("previous_proposal_id", "owner_user_id", "course_id"),
    } <= _foreign_key_columns(proposal)
    assert proposal.columns["explanation_check_id"].nullable is True

    assert {
        "uq_learning_memories_source_proposal",
        "uq_learning_memories_logical_version",
        "uq_learning_memories_previous",
        "uq_learning_memories_index_document",
        "uq_learning_memories_id_owner_course",
    } <= _constraint_names(memory)
    assert {
        ("source_proposal_id", "owner_user_id", "course_id"),
        ("source_diagnosis_id", "course_id", "owner_user_id"),
        ("logical_memory_id", "owner_user_id", "course_id"),
        ("previous_version_id", "owner_user_id", "course_id"),
    } <= _foreign_key_columns(memory)
    assert memory.columns["source_proposal_id"].nullable is True

    active = next(
        index for index in memory.indexes if index.name == "uq_learning_memories_one_active"
    )
    assert active.unique is True
    assert tuple(column.name for column in active.columns) == ("logical_memory_id",)
    assert "status = 'active'" in str(active.dialect_options["postgresql"]["where"])


def test_grants_deletions_idempotency_and_audit_have_named_guards():
    from app.persistence.models import Base

    tables = Base.metadata.tables
    assert {
        "ck_share_grants_resource_type",
        "ck_share_grants_status",
        "ck_share_grants_revocation",
        "uq_share_grants_exact_scope",
    } <= _constraint_names(tables["share_grants"])
    assert {
        "ck_memory_deletions_status",
        "ck_memory_deletions_attempts",
        "ck_memory_deletions_completion",
        "uq_memory_deletions_logical_memory",
    } <= _constraint_names(tables["memory_deletions"])
    assert "uq_memory_tombstones_deletion" in _constraint_names(
        tables["memory_tombstones"]
    )
    assert "uq_memory_idempotency_scope" in _constraint_names(
        tables["memory_idempotency_results"]
    )
    assert {
        "ck_audit_events_actor_role",
        "ck_audit_events_outcome",
        "ck_audit_events_reason_code",
    } <= _constraint_names(tables["audit_events"])


def test_deletion_tombstone_and_audit_tables_cannot_store_private_material():
    from app.persistence.models import Base

    allowed = {
        "memory_deletions": {
            "id",
            "logical_memory_id",
            "owner_user_id",
            "course_id",
            "status",
            "requested_at",
            "completed_at",
            "attempts",
            "index_cleared",
            "cache_cleared",
            "model_references_cleared",
            "reverse_lookup_absent",
            "error_code",
            "request_id",
        },
        "memory_tombstones": {
            "logical_memory_id",
            "deletion_id",
            "owner_user_id",
            "course_id",
            "created_at",
        },
        "audit_events": {
            "id",
            "event_type",
            "actor_user_id",
            "actor_role",
            "target_type",
            "target_id",
            "owner_user_id",
            "course_id",
            "outcome",
            "reason_code",
            "request_id",
            "created_at",
            "related_id",
        },
    }
    for table_name, expected in allowed.items():
        assert set(Base.metadata.tables[table_name].columns.keys()) == expected


def test_migration_upgrade_and_downgrade_are_ordered_and_reversible():
    source = (VERSIONS / "0005_memories_audit.py").read_text(encoding="utf-8")
    assert '"uq_diagnoses_id_course_owner"' in source
    assert '"uq_explanation_checks_id_diagnosis"' in source
    assert "for table_name in _TABLES" in source
    assert "for table_name in reversed(_TABLES)" in source
    assert source.index('"uq_diagnoses_id_course_owner"') < source.index(
        "for table_name in _TABLES"
    )
    assert source.rindex('"uq_explanation_checks_id_diagnosis"') > source.index(
        "for table_name in reversed(_TABLES)"
    )
