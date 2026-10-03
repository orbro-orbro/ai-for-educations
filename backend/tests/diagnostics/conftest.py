from __future__ import annotations

import pytest

from app.auth.models import Actor, Role
from app.courses.service import ResourceNotAvailable
from app.diagnostics.rules import RuleMatch
from app.knowledge.models import Concept, MisconceptionPattern
from app.knowledge.repository import InMemoryKnowledgeRepository
from app.submissions.models import ExecutionResult, SubmissionStatus
from app.submissions.repository import InMemorySubmissionRepository
from app.submissions.runner_contract import RunnerResult


COURSE_ID = "course-1"
OTHER_COURSE_ID = "course-2"
CONCEPT_ID = "cj.pattern-match.exhaustiveness"
MISCONCEPTION_ID = "cj.misconception.match-non-exhaustive"


class StudentSubmissionAccess:
    def __init__(self):
        self.allowed = True

    def require_read(self, actor, submission):
        if (
            not self.allowed
            or actor.role is not Role.STUDENT
            or actor.user_id != submission.owner_user_id
        ):
            raise ResourceNotAvailable()


def load_approved_knowledge(repository, course_id=COURSE_ID, *, concept_id=CONCEPT_ID):
    source = {
        "kind": "toolchain_experiment",
        "references": [f"exp:{course_id}:match_non_exhaustive"],
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
    misconception = MisconceptionPattern.model_validate(
        {
            "id": MISCONCEPTION_ID if course_id == COURSE_ID else "cj.misconception.other-course",
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
            "explanation": "A match must cover every possible value.",
            "hint_ladder": [
                {"level": level, "outline": f"approved outline {level}"}
                for level in (1, 2, 3, 4)
            ],
            "review_status": "approved",
            "source": source,
            "verification": {
                "method": "cjc_minimal_repro",
                "toolchain_version": "cjc 1.2.0 (cjnative)",
                "expected_outcome": "compile_error",
                "snippet": "main() {}",
                "note": "existing Task 4 fixture",
            },
        }
    )
    repository.load_course(course_id, [concept], [], [misconception])


def diagnosis_output(**overrides):
    data = {
        "category": "conceptual",
        "locations": [{"file": "main.cj", "start_line": 2, "end_line": 2}],
        "concept_ids": [CONCEPT_ID],
        "root_cause": "The match omits a possible value.",
        "evidence": [
            {
                "kind": "compiler_diagnostic",
                "summary": "compiler reported a non-exhaustive match",
                "diagnostic_index": 0,
            },
            {
                "kind": "approved_knowledge",
                "summary": "approved course evidence explains exhaustiveness",
                "misconception_id": MISCONCEPTION_ID,
                "source_reference": f"exp:{COURSE_ID}:match_non_exhaustive",
            },
        ],
        "confidence": 0.9,
        "recommended_hint_level": 1,
    }
    data.update(overrides)
    return data


def seed_executed_submission(repository, *, submission_id="sub-1", owner="student-1"):
    repository.create(
        submission_id=submission_id,
        course_id=COURSE_ID,
        exercise_id="exercise-1",
        owner_user_id=owner,
        source_files=[
            {
                "path": "main.cj",
                "content": "enum Choice { A | B }\nmain() {\n  match (Choice.A) { case A => 1 }\n}",
            }
        ],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-create",
    )
    repository.transition(
        submission_id,
        SubmissionStatus.executing,
        request_id="req-run",
        reason="runner request started",
    )
    result = RunnerResult.model_validate(
        {
            "submission_id": submission_id,
            "status": "compile_failed",
            "phase": "compile",
            "retryable": False,
            "exit_code": 1,
            "signal": None,
            "stdout": "",
            "stderr": "main.cj:2:1: non-exhaustive patterns",
            "diagnostics": [
                {
                    "severity": "error",
                    "message": "non-exhaustive patterns",
                    "code": None,
                    "file": "main.cj",
                    "start_line": 2,
                    "start_column": 1,
                    "end_line": 2,
                    "end_column": 10,
                }
            ],
            "command_summary": {"source_count": 1, "entrypoint": "main.cj"},
            "limits": {"timeout_ms": 5000},
            "toolchain": {},
        }
    )
    execution = ExecutionResult.from_runner(
        course_id=COURSE_ID, result=result, request_id="req-run"
    )
    match = RuleMatch(
        course_id=COURSE_ID,
        misconception_id=MISCONCEPTION_ID,
        root_concept_id=CONCEPT_ID,
        related_concept_ids=(),
        diagnostic_indices=(0,),
        evidence_kind="compiler_diagnostic",
        evidence_summary="non-exhaustive patterns",
        source_references=(f"exp:{COURSE_ID}:match_non_exhaustive",),
        match_strength="strong",
    )
    repository.complete_execution(
        execution,
        [match],
        request_id="req-run",
        reason="runner completed with compile_failed",
    )


@pytest.fixture
def knowledge():
    repository = InMemoryKnowledgeRepository()
    load_approved_knowledge(repository)
    load_approved_knowledge(
        repository,
        OTHER_COURSE_ID,
        concept_id="cj.pattern-match.other-course",
    )
    return repository


@pytest.fixture
def submissions():
    repository = InMemorySubmissionRepository()
    seed_executed_submission(repository)
    return repository


@pytest.fixture
def student():
    return Actor("student-1", Role.STUDENT)
