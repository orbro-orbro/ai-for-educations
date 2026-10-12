"""Persist one authoritative teacher review per diagnosis."""
from alembic import op
import sqlalchemy as sa

revision = "0007_teacher_analytics_reviews"
down_revision = "0006_token_revocations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("teacher_diagnosis_reviews",
        sa.Column("diagnosis_id", sa.String(128), primary_key=True),
        sa.Column("course_id", sa.String(128), nullable=False),
        sa.Column("reviewer_user_id", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["diagnosis_id", "course_id"], ["diagnoses.id", "diagnoses.course_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("decision IN ('confirmed','overturned','insufficient_evidence')", name="ck_teacher_review_decision"),
        sa.CheckConstraint("length(trim(reason)) > 0 AND length(reason) <= 2000", name="ck_teacher_review_reason"))
    op.create_index("ix_teacher_reviews_course", "teacher_diagnosis_reviews", ["course_id"])


def downgrade():
    op.drop_index("ix_teacher_reviews_course", table_name="teacher_diagnosis_reviews")
    op.drop_table("teacher_diagnosis_reviews")
