"""Persist token digests so logout survives worker changes and restart."""
from alembic import op
import sqlalchemy as sa

revision = "0006_token_revocations"
down_revision = "0005_memories_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("token_revocations",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(token_digest) = 64", name="ck_token_revocation_digest"))
    # One-way privacy cleanup for already deleted/pending chains. Downgrade
    # cannot restore erased text. Dropping the revocation table requires token
    # key rotation before authentication is re-enabled after a rollback.
    scope = "SELECT source_diagnosis_id FROM learning_memories WHERE status IN ('deletion_pending','deleted')"
    for table, key, assignments in (
        ("memory_proposals", "diagnosis_id", "content = :marker"),
        ("diagnoses", "id", "root_cause = :marker"),
        ("evidence_bindings", "diagnosis_id", "summary = :marker"),
        ("hint_events", "diagnosis_id", "reason = :marker, content = :marker"),
        ("explanation_checks", "diagnosis_id", "evidence_summary = :marker, feedback = :marker, memory_proposal_eligible = false"),
    ):
        op.get_bind().execute(sa.text(f"UPDATE {table} SET {assignments} WHERE {key} IN ({scope})"),
            {"marker": "[Deleted by student]"})


def downgrade():
    op.drop_table("token_revocations")
