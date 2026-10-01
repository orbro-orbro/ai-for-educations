from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.auth.models import Role


@dataclass(frozen=True, slots=True)
class Course:
    course_id: str
    title: str
    owner_teacher_id: str
    authorized_teacher_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Enrollment:
    course_id: str
    user_id: str
    role: Role

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))


@dataclass(frozen=True, slots=True)
class Exercise:
    exercise_id: str
    course_id: str
    title: str


class CourseRepository:
    """In-memory MVP repository behind a database-replaceable interface."""

    def __init__(
        self,
        courses: Iterable[Course] = (),
        exercises: Iterable[Exercise] = (),
    ) -> None:
        self._courses: dict[str, Course] = {}
        self._exercises: dict[str, Exercise] = {}
        for course in courses:
            self.add(course)
        for exercise in exercises:
            self.add_exercise(exercise)

    def add(self, course: Course) -> None:
        if course.course_id in self._courses:
            raise ValueError("duplicate course")
        self._courses[course.course_id] = course

    def get(self, course_id: str) -> Course | None:
        return self._courses.get(course_id)

    def list_all(self) -> list[Course]:
        return sorted(self._courses.values(), key=lambda course: course.course_id)

    def add_exercise(self, exercise: Exercise) -> None:
        if exercise.exercise_id in self._exercises:
            raise ValueError("duplicate exercise")
        if exercise.course_id not in self._courses:
            raise ValueError("exercise course does not exist")
        self._exercises[exercise.exercise_id] = exercise

    def list_exercises(self, course_id: str) -> list[Exercise]:
        return sorted(
            (
                exercise
                for exercise in self._exercises.values()
                if exercise.course_id == course_id
            ),
            key=lambda exercise: exercise.exercise_id,
        )


class EnrollmentRepository:
    def __init__(self, enrollments: Iterable[Enrollment] = ()) -> None:
        self._enrollments: dict[tuple[str, str], Enrollment] = {}
        for enrollment in enrollments:
            self.add(enrollment)

    def add(self, enrollment: Enrollment) -> Enrollment:
        key = (enrollment.course_id, enrollment.user_id)
        existing = self._enrollments.get(key)
        if existing is not None:
            return existing
        self._enrollments[key] = enrollment
        return enrollment

    def is_member(self, course_id: str, user_id: str) -> bool:
        return (course_id, user_id) in self._enrollments

    def member_user_ids(self, course_id: str) -> frozenset[str]:
        return frozenset(
            user_id
            for enrolled_course_id, user_id in self._enrollments
            if enrolled_course_id == course_id
        )
