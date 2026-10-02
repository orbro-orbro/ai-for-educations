"""Course-scoped knowledge graph and review state."""

from alembic import op
import sqlalchemy as sa


revision = "0002_knowledge_graph"
down_revision = "0001_identity_courses"
branch_labels = None
depends_on = None


REVIEW_CHECK = "review_status IN ('draft','pending_review','approved','rejected')"


def upgrade() -> None:
    op.create_table(
        "concepts",
        sa.Column("course_id", sa.String(128), sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(256), primary_key=True),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", sa.String(128), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("review_note", sa.Text()),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.CheckConstraint(REVIEW_CHECK, name="ck_concepts_review"),
    )
    op.create_index("ix_concepts_course_review", "concepts", ["course_id", "review_status"])
    op.create_table(
        "misconception_patterns",
        sa.Column("course_id", sa.String(128), primary_key=True),
        sa.Column("id", sa.String(256), primary_key=True),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("root_concept_id", sa.String(256), nullable=False),
        sa.Column("related_concept_ids", sa.JSON(), nullable=False),
        sa.Column("trigger_evidence", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("hint_ladder", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", sa.String(128), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("review_note", sa.Text()),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("verification", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id", "root_concept_id"], ["concepts.course_id", "concepts.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(REVIEW_CHECK, name="ck_misconceptions_review"),
    )
    op.create_index("ix_misconceptions_course_review", "misconception_patterns", ["course_id", "review_status"])
    op.create_index("ix_misconceptions_root", "misconception_patterns", ["course_id", "root_concept_id"])
    op.create_table(
        "misconception_related_concepts",
        sa.Column("course_id", sa.String(128), primary_key=True),
        sa.Column("misconception_id", sa.String(256), primary_key=True),
        sa.Column("concept_id", sa.String(256), primary_key=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["course_id", "misconception_id"], ["misconception_patterns.course_id", "misconception_patterns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id", "concept_id"], ["concepts.course_id", "concepts.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "uq_misconception_related_ordinal",
        "misconception_related_concepts",
        ["course_id", "misconception_id", "ordinal"],
        unique=True,
    )
    op.create_table(
        "concept_edges",
        sa.Column("course_id", sa.String(128), primary_key=True),
        sa.Column("source_concept_id", sa.String(256), primary_key=True),
        sa.Column("target_id", sa.String(256), primary_key=True),
        sa.Column("edge_type", sa.String(32), primary_key=True),
        sa.Column("target_concept_id", sa.String(256)),
        sa.Column("target_misconception_id", sa.String(256)),
        sa.Column("note", sa.Text()),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id", "source_concept_id"], ["concepts.course_id", "concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id", "target_concept_id"], ["concepts.course_id", "concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id", "target_misconception_id"], ["misconception_patterns.course_id", "misconception_patterns.id"], ondelete="CASCADE"),
        sa.CheckConstraint("edge_type IN ('prerequisite','confusable_with','used_by','explains_error')", name="ck_concept_edges_type"),
        sa.CheckConstraint("(edge_type = 'explains_error' AND target_concept_id IS NULL AND target_misconception_id IS NOT NULL) OR (edge_type <> 'explains_error' AND target_concept_id IS NOT NULL AND target_misconception_id IS NULL)", name="ck_concept_edges_target_kind"),
    )
    op.create_index("ix_concept_edges_course_source", "concept_edges", ["course_id", "source_concept_id"])
    op.create_index("ix_concept_edges_course_target", "concept_edges", ["course_id", "target_id"])


def downgrade() -> None:
    op.drop_table("concept_edges")
    op.drop_table("misconception_related_concepts")
    op.drop_table("misconception_patterns")
    op.drop_table("concepts")
