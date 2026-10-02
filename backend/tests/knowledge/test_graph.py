import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import knowledge as knowledge_api
from app.knowledge.models import (
    Concept,
    ConceptEdge,
    EdgeType,
    KnowledgeValidationError,
    MisconceptionPattern,
    ReviewStatus,
    parse_concept,
    parse_edge,
    parse_misconception,
)
from app.knowledge.repository import (
    InMemoryKnowledgeRepository,
    KnowledgeGraph,
    UnapprovedEvidenceError,
)

TOOLCHAIN = "cjc 1.2.0 (cjnative) / cjpm 1.2.0"


def source(**overrides):
    data = {
        "kind": "toolchain_experiment",
        "references": ["exp:match_non_exhaustive"],
        "toolchain_version": TOOLCHAIN,
        "verification_status": "experiment_verified",
    }
    data.update(overrides)
    return data


def concept_data(concept_id, status="approved", topic="enum_match"):
    return {
        "id": concept_id,
        "topic": topic,
        "title": concept_id,
        "summary": "summary",
        "review_status": status,
        "source": source(),
    }


def hint_ladder():
    return [{"level": level, "outline": f"step {level}"} for level in (1, 2, 3, 4)]


def misconception_data(mid, root, status="approved"):
    return {
        "id": mid,
        "topic": "enum_match",
        "title": "match without wildcard",
        "root_concept_id": root,
        "related_concept_ids": [],
        "trigger_evidence": [
            {"kind": "compiler_diagnostic", "pattern": "non-exhaustive patterns", "strength": "strong"}
        ],
        "explanation": "match must be exhaustive",
        "hint_ladder": hint_ladder(),
        "review_status": status,
        "source": source(),
        "verification": {
            "method": "cjc_minimal_repro",
            "toolchain_version": TOOLCHAIN,
            "expected_outcome": "compile_error",
            "snippet": "main() {}",
            "note": "verified",
        },
    }


def edge(src, dst, edge_type="prerequisite"):
    return ConceptEdge(source_id=src, target_id=dst, edge_type=EdgeType(edge_type))


def concepts(*ids, status="approved"):
    return [Concept.model_validate(concept_data(cid, status)) for cid in ids]


ENUM = "cj.enum.declaration"
MATCH = "cj.pattern-match.match-expression"
EXHAUSTIVE = "cj.pattern-match.exhaustiveness"
MIS = "cj.misconception.match-non-exhaustive"


def small_graph(mis_status="approved", root_status="approved"):
    cs = concepts(ENUM, MATCH) + [Concept.model_validate(concept_data(EXHAUSTIVE, root_status))]
    edges = [edge(ENUM, MATCH), edge(MATCH, EXHAUSTIVE)]
    mis = [MisconceptionPattern.model_validate(misconception_data(MIS, EXHAUSTIVE, mis_status))]
    return KnowledgeGraph.build(cs, edges, mis)


def assert_code(exc_info, code):
    assert exc_info.value.code == code, exc_info.value


def test_valid_graph_traverses_transitive_prerequisites():
    graph = small_graph()
    assert graph.prerequisites_of(EXHAUSTIVE) == [MATCH, ENUM]
    assert graph.dependents_of(ENUM) == [MATCH, EXHAUSTIVE]
    assert [m.id for m in graph.misconceptions_for_concept(EXHAUSTIVE)] == [MIS]


def test_rejects_duplicate_concept_id():
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM, ENUM), [], [])
    assert_code(exc, "DUPLICATE_ID")


def test_rejects_duplicate_misconception_id():
    mis = MisconceptionPattern.model_validate(misconception_data(MIS, ENUM))
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM), [], [mis, mis])
    assert_code(exc, "DUPLICATE_ID")


def test_rejects_id_shared_between_concept_and_misconception():
    mis = MisconceptionPattern.model_validate(misconception_data(ENUM, ENUM))
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM), [], [mis])
    assert_code(exc, "DUPLICATE_ID")


def test_rejects_edge_to_missing_node():
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM), [edge(ENUM, "cj.missing.node")], [])
    assert_code(exc, "UNKNOWN_NODE")


def test_rejects_misconception_with_missing_root_concept():
    mis = MisconceptionPattern.model_validate(misconception_data(MIS, "cj.missing.node"))
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM), [], [mis])
    assert_code(exc, "UNKNOWN_NODE")


def test_rejects_prerequisite_cycle():
    edges = [edge(ENUM, MATCH), edge(MATCH, EXHAUSTIVE), edge(EXHAUSTIVE, ENUM)]
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM, MATCH, EXHAUSTIVE), edges, [])
    assert_code(exc, "PREREQUISITE_CYCLE")
    assert ENUM in str(exc.value)


def test_rejects_prerequisite_self_loop():
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM), [edge(ENUM, ENUM)], [])
    assert_code(exc, "PREREQUISITE_CYCLE")


@pytest.mark.parametrize("edge_type", ["confusable_with", "used_by"])
def test_non_prerequisite_edges_may_be_bidirectional_or_cyclic(edge_type):
    edges = [
        edge(ENUM, MATCH, edge_type),
        edge(MATCH, ENUM, edge_type),
        edge(MATCH, EXHAUSTIVE, edge_type),
        edge(EXHAUSTIVE, ENUM, edge_type),
    ]
    graph = KnowledgeGraph.build(concepts(ENUM, MATCH, EXHAUSTIVE), edges, [])
    assert set(graph.neighbors(MATCH, EdgeType(edge_type))) == {ENUM, EXHAUSTIVE}


def test_explains_error_must_link_concept_to_misconception():
    mis = MisconceptionPattern.model_validate(misconception_data(MIS, EXHAUSTIVE))
    cs = concepts(MATCH, EXHAUSTIVE)
    graph = KnowledgeGraph.build(cs, [edge(MATCH, MIS, "explains_error")], [mis])
    assert [m.id for m in graph.misconceptions_for_concept(MATCH)] == [MIS]
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(cs, [edge(MIS, MATCH, "explains_error")], [mis])
    assert_code(exc, "INVALID_EDGE_ENDPOINT")
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(cs, [edge(MATCH, MIS, "prerequisite")], [mis])
    assert_code(exc, "INVALID_EDGE_ENDPOINT")


def test_rejects_duplicate_edge():
    with pytest.raises(KnowledgeValidationError) as exc:
        KnowledgeGraph.build(concepts(ENUM, MATCH), [edge(ENUM, MATCH), edge(ENUM, MATCH)], [])
    assert_code(exc, "EDGE_CONFLICT")


def test_approved_evidence_excludes_unreviewed_misconceptions():
    graph = small_graph(mis_status="pending_review")
    assert graph.approved_evidence() == []
    with pytest.raises(UnapprovedEvidenceError):
        graph.get_approved_misconception(MIS)


def test_approved_evidence_requires_approved_root_concept():
    graph = small_graph(root_status="pending_review")
    assert graph.approved_evidence() == []
    with pytest.raises(UnapprovedEvidenceError):
        graph.get_approved_misconception(MIS)


def test_approved_evidence_requires_every_related_concept_to_be_approved():
    pending_related = Concept.model_validate(concept_data(MATCH, "pending_review"))
    root = Concept.model_validate(concept_data(EXHAUSTIVE, "approved"))
    data = misconception_data(MIS, EXHAUSTIVE)
    data["related_concept_ids"] = [MATCH]
    misconception = MisconceptionPattern.model_validate(data)

    graph = KnowledgeGraph.build([pending_related, root], [], [misconception])

    assert graph.approved_evidence() == []
    with pytest.raises(UnapprovedEvidenceError):
        graph.get_approved_misconception(MIS)


def test_approved_evidence_requires_explaining_concept_to_be_approved():
    pending_explainer = Concept.model_validate(concept_data(MATCH, "pending_review"))
    root = Concept.model_validate(concept_data(EXHAUSTIVE, "approved"))
    misconception = MisconceptionPattern.model_validate(misconception_data(MIS, EXHAUSTIVE))

    graph = KnowledgeGraph.build(
        [pending_explainer, root],
        [edge(MATCH, MIS, "explains_error")],
        [misconception],
    )

    assert graph.approved_evidence() == []


def test_approved_evidence_returns_reviewed_pattern_with_source():
    graph = small_graph()
    evidence = graph.approved_evidence(concept_ids=[EXHAUSTIVE])
    assert [e.misconception_id for e in evidence] == [MIS]
    assert evidence[0].root_concept_id == EXHAUSTIVE
    assert evidence[0].source.toolchain_version == TOOLCHAIN
    assert graph.get_approved_misconception(MIS).misconception_id == MIS
    assert graph.approved_evidence(concept_ids=[ENUM]) == []


@pytest.mark.parametrize("status", ["draft", "pending_review", "rejected"])
def test_every_non_approved_status_is_excluded(status):
    assert small_graph(mis_status=status).approved_evidence() == []


def test_parse_rejects_unknown_review_status():
    with pytest.raises(KnowledgeValidationError) as exc:
        parse_concept(concept_data(ENUM, status="teacher_liked_it"))
    assert_code(exc, "UNKNOWN_REVIEW_STATUS")
    with pytest.raises(KnowledgeValidationError) as exc:
        parse_misconception(misconception_data(MIS, ENUM, status="auto"))
    assert_code(exc, "UNKNOWN_REVIEW_STATUS")


def test_parse_rejects_unknown_edge_type():
    with pytest.raises(KnowledgeValidationError) as exc:
        parse_edge({"source_id": ENUM, "target_id": MATCH, "edge_type": "similar_to"})
    assert_code(exc, "UNKNOWN_EDGE_TYPE")


@pytest.mark.parametrize("missing", [None, "references", "toolchain_version", "verification_status"])
def test_parse_rejects_missing_source_metadata(missing):
    data = concept_data(ENUM)
    if missing is None:
        del data["source"]
    else:
        del data["source"][missing]
    with pytest.raises(KnowledgeValidationError) as exc:
        parse_concept(data)
    assert_code(exc, "MISSING_SOURCE")


def test_parse_rejects_empty_source_references():
    data = misconception_data(MIS, ENUM)
    data["source"]["references"] = []
    with pytest.raises(KnowledgeValidationError) as exc:
        parse_misconception(data)
    assert_code(exc, "MISSING_SOURCE")


@pytest.mark.parametrize("bad_id", ["pattern-match", "cj.Pattern.Match", "cj.only", "cj..x", "cj.a_b.c"])
def test_parse_rejects_unstable_ids(bad_id):
    with pytest.raises(KnowledgeValidationError) as exc:
        parse_concept(concept_data(bad_id))
    assert_code(exc, "VALIDATION_ERROR")


def test_misconception_requires_four_level_hint_ladder():
    data = misconception_data(MIS, ENUM)
    data["hint_ladder"] = hint_ladder()[:3]
    with pytest.raises(KnowledgeValidationError):
        parse_misconception(data)
    data["hint_ladder"] = list(reversed(hint_ladder()))
    with pytest.raises(KnowledgeValidationError):
        parse_misconception(data)


def test_misconception_requires_trigger_evidence():
    data = misconception_data(MIS, ENUM)
    data["trigger_evidence"] = []
    with pytest.raises(KnowledgeValidationError):
        parse_misconception(data)


def test_repository_rejects_mutation_that_breaks_graph_atomically():
    repo = InMemoryKnowledgeRepository()
    for c in concepts(ENUM, MATCH):
        repo.create_concept("course-1", c.model_copy(update={"review_status": ReviewStatus.pending_review}))
    repo.add_edge("course-1", edge(ENUM, MATCH))
    with pytest.raises(KnowledgeValidationError):
        repo.add_edge("course-1", edge(MATCH, ENUM))
    assert len(repo.list_edges("course-1")) == 1


def test_repository_isolates_courses():
    repo = InMemoryKnowledgeRepository()
    repo.create_concept("course-1", concepts(ENUM)[0])
    assert repo.get_concept("course-2", ENUM) is None
    assert repo.list_concepts("course-2") == []


# ---------------------------------------------------------------- API

COURSE = "course-1"
OWNER = "teacher-1"


def make_app(owner_courses=None, repo=None):
    app = FastAPI()
    app.include_router(knowledge_api.router)
    repo = repo or InMemoryKnowledgeRepository()
    app.dependency_overrides[knowledge_api.get_knowledge_repository] = lambda: repo
    if owner_courses is not None:

        def authorize(course_id: str) -> knowledge_api.CourseAuthorization:
            if course_id in owner_courses:
                return knowledge_api.CourseAuthorization.allow(OWNER, course_id)
            return knowledge_api.CourseAuthorization.deny()

        app.dependency_overrides[knowledge_api.authorize_course_teacher] = authorize
    return app, repo


def call(app, method, url, json=None):
    async def go():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            return await client.request(method, url, json=json, headers={"X-Request-ID": "req-1"})

    return anyio.run(go)


def create_payload(concept_id):
    data = concept_data(concept_id)
    del data["review_status"]
    return data


def mis_payload(mid, root):
    data = misconception_data(mid, root)
    del data["review_status"]
    return data


BASE = f"/teacher/courses/{COURSE}"


def test_api_denies_by_default_without_task2_authorizer():
    app, _ = make_app(owner_courses=None)
    response = call(app, "GET", f"{BASE}/concepts")
    assert response.status_code == 404
    assert response.json() == {
        "code": "RESOURCE_NOT_AVAILABLE",
        "message": "Resource is not available.",
        "request_id": "req-1",
    }


def test_api_foreign_course_and_unknown_resource_look_identical():
    app, _ = make_app(owner_courses={COURSE})
    foreign = call(app, "POST", "/teacher/courses/course-2/concepts", create_payload(ENUM))
    missing = call(app, "PATCH", f"{BASE}/concepts/cj.missing.node", {"title": "x"})
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["code"] == missing.json()["code"] == "RESOURCE_NOT_AVAILABLE"


def test_api_create_concept_starts_pending_review():
    app, repo = make_app(owner_courses={COURSE})
    response = call(app, "POST", f"{BASE}/concepts", create_payload(ENUM))
    assert response.status_code == 201
    assert response.json()["review_status"] == "pending_review"
    assert repo.get_concept(COURSE, ENUM) is not None
    assert call(app, "GET", f"{BASE}/concepts").json()[0]["id"] == ENUM


def test_api_rejects_client_supplied_review_status_and_missing_source():
    app, _ = make_app(owner_courses={COURSE})
    payload = create_payload(ENUM) | {"review_status": "approved"}
    assert call(app, "POST", f"{BASE}/concepts", payload).json()["code"] == "VALIDATION_ERROR"
    payload = create_payload(ENUM)
    del payload["source"]
    response = call(app, "POST", f"{BASE}/concepts", payload)
    assert response.status_code == 422
    assert response.json()["code"] == "MISSING_SOURCE"


def test_api_duplicate_concept_conflicts():
    app, _ = make_app(owner_courses={COURSE})
    call(app, "POST", f"{BASE}/concepts", create_payload(ENUM))
    response = call(app, "POST", f"{BASE}/concepts", create_payload(ENUM))
    assert response.status_code == 409
    assert response.json()["code"] == "KNOWLEDGE_ID_CONFLICT"


def test_api_review_then_update_resets_approval():
    app, _ = make_app(owner_courses={COURSE})
    call(app, "POST", f"{BASE}/concepts", create_payload(ENUM))
    reviewed = call(app, "POST", f"{BASE}/concepts/{ENUM}/review", {"decision": "approved", "note": "ok"})
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "approved"
    assert reviewed.json()["reviewed_by"] == OWNER
    updated = call(app, "PATCH", f"{BASE}/concepts/{ENUM}", {"summary": "changed"})
    assert updated.json()["review_status"] == "pending_review"
    assert updated.json()["reviewed_by"] is None


def test_api_rejects_unknown_review_decision():
    app, _ = make_app(owner_courses={COURSE})
    call(app, "POST", f"{BASE}/concepts", create_payload(ENUM))
    response = call(app, "POST", f"{BASE}/concepts/{ENUM}/review", {"decision": "maybe"})
    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_REVIEW_STATUS"


def test_api_misconception_lifecycle_feeds_approved_evidence_only_after_review():
    app, repo = make_app(owner_courses={COURSE})
    call(app, "POST", f"{BASE}/concepts", create_payload(EXHAUSTIVE))
    created = call(app, "POST", f"{BASE}/misconceptions", mis_payload(MIS, EXHAUSTIVE))
    assert created.status_code == 201
    assert created.json()["review_status"] == "pending_review"
    assert repo.approved_evidence(COURSE) == []

    blocked = call(app, "POST", f"{BASE}/misconceptions/{MIS}/review", {"decision": "approved"})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ROOT_CONCEPT_NOT_APPROVED"

    call(app, "POST", f"{BASE}/concepts/{EXHAUSTIVE}/review", {"decision": "approved"})
    approved = call(app, "POST", f"{BASE}/misconceptions/{MIS}/review", {"decision": "approved"})
    assert approved.json()["review_status"] == "approved"
    assert [e.misconception_id for e in repo.approved_evidence(COURSE)] == [MIS]

    call(app, "PATCH", f"{BASE}/misconceptions/{MIS}", {"explanation": "edited"})
    assert repo.approved_evidence(COURSE) == []


def test_api_misconception_with_unknown_root_is_rejected():
    app, _ = make_app(owner_courses={COURSE})
    response = call(app, "POST", f"{BASE}/misconceptions", mis_payload(MIS, "cj.missing.node"))
    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_NODE"


def test_api_edge_rules():
    app, _ = make_app(owner_courses={COURSE})
    for cid in (ENUM, MATCH):
        call(app, "POST", f"{BASE}/concepts", create_payload(cid))
    ok = call(app, "POST", f"{BASE}/concept-edges", {"source_id": ENUM, "target_id": MATCH, "edge_type": "prerequisite"})
    assert ok.status_code == 201
    cycle = call(app, "POST", f"{BASE}/concept-edges", {"source_id": MATCH, "target_id": ENUM, "edge_type": "prerequisite"})
    assert cycle.status_code == 422
    assert cycle.json()["code"] == "PREREQUISITE_CYCLE"
    back = call(app, "POST", f"{BASE}/concept-edges", {"source_id": MATCH, "target_id": ENUM, "edge_type": "confusable_with"})
    assert back.status_code == 201
    unknown = call(app, "POST", f"{BASE}/concept-edges", {"source_id": MATCH, "target_id": ENUM, "edge_type": "related"})
    assert unknown.json()["code"] == "UNKNOWN_EDGE_TYPE"
    assert len(call(app, "GET", f"{BASE}/concept-edges").json()) == 2
