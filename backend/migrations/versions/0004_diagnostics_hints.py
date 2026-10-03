"""Persist evidence-bound diagnoses, hints, attempts and explanation checks."""

from alembic import op
import sqlalchemy as sa

from app.persistence.models import Base


revision = "0004_diagnostics_hints"
down_revision = "0003_submissions_diagnostics"
branch_labels = None
depends_on = None


_TABLES = (
    "diagnoses",
    "diagnosis_concepts",
    "evidence_bindings",
    "review_queue_events",
    "hint_events",
    "diagnosis_attempts",
    "explanation_checks",
    "diagnosis_run_results",
)


def upgrade() -> None:
    op.add_column("exercises", sa.Column("protected_answer", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_submissions_id_course_owner",
        "submissions",
        ["id", "course_id", "owner_user_id"],
    )
    bind = op.get_bind()
    for table_name in _TABLES:
        Base.metadata.tables[table_name].create(bind=bind)


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.drop_table(table_name)
    op.drop_constraint(
        "uq_submissions_id_course_owner", "submissions", type_="unique"
    )
    op.drop_column("exercises", "protected_answer")
