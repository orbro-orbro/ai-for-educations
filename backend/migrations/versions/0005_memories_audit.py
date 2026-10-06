"""Persist private learning-memory state, idempotency and metadata-only audit events."""

from alembic import op
import sqlalchemy as sa

from app.persistence.models import Base


revision = "0005_memories_audit"
down_revision = "0004_diagnostics_hints"
branch_labels = None
depends_on = None


_TABLES = (
    "memory_proposals",
    "learning_memories",
    "share_grants",
    "memory_deletions",
    "memory_tombstones",
    "memory_idempotency_results",
    "audit_events",
)


def _unique_constraint_names(bind, table_name: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(bind).get_unique_constraints(table_name)
        if item.get("name")
    }


def _ensure_unique(
    bind,
    table_name: str,
    constraint_name: str,
    columns: list[str],
) -> None:
    if constraint_name not in _unique_constraint_names(bind, table_name):
        op.create_unique_constraint(constraint_name, table_name, columns)


def _drop_unique_if_present(bind, table_name: str, constraint_name: str) -> None:
    if constraint_name in _unique_constraint_names(bind, table_name):
        op.drop_constraint(constraint_name, table_name, type_="unique")


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_unique(
        bind,
        "diagnoses",
        "uq_diagnoses_id_course_owner",
        ["id", "course_id", "owner_user_id"],
    )
    _ensure_unique(
        bind,
        "explanation_checks",
        "uq_explanation_checks_id_diagnosis",
        ["id", "diagnosis_id"],
    )
    for table_name in _TABLES:
        Base.metadata.tables[table_name].create(bind=bind)


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.drop_table(table_name)
    bind = op.get_bind()
    _drop_unique_if_present(
        bind,
        "explanation_checks",
        "uq_explanation_checks_id_diagnosis",
    )
    _drop_unique_if_present(
        bind,
        "diagnoses",
        "uq_diagnoses_id_course_owner",
    )
