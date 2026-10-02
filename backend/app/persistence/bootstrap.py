from __future__ import annotations

import json
import os

from app.auth.models import Role, User
from app.courses.models import Course
from app.knowledge.seed import import_seed, load_seed
from app.persistence.repositories import SqlRepositories, create_sql_repositories


COURSE_ID = "cangjie-language-design"
DEVELOPMENT_TEACHER_PASSWORD = "teacher-change-me"
DEVELOPMENT_STUDENT_PASSWORD = "student-change-me"


def _ensure_user(
    repositories: SqlRepositories,
    *,
    user_id: str,
    username: str,
    password: str,
    role: Role,
) -> None:
    existing = repositories.users.find_by_username(username)
    if existing is None:
        repositories.users.add(User.with_password(user_id, username, password, role))
        return
    if existing.user_id != user_id or existing.role is not role:
        raise RuntimeError(f"bootstrap username {username!r} belongs to a different identity")


def bootstrap(
    database_url: str,
    *,
    teacher_username: str,
    teacher_password: str,
    student_username: str,
    student_password: str,
    create_schema: bool = False,
) -> SqlRepositories:
    repositories = create_sql_repositories(database_url, create_schema=create_schema)
    _ensure_user(
        repositories,
        user_id="bootstrap-teacher",
        username=teacher_username,
        password=teacher_password,
        role=Role.TEACHER,
    )
    _ensure_user(
        repositories,
        user_id="bootstrap-student",
        username=student_username,
        password=student_password,
        role=Role.STUDENT,
    )
    course = repositories.courses.get(COURSE_ID)
    if course is None:
        repositories.courses.add(Course(COURSE_ID, "仓颉语言设计", "bootstrap-teacher"))
    elif course.owner_teacher_id != "bootstrap-teacher":
        raise RuntimeError(f"bootstrap course {COURSE_ID!r} has a different owner")
    if not repositories.knowledge.list_concepts(COURSE_ID):
        import_seed(repositories.knowledge, COURSE_ID, load_seed())
    return repositories


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set for database bootstrap")
    environment = os.environ.get("APP_ENV", "development")
    teacher_password = os.environ.get("BOOTSTRAP_TEACHER_PASSWORD", DEVELOPMENT_TEACHER_PASSWORD)
    student_password = os.environ.get("BOOTSTRAP_STUDENT_PASSWORD", DEVELOPMENT_STUDENT_PASSWORD)
    if environment not in {"development", "test"} and {
        teacher_password,
        student_password,
    } & {DEVELOPMENT_TEACHER_PASSWORD, DEVELOPMENT_STUDENT_PASSWORD}:
        raise RuntimeError("production bootstrap passwords must not use development defaults")
    repositories = bootstrap(
        database_url,
        teacher_username=os.environ.get("BOOTSTRAP_TEACHER_USERNAME", "teacher"),
        teacher_password=teacher_password,
        student_username=os.environ.get("BOOTSTRAP_STUDENT_USERNAME", "student"),
        student_password=student_password,
    )
    print(
        json.dumps(
            {
                "course_id": COURSE_ID,
                "concepts": len(repositories.knowledge.list_concepts(COURSE_ID)),
                "misconceptions": len(repositories.knowledge.list_misconceptions(COURSE_ID)),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
