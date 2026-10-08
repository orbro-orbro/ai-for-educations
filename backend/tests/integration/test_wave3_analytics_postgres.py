import pytest
from sqlalchemy import event, select
from app.persistence.models import DiagnosisConceptRow
from tests.integration.wave3_support import Wave3PG, PRIVATE, NOW


@pytest.fixture
def wave3_pg():
    pg = Wave3PG()
    yield pg
    pg.close()


def test_course_and_authorized_teacher_are_persisted_in_foreign_key_order(wave3_pg):
    from app.courses.models import Course
    course = Course("course-with-teacher", "Synthetic course", "teacher-a", frozenset({"teacher-b"}))
    wave3_pg.repos.courses.add(course)
    assert wave3_pg.repos.courses.get(course.course_id) == course


@pytest.mark.parametrize("students,status", [(4,"insufficient_sample"),(5,"available")])
def test_distinct_students_at_sql_boundary(wave3_pg, students, status):
    wave3_pg.seed_diagnoses(students=students, duplicates=3)
    wave3_pg.mount()
    response = wave3_pg.get_analytics()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status
    if students == 4:
        assert set(body) == {"status","course_id","filters","minimum_sample_size"}
    else:
        assert body["sample_size"] == 5
        assert body["groups"][0]["diagnosis_count"] == 8
    assert PRIVATE not in response.text


def test_sql_queue_projects_course_evidence_without_private_text(wave3_pg, caplog):
    wave3_pg.seed_diagnoses()
    wave3_pg.seed_private_memory()
    wave3_pg.mount()
    statements = []
    engine = wave3_pg.sessions.kw["bind"]
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = wave3_pg.request("GET", "/teacher/courses/course-a/review-queue")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 5
        assert all(item["root_cause"] == "A match must cover all possible cases." for item in response.json()["items"])
        wave3_pg.get_analytics()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    forbidden = ("source_files", "diagnoses.root_cause", "review_queue_events.summary", "learning_memories", "memory_proposals", "explanation_checks.feedback", "execution_results.stdout")
    assert all(not any(name in query for name in forbidden) for query in statements)
    assert PRIVATE not in response.text + caplog.text + wave3_pg.repos.audit.serialized_events()


def test_sql_projection_deduplicates_concepts_and_rejects_mismatched_queue_relations(wave3_pg):
    from app.persistence.models import ReviewQueueEventRow
    wave3_pg.seed_diagnoses()
    with wave3_pg.sessions.begin() as session:
        from app.persistence.models import ConceptRow
        template = session.get(ConceptRow, ("course-a", "cj.pattern-match.exhaustiveness"))
        session.add(ConceptRow(course_id="course-a", id="cj.synthetic.additional", topic=template.topic, title="Additional concept", summary="Synthetic", review_status="approved", source=template.source))
        session.flush()
        for i in range(5):
            session.add(DiagnosisConceptRow(diagnosis_id=f"diag-{i}", course_id="course-a", concept_id="cj.synthetic.additional", ordinal=1))
        for name, diagnosis in [("null",None), ("mismatch","diag-1")]:
            session.add(ReviewQueueEventRow(id=name, submission_id="sub-diag-0", diagnosis_id=diagnosis, course_id="course-a", owner_user_id="synthetic-student-0",
                reason=PRIVATE, summary=PRIVATE, created_at=NOW, request_id=name))
    wave3_pg.mount()
    body = wave3_pg.get_analytics().json()
    assert body["sample_size"] == 5
    assert len(body["groups"]) == 2
    assert [g["diagnosis_count"] for g in body["groups"]] == [5,5]
    queue = wave3_pg.request("GET", "/teacher/courses/course-a/review-queue").json()
    assert len(queue["items"]) == 5
    assert not {"null","mismatch"} & {q["queue_event_id"] for q in queue["items"]}


def test_sql_time_window_is_half_open_and_subject_keys_are_distinct_across_courses(wave3_pg):
    from datetime import timedelta
    facts = [dict(diagnosis_id=f"diag-{i}", subject_key=f"student-{i}", course_id="course-a", concept_id="cj.pattern-match.exhaustiveness",
        exercise_id="exercise-a", category="conceptual", created_at=(NOW+timedelta(hours=1) if i == 4 else NOW).isoformat(), independently_repaired=False) for i in range(5)]
    facts.append({**facts[0], "diagnosis_id":"other-course", "course_id":"course-b", "exercise_id":"exercise-b"})
    wave3_pg.seed_vector_facts(facts)
    wave3_pg.mount()
    response = wave3_pg.get_analytics(filters={"start_at":NOW.isoformat(), "end_at":(NOW+timedelta(hours=1)).isoformat()})
    assert response.json()["status"] == "insufficient_sample"
    assert wave3_pg.get_analytics().json()["sample_size"] == 5
    a = next(f for f in wave3_pg.repository.list_facts("course-a") if f.diagnosis_id == "diag-0")
    b = wave3_pg.repository.list_facts("course-b")[0]
    assert a.subject_key != b.subject_key


@pytest.mark.parametrize("options,repaired", [({},True), ({"understands":False},False), ({"confidence":.2},False), ({"linked":False},False), ({"succeeded":False},False), ({"hint4":True},False)])
def test_independent_repair_requires_explicit_successful_retry_and_understanding(wave3_pg, options, repaired):
    wave3_pg.seed_diagnoses()
    wave3_pg.add_repair("diag-0", **options)
    wave3_pg.mount()
    body = wave3_pg.get_analytics().json()
    assert body["groups"][0]["diagnosis_count"] == 5
    assert body["groups"][0]["independent_repair_count"] == int(repaired)


def test_subject_key_is_course_scoped_and_never_public(wave3_pg):
    facts = wave3_pg.seed_diagnoses()
    wave3_pg.mount()
    internal = wave3_pg.repository.list_facts("course-a")
    assert len({f.subject_key for f in internal}) == 5
    assert all(f.subject_key != f"student-{i}" for i,f in enumerate(internal))
    response = wave3_pg.get_analytics()
    assert all(f.subject_key not in response.text for f in internal)
    from app.analytics.persistence import subject_key
    assert subject_key("same-owner", "course-a", "secret") != subject_key("same-owner", "course-b", "secret")
