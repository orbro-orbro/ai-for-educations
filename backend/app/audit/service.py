from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Callable, ContextManager, Protocol
from uuid import uuid4

from app.auth.models import Actor


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    actor_user_id: str
    actor_role: str
    target_type: str
    target_id: str
    owner_user_id: str
    course_id: str
    outcome: str
    reason_code: str
    request_id: str
    created_at: datetime
    related_id: str | None = None


class AuditLog(Protocol):
    def transaction(self) -> ContextManager[None]: ...

    def record(
        self,
        *,
        event_type: str,
        actor: Actor,
        target_type: str,
        target_id: str,
        owner_user_id: str,
        course_id: str,
        outcome: str,
        reason_code: str,
        request_id: str,
        related_id: str | None = None,
    ) -> AuditEvent: ...


class AuditService:
    """Stores metadata-only audit events; private content is not accepted."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory
        self._events: list[AuditEvent] = []
        self._lock = RLock()

    @contextmanager
    def transaction(self):
        with self._lock:
            original_length = len(self._events)
            try:
                yield
            except BaseException:
                del self._events[original_length:]
                raise

    def record(
        self,
        *,
        event_type: str,
        actor: Actor,
        target_type: str,
        target_id: str,
        owner_user_id: str,
        course_id: str,
        outcome: str,
        reason_code: str,
        request_id: str,
        related_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=self._id_factory(),
            event_type=event_type,
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            target_type=target_type,
            target_id=target_id,
            owner_user_id=owner_user_id,
            course_id=course_id,
            outcome=outcome,
            reason_code=reason_code,
            request_id=request_id,
            created_at=self._clock(),
            related_id=related_id,
        )
        with self._lock:
            self._events.append(event)
        return event

    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def serialized_events(self) -> str:
        return json.dumps(
            [asdict(event) for event in self.events()],
            default=str,
            ensure_ascii=False,
            sort_keys=True,
        )
