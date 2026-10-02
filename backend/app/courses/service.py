from __future__ import annotations

from app.auth.models import Actor, Role, UserRepository
from app.auth.policy import (
    RESOURCE_NOT_AVAILABLE,
    AuthorizationDecision,
    AuthorizationPolicy,
    AuthorizationResource,
)
from app.courses.models import (
    Course,
    CourseRepository,
    Enrollment,
    EnrollmentRepository,
    Exercise,
)


class ResourceNotAvailable(Exception):
    public_error_code = RESOURCE_NOT_AVAILABLE
    public_message = "Resource is not available."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class CourseService:
    def __init__(
        self,
        users: UserRepository,
        courses: CourseRepository,
        enrollments: EnrollmentRepository,
        policy: AuthorizationPolicy,
    ) -> None:
        self._users = users
        self._courses = courses
        self._enrollments = enrollments
        self._policy = policy

    def list_courses(self, actor: Actor) -> list[Course]:
        actor = self._verified_actor(actor)
        visible: list[Course] = []
        for course in self._courses.list_all():
            decision = self._policy.authorize(
                actor, "read_course", self._course_resource(course)
            )
            if decision.allowed:
                visible.append(course)
        return visible

    def list_exercises(self, actor: Actor, course_id: str) -> list[Exercise]:
        actor = self._verified_actor(actor)
        course = self._required_course(course_id)
        self._require_allowed(
            self._policy.authorize(
                actor, "read_exercises", self._course_resource(course)
            )
        )
        return self._courses.list_exercises(course.course_id)

    def create_course(
        self, actor: Actor, course_id: str, title: str
    ) -> Course:
        actor = self._verified_actor(actor)
        collection = AuthorizationResource(
            resource_id="courses",
            resource_type="course_collection",
            course_id=None,
        )
        self._require_allowed(
            self._policy.authorize(actor, "create_course", collection)
        )
        if self._courses.get(course_id) is not None:
            raise ResourceNotAvailable()
        course = Course(course_id, title, actor.user_id)
        self._courses.add(course)
        return course

    def enroll_current_student(
        self, actor: Actor, course_id: str
    ) -> Enrollment:
        actor = self._verified_actor(actor)
        course = self._required_course(course_id)
        self._require_allowed(
            self._policy.authorize(actor, "enroll_self", self._course_resource(course))
        )
        return self._enrollments.add(
            Enrollment(course.course_id, actor.user_id, Role.STUDENT)
        )

    def require_teacher_access(self, actor: Actor, course_id: str) -> None:
        """Authorize a teacher management operation without leaking course existence."""

        actor = self._verified_actor(actor)
        course = self._required_course(course_id)
        self._require_allowed(
            self._policy.authorize(
                actor, "teacher_operation", self._course_resource(course)
            )
        )

    def _verified_actor(self, actor: Actor) -> Actor:
        user = self._users.get(actor.user_id)
        if user is None or not user.active or user.role is not actor.role:
            raise ResourceNotAvailable()
        return Actor(user.user_id, user.role)

    def _required_course(self, course_id: str) -> Course:
        course = self._courses.get(course_id)
        if course is None:
            raise ResourceNotAvailable()
        return course

    def _course_resource(self, course: Course) -> AuthorizationResource:
        return AuthorizationResource(
            resource_id=course.course_id,
            resource_type="course",
            course_id=course.course_id,
            owner_user_id=course.owner_teacher_id,
            member_user_ids=self._enrollments.member_user_ids(course.course_id),
            course_owner_user_id=course.owner_teacher_id,
            authorized_teacher_user_ids=course.authorized_teacher_ids,
        )

    @staticmethod
    def _require_allowed(decision: AuthorizationDecision) -> None:
        if not decision.allowed:
            raise ResourceNotAvailable()
