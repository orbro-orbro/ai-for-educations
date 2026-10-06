from __future__ import annotations

from typing import Protocol

from app.auth.models import Actor, Role
from app.courses.service import ResourceNotAvailable


class MemoryCourseAccess(Protocol):
    def require_student(self, actor: Actor, course_id: str) -> None: ...
    def require_teacher(self, actor: Actor, course_id: str) -> None: ...


class CourseServiceMemoryAccess:
    """Adapter that reuses Task 2's authoritative course checks."""

    def __init__(self, course_service) -> None:
        self._courses = course_service

    def require_student(self, actor: Actor, course_id: str) -> None:
        if actor.role is not Role.STUDENT:
            raise ResourceNotAvailable()
        self._courses.list_exercises(actor, course_id)

    def require_teacher(self, actor: Actor, course_id: str) -> None:
        if actor.role is not Role.TEACHER:
            raise ResourceNotAvailable()
        self._courses.require_teacher_access(actor, course_id)


class MemoryPolicy:
    """Deny-by-default owner and course policy for private memory data."""

    def __init__(self, course_access: MemoryCourseAccess) -> None:
        self._course_access = course_access

    def require_owner(self, actor: Actor, owner_user_id: str, course_id: str) -> None:
        if actor.role is not Role.STUDENT or actor.user_id != owner_user_id:
            raise ResourceNotAvailable()
        self._course_access.require_student(actor, course_id)

    def require_student_course(self, actor: Actor, course_id: str) -> None:
        if actor.role is not Role.STUDENT:
            raise ResourceNotAvailable()
        self._course_access.require_student(actor, course_id)

    def require_grantee_teacher(
        self, actor: Actor, grantee_user_id: str, course_id: str
    ) -> None:
        if actor.role is not Role.TEACHER or actor.user_id != grantee_user_id:
            raise ResourceNotAvailable()
        self._course_access.require_teacher(actor, course_id)

    def require_teacher_for_course(self, teacher_user_id: str, course_id: str) -> None:
        self._course_access.require_teacher(
            Actor(teacher_user_id, Role.TEACHER), course_id
        )
