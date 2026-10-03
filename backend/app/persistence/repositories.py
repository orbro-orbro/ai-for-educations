from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import Role, User
from app.courses.models import Course, Enrollment, Exercise
from app.knowledge.models import Concept, ConceptEdge, EdgeType, KnowledgeValidationError, MisconceptionPattern
from app.knowledge.repository import ApprovedEvidence, KnowledgeGraph
from app.persistence.models import (
    Base,
    ConceptEdgeRow,
    ConceptRow,
    CourseAuthorizedTeacherRow,
    CourseRow,
    EnrollmentRow,
    ExerciseRow,
    MisconceptionRelatedConceptRow,
    MisconceptionRow,
    UserRow,
)

if TYPE_CHECKING:
    from app.submissions.persistence import SqlSubmissionRepository


class SqlUserRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, user: User) -> None:
        try:
            with self._sessions.begin() as session:
                session.add(UserRow(id=user.user_id, username=user.username, password_hash=user.password_hash, role=user.role.value, active=user.active))
        except IntegrityError as exc:
            raise ValueError("duplicate user") from exc

    def get(self, user_id: str) -> User | None:
        with self._sessions() as session:
            row = session.get(UserRow, user_id)
            return _user(row) if row else None

    def find_by_username(self, username: str) -> User | None:
        with self._sessions() as session:
            row = session.scalar(select(UserRow).where(UserRow.username == username))
            return _user(row) if row else None


class SqlCourseRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, course: Course) -> None:
        try:
            with self._sessions.begin() as session:
                session.add(CourseRow(id=course.course_id, title=course.title, owner_teacher_id=course.owner_teacher_id))
                session.add_all(
                    CourseAuthorizedTeacherRow(course_id=course.course_id, teacher_id=teacher_id)
                    for teacher_id in course.authorized_teacher_ids
                )
        except IntegrityError as exc:
            raise ValueError("duplicate or invalid course") from exc

    def get(self, course_id: str) -> Course | None:
        with self._sessions() as session:
            row = session.get(CourseRow, course_id)
            if row is None:
                return None
            teachers = session.scalars(
                select(CourseAuthorizedTeacherRow.teacher_id).where(CourseAuthorizedTeacherRow.course_id == course_id)
            ).all()
            return Course(row.id, row.title, row.owner_teacher_id, frozenset(teachers))

    def list_all(self) -> list[Course]:
        with self._sessions() as session:
            ids = session.scalars(select(CourseRow.id).order_by(CourseRow.id)).all()
        return [course for course_id in ids if (course := self.get(course_id)) is not None]

    def add_exercise(self, exercise: Exercise) -> None:
        try:
            with self._sessions.begin() as session:
                session.add(
                    ExerciseRow(
                        id=exercise.exercise_id,
                        course_id=exercise.course_id,
                        title=exercise.title,
                        is_published=exercise.is_published,
                    )
                )
        except IntegrityError as exc:
            raise ValueError("duplicate exercise or missing course") from exc

    def list_exercises(self, course_id: str) -> list[Exercise]:
        with self._sessions() as session:
            rows = session.scalars(select(ExerciseRow).where(ExerciseRow.course_id == course_id).order_by(ExerciseRow.id)).all()
            return [
                Exercise(row.id, row.course_id, row.title, row.is_published)
                for row in rows
            ]

    def set_protected_answer(
        self, course_id: str, exercise_id: str, answer: str | None
    ) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(ExerciseRow).where(
                    ExerciseRow.id == exercise_id,
                    ExerciseRow.course_id == course_id,
                )
            )
            if row is None:
                raise ValueError("exercise does not belong to course")
            row.protected_answer = answer

    def for_exercise(self, course_id: str, exercise_id: str) -> str | None:
        with self._sessions() as session:
            return session.scalar(
                select(ExerciseRow.protected_answer).where(
                    ExerciseRow.id == exercise_id,
                    ExerciseRow.course_id == course_id,
                )
            )


class SqlEnrollmentRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, enrollment: Enrollment) -> Enrollment:
        with self._sessions.begin() as session:
            existing = session.get(EnrollmentRow, (enrollment.course_id, enrollment.user_id))
            if existing is None:
                session.add(EnrollmentRow(course_id=enrollment.course_id, user_id=enrollment.user_id, role=enrollment.role.value))
        return enrollment

    def is_member(self, course_id: str, user_id: str) -> bool:
        with self._sessions() as session:
            return session.get(EnrollmentRow, (course_id, user_id)) is not None

    def member_user_ids(self, course_id: str) -> frozenset[str]:
        with self._sessions() as session:
            values = session.scalars(select(EnrollmentRow.user_id).where(EnrollmentRow.course_id == course_id)).all()
            return frozenset(values)


class SqlKnowledgeRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def list_concepts(self, course_id: str) -> list[Concept]:
        with self._sessions() as session:
            rows = session.scalars(select(ConceptRow).where(ConceptRow.course_id == course_id).order_by(ConceptRow.id)).all()
            return [_concept(row) for row in rows]

    def get_concept(self, course_id: str, concept_id: str) -> Concept | None:
        with self._sessions() as session:
            row = session.get(ConceptRow, (course_id, concept_id))
            return _concept(row) if row else None

    def create_concept(self, course_id: str, concept: Concept) -> Concept:
        KnowledgeGraph.build([*self.list_concepts(course_id), concept], self.list_edges(course_id), self.list_misconceptions(course_id))
        try:
            with self._sessions.begin() as session:
                session.add(_concept_row(course_id, concept))
        except IntegrityError as exc:
            raise KnowledgeValidationError("KNOWLEDGE_ID_CONFLICT", f"{concept.id} already exists") from exc
        return concept

    def replace_concept(self, course_id: str, concept: Concept) -> Concept:
        concepts = {item.id: item for item in self.list_concepts(course_id)}
        if concept.id not in concepts:
            raise KeyError(concept.id)
        concepts[concept.id] = concept
        KnowledgeGraph.build(concepts.values(), self.list_edges(course_id), self.list_misconceptions(course_id))
        with self._sessions.begin() as session:
            row = session.get(ConceptRow, (course_id, concept.id))
            _set_concept(row, concept)
        return concept

    def list_misconceptions(self, course_id: str) -> list[MisconceptionPattern]:
        with self._sessions() as session:
            rows = session.scalars(select(MisconceptionRow).where(MisconceptionRow.course_id == course_id).order_by(MisconceptionRow.id)).all()
            return [_misconception(row) for row in rows]

    def get_misconception(self, course_id: str, misconception_id: str) -> MisconceptionPattern | None:
        with self._sessions() as session:
            row = session.get(MisconceptionRow, (course_id, misconception_id))
            return _misconception(row) if row else None

    def create_misconception(self, course_id: str, item: MisconceptionPattern) -> MisconceptionPattern:
        KnowledgeGraph.build(self.list_concepts(course_id), self.list_edges(course_id), [*self.list_misconceptions(course_id), item])
        try:
            with self._sessions.begin() as session:
                session.add(_misconception_row(course_id, item))
                session.flush()
                session.add_all(_related_rows(course_id, item))
        except IntegrityError as exc:
            raise KnowledgeValidationError("KNOWLEDGE_ID_CONFLICT", f"{item.id} already exists") from exc
        return item

    def replace_misconception(self, course_id: str, item: MisconceptionPattern) -> MisconceptionPattern:
        items = {value.id: value for value in self.list_misconceptions(course_id)}
        if item.id not in items:
            raise KeyError(item.id)
        items[item.id] = item
        KnowledgeGraph.build(self.list_concepts(course_id), self.list_edges(course_id), items.values())
        with self._sessions.begin() as session:
            row = session.get(MisconceptionRow, (course_id, item.id))
            _set_misconception(row, item)
            session.execute(
                delete(MisconceptionRelatedConceptRow).where(
                    MisconceptionRelatedConceptRow.course_id == course_id,
                    MisconceptionRelatedConceptRow.misconception_id == item.id,
                )
            )
            session.add_all(_related_rows(course_id, item))
        return item

    def list_edges(self, course_id: str) -> list[ConceptEdge]:
        with self._sessions() as session:
            rows = session.scalars(select(ConceptEdgeRow).where(ConceptEdgeRow.course_id == course_id)).all()
            return [ConceptEdge(source_id=row.source_concept_id, target_id=row.target_id, edge_type=EdgeType(row.edge_type), note=row.note) for row in rows]

    def add_edge(self, course_id: str, edge: ConceptEdge) -> ConceptEdge:
        KnowledgeGraph.build(self.list_concepts(course_id), [*self.list_edges(course_id), edge], self.list_misconceptions(course_id))
        with self._sessions.begin() as session:
            session.add(_edge_row(course_id, edge))
        return edge

    def load_course(self, course_id: str, concepts: Iterable[Concept], edges: Iterable[ConceptEdge], misconceptions: Iterable[MisconceptionPattern]) -> None:
        incoming = KnowledgeGraph.build(concepts, edges, misconceptions)
        existing = self.graph(course_id)
        if existing.concepts or existing.edges or existing.misconceptions:
            if existing == incoming:
                return
            raise KnowledgeValidationError("KNOWLEDGE_ID_CONFLICT", f"course {course_id} already has different knowledge")
        with self._sessions.begin() as session:
            session.add_all(_concept_row(course_id, item) for item in incoming.concepts.values())
            session.flush()
            session.add_all(_misconception_row(course_id, item) for item in incoming.misconceptions.values())
            session.flush()
            session.add_all(
                related
                for item in incoming.misconceptions.values()
                for related in _related_rows(course_id, item)
            )
            session.flush()
            session.add_all(_edge_row(course_id, edge) for edge in incoming.edges)

    def graph(self, course_id: str) -> KnowledgeGraph:
        return KnowledgeGraph.build(self.list_concepts(course_id), self.list_edges(course_id), self.list_misconceptions(course_id))

    def approved_evidence(self, course_id: str, concept_ids=None, misconception_ids=None) -> list[ApprovedEvidence]:
        return self.graph(course_id).approved_evidence(concept_ids, misconception_ids)

    def get_approved_misconception(self, course_id: str, misconception_id: str) -> ApprovedEvidence:
        return self.graph(course_id).get_approved_misconception(misconception_id)


@dataclass(frozen=True)
class SqlRepositories:
    users: SqlUserRepository
    courses: SqlCourseRepository
    enrollments: SqlEnrollmentRepository
    knowledge: SqlKnowledgeRepository
    submissions: "SqlSubmissionRepository"


def create_sql_repositories(database_url: str, *, create_schema: bool = False) -> SqlRepositories:
    from app.submissions.persistence import SqlSubmissionRepository

    engine = create_engine(database_url, pool_pre_ping=True)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    if create_schema:
        Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    return SqlRepositories(
        SqlUserRepository(sessions),
        SqlCourseRepository(sessions),
        SqlEnrollmentRepository(sessions),
        SqlKnowledgeRepository(sessions),
        SqlSubmissionRepository(sessions),
    )


def _user(row: UserRow) -> User:
    return User(row.id, row.username, row.password_hash, Role(row.role), row.active)


def _concept(row: ConceptRow) -> Concept:
    return Concept.model_validate({
        "id": row.id, "topic": row.topic, "title": row.title, "summary": row.summary,
        "review_status": row.review_status, "reviewed_by": row.reviewed_by,
        "review_note": row.review_note, "source": row.source,
    })


def _concept_row(course_id: str, item: Concept) -> ConceptRow:
    data = item.model_dump(mode="json")
    return ConceptRow(course_id=course_id, **data)


def _set_concept(row: ConceptRow, item: Concept) -> None:
    for key, value in item.model_dump(mode="json").items():
        setattr(row, key, value)


def _misconception(row: MisconceptionRow) -> MisconceptionPattern:
    return MisconceptionPattern.model_validate({
        "id": row.id, "topic": row.topic, "title": row.title, "root_concept_id": row.root_concept_id,
        "related_concept_ids": row.related_concept_ids, "trigger_evidence": row.trigger_evidence,
        "explanation": row.explanation, "hint_ladder": row.hint_ladder,
        "review_status": row.review_status, "reviewed_by": row.reviewed_by, "review_note": row.review_note,
        "source": row.source, "verification": row.verification,
    })


def _misconception_row(course_id: str, item: MisconceptionPattern) -> MisconceptionRow:
    return MisconceptionRow(course_id=course_id, **item.model_dump(mode="json"))


def _set_misconception(row: MisconceptionRow, item: MisconceptionPattern) -> None:
    for key, value in item.model_dump(mode="json").items():
        setattr(row, key, value)


def _related_rows(course_id: str, item: MisconceptionPattern):
    return [
        MisconceptionRelatedConceptRow(
            course_id=course_id,
            misconception_id=item.id,
            concept_id=concept_id,
            ordinal=ordinal,
        )
        for ordinal, concept_id in enumerate(item.related_concept_ids)
    ]


def _edge_row(course_id: str, edge: ConceptEdge) -> ConceptEdgeRow:
    explains = edge.edge_type is EdgeType.explains_error
    return ConceptEdgeRow(
        course_id=course_id,
        source_concept_id=edge.source_id,
        target_id=edge.target_id,
        edge_type=edge.edge_type.value,
        target_concept_id=None if explains else edge.target_id,
        target_misconception_id=edge.target_id if explains else None,
        note=edge.note,
    )
