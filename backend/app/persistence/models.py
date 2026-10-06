from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
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
        UniqueConstraint(
            "id",
            "course_id",
            "owner_user_id",
            name="uq_submissions_id_course_owner",
        ),
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


class DiagnosisRow(Base):
    __tablename__ = "diagnoses"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    locations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_hint_level: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_teacher_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["submission_id", "course_id", "owner_user_id"],
            ["submissions.id", "submissions.course_id", "submissions.owner_user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "course_id", name="uq_diagnoses_id_course"),
        UniqueConstraint(
            "id",
            "course_id",
            "owner_user_id",
            name="uq_diagnoses_id_course_owner",
        ),
        CheckConstraint(
            "category IN ('conceptual','strategic','procedural','expression')",
            name="ck_diagnoses_category",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_diagnoses_confidence"),
        CheckConstraint(
            "recommended_hint_level >= 1 AND recommended_hint_level <= 4",
            name="ck_diagnoses_hint_level",
        ),
        Index("ix_diagnoses_course_owner", "course_id", "owner_user_id"),
    )


class DiagnosisConceptRow(Base):
    __tablename__ = "diagnosis_concepts"
    diagnosis_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    concept_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["diagnosis_id", "course_id"],
            ["diagnoses.id", "diagnoses.course_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["course_id", "concept_id"],
            ["concepts.course_id", "concepts.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("diagnosis_id", "ordinal", name="uq_diagnosis_concepts_ordinal"),
    )


class EvidenceBindingRow(Base):
    __tablename__ = "evidence_bindings"
    diagnosis_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    diagnostic_index: Mapped[int | None] = mapped_column(Integer)
    rule_submission_id: Mapped[str | None] = mapped_column(String(128))
    misconception_id: Mapped[str | None] = mapped_column(String(256))
    source_reference: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(
            ["diagnosis_id", "course_id"],
            ["diagnoses.id", "diagnoses.course_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["rule_submission_id", "misconception_id", "course_id"],
            ["rule_matches.submission_id", "rule_matches.misconception_id", "rule_matches.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["course_id", "misconception_id"],
            ["misconception_patterns.course_id", "misconception_patterns.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(kind = 'compiler_diagnostic' AND diagnostic_index IS NOT NULL AND rule_submission_id IS NULL AND misconception_id IS NULL AND source_reference IS NULL) OR "
            "(kind = 'rule_match' AND diagnostic_index IS NULL AND rule_submission_id IS NOT NULL AND misconception_id IS NOT NULL AND source_reference IS NULL) OR "
            "(kind = 'approved_knowledge' AND diagnostic_index IS NULL AND rule_submission_id IS NULL AND misconception_id IS NOT NULL AND source_reference IS NOT NULL)",
            name="ck_evidence_bindings_kind_fields",
        ),
    )


class ReviewQueueEventRow(Base):
    __tablename__ = "review_queue_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(128), nullable=False)
    diagnosis_id: Mapped[str | None] = mapped_column(ForeignKey("diagnoses.id", ondelete="CASCADE"))
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["submission_id", "course_id", "owner_user_id"],
            ["submissions.id", "submissions.course_id", "submissions.owner_user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("submission_id", "request_id", name="uq_review_queue_request"),
        Index("ix_review_queue_course_created", "course_id", "created_at"),
    )


class HintEventRow(Base):
    __tablename__ = "hint_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=False)
    previous_level: Mapped[int] = mapped_column(Integer, nullable=False)
    current_level: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    previous_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    used_safe_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        UniqueConstraint("diagnosis_id", "request_id", name="uq_hint_events_request"),
        UniqueConstraint("diagnosis_id", "current_level", name="uq_hint_events_level"),
        CheckConstraint("current_level = previous_level + 1", name="ck_hint_events_progression"),
        CheckConstraint("current_level >= 1 AND current_level <= 4", name="ck_hint_events_level"),
    )


class DiagnosisAttemptRow(Base):
    __tablename__ = "diagnosis_attempts"
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("diagnoses.id", ondelete="CASCADE"), primary_key=True)
    attempt_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_id: Mapped[str | None] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExplanationCheckRow(Base):
    __tablename__ = "explanation_checks"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=False)
    understands: Mapped[bool] = mapped_column(Boolean, nullable=False)
    concept_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    memory_proposal_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        UniqueConstraint("diagnosis_id", "request_id", name="uq_explanation_checks_request"),
        UniqueConstraint(
            "id", "diagnosis_id", name="uq_explanation_checks_id_diagnosis"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_explanation_checks_confidence"),
    )


class DiagnosisRunResultRow(Base):
    __tablename__ = "diagnosis_run_results"
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    result_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    diagnosis_id: Mapped[str | None] = mapped_column(ForeignKey("diagnoses.id", ondelete="CASCADE"))
    review_event_id: Mapped[str | None] = mapped_column(ForeignKey("review_queue_events.id", ondelete="CASCADE"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "result_kind IN ('diagnosis','review','evidence_unavailable')",
            name="ck_diagnosis_run_results_kind",
        ),
    )


class MemoryProposalRow(Base):
    __tablename__ = "memory_proposals"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    root_proposal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_proposal_id: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    diagnosis_id: Mapped[str] = mapped_column(String(128), nullable=False)
    explanation_check_id: Mapped[str | None] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    concept_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["diagnosis_id", "course_id", "owner_user_id"],
            ["diagnoses.id", "diagnoses.course_id", "diagnoses.owner_user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["explanation_check_id", "diagnosis_id"],
            ["explanation_checks.id", "explanation_checks.diagnosis_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["root_proposal_id", "owner_user_id", "course_id"],
            ["memory_proposals.id", "memory_proposals.owner_user_id", "memory_proposals.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_proposal_id", "owner_user_id", "course_id"],
            ["memory_proposals.id", "memory_proposals.owner_user_id", "memory_proposals.course_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "explanation_check_id", name="uq_memory_proposals_explanation_check"
        ),
        UniqueConstraint(
            "root_proposal_id", "version", name="uq_memory_proposals_root_version"
        ),
        UniqueConstraint(
            "previous_proposal_id", name="uq_memory_proposals_previous"
        ),
        UniqueConstraint(
            "id",
            "owner_user_id",
            "course_id",
            name="uq_memory_proposals_id_owner_course",
        ),
        CheckConstraint("version >= 1", name="ck_memory_proposals_version"),
        CheckConstraint(
            "(id = root_proposal_id AND previous_proposal_id IS NULL "
            "AND version = 1 AND explanation_check_id IS NOT NULL) OR "
            "(id <> root_proposal_id AND previous_proposal_id IS NOT NULL "
            "AND version > 1 AND explanation_check_id IS NULL)",
            name="ck_memory_proposals_lineage_shape",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_memory_proposals_confidence",
        ),
        CheckConstraint(
            "status IN ('pending','accepted','rejected','superseded','expired')",
            name="ck_memory_proposals_status",
        ),
        CheckConstraint(
            "expires_at > created_at", name="ck_memory_proposals_expiry"
        ),
        Index(
            "ix_memory_proposals_owner_course_status_expiry",
            "owner_user_id",
            "course_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_memory_proposals_root_version", "root_proposal_id", "version"
        ),
    )


class LearningMemoryRow(Base):
    __tablename__ = "learning_memories"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    logical_memory_id: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_version_id: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    concept_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_diagnosis_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_proposal_id: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    allowed_purposes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    index_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_proposal_id", "owner_user_id", "course_id"],
            ["memory_proposals.id", "memory_proposals.owner_user_id", "memory_proposals.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_diagnosis_id", "course_id", "owner_user_id"],
            ["diagnoses.id", "diagnoses.course_id", "diagnoses.owner_user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["logical_memory_id", "owner_user_id", "course_id"],
            ["learning_memories.id", "learning_memories.owner_user_id", "learning_memories.course_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_version_id", "owner_user_id", "course_id"],
            ["learning_memories.id", "learning_memories.owner_user_id", "learning_memories.course_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "source_proposal_id", name="uq_learning_memories_source_proposal"
        ),
        UniqueConstraint(
            "logical_memory_id",
            "version",
            name="uq_learning_memories_logical_version",
        ),
        UniqueConstraint(
            "previous_version_id", name="uq_learning_memories_previous"
        ),
        UniqueConstraint(
            "index_document_id", name="uq_learning_memories_index_document"
        ),
        UniqueConstraint(
            "id",
            "owner_user_id",
            "course_id",
            name="uq_learning_memories_id_owner_course",
        ),
        CheckConstraint("version >= 1", name="ck_learning_memories_version"),
        CheckConstraint(
            "(id = logical_memory_id AND previous_version_id IS NULL "
            "AND version = 1 AND source_proposal_id IS NOT NULL) OR "
            "(id <> logical_memory_id AND previous_version_id IS NOT NULL "
            "AND version > 1 AND source_proposal_id IS NULL)",
            name="ck_learning_memories_lineage_shape",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_learning_memories_confidence",
        ),
        CheckConstraint("visibility = 'private'", name="ck_learning_memories_visibility"),
        CheckConstraint(
            "status IN ('active','superseded','expired','deletion_pending','deleted')",
            name="ck_learning_memories_status",
        ),
        CheckConstraint(
            "status NOT IN ('deletion_pending','deleted') OR content IS NULL",
            name="ck_learning_memories_deleted_content",
        ),
        Index(
            "uq_learning_memories_one_active",
            "logical_memory_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_learning_memories_owner_course_status_expiry",
            "owner_user_id",
            "course_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_learning_memories_logical_version", "logical_memory_id", "version"
        ),
    )


class ShareGrantRow(Base):
    __tablename__ = "share_grants"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    grantee_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_id", "course_id", "owner_user_id"],
            ["diagnoses.id", "diagnoses.course_id", "diagnoses.owner_user_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "uq_share_grants_active_scope",
            "owner_user_id",
            "resource_id",
            "grantee_user_id",
            "purpose",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "resource_type = 'diagnosis_summary'",
            name="ck_share_grants_resource_type",
        ),
        CheckConstraint(
            "status IN ('active','revoked','expired')",
            name="ck_share_grants_status",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status <> 'revoked' AND revoked_at IS NULL)",
            name="ck_share_grants_revocation",
        ),
        Index(
            "ix_share_grants_grantee_course_status",
            "grantee_user_id",
            "course_id",
            "status",
        ),
        Index(
            "ix_share_grants_owner_course_status",
            "owner_user_id",
            "course_id",
            "status",
        ),
    )


class MemoryDeletionRow(Base):
    __tablename__ = "memory_deletions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    logical_memory_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    index_cleared: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cache_cleared: Mapped[bool] = mapped_column(Boolean, nullable=False)
    model_references_cleared: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reverse_lookup_absent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["logical_memory_id", "owner_user_id", "course_id"],
            ["learning_memories.id", "learning_memories.owner_user_id", "learning_memories.course_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "logical_memory_id", name="uq_memory_deletions_logical_memory"
        ),
        CheckConstraint(
            "status IN ('deletion_pending','deleted')",
            name="ck_memory_deletions_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_memory_deletions_attempts"),
        CheckConstraint(
            "(status = 'deletion_pending' AND completed_at IS NULL) OR "
            "(status = 'deleted' AND completed_at IS NOT NULL AND "
            "index_cleared AND cache_cleared AND model_references_cleared "
            "AND reverse_lookup_absent)",
            name="ck_memory_deletions_completion",
        ),
        Index(
            "ix_memory_deletions_owner_course_status",
            "owner_user_id",
            "course_id",
            "status",
        ),
    )


class MemoryTombstoneRow(Base):
    __tablename__ = "memory_tombstones"
    logical_memory_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    deletion_id: Mapped[str] = mapped_column(
        ForeignKey("memory_deletions.id", ondelete="RESTRICT"), nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["logical_memory_id", "owner_user_id", "course_id"],
            ["learning_memories.id", "learning_memories.owner_user_id", "learning_memories.course_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("deletion_id", name="uq_memory_tombstones_deletion"),
    )


class MemoryIdempotencyResultRow(Base):
    __tablename__ = "memory_idempotency_results"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)
    result_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "actor_user_id",
            "operation",
            "idempotency_key",
            name="uq_memory_idempotency_scope",
        ),
        Index(
            "ix_memory_idempotency_result", "result_type", "result_id"
        ),
    )


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    related_id: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        CheckConstraint(
            "actor_role IN ('student','teacher')",
            name="ck_audit_events_actor_role",
        ),
        CheckConstraint("length(outcome) > 0", name="ck_audit_events_outcome"),
        CheckConstraint(
            "length(reason_code) > 0", name="ck_audit_events_reason_code"
        ),
        Index("ix_audit_events_course_created", "course_id", "created_at"),
        Index("ix_audit_events_target", "target_type", "target_id"),
    )
