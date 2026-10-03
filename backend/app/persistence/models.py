from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (CheckConstraint("role IN ('student','teacher')", name="ck_users_role"),)


class CourseRow(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    owner_teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    __table_args__ = (Index("ix_courses_owner_teacher", "owner_teacher_id"),)


class CourseAuthorizedTeacherRow(Base):
    __tablename__ = "course_authorized_teachers"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class EnrollmentRow(Base):
    __tablename__ = "enrollments"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    __table_args__ = (
        CheckConstraint("role IN ('student','teacher')", name="ck_enrollments_role"),
        Index("ix_enrollments_user", "user_id"),
    )


class ExerciseRow(Base):
    __tablename__ = "exercises"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    protected_answer: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("id", "course_id", name="uq_exercises_id_course"),
        Index("ix_exercises_course", "course_id"),
    )


class ConceptRow(Base):
    __tablename__ = "concepts"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        CheckConstraint("review_status IN ('draft','pending_review','approved','rejected')", name="ck_concepts_review"),
        Index("ix_concepts_course_review", "course_id", "review_status"),
    )


class MisconceptionRow(Base):
    __tablename__ = "misconception_patterns"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    root_concept_id: Mapped[str] = mapped_column(String(256), nullable=False)
    related_concept_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    trigger_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    hint_ladder: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["course_id", "root_concept_id"], ["concepts.course_id", "concepts.id"], ondelete="RESTRICT"),
        CheckConstraint("review_status IN ('draft','pending_review','approved','rejected')", name="ck_misconceptions_review"),
        Index("ix_misconceptions_course_review", "course_id", "review_status"),
        Index("ix_misconceptions_root", "course_id", "root_concept_id"),
    )


class MisconceptionRelatedConceptRow(Base):
    __tablename__ = "misconception_related_concepts"
    course_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    misconception_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    concept_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["course_id", "misconception_id"],
            ["misconception_patterns.course_id", "misconception_patterns.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["course_id", "concept_id"],
            ["concepts.course_id", "concepts.id"],
            ondelete="RESTRICT",
        ),
        Index(
            "uq_misconception_related_ordinal",
            "course_id",
            "misconception_id",
            "ordinal",
            unique=True,
        ),
    )


class ConceptEdgeRow(Base):
    __tablename__ = "concept_edges"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    source_concept_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    edge_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_concept_id: Mapped[str | None] = mapped_column(String(256))
    target_misconception_id: Mapped[str | None] = mapped_column(String(256))
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(["course_id", "source_concept_id"], ["concepts.course_id", "concepts.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["course_id", "target_concept_id"], ["concepts.course_id", "concepts.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["course_id", "target_misconception_id"], ["misconception_patterns.course_id", "misconception_patterns.id"], ondelete="CASCADE"),
        CheckConstraint(
            "(edge_type = 'explains_error' AND target_concept_id IS NULL AND target_misconception_id IS NOT NULL) OR "
            "(edge_type <> 'explains_error' AND target_concept_id IS NOT NULL AND target_misconception_id IS NULL)",
            name="ck_concept_edges_target_kind",
        ),
        CheckConstraint("edge_type IN ('prerequisite','confusable_with','used_by','explains_error')", name="ck_concept_edges_type"),
        Index("ix_concept_edges_course_source", "course_id", "source_concept_id"),
        Index("ix_concept_edges_course_target", "course_id", "target_id"),
    )


_SUBMISSION_STATUS_SQL = (
    "'received','executing','executed','execution_unavailable',"
    "'diagnosing','diagnosed','needs_review'"
)


class SubmissionRow(Base):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    exercise_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_files: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(255), nullable=False)
    is_formal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["exercise_id", "course_id"],
            ["exercises.id", "exercises.course_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "course_id", name="uq_submissions_id_course"),
        CheckConstraint(
            f"status IN ({_SUBMISSION_STATUS_SQL})", name="ck_submissions_status"
        ),
        Index("ix_submissions_exercise_owner", "exercise_id", "owner_user_id"),
        Index("ix_submissions_status", "status"),
    )


class SubmissionTransitionRow(Base):
    __tablename__ = "submission_transitions"
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_SUBMISSION_STATUS_SQL})",
            name="ck_submission_transitions_from",
        ),
        CheckConstraint(
            f"to_status IN ({_SUBMISSION_STATUS_SQL})",
            name="ck_submission_transitions_to",
        ),
        Index("ix_submission_transitions_changed_at", "changed_at"),
    )


class ExecutionResultRow(Base):
    __tablename__ = "execution_results"
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True
    )
    protocol_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    signal: Mapped[int | None] = mapped_column(Integer)
    stdout: Mapped[str] = mapped_column(Text, nullable=False)
    stderr: Mapped[str] = mapped_column(Text, nullable=False)
    stdout_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stderr_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    command_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    toolchain: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded','compile_failed','run_failed','timed_out','resource_exhausted')",
            name="ck_execution_results_status",
        ),
        CheckConstraint(
            "phase IN ('compile','run','control')", name="ck_execution_results_phase"
        ),
    )


class RuleMatchRow(Base):
    __tablename__ = "rule_matches"
    submission_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    misconception_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    root_concept_id: Mapped[str] = mapped_column(String(256), nullable=False)
    diagnostic_indices: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    match_strength: Mapped[str] = mapped_column(String(16), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["submission_id", "course_id"],
            ["submissions.id", "submissions.course_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["course_id", "misconception_id"],
            ["misconception_patterns.course_id", "misconception_patterns.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["course_id", "root_concept_id"],
            ["concepts.course_id", "concepts.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "evidence_kind = 'compiler_diagnostic'",
            name="ck_rule_matches_evidence_kind",
        ),
        CheckConstraint(
            "match_strength IN ('strong','weak')", name="ck_rule_matches_strength"
        ),
        UniqueConstraint(
            "submission_id",
            "misconception_id",
            "course_id",
            name="uq_rule_matches_submission_misconception_course",
        ),
        Index(
            "ix_rule_matches_course_misconception", "course_id", "misconception_id"
        ),
        Index("ix_rule_matches_course_root", "course_id", "root_concept_id"),
    )


class RuleMatchRelatedConceptRow(Base):
    __tablename__ = "rule_match_related_concepts"
    submission_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    misconception_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    concept_id: Mapped[str] = mapped_column(String(256), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["submission_id", "misconception_id", "course_id"],
            [
                "rule_matches.submission_id",
                "rule_matches.misconception_id",
                "rule_matches.course_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["course_id", "concept_id"],
            ["concepts.course_id", "concepts.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "submission_id",
            "misconception_id",
            "concept_id",
            name="uq_rule_match_related_concept",
        ),
        Index("ix_rule_match_related_course_concept", "course_id", "concept_id"),
    )
