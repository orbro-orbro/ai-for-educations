"""Identity, courses and enrollments."""

from alembic import op
import sqlalchemy as sa


revision = "0001_identity_courses"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("role IN ('student','teacher')", name="ck_users_role"),
    )
    op.create_table(
        "courses",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("owner_teacher_id", sa.String(128), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    )
    op.create_index("ix_courses_owner_teacher", "courses", ["owner_teacher_id"])
    op.create_table(
        "course_authorized_teachers",
        sa.Column("course_id", sa.String(128), sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("teacher_id", sa.String(128), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "enrollments",
        sa.Column("course_id", sa.String(128), sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(128), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.CheckConstraint("role IN ('student','teacher')", name="ck_enrollments_role"),
    )
    op.create_index("ix_enrollments_user", "enrollments", ["user_id"])
    op.create_table(
        "exercises",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("course_id", sa.String(128), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
    )
    op.create_index("ix_exercises_course", "exercises", ["course_id"])


def downgrade() -> None:
    op.drop_table("exercises")
    op.drop_table("enrollments")
    op.drop_table("course_authorized_teachers")
    op.drop_table("courses")
    op.drop_table("users")
