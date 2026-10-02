"""Validated knowledge graph, approved-evidence lookup and course-scoped repository."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Iterable, Protocol

from app.knowledge.models import (
    Concept,
    ConceptEdge,
    EdgeType,
    HintStep,
    KnowledgeValidationError,
    MisconceptionPattern,
    ReviewStatus,
    SourceMetadata,
    TriggerEvidence,
)

_CONCEPT_TO_CONCEPT = {EdgeType.prerequisite, EdgeType.confusable_with, EdgeType.used_by}


class UnapprovedEvidenceError(LookupError):
    """Raised when a misconception that is not approved is requested as diagnosis evidence."""


@dataclass(frozen=True)
class ApprovedEvidence:
    misconception_id: str
    root_concept_id: str
    related_concept_ids: tuple[str, ...]
    trigger_evidence: tuple[TriggerEvidence, ...]
    explanation: str
    hint_ladder: tuple[HintStep, ...]
    source: SourceMetadata

    @classmethod
    def of(cls, m: MisconceptionPattern) -> "ApprovedEvidence":
        return cls(
            misconception_id=m.id,
            root_concept_id=m.root_concept_id,
            related_concept_ids=tuple(m.related_concept_ids),
            trigger_evidence=tuple(m.trigger_evidence),
            explanation=m.explanation,
            hint_ladder=tuple(m.hint_ladder),
            source=m.source,
        )


class KnowledgeGraph:
    """Immutable, fully validated snapshot of one course's knowledge graph."""

    def __init__(
        self,
        concepts: dict[str, Concept],
        edges: tuple[ConceptEdge, ...],
        misconceptions: dict[str, MisconceptionPattern],
    ) -> None:
        self.concepts = concepts
        self.edges = edges
        self.misconceptions = misconceptions

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KnowledgeGraph):
            return NotImplemented
        return (
            self.concepts == other.concepts
            and set(self.edges) == set(other.edges)
            and self.misconceptions == other.misconceptions
        )

    @classmethod
    def build(
        cls,
        concepts: Iterable[Concept],
        edges: Iterable[ConceptEdge],
        misconceptions: Iterable[MisconceptionPattern],
    ) -> "KnowledgeGraph":
        concept_map: dict[str, Concept] = {}
        mis_map: dict[str, MisconceptionPattern] = {}
        for c in concepts:
            if c.id in concept_map:
                raise KnowledgeValidationError("DUPLICATE_ID", f"duplicate concept id {c.id}")
            concept_map[c.id] = c
        for m in misconceptions:
            if m.id in mis_map or m.id in concept_map:
                raise KnowledgeValidationError("DUPLICATE_ID", f"duplicate misconception id {m.id}")
            mis_map[m.id] = m

        for m in mis_map.values():
            for ref in (m.root_concept_id, *m.related_concept_ids):
                if ref not in concept_map:
                    raise KnowledgeValidationError("UNKNOWN_NODE", f"{m.id} references unknown concept {ref}")

        edge_list = tuple(edges)
        seen: set[tuple[str, str, EdgeType]] = set()
        for e in edge_list:
            label = f"{e.edge_type.value} edge {e.source_id}->{e.target_id}"
            for node in (e.source_id, e.target_id):
                if node not in concept_map and node not in mis_map:
                    raise KnowledgeValidationError("UNKNOWN_NODE", f"{label} points to unknown node {node}")
            if e.edge_type in _CONCEPT_TO_CONCEPT:
                valid = e.source_id in concept_map and e.target_id in concept_map
            else:
                valid = e.source_id in concept_map and e.target_id in mis_map
            if not valid:
                raise KnowledgeValidationError("INVALID_EDGE_ENDPOINT", f"{label} connects wrong node kinds")
            key = (e.source_id, e.target_id, e.edge_type)
            if key in seen:
                raise KnowledgeValidationError("EDGE_CONFLICT", f"duplicate {label}")
            seen.add(key)

        _ensure_prerequisites_acyclic(concept_map, edge_list)
        return cls(concept_map, edge_list, mis_map)

    def _targets(self, node: str, edge_type: EdgeType) -> list[str]:
        return [e.target_id for e in self.edges if e.edge_type is edge_type and e.source_id == node]

    def _sources(self, node: str, edge_type: EdgeType) -> list[str]:
        return [e.source_id for e in self.edges if e.edge_type is edge_type and e.target_id == node]

    def _walk(self, start: str, step) -> list[str]:
        order: list[str] = []
        visited = {start}
        queue = deque([start])
        while queue:
            for nxt in step(queue.popleft()):
                if nxt not in visited:
                    visited.add(nxt)
                    order.append(nxt)
                    queue.append(nxt)
        return order

    def prerequisites_of(self, concept_id: str) -> list[str]:
        """Transitive prerequisites, nearest first."""
        return self._walk(concept_id, lambda n: self._sources(n, EdgeType.prerequisite))

    def dependents_of(self, concept_id: str) -> list[str]:
        """Concepts that transitively require ``concept_id``, nearest first."""
        return self._walk(concept_id, lambda n: self._targets(n, EdgeType.prerequisite))

    def neighbors(self, node_id: str, edge_type: EdgeType) -> list[str]:
        """Direct neighbours over ``edge_type`` in either direction."""
        found = self._targets(node_id, edge_type) + self._sources(node_id, edge_type)
        return list(dict.fromkeys(found))

    def misconceptions_for_concept(self, concept_id: str) -> list[MisconceptionPattern]:
        ids = [m.id for m in self.misconceptions.values() if m.root_concept_id == concept_id]
        ids += self._targets(concept_id, EdgeType.explains_error)
        return [self.misconceptions[i] for i in dict.fromkeys(ids)]

    def _is_evidence(self, m: MisconceptionPattern) -> bool:
        referenced_concepts = {m.root_concept_id, *m.related_concept_ids}
        referenced_concepts.update(
            edge.source_id
            for edge in self.edges
            if edge.edge_type is EdgeType.explains_error and edge.target_id == m.id
        )
        return m.review_status is ReviewStatus.approved and all(
            self.concepts[concept_id].review_status is ReviewStatus.approved
            for concept_id in referenced_concepts
        )

    def approved_evidence(
        self,
        concept_ids: Iterable[str] | None = None,
        misconception_ids: Iterable[str] | None = None,
    ) -> list[ApprovedEvidence]:
        """Return evidence only when the complete referenced concept closure is approved."""
        if concept_ids is None:
            candidates = list(self.misconceptions.values())
        else:
            candidates = [m for cid in concept_ids for m in self.misconceptions_for_concept(cid)]
        if misconception_ids is not None:
            wanted = set(misconception_ids)
            candidates = [m for m in candidates if m.id in wanted]
        unique = {m.id: m for m in candidates}
        return [ApprovedEvidence.of(m) for m in unique.values() if self._is_evidence(m)]

    def get_approved_misconception(self, misconception_id: str) -> ApprovedEvidence:
        m = self.misconceptions.get(misconception_id)
        if m is None or not self._is_evidence(m):
            raise UnapprovedEvidenceError(misconception_id)
        return ApprovedEvidence.of(m)


def _ensure_prerequisites_acyclic(concepts: dict[str, Concept], edges: tuple[ConceptEdge, ...]) -> None:
    graph: dict[str, list[str]] = {cid: [] for cid in concepts}
    for e in edges:
        if e.edge_type is EdgeType.prerequisite:
            graph[e.source_id].append(e.target_id)
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(graph, white)
    for root in graph:
        if color[root] != white:
            continue
        stack: list[tuple[str, Iterable[str]]] = [(root, iter(graph[root]))]
        path = [root]
        color[root] = grey
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                color[node] = black
                stack.pop()
                path.pop()
            elif color[child] == grey:
                cycle = path[path.index(child):] + [child]
                raise KnowledgeValidationError("PREREQUISITE_CYCLE", " -> ".join(cycle))
            elif color[child] == white:
                color[child] = grey
                path.append(child)
                stack.append((child, iter(graph[child])))


class KnowledgeRepository(Protocol):
    """Course-scoped knowledge storage. A SQL implementation must keep these semantics."""

    def list_concepts(self, course_id: str) -> list[Concept]: ...
    def get_concept(self, course_id: str, concept_id: str) -> Concept | None: ...
    def create_concept(self, course_id: str, concept: Concept) -> Concept: ...
    def replace_concept(self, course_id: str, concept: Concept) -> Concept: ...
    def list_misconceptions(self, course_id: str) -> list[MisconceptionPattern]: ...
    def get_misconception(self, course_id: str, misconception_id: str) -> MisconceptionPattern | None: ...
    def create_misconception(self, course_id: str, m: MisconceptionPattern) -> MisconceptionPattern: ...
    def replace_misconception(self, course_id: str, m: MisconceptionPattern) -> MisconceptionPattern: ...
    def list_edges(self, course_id: str) -> list[ConceptEdge]: ...
    def add_edge(self, course_id: str, edge: ConceptEdge) -> ConceptEdge: ...
    def load_course(
        self,
        course_id: str,
        concepts: Iterable[Concept],
        edges: Iterable[ConceptEdge],
        misconceptions: Iterable[MisconceptionPattern],
    ) -> None: ...
    def graph(self, course_id: str) -> KnowledgeGraph: ...
    def approved_evidence(
        self,
        course_id: str,
        concept_ids: Iterable[str] | None = None,
        misconception_ids: Iterable[str] | None = None,
    ) -> list[ApprovedEvidence]: ...
    def get_approved_misconception(self, course_id: str, misconception_id: str) -> ApprovedEvidence: ...


@dataclass
class _CourseState:
    concepts: dict[str, Concept]
    edges: list[ConceptEdge]
    misconceptions: dict[str, MisconceptionPattern]


class InMemoryKnowledgeRepository:
    """Reference implementation; every mutation is validated against the whole graph first."""

    def __init__(self) -> None:
        self._courses: dict[str, _CourseState] = {}
        self._lock = Lock()

    def _state(self, course_id: str) -> _CourseState:
        return self._courses.get(course_id) or _CourseState({}, [], {})

    def _commit(self, course_id: str, state: _CourseState) -> None:
        KnowledgeGraph.build(state.concepts.values(), state.edges, state.misconceptions.values())
        self._courses[course_id] = state

    def list_concepts(self, course_id: str) -> list[Concept]:
        return list(self._state(course_id).concepts.values())

    def get_concept(self, course_id: str, concept_id: str) -> Concept | None:
        return self._state(course_id).concepts.get(concept_id)

    def create_concept(self, course_id: str, concept: Concept) -> Concept:
        with self._lock:
            s = self._state(course_id)
            if concept.id in s.concepts or concept.id in s.misconceptions:
                raise KnowledgeValidationError("KNOWLEDGE_ID_CONFLICT", f"{concept.id} already exists")
            self._commit(course_id, _CourseState({**s.concepts, concept.id: concept}, list(s.edges), dict(s.misconceptions)))
        return concept

    def replace_concept(self, course_id: str, concept: Concept) -> Concept:
        with self._lock:
            s = self._state(course_id)
            if concept.id not in s.concepts:
                raise KeyError(concept.id)
            self._commit(course_id, _CourseState({**s.concepts, concept.id: concept}, list(s.edges), dict(s.misconceptions)))
        return concept

    def list_misconceptions(self, course_id: str) -> list[MisconceptionPattern]:
        return list(self._state(course_id).misconceptions.values())

    def get_misconception(self, course_id: str, misconception_id: str) -> MisconceptionPattern | None:
        return self._state(course_id).misconceptions.get(misconception_id)

    def create_misconception(self, course_id: str, m: MisconceptionPattern) -> MisconceptionPattern:
        with self._lock:
            s = self._state(course_id)
            if m.id in s.misconceptions or m.id in s.concepts:
                raise KnowledgeValidationError("KNOWLEDGE_ID_CONFLICT", f"{m.id} already exists")
            self._commit(course_id, _CourseState(dict(s.concepts), list(s.edges), {**s.misconceptions, m.id: m}))
        return m

    def replace_misconception(self, course_id: str, m: MisconceptionPattern) -> MisconceptionPattern:
        with self._lock:
            s = self._state(course_id)
            if m.id not in s.misconceptions:
                raise KeyError(m.id)
            self._commit(course_id, _CourseState(dict(s.concepts), list(s.edges), {**s.misconceptions, m.id: m}))
        return m

    def list_edges(self, course_id: str) -> list[ConceptEdge]:
        return list(self._state(course_id).edges)

    def add_edge(self, course_id: str, edge: ConceptEdge) -> ConceptEdge:
        with self._lock:
            s = self._state(course_id)
            self._commit(course_id, _CourseState(dict(s.concepts), [*s.edges, edge], dict(s.misconceptions)))
        return edge

    def load_course(
        self,
        course_id: str,
        concepts: Iterable[Concept],
        edges: Iterable[ConceptEdge],
        misconceptions: Iterable[MisconceptionPattern],
    ) -> None:
        """Bulk import atomically; replaying byte-equivalent seed data is idempotent."""
        with self._lock:
            graph = KnowledgeGraph.build(concepts, edges, misconceptions)
            incoming = _CourseState(
                dict(graph.concepts), list(graph.edges), dict(graph.misconceptions)
            )
            existing = self._courses.get(course_id)
            if existing is not None:
                if existing == incoming:
                    return
                raise KnowledgeValidationError("KNOWLEDGE_ID_CONFLICT", f"course {course_id} already has different knowledge")
            self._courses[course_id] = incoming

    def graph(self, course_id: str) -> KnowledgeGraph:
        s = self._state(course_id)
        return KnowledgeGraph.build(s.concepts.values(), s.edges, s.misconceptions.values())

    def approved_evidence(
        self,
        course_id: str,
        concept_ids: Iterable[str] | None = None,
        misconception_ids: Iterable[str] | None = None,
    ) -> list[ApprovedEvidence]:
        return self.graph(course_id).approved_evidence(concept_ids, misconception_ids)

    def get_approved_misconception(self, course_id: str, misconception_id: str) -> ApprovedEvidence:
        return self.graph(course_id).get_approved_misconception(misconception_id)
