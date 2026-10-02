from __future__ import annotations

from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]


def test_two_ordered_migrations_define_identity_and_course_scoped_knowledge():
    first = (BACKEND / "migrations/versions/0001_identity_courses.py").read_text(encoding="utf-8")
    second = (BACKEND / "migrations/versions/0002_knowledge_graph.py").read_text(encoding="utf-8")

    for table in ("users", "courses", "course_authorized_teachers", "enrollments", "exercises"):
        assert f'"{table}"' in first
    for table in ("concepts", "misconception_patterns", "misconception_related_concepts", "concept_edges"):
        assert f'"{table}"' in second
    assert 'down_revision = "0001_identity_courses"' in second
    assert "ForeignKeyConstraint" in second
    assert "course_id" in second
    assert "review_status" in second
    assert "reviewed_by" in second
    assert "create_index" in second


def test_production_dependencies_include_database_and_seed_runtime_packages():
    pyproject = (BACKEND / "pyproject.toml").read_text(encoding="utf-8")
    dependencies = pyproject.split("[project.optional-dependencies]", 1)[0]
    for package in ("SQLAlchemy", "alembic", "psycopg", "PyYAML"):
        assert package in dependencies


def test_sqlalchemy_metadata_has_composite_course_keys_and_foreign_keys():
    from app.persistence.models import Base

    tables = Base.metadata.tables
    assert {"users", "courses", "enrollments", "exercises", "concepts", "misconception_patterns", "misconception_related_concepts", "concept_edges"} <= set(tables)
    for name in ("concepts", "misconception_patterns"):
        assert [column.name for column in tables[name].primary_key.columns] == ["course_id", "id"]
    edge_fks = {tuple(element.parent.name for element in constraint.elements) for constraint in tables["concept_edges"].foreign_key_constraints}
    assert ("course_id", "source_concept_id") in edge_fks
    assert ("course_id", "target_concept_id") in edge_fks
    assert ("course_id", "target_misconception_id") in edge_fks
    related_fks = {tuple(element.parent.name for element in constraint.elements) for constraint in tables["misconception_related_concepts"].foreign_key_constraints}
    assert ("course_id", "misconception_id") in related_fks
    assert ("course_id", "concept_id") in related_fks


def test_sql_repositories_survive_adapter_recreation(tmp_path):
    from app.auth.models import Role, User
    from app.courses.models import Course
    from app.knowledge.models import Concept, ReviewStatus, SourceMetadata, SourceKind, Topic, VerificationStatus
    from app.persistence.repositories import create_sql_repositories

    database_url = f"sqlite:///{(tmp_path / 'persistence.db').as_posix()}"
    first = create_sql_repositories(database_url, create_schema=True)
    first.users.add(User.with_password("teacher-1", "teacher", "pw", Role.TEACHER))
    first.courses.add(Course("course-1", "仓颉语言设计", "teacher-1"))
    first.knowledge.create_concept(
        "course-1",
        Concept(
            id="cj.basics.entrypoint",
            topic=Topic.basics_control_flow,
            title="入口",
            summary="main",
            review_status=ReviewStatus.pending_review,
            source=SourceMetadata(
                kind=SourceKind.teacher_authored,
                references=["course"],
                toolchain_version="cjc 1.2.0 (cjnative)",
                verification_status=VerificationStatus.teacher_asserted,
            ),
        ),
    )
    snapshot = first.knowledge.graph("course-1")
    first.knowledge.load_course(
        "course-1",
        snapshot.concepts.values(),
        snapshot.edges,
        snapshot.misconceptions.values(),
    )

    second = create_sql_repositories(database_url)

    assert second.users.get("teacher-1").username == "teacher"
    assert second.courses.get("course-1").owner_teacher_id == "teacher-1"
    assert second.knowledge.get_concept("course-1", "cj.basics.entrypoint").title == "入口"


def test_composed_app_uses_sql_repositories_when_database_url_is_configured(monkeypatch, tmp_path):
    from app.main import create_app
    from app.persistence.repositories import SqlKnowledgeRepository

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    app = create_app()

    assert isinstance(app.state.knowledge_repository, SqlKnowledgeRepository)


def test_full_seed_import_is_sql_idempotent_and_starts_without_evidence(tmp_path):
    from app.auth.models import Role, User
    from app.courses.models import Course
    from app.knowledge.seed import DEFAULT_SEED_DIR, import_seed, load_seed
    from app.persistence.repositories import create_sql_repositories

    repositories = create_sql_repositories(
        f"sqlite:///{(tmp_path / 'seed.db').as_posix()}", create_schema=True
    )
    repositories.users.add(User.with_password("teacher-1", "teacher", "pw", Role.TEACHER))
    repositories.courses.add(Course("course-cj", "仓颉语言设计", "teacher-1"))
    bundle = load_seed(DEFAULT_SEED_DIR)

    import_seed(repositories.knowledge, "course-cj", bundle)
    import_seed(repositories.knowledge, "course-cj", bundle)

    assert len(repositories.knowledge.list_concepts("course-cj")) == 48
    assert len(repositories.knowledge.list_misconceptions("course-cj")) == 29
    assert repositories.knowledge.approved_evidence("course-cj") == []


def test_bootstrap_creates_idempotent_login_course_and_pending_seed(tmp_path):
    from app.api.auth import Authenticator, TokenCodec
    from app.persistence.bootstrap import bootstrap

    database_url = f"sqlite:///{(tmp_path / 'bootstrap.db').as_posix()}"
    first = bootstrap(
        database_url,
        teacher_username="teacher",
        teacher_password="teacher-password",
        student_username="student",
        student_password="student-password",
        create_schema=True,
    )
    second = bootstrap(
        database_url,
        teacher_username="teacher",
        teacher_password="teacher-password",
        student_username="student",
        student_password="student-password",
    )

    token, actor = Authenticator(second.users, TokenCodec("bootstrap-test-token-secret")).login(
        "teacher", "teacher-password"
    )
    assert token and actor.role.value == "teacher"
    assert first.courses.get("cangjie-language-design").owner_teacher_id == "bootstrap-teacher"
    assert len(second.knowledge.list_concepts("cangjie-language-design")) == 48
    assert second.knowledge.approved_evidence("cangjie-language-design") == []
