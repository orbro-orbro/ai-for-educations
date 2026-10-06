from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from uuid import uuid4

from sqlalchemy import select

from app.audit.service import AuditEvent
from app.auth.models import Actor
from app.memories.persistence import SqlMemoryUnitOfWork
from app.persistence.models import AuditEventRow


class SqlAuditLog:
    """Metadata-only audit log that joins the active memory transaction."""

    def __init__(self, uow: SqlMemoryUnitOfWork) -> None:
        self._uow = uow

    def transaction(self):
        return self._uow.transaction()

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
        if self._uow.active_session is None:
            with self._uow.transaction():
                return self._record(
                    event_type=event_type,
                    actor=actor,
                    target_type=target_type,
                    target_id=target_id,
                    owner_user_id=owner_user_id,
                    course_id=course_id,
                    outcome=outcome,
                    reason_code=reason_code,
                    request_id=request_id,
                    related_id=related_id,
                )
        return self._record(
            event_type=event_type,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            owner_user_id=owner_user_id,
            course_id=course_id,
            outcome=outcome,
            reason_code=reason_code,
            request_id=request_id,
            related_id=related_id,
        )

    def _record(
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
        related_id: str | None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid4()),
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
            created_at=datetime.now(UTC),
            related_id=related_id,
        )
        session = self._uow.require_session()
        session.add(
            AuditEventRow(
                id=event.event_id,
                event_type=event.event_type,
                actor_user_id=event.actor_user_id,
                actor_role=event.actor_role,
                target_type=event.target_type,
                target_id=event.target_id,
                owner_user_id=event.owner_user_id,
                course_id=event.course_id,
                outcome=event.outcome,
                reason_code=event.reason_code,
                request_id=event.request_id,
                created_at=event.created_at,
                related_id=event.related_id,
            )
        )
        session.flush()
        return event

    def events(self) -> tuple[AuditEvent, ...]:
        with self._uow.read_session() as session:
            rows = session.scalars(
                select(AuditEventRow).order_by(AuditEventRow.created_at, AuditEventRow.id)
            ).all()
            return tuple(
                AuditEvent(
                    event_id=row.id,
                    event_type=row.event_type,
                    actor_user_id=row.actor_user_id,
                    actor_role=row.actor_role,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    owner_user_id=row.owner_user_id,
                    course_id=row.course_id,
                    outcome=row.outcome,
                    reason_code=row.reason_code,
                    request_id=row.request_id,
                    created_at=(
                        row.created_at.replace(tzinfo=UTC)
                        if row.created_at.tzinfo is None
                        else row.created_at.astimezone(UTC)
                    ),
                    related_id=row.related_id,
                )
                for row in rows
            )

    def serialized_events(self) -> str:
        return json.dumps(
            [asdict(event) for event in self.events()],
            default=str,
            ensure_ascii=False,
            sort_keys=True,
        )
