from __future__ import annotations

from dataclasses import dataclass, field

from app.auth.models import Actor, Role


RESOURCE_NOT_AVAILABLE = "RESOURCE_NOT_AVAILABLE"


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    public_error_code: str | None = None
    reason: str | None = field(default=None, repr=False)

    @classmethod
    def allow(cls) -> AuthorizationDecision:
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> AuthorizationDecision:
        return cls(
            allowed=False,
            public_error_code=RESOURCE_NOT_AVAILABLE,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class AuthorizationResource:
    """Trusted resource facts assembled by a server-side service/repository."""

    resource_id: str
    resource_type: str
    course_id: str | None
    owner_user_id: str | None = None
    member_user_ids: frozenset[str] = frozenset()
    course_owner_user_id: str | None = None
    authorized_teacher_user_ids: frozenset[str] = frozenset()
    granted_teacher_user_ids: frozenset[str] = frozenset()
    is_formal_submission: bool = False


class AuthorizationPolicy:
    """Course-scoped, deny-by-default authorization."""

    def authorize(
        self, actor: Actor, action: str, resource: AuthorizationResource
    ) -> AuthorizationDecision:
        if action == "create_course":
            if actor.role is Role.TEACHER and resource.resource_type == "course_collection":
                return AuthorizationDecision.allow()
            return AuthorizationDecision.deny("only teachers create courses")

        if action == "enroll_self":
            if actor.role is Role.STUDENT and resource.resource_type == "course":
                return AuthorizationDecision.allow()
            return AuthorizationDecision.deny("only students enroll themselves")

        if resource.course_id is None:
            return AuthorizationDecision.deny("course scope is missing")

        teacher_can_manage = (
            actor.role is Role.TEACHER
            and (
                actor.user_id == resource.course_owner_user_id
                or actor.user_id in resource.authorized_teacher_user_ids
            )
        )
        is_course_member = (
            actor.user_id in resource.member_user_ids or teacher_can_manage
        )

        if not is_course_member:
            return AuthorizationDecision.deny("actor is not a course member")

        if action in {"manage_course", "teacher_operation"}:
            if teacher_can_manage:
                return AuthorizationDecision.allow()
            return AuthorizationDecision.deny("teacher does not manage this course")

        if action == "read_private_memory" and resource.resource_type != "private_memory":
            return AuthorizationDecision.deny("resource is not a private memory")

        if resource.resource_type in {"private_memory", "diagnosis_summary"}:
            if actor.role is Role.STUDENT and actor.user_id == resource.owner_user_id:
                return AuthorizationDecision.allow()
            if (
                actor.role is Role.TEACHER
                and teacher_can_manage
                and actor.user_id in resource.granted_teacher_user_ids
            ):
                return AuthorizationDecision.allow()
            return AuthorizationDecision.deny("private resource is not granted")

        if action in {"read", "read_course", "read_exercises"}:
            if resource.resource_type in {"course", "exercise"}:
                return AuthorizationDecision.allow()
            if actor.role is Role.STUDENT:
                if actor.user_id == resource.owner_user_id:
                    return AuthorizationDecision.allow()
                return AuthorizationDecision.deny("student does not own resource")
            if (
                teacher_can_manage
                and resource.resource_type == "submission"
                and resource.is_formal_submission
            ):
                return AuthorizationDecision.allow()
            return AuthorizationDecision.deny("resource is not readable")

        return AuthorizationDecision.deny("action is not allowed")


def authorize(
    actor: Actor, action: str, resource: AuthorizationResource
) -> AuthorizationDecision:
    """Stable functional entry point for downstream modules."""

    return AuthorizationPolicy().authorize(actor, action, resource)
