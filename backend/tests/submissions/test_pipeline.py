from datetime import UTC

import httpx
import pytest

from app.submissions.models import ExecutionResult, InvalidSubmissionTransition, SubmissionStatus
from app.submissions.repository import InMemorySubmissionRepository, SubmissionPersistenceError
from app.submissions.service import SubmissionService
from app.submissions.runner_client import RunnerClient, RunnerUnavailable
from app.auth.models import Actor, Role
from app.courses.models import Exercise
from app.submissions.runner_contract import RunnerResult, RunnerStatus


def test_create_submission_persists_received_state_and_utc_transition():
    repository = InMemorySubmissionRepository()

    submission = repository.create(
        submission_id="sub-1",
        course_id="course-1",
        exercise_id="exercise-1",
        owner_user_id="student-1",
        source_files=({"path": "main.cj", "content": "main() {}"},),
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-1",
    )

    assert submission.status is SubmissionStatus.received
    assert submission.created_at.tzinfo is UTC
    assert repository.get("sub-1") == submission
    assert repository.transitions("sub-1")[0].from_status is None
    assert repository.transitions("sub-1")[0].to_status is SubmissionStatus.received
    assert repository.transitions("sub-1")[0].changed_at.tzinfo is UTC
    assert repository.transitions("sub-1")[0].request_id == "req-1"


def test_transition_records_history_and_rejects_illegal_jump():
    repository = InMemorySubmissionRepository()
    repository.create(
        submission_id="sub-1",
        course_id="course-1",
        exercise_id="exercise-1",
        owner_user_id="student-1",
        source_files=({"path": "main.cj", "content": "main() {}"},),
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-create",
    )

    executing = repository.transition(
        "sub-1",
        SubmissionStatus.executing,
        request_id="req-run",
        reason="runner request started",
    )

    assert executing.status is SubmissionStatus.executing
    transition = repository.transitions("sub-1")[-1]
    assert (transition.from_status, transition.to_status) == (
        SubmissionStatus.received,
        SubmissionStatus.executing,
    )
    assert transition.request_id == "req-run"
    assert transition.reason == "runner request started"
    assert transition.changed_at.tzinfo is UTC

    with pytest.raises(InvalidSubmissionTransition):
        repository.transition(
            "sub-1",
            SubmissionStatus.diagnosed,
            request_id="req-bad",
            reason="illegal",
        )
    assert repository.get("sub-1").status is SubmissionStatus.executing


class ExerciseAccess:
    def resolve_student_exercise(self, actor, exercise_id):
        if actor != Actor("student-1", Role.STUDENT) or exercise_id != "exercise-1":
            raise AssertionError("unexpected authorization input")
        return Exercise("exercise-1", "course-1", "Exercise")

    def require_read(self, actor, submission):
        return None


class NoApprovedEvidence:
    def approved_evidence(self, course_id, concept_ids=None, misconception_ids=None):
        return []


def load_approved_knowledge(
    repository,
    course_id,
    misconception_id=None,
    concept_id="cj.pattern-match.exhaustiveness",
):
    from app.knowledge.models import Concept, MisconceptionPattern

    source = {
        "kind": "toolchain_experiment",
        "references": ["exp:match_non_exhaustive"],
        "toolchain_version": "cjc 1.2.0 (cjnative)",
        "verification_status": "experiment_verified",
    }
    concept = Concept.model_validate(
        {
            "id": concept_id,
            "topic": "enum_match",
            "title": "Exhaustiveness",
            "summary": "All cases are covered.",
            "review_status": "approved",
            "source": source,
        }
    )
    misconceptions = []
    if misconception_id is not None:
        misconceptions.append(
            MisconceptionPattern.model_validate(
                {
                    "id": misconception_id,
                    "topic": "enum_match",
                    "title": "Non-exhaustive match",
                    "root_concept_id": concept.id,
                    "related_concept_ids": [],
                    "trigger_evidence": [
                        {
                            "kind": "compiler_diagnostic",
                            "pattern": "non-exhaustive patterns",
                            "strength": "strong",
                        }
                    ],
                    "explanation": "A match must be exhaustive.",
                    "hint_ladder": [
                        {"level": level, "outline": f"step {level}"}
                        for level in (1, 2, 3, 4)
                    ],
                    "review_status": "approved",
                    "source": source,
                    "verification": {
                        "method": "cjc_minimal_repro",
                        "toolchain_version": "cjc 1.2.0 (cjnative)",
                        "expected_outcome": "compile_error",
                        "snippet": "main() {}",
                        "note": "verified",
                    },
                }
            )
        )
    repository.load_course(course_id, [concept], [], misconceptions)


class CompileFailureRunner:
    def execute(self, request):
        return RunnerResult.model_validate(
            {
                "protocol_version": "2",
                "submission_id": request.submission_id,
                "status": "compile_failed",
                "phase": "compile",
                "retryable": False,
                "exit_code": 1,
                "signal": None,
                "stdout": "",
                "stderr": "main.cj:1:1: error: non-exhaustive patterns",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "diagnostics": [
                    {
                        "severity": "error",
                        "message": "non-exhaustive patterns",
                        "code": None,
                        "file": "main.cj",
                        "start_line": 1,
                        "start_column": 1,
                        "end_line": None,
                        "end_column": None,
                    }
                ],
                "command_summary": {
                    "compiler": "cjc",
                    "source_count": 1,
                    "entrypoint": "main.cj",
                    "output_kind": "executable",
                },
                "limits": {"timeout_ms": 5000},
                "toolchain": {
                    "cjc": "1.2.0",
                    "cjpm": "1.2.0",
                    "backend": "cjnative",
                },
            }
        )


class UnavailableRunner:
    def execute(self, _request):
        raise RunnerUnavailable("http://runner.internal private student source")


class InternalErrorRunner:
    def execute(self, request):
        return CompileFailureRunner().execute(request).model_copy(
            update={
                "status": RunnerStatus.internal_error,
                "phase": "control",
                "retryable": True,
                "exit_code": None,
                "diagnostics": [],
            }
        )


def test_compile_failure_is_persisted_as_real_execution_and_executed_state():
    repository = InMemorySubmissionRepository()
    service = SubmissionService(
        repository=repository,
        access=ExerciseAccess(),
        runner=CompileFailureRunner(),
        knowledge=NoApprovedEvidence(),
        id_factory=lambda: "sub-compile",
    )

    submission = service.submit(
        actor=Actor("student-1", Role.STUDENT),
        exercise_id="exercise-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-compile",
    )

    assert submission.status is SubmissionStatus.executed
    assert repository.get("sub-compile").source_files[0].content == "main() {}"
    result = repository.execution_result("sub-compile")
    assert result.status.value == "compile_failed"
    assert result.diagnostics[0].message == "non-exhaustive patterns"
    assert result.created_at.tzinfo is UTC
    assert [item.to_status for item in repository.transitions("sub-compile")] == [
        SubmissionStatus.received,
        SubmissionStatus.executing,
        SubmissionStatus.executed,
    ]


def test_runner_infrastructure_failure_preserves_source_without_fake_result():
    repository = InMemorySubmissionRepository()
    service = SubmissionService(
        repository=repository,
        access=ExerciseAccess(),
        runner=UnavailableRunner(),
        knowledge=NoApprovedEvidence(),
        id_factory=lambda: "sub-unavailable",
    )

    submission = service.submit(
        actor=Actor("student-1", Role.STUDENT),
        exercise_id="exercise-1",
        source_files=[{"path": "main.cj", "content": "private student source"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-unavailable",
    )

    assert submission.status is SubmissionStatus.execution_unavailable
    assert repository.get("sub-unavailable").source_files[0].content == "private student source"
    assert repository.execution_result("sub-unavailable") is None
    assert repository.rule_matches("sub-unavailable") == ()
    assert repository.transitions("sub-unavailable")[-1].reason == "runner infrastructure unavailable"


def test_runner_internal_error_is_unavailable_without_fake_result():
    repository = InMemorySubmissionRepository()
    submission = SubmissionService(
        repository=repository,
        access=ExerciseAccess(),
        runner=InternalErrorRunner(),
        knowledge=NoApprovedEvidence(),
        id_factory=lambda: "sub-internal-error",
    ).submit(
        actor=Actor("student-1", Role.STUDENT),
        exercise_id="exercise-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-internal-error",
    )

    assert submission.status is SubmissionStatus.execution_unavailable
    assert repository.execution_result("sub-internal-error") is None
    assert repository.rule_matches("sub-internal-error") == ()


def test_retryable_runner_http_503_becomes_execution_unavailable():
    payload = {
        "protocol_version": "2",
        "submission_id": "sub-http-503",
        "status": "runner_unavailable",
        "phase": "control",
        "retryable": True,
        "exit_code": None,
        "signal": None,
        "stdout": "",
        "stderr": "runner unavailable",
        "diagnostics": [],
        "command_summary": {"source_count": 0, "entrypoint": ""},
        "limits": {"timeout_ms": 0},
        "toolchain": {},
    }
    runner = RunnerClient(
        "http://runner.internal",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, json=payload)
        ),
    )
    repository = InMemorySubmissionRepository()

    submission = SubmissionService(
        repository=repository,
        access=ExerciseAccess(),
        runner=runner,
        knowledge=NoApprovedEvidence(),
        id_factory=lambda: "sub-http-503",
    ).submit(
        actor=Actor("student-1", Role.STUDENT),
        exercise_id="exercise-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-http-503",
    )

    assert submission.status is SubmissionStatus.execution_unavailable
    assert repository.execution_result("sub-http-503") is None
    assert repository.rule_matches("sub-http-503") == ()


def test_completion_failure_does_not_publish_partial_execution_result():
    class FailingAtomicRepository(InMemorySubmissionRepository):
        def complete_execution(self, *_args, **_kwargs):
            raise SubmissionPersistenceError("commit failed")

    repository = FailingAtomicRepository()
    service = SubmissionService(
        repository=repository,
        access=ExerciseAccess(),
        runner=CompileFailureRunner(),
        knowledge=NoApprovedEvidence(),
        id_factory=lambda: "sub-atomic",
    )

    with pytest.raises(SubmissionPersistenceError, match="commit failed"):
        service.submit(
            actor=Actor("student-1", Role.STUDENT),
            exercise_id="exercise-1",
            source_files=[{"path": "main.cj", "content": "main() {}"}],
            entrypoint="main.cj",
            is_formal=True,
            request_id="req-atomic",
        )

    assert repository.get("sub-atomic").status is SubmissionStatus.executing
    assert repository.execution_result("sub-atomic") is None
    assert repository.rule_matches("sub-atomic") == ()


def test_knowledge_failure_does_not_publish_partial_execution_result():
    class FailingKnowledge:
        def approved_evidence(self, *_args, **_kwargs):
            raise SubmissionPersistenceError("knowledge storage failed")

    repository = InMemorySubmissionRepository()
    service = SubmissionService(
        repository=repository,
        access=ExerciseAccess(),
        runner=CompileFailureRunner(),
        knowledge=FailingKnowledge(),
        id_factory=lambda: "sub-knowledge-failure",
    )

    with pytest.raises(SubmissionPersistenceError, match="knowledge storage failed"):
        service.submit(
            actor=Actor("student-1", Role.STUDENT),
            exercise_id="exercise-1",
            source_files=[{"path": "main.cj", "content": "main() {}"}],
            entrypoint="main.cj",
            is_formal=True,
            request_id="req-knowledge-failure",
        )

    assert repository.get("sub-knowledge-failure").status is SubmissionStatus.executing
    assert repository.execution_result("sub-knowledge-failure") is None
    assert repository.rule_matches("sub-knowledge-failure") == ()


@pytest.mark.parametrize(
    ("status", "phase"),
    [
        (RunnerStatus.succeeded, "run"),
        (RunnerStatus.compile_failed, "compile"),
        (RunnerStatus.run_failed, "run"),
        (RunnerStatus.timed_out, "run"),
        (RunnerStatus.resource_exhausted, "run"),
    ],
)
def test_real_runner_outcomes_are_persisted_not_marked_unavailable(status, phase):
    result = CompileFailureRunner().execute(type("Request", (), {"submission_id": "sub-real"})())

    class Runner:
        def execute(self, _request):
            return result.model_copy(update={"status": status, "phase": phase})

    repository = InMemorySubmissionRepository()
    submission = SubmissionService(
        repository=repository,
        access=ExerciseAccess(),
        runner=Runner(),
        knowledge=NoApprovedEvidence(),
        id_factory=lambda: "sub-real",
    ).submit(
        actor=Actor("student-1", Role.STUDENT),
        exercise_id="exercise-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-real",
    )

    assert submission.status is SubmissionStatus.executed
    assert repository.execution_result("sub-real").status is status


def test_sql_repository_survives_recreation_and_derives_course_from_exercise(tmp_path):
    from app.auth.models import User
    from app.courses.models import Course
    from app.persistence.repositories import create_sql_repositories
    from app.submissions.persistence import create_sql_submission_repository

    database_url = f"sqlite:///{(tmp_path / 'submissions.db').as_posix()}"
    base = create_sql_repositories(database_url, create_schema=True)
    base.users.add(User.with_password("teacher-1", "teacher", "pw", Role.TEACHER))
    base.users.add(User.with_password("student-1", "student", "pw", Role.STUDENT))
    base.courses.add(Course("course-1", "Course", "teacher-1"))
    base.courses.add_exercise(Exercise("exercise-1", "course-1", "Exercise"))
    load_approved_knowledge(
        base.knowledge,
        "course-1",
        "cj.misconception.match-non-exhaustive",
    )

    first = create_sql_submission_repository(database_url, create_schema=True)
    first.create(
        submission_id="sub-sql",
        course_id="course-1",
        exercise_id="exercise-1",
        owner_user_id="student-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-create",
    )
    first.transition(
        "sub-sql",
        SubmissionStatus.executing,
        request_id="req-run",
        reason="runner request started",
    )
    runner_result = CompileFailureRunner().execute(
        type("Request", (), {"submission_id": "sub-sql"})()
    )
    from app.diagnostics.rules import RuleMatch

    first.complete_execution(
        ExecutionResult.from_runner(
            course_id="course-1",
            result=runner_result,
            request_id="req-run",
        ),
        [
            RuleMatch(
                course_id="course-1",
                misconception_id="cj.misconception.match-non-exhaustive",
                root_concept_id="cj.pattern-match.exhaustiveness",
                related_concept_ids=(),
                diagnostic_indices=(0,),
                evidence_kind="compiler_diagnostic",
                evidence_summary="non-exhaustive patterns",
                source_references=("exp:match_non_exhaustive",),
                match_strength="strong",
            )
        ],
        request_id="req-run",
        reason="runner completed with compile_failed",
    )

    second = create_sql_submission_repository(database_url)
    restored = second.get("sub-sql")

    assert restored.course_id == "course-1"
    assert restored.status is SubmissionStatus.executed
    assert restored.source_files[0].content == "main() {}"
    assert [item.to_status for item in second.transitions("sub-sql")] == [
        SubmissionStatus.received,
        SubmissionStatus.executing,
        SubmissionStatus.executed,
    ]
    assert all(item.changed_at.tzinfo is UTC for item in second.transitions("sub-sql"))
    assert second.execution_result("sub-sql").status.value == "compile_failed"
    assert second.execution_result("sub-sql").diagnostics[0].message == "non-exhaustive patterns"
    assert second.rule_matches("sub-sql")[0].misconception_id == "cj.misconception.match-non-exhaustive"

    with pytest.raises(ValueError, match="exercise does not belong to course"):
        second.create(
            submission_id="sub-cross-course",
            course_id="course-other",
            exercise_id="exercise-1",
            owner_user_id="student-1",
            source_files=[{"path": "main.cj", "content": "main() {}"}],
            entrypoint="main.cj",
            is_formal=True,
            request_id="req-cross",
        )


def test_sql_completion_rejects_cross_course_knowledge_and_rolls_back(tmp_path):
    from app.auth.models import User
    from app.courses.models import Course
    from app.diagnostics.rules import RuleMatch
    from app.persistence.repositories import create_sql_repositories
    from app.submissions.persistence import create_sql_submission_repository

    database_url = f"sqlite:///{(tmp_path / 'cross-course.db').as_posix()}"
    base = create_sql_repositories(database_url, create_schema=True)
    base.users.add(User.with_password("teacher-1", "teacher", "pw", Role.TEACHER))
    base.users.add(User.with_password("student-1", "student", "pw", Role.STUDENT))
    base.courses.add(Course("course-a", "Course A", "teacher-1"))
    base.courses.add(Course("course-b", "Course B", "teacher-1"))
    base.courses.add_exercise(Exercise("exercise-a", "course-a", "Exercise"))
    load_approved_knowledge(base.knowledge, "course-a")
    load_approved_knowledge(base.knowledge, "course-b", "cj.misconception.course-b")

    repository = create_sql_submission_repository(database_url, create_schema=True)
    repository.create(
        submission_id="sub-cross-knowledge",
        course_id="course-a",
        exercise_id="exercise-a",
        owner_user_id="student-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-create",
    )
    repository.transition(
        "sub-cross-knowledge",
        SubmissionStatus.executing,
        request_id="req-run",
        reason="runner request started",
    )
    execution = ExecutionResult.from_runner(
        course_id="course-a",
        result=CompileFailureRunner().execute(
            type("Request", (), {"submission_id": "sub-cross-knowledge"})()
        ),
        request_id="req-run",
    )

    with pytest.raises(SubmissionPersistenceError):
        repository.complete_execution(
            execution,
            [
                RuleMatch(
                    course_id="course-a",
                    misconception_id="cj.misconception.course-b",
                    root_concept_id="cj.pattern-match.exhaustiveness",
                    related_concept_ids=(),
                    diagnostic_indices=(0,),
                    evidence_kind="compiler_diagnostic",
                    evidence_summary="non-exhaustive patterns",
                    source_references=("exp:match_non_exhaustive",),
                    match_strength="strong",
                )
            ],
            request_id="req-run",
            reason="runner completed with compile_failed",
        )

    assert repository.get("sub-cross-knowledge").status is SubmissionStatus.executing
    assert repository.execution_result("sub-cross-knowledge") is None
    assert repository.rule_matches("sub-cross-knowledge") == ()


def test_sql_completion_rejects_cross_course_related_concept(tmp_path):
    from app.auth.models import User
    from app.courses.models import Course
    from app.diagnostics.rules import RuleMatch
    from app.persistence.repositories import create_sql_repositories
    from app.submissions.persistence import create_sql_submission_repository

    database_url = f"sqlite:///{(tmp_path / 'cross-related.db').as_posix()}"
    base = create_sql_repositories(database_url, create_schema=True)
    base.users.add(User.with_password("teacher-1", "teacher", "pw", Role.TEACHER))
    base.users.add(User.with_password("student-1", "student", "pw", Role.STUDENT))
    base.courses.add(Course("course-a", "Course A", "teacher-1"))
    base.courses.add(Course("course-b", "Course B", "teacher-1"))
    base.courses.add_exercise(Exercise("exercise-a", "course-a", "Exercise"))
    load_approved_knowledge(base.knowledge, "course-a", "cj.misconception.course-a")
    load_approved_knowledge(
        base.knowledge,
        "course-b",
        concept_id="cj.pattern-match.course-b-related",
    )

    repository = create_sql_submission_repository(database_url, create_schema=True)
    repository.create(
        submission_id="sub-cross-related",
        course_id="course-a",
        exercise_id="exercise-a",
        owner_user_id="student-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-create",
    )
    repository.transition(
        "sub-cross-related",
        SubmissionStatus.executing,
        request_id="req-run",
        reason="runner request started",
    )
    execution = ExecutionResult.from_runner(
        course_id="course-a",
        result=CompileFailureRunner().execute(
            type("Request", (), {"submission_id": "sub-cross-related"})()
        ),
        request_id="req-run",
    )

    with pytest.raises(SubmissionPersistenceError):
        repository.complete_execution(
            execution,
            [
                RuleMatch(
                    course_id="course-a",
                    misconception_id="cj.misconception.course-a",
                    root_concept_id="cj.pattern-match.exhaustiveness",
                    related_concept_ids=("cj.pattern-match.course-b-related",),
                    diagnostic_indices=(0,),
                    evidence_kind="compiler_diagnostic",
                    evidence_summary="non-exhaustive patterns",
                    source_references=("exp:match_non_exhaustive",),
                    match_strength="strong",
                )
            ],
            request_id="req-run",
            reason="runner completed with compile_failed",
        )

    assert repository.get("sub-cross-related").status is SubmissionStatus.executing
    assert repository.execution_result("sub-cross-related") is None
    assert repository.rule_matches("sub-cross-related") == ()
