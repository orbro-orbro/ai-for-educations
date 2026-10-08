"""Synthetic fixtures against the dedicated Gate PostgreSQL; no API facts double."""
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

import anyio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.api.auth import Authenticator, TokenCodec
from app.api.errors import install_error_handling
from app.api.teacher import create_teacher_router
from app.analytics.service import TeacherAnalyticsService
from app.auth.models import Actor, Role, User
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, Enrollment, Exercise
from app.courses.service import CourseService
from app.persistence.models import (Base, DiagnosisRow, DiagnosisConceptRow, SubmissionRow,
    ReviewQueueEventRow, ExplanationCheckRow, DiagnosisAttemptRow, ExecutionResultRow)
from app.persistence.repositories import create_sql_repositories
from tests.security.security_support import knowledge_for

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 7, 1, tzinfo=UTC)
SECRET = "synthetic-wave3-gate-secret-at-least-16-bytes"
PRIVATE = "PRIVATE_WAVE3_SENTINEL_DO_NOT_PROJECT"


def postgres_url(database="wave3_router"):
    value = os.environ.get("WAVE3_POSTGRES_URL", "postgresql+psycopg://knowbound:change-me@127.0.0.1:55430/wave3_router")
    url = make_url(value)
    if url.host != "127.0.0.1" or url.port != 55430 or url.database != "wave3_router" or not url.drivername.startswith("postgresql"):
        raise ValueError("Only the dedicated synthetic Gate router database is allowed")
    return url.set(database=database).render_as_string(hide_password=False)


def upgrade(database="wave3_router", revision="head"):
    if os.environ.get("DATABASE_URL"):
        raise ValueError("DATABASE_URL must not override isolated migration configuration")
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", postgres_url(database))
    command.upgrade(cfg, revision)
    return cfg


class Wave3PG:
    def __init__(self):
        upgrade()
        self.repos = create_sql_repositories(postgres_url())
        self.sessions = self.repos.memory_uow.sessions
        with self.sessions.begin() as session:
            # This database contains synthetic Gate fixtures only; never daily data.
            names = ", ".join('"' + name + '"' for name in Base.metadata.tables)
            session.execute(text("TRUNCATE TABLE " + names + " CASCADE"))
        self.repos.users.add(User.with_password("teacher-a", "teacher-a", "synthetic-password", Role.TEACHER))
        self.repos.users.add(User.with_password("teacher-b", "teacher-b", "synthetic-password", Role.TEACHER))
        self.courses = CourseService(self.repos.users, self.repos.courses, self.repos.enrollments, AuthorizationPolicy())
        self.auth = Authenticator(self.repos.users, TokenCodec(SECRET), self.repos.token_revocations)
        self.repository = None
        self.application = None

    def mount(self, repository=None):
        from app.analytics.persistence import SqlTeacherAnalyticsRepository
        self.repository = repository or SqlTeacherAnalyticsRepository(self.repos.memory_uow, secret=SECRET)
        from app.audit.persistence import SqlAuditLog
        self.audit = self.repos.audit if self.repository.uow is self.repos.memory_uow else SqlAuditLog(self.repository.uow)
        self.service = TeacherAnalyticsService(courses=self.courses, repository=self.repository, audit=self.audit, clock=lambda: NOW)
        self.application = FastAPI()
        install_error_handling(self.application)
        self.application.include_router(create_teacher_router(self.service, self.auth))

    def request(self, method, path, *, body=None, actor="teacher-a", headers=None, application=None):
        token, _ = self.auth.login(actor, "synthetic-password")
        target = application or self.application
        async def call():
            async with AsyncClient(transport=ASGITransport(app=target), base_url="http://gate") as client:
                return await client.request(method, path, json=body, headers={"Authorization": "Bearer " + token, **(headers or {})})
        return anyio.run(call)

    def get_analytics(self, course="course-a", filters=None):
        from urllib.parse import urlencode
        query = urlencode(filters or {})
        return self.request("GET", f"/teacher/courses/{course}/analytics" + ("?" + query if query else ""))

    def post_review(self, diagnosis="diag-0", decision="confirmed", reason="Course evidence reviewed", actor="teacher-a"):
        return self.request("POST", f"/teacher/diagnoses/{diagnosis}/review", body={"decision":decision, "reason":reason}, actor=actor)

    def seed_vector_facts(self, facts):
        courses = {f["course_id"] for f in facts}
        # Vectors use course-local exercise names; SQL uses global IDs plus a
        # composite course FK. Preserve every fact using a stable foreign-course
        # namespace; the requested course retains the frozen public IDs.
        exercise_ids = {(f["course_id"], f["exercise_id"]):
            f["exercise_id"] if f["course_id"] == "course-a" else f["course_id"] + "--" + f["exercise_id"]
            for f in facts if f["exercise_id"]}
        for course in sorted(courses):
            self.repos.courses.add(Course(course, "Synthetic 仓颉语言设计", "teacher-a", frozenset({"teacher-b"})))
            for exercise in sorted({f["exercise_id"] for f in facts if f["course_id"] == course and f["exercise_id"]}):
                self.repos.courses.add_exercise(Exercise(exercise_ids[course,exercise], course, "Synthetic exercise", True))
            concepts = {f["concept_id"] for f in facts if f["course_id"] == course}
            # Every concept has separately approved synthetic course evidence.
            from app.knowledge.models import Concept, MisconceptionPattern
            from app.knowledge.repository import InMemoryKnowledgeRepository
            concept_models, misconception_models = [], []
            for concept in sorted(concepts):
                temporary = InMemoryKnowledgeRepository()
                knowledge_for(temporary, course, concept=concept)
                graph = temporary.graph(course)
                concept_models.extend(graph.concepts.values())
                misconception_models.extend(m.model_copy(update={"id":"cj.synthetic."+concept.removeprefix("cj.")}) for m in graph.misconceptions.values())
            self.repos.knowledge.load_course(course, concept_models, [], misconception_models)
        students = sorted({f["subject_key"] for f in facts})
        mapping = {key: "synthetic-student-"+str(i) for i, key in enumerate(students)}
        for key, uid in mapping.items():
            self.repos.users.add(User.with_password(uid, uid, "synthetic-password", Role.STUDENT))
        for course in courses:
            for key in {f["subject_key"] for f in facts if f["course_id"] == course}:
                self.repos.enrollments.add(Enrollment(course, mapping[key], Role.STUDENT))
        self.subject_mapping = mapping
        for f in facts:
            at = datetime.fromisoformat(f["created_at"].replace("Z", "+00:00"))
            did, course, owner = f["diagnosis_id"], f["course_id"], mapping[f["subject_key"]]
            exercise = f["exercise_id"]
            if exercise is not None:
                exercise = exercise_ids[course,exercise]
            if exercise is None:
                exercise = "synthetic-unassigned-" + course
                if exercise not in {e.exercise_id for e in self.repos.courses.list_exercises(course)}:
                    self.repos.courses.add_exercise(Exercise(exercise, course, "Synthetic unassigned", True))
            sid = "sub-" + did
            self.repos.submissions.create(submission_id=sid, course_id=course, exercise_id=exercise, owner_user_id=owner,
                source_files=[{"path":"main.cj", "content":PRIVATE}], entrypoint="main.cj", is_formal=True, request_id=sid)
            with self.sessions.begin() as session:
                session.execute(text("UPDATE submissions SET created_at=:at WHERE id=:sid"), {"at":at, "sid":sid})
                session.add(DiagnosisRow(id=did, submission_id=sid, course_id=course, owner_user_id=owner, category=f["category"], locations=[],
                    root_cause=PRIVATE, confidence=.9, recommended_hint_level=1, requires_teacher_review=True, created_at=at, request_id=did))
                session.flush()
                session.add(DiagnosisConceptRow(diagnosis_id=did, course_id=course, concept_id=f["concept_id"], ordinal=0))
                session.add(ReviewQueueEventRow(id="queue-"+did, submission_id=sid, diagnosis_id=did, course_id=course, owner_user_id=owner,
                    reason="low_confidence", summary=PRIVATE, created_at=at, request_id=did))
            if f["independently_repaired"]:
                self.add_repair(did)

    def seed_diagnoses(self, students=5, duplicates=0):
        facts = [dict(diagnosis_id=f"diag-{i}", subject_key=f"student-{i % students}", course_id="course-a", concept_id="cj.pattern-match.exhaustiveness",
            exercise_id="exercise-a", category="conceptual", created_at=NOW.isoformat(), independently_repaired=False)
            for i in range(students+duplicates)]
        self.seed_vector_facts(facts)
        return facts

    def add_repair(self, diagnosis, *, understands=True, confidence=.9, linked=True, succeeded=True, hint4=False):
        with self.sessions() as session:
            d = session.get(DiagnosisRow, diagnosis)
            original = session.get(SubmissionRow, d.submission_id)
            owner, course, exercise, at = d.owner_user_id, d.course_id, original.exercise_id, original.created_at
        retry = "retry-"+diagnosis
        self.repos.submissions.create(submission_id=retry, course_id=course, exercise_id=exercise, owner_user_id=owner,
            source_files=[{"path":"main.cj", "content":PRIVATE}], entrypoint="main.cj", is_formal=True, request_id=retry)
        with self.sessions.begin() as session:
            session.execute(text("UPDATE submissions SET created_at=:at WHERE id=:sid"), {"at":at+timedelta(minutes=1), "sid":retry})
            session.add(ExecutionResultRow(submission_id=retry, protocol_version="2", status="succeeded" if succeeded else "compile_failed", phase="run" if succeeded else "compile",
                retryable=False, exit_code=0 if succeeded else 1, signal=None, stdout=PRIVATE, stderr=PRIVATE, stdout_truncated=False, stderr_truncated=False,
                diagnostics=[], command_summary={}, limits={}, toolchain={}, created_at=at+timedelta(minutes=2), request_id=retry))
            if linked:
                session.add(DiagnosisAttemptRow(diagnosis_id=diagnosis, attempt_key=retry, submission_id=retry, created_at=at+timedelta(minutes=1)))
            for i in range(2):
                session.add(ExplanationCheckRow(id=f"check-{diagnosis}-{i}", diagnosis_id=diagnosis, understands=understands, concept_ids=[], evidence_summary=PRIVATE,
                    confidence=confidence, feedback=PRIVATE, memory_proposal_eligible=False, created_at=at+timedelta(minutes=3), request_id=f"check-{diagnosis}-{i}"))
            if hint4:
                from app.persistence.models import HintEventRow
                session.add(HintEventRow(id="hint4-"+diagnosis, diagnosis_id=diagnosis, previous_level=3, current_level=4, reason=PRIVATE,
                    previous_attempt_count=1, content=PRIVATE, used_safe_fallback=False, created_at=at, request_id="hint4-"+diagnosis))

    def close(self):
        self.sessions.kw["bind"].dispose()

    def seed_private_memory(self, diagnosis="diag-0"):
        self.add_repair(diagnosis)
        from app.persistence.models import LearningMemoryRow
        with self.sessions.begin() as session:
            d = session.get(DiagnosisRow, diagnosis)
            d.requires_teacher_review = False
            concepts = session.scalars(select(DiagnosisConceptRow.concept_id).where(DiagnosisConceptRow.diagnosis_id == diagnosis)).all()
            for c in session.scalars(select(ExplanationCheckRow).where(ExplanationCheckRow.diagnosis_id == diagnosis)):
                c.concept_ids = list(concepts)
                c.memory_proposal_eligible = True
            owner = d.owner_user_id
        from app.memories.service import MemoryService
        from app.memories.policy import MemoryPolicy, CourseServiceMemoryAccess
        from app.memories.retrieval import InMemoryRetrievalIndex
        service = MemoryService(repository=self.repos.memories, policy=MemoryPolicy(CourseServiceMemoryAccess(self.courses)),
            source=self.repos.memory_source, retrieval_index=InMemoryRetrievalIndex(repository=self.repos.memories), audit=self.repos.audit)
        actor = Actor(owner, Role.STUDENT)
        proposal = service.create_proposal(actor, f"check-{diagnosis}-0", request_id="seed-memory")
        return service.accept_proposal(actor, proposal.proposal_id, request_id="seed-memory", idempotency_key="seed-memory")
