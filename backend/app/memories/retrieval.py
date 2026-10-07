from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol, TYPE_CHECKING
from datetime import datetime, UTC
from contextlib import nullcontext

from app.memories.models import LearningMemory, LearningMemoryStatus
if TYPE_CHECKING:
    from app.memories.repository import MemoryRepository


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
    def verify_absent(
        self,
        index_document_ids: frozenset[str],
        *,
        owner_user_id: str,
        course_id: str,
        logical_memory_id: str,
    ) -> bool: ...


class InMemoryRetrievalIndex:
    """Deterministic derived index used by Task 7 tests, never for authorization."""

    def __init__(self, *, repository: MemoryRepository | None = None) -> None:
        self._repository = repository
        self._repositories = (repository,) if repository is not None else ()
        self._deleted_ids: set[str] = set()
        self._documents: dict[str, tuple[str, str, str, str]] = {}
        self._injected_results: tuple[str, ...] | None = None
        self._delete_failures = 0
        self._verification_failures = 0
        self._lock = Lock()
        self.search_calls: list[SearchCall] = []

    def upsert(self, memory: LearningMemory) -> None:
        repository = next((item for item in self._repositories
            if getattr(getattr(item, "uow", None), "active_session", None) is not None), self._repository)
        claim = repository.memory_claim(memory.logical_memory_id) if repository else nullcontext()
        # Same lock order as deletion: authoritative memory claim, then index.
        with claim:
            if repository is not None:
                current = repository.get_memory(memory.memory_id)
                if current != memory or repository.get_deletion_for_memory(memory.logical_memory_id) is not None:
                    return
            if memory.content is None or memory.status is not LearningMemoryStatus.active or (
                memory.expires_at is not None and memory.expires_at <= datetime.now(UTC)
            ): return
            with self._lock:
                if memory.index_document_id in self._deleted_ids: return
                self._documents[memory.index_document_id] = (
                    memory.owner_user_id, memory.course_id, memory.logical_memory_id, memory.content,
                )

    def bind_repository(self, repository: MemoryRepository) -> None:
        with self._lock:
            if self._repository is repository:
                return
            if self._repository is not None:
                original_uow = getattr(self._repository, "uow", None)
                replacement_uow = getattr(repository, "uow", None)
                if original_uow is not None and replacement_uow is not None and (
                    original_uow.sessions.kw["bind"].url == replacement_uow.sessions.kw["bind"].url
                ):
                    # Use the active calling transaction, not a second SQL
                    # connection that would block on its own writer's row lock.
                    if all(item is not repository for item in self._repositories):
                        self._repositories += (repository,)
                    return
                raise ValueError("Index already bound to a different authoritative repository")
            self._repository = repository
            self._repositories = (repository,)

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
                for document_id, (owner, course, _logical_memory, content) in self._documents.items()
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
            self._deleted_ids.add(index_document_id)
            if self._delete_failures:
                self._delete_failures -= 1
                raise RetrievalDeletionError("index deletion failed")
            self._documents.pop(index_document_id, None)

    def verify_absent(
        self,
        index_document_ids: frozenset[str],
        *,
        owner_user_id: str,
        course_id: str,
        logical_memory_id: str,
    ) -> bool:
        with self._lock:
            if self._verification_failures:
                self._verification_failures -= 1
                return False
            return not any(
                document_id in index_document_ids
                or (
                    owner == owner_user_id
                    and course == course_id
                    and logical_memory == logical_memory_id
                )
                for document_id, (
                    owner,
                    course,
                    logical_memory,
                    _content,
                ) in self._documents.items()
            )

    def contains(self, index_document_id: str) -> bool:
        with self._lock:
            return index_document_id in self._documents
