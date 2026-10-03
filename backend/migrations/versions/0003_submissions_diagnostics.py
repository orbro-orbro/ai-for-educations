"""Submission pipeline, compiler evidence, and exercise publication."""

from alembic import op
import sqlalchemy as sa


revision = "0003_submissions_diagnostics"
down_revision = "0002_knowledge_graph"
branch_labels = None
depends_on = None


SUBMISSION_STATUS_CHECK = (
    "'received','executing','executed','execution_unavailable',"
    "'diagnosing','diagnosed','needs_review'"
)


def upgrade() -> None:
    op.add_column(
        "exercises",
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_unique_constraint(
        "uq_exercises_id_course", "exercises", ["id", "course_id"]
    )
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("course_id", sa.String(128), nullable=False),
        sa.Column("exercise_id", sa.String(128), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.String(128),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_files", sa.JSON(), nullable=False),
        sa.Column("entrypoint", sa.String(255), nullable=False),
        sa.Column("is_formal", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["exercise_id", "course_id"],
            ["exercises.id", "exercises.course_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "course_id", name="uq_submissions_id_course"),
        sa.CheckConstraint(
            f"status IN ({SUBMISSION_STATUS_CHECK})", name="ck_submissions_status"
        ),
    )
    op.create_index(
        "ix_submissions_exercise_owner",
        "submissions",
        ["exercise_id", "owner_user_id"],
    )
    op.create_index("ix_submissions_status", "submissions", ["status"])
    op.create_table(
        "submission_transitions",
        sa.Column(
            "submission_id",
            sa.String(128),
            sa.ForeignKey("submissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({SUBMISSION_STATUS_CHECK})",
            name="ck_submission_transitions_from",
        ),
        sa.CheckConstraint(
            f"to_status IN ({SUBMISSION_STATUS_CHECK})",
            name="ck_submission_transitions_to",
        ),
    )
    op.create_index(
        "ix_submission_transitions_changed_at",
        "submission_transitions",
        ["changed_at"],
    )
    op.create_table(
        "execution_results",
        sa.Column(
            "submission_id",
            sa.String(128),
            sa.ForeignKey("submissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("protocol_version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("signal", sa.Integer()),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("stdout_truncated", sa.Boolean(), nullable=False),
        sa.Column("stderr_truncated", sa.Boolean(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("command_summary", sa.JSON(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("toolchain", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded','compile_failed','run_failed','timed_out','resource_exhausted')",
            name="ck_execution_results_status",
        ),
        sa.CheckConstraint(
            "phase IN ('compile','run','control')",
            name="ck_execution_results_phase",
        ),
    )
    op.create_table(
        "rule_matches",
        sa.Column("submission_id", sa.String(128), primary_key=True),
        sa.Column("course_id", sa.String(128), nullable=False),
        sa.Column("misconception_id", sa.String(256), primary_key=True),
        sa.Column("root_concept_id", sa.String(256), nullable=False),
        sa.Column("diagnostic_indices", sa.JSON(), nullable=False),
        sa.Column("evidence_kind", sa.String(64), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("match_strength", sa.String(16), nullable=False),
        sa.ForeignKeyConstraint(
            ["submission_id", "course_id"],
            ["submissions.id", "submissions.course_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id", "misconception_id"],
            ["misconception_patterns.course_id", "misconception_patterns.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_id", "root_concept_id"],
            ["concepts.course_id", "concepts.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "evidence_kind = 'compiler_diagnostic'",
            name="ck_rule_matches_evidence_kind",
        ),
        sa.CheckConstraint(
            "match_strength IN ('strong','weak')", name="ck_rule_matches_strength"
        ),
        sa.UniqueConstraint(
            "submission_id",
            "misconception_id",
            "course_id",
            name="uq_rule_matches_submission_misconception_course",
        ),
    )
    op.create_index(
        "ix_rule_matches_course_misconception",
        "rule_matches",
        ["course_id", "misconception_id"],
    )
    op.create_index(
        "ix_rule_matches_course_root",
        "rule_matches",
        ["course_id", "root_concept_id"],
    )
    op.create_table(
        "rule_match_related_concepts",
        sa.Column("submission_id", sa.String(128), primary_key=True),
        sa.Column("misconception_id", sa.String(256), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.String(128), nullable=False),
        sa.Column("concept_id", sa.String(256), nullable=False),
        sa.ForeignKeyConstraint(
            ["submission_id", "misconception_id", "course_id"],
            [
                "rule_matches.submission_id",
                "rule_matches.misconception_id",
                "rule_matches.course_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id", "concept_id"],
            ["concepts.course_id", "concepts.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "submission_id",
            "misconception_id",
            "concept_id",
            name="uq_rule_match_related_concept",
        ),
    )
    op.create_index(
        "ix_rule_match_related_course_concept",
        "rule_match_related_concepts",
        ["course_id", "concept_id"],
    )


def downgrade() -> None:
    op.drop_table("rule_match_related_concepts")
    op.drop_table("rule_matches")
    op.drop_table("execution_results")
    op.drop_table("submission_transitions")
    op.drop_table("submissions")
    op.drop_constraint("uq_exercises_id_course", "exercises", type_="unique")
    op.drop_column("exercises", "is_published")
