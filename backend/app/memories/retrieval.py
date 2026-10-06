from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from app.memories.models import LearningMemory


class RetrievalDeletionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SearchCall:
    query: str
    candidate_document_ids: frozenset[str]
    owner_user_id: str
    course_id: str
    purpose: str


class RetrievalIndex(Protocol):
    def upsert(self, memory: LearningMemory) -> None: ...
    def search(
        self,
        query: str,
        *,
        candidate_document_ids: frozenset[str],
        owner_user_id: str,
        course_id: str,
        purpose: str,
    ) -> tuple[str, ...]: ...
    def delete(self, index_document_id: str) -> None: ...
    def verify_absent(self, index_document_ids: frozenset[str]) -> bool: ...


class InMemoryRetrievalIndex:
    """Deterministic derived index used by Task 7 tests, never for authorization."""

    def __init__(self) -> None:
        self._documents: dict[str, tuple[str, str, str]] = {}
        self._injected_results: tuple[str, ...] | None = None
        self._delete_failures = 0
        self._verification_failures = 0
        self._lock = Lock()
        self.search_calls: list[SearchCall] = []

    def upsert(self, memory: LearningMemory) -> None:
        if memory.content is None:
            return
        with self._lock:
            self._documents[memory.index_document_id] = (
                memory.owner_user_id,
                memory.course_id,
                memory.content,
            )

    def search(
        self,
        query: str,
        *,
        candidate_document_ids: frozenset[str],
        owner_user_id: str,
        course_id: str,
        purpose: str,
    ) -> tuple[str, ...]:
        call = SearchCall(
            query=query,
            candidate_document_ids=candidate_document_ids,
            owner_user_id=owner_user_id,
            course_id=course_id,
            purpose=purpose,
        )
        with self._lock:
            self.search_calls.append(call)
            if self._injected_results is not None:
                return self._injected_results
            lowered = query.casefold()
            return tuple(
                document_id
                for document_id, (owner, course, content) in self._documents.items()
                if document_id in candidate_document_ids
                and owner == owner_user_id
                and course == course_id
                and (
                    not lowered
                    or lowered in content.casefold()
                    or any(part in content.casefold() for part in lowered.split())
                )
            )

    def inject_search_results(self, *index_document_ids: str) -> None:
        with self._lock:
            self._injected_results = tuple(index_document_ids)

    def fail_next_deletes(self, count: int) -> None:
        with self._lock:
            self._delete_failures = count

    def fail_next_verifications(self, count: int) -> None:
        with self._lock:
            self._verification_failures = count

    def delete(self, index_document_id: str) -> None:
        with self._lock:
            if self._delete_failures:
                self._delete_failures -= 1
                raise RetrievalDeletionError("index deletion failed")
            self._documents.pop(index_document_id, None)

    def verify_absent(self, index_document_ids: frozenset[str]) -> bool:
        with self._lock:
            if self._verification_failures:
                self._verification_failures -= 1
                return False
            return not any(item in self._documents for item in index_document_ids)

    def contains(self, index_document_id: str) -> bool:
        with self._lock:
            return index_document_id in self._documents
