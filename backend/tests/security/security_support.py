"""Synthetic fixtures. Only Runner and provider are doubles; permissions are real.

The deterministic Runner below does not compile or execute source. Its result is
test evidence, never a claim that a compiler or isolated container was exercised.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime

import anyio
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec
from app.audit.service import AuditService
from app.auth.models import Actor, Role, User, UserRepository
from app.auth.policy import AuthorizationPolicy
from app.courses.models import Course, CourseRepository, Enrollment, EnrollmentRepository, Exercise
from app.courses.service import CourseService
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.diagnostics.schema import Diagnosis, DiagnosisCategory, DiagnosisLocation, CompilerDiagnosticEvidence, ExplanationCheck
from app.diagnostics.service import DiagnosisService
from app.knowledge.models import Concept, MisconceptionPattern
from app.knowledge.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.memories.repository import InMemoryMemoryRepository
from app.memories.retrieval import InMemoryRetrievalIndex
from app.memories.service import DiagnosticMemorySource
from app.model_gateway.mock import DeterministicMockProvider
from app.submissions.models import ExecutionResult, SubmissionStatus
from app.submissions.repository import InMemorySubmissionRepository
from app.submissions.runner_contract import RunnerRequest, RunnerResult
from app.submissions.service import CourseSubmissionAccess, SubmissionService

COURSE_A, COURSE_B = "course-a", "course-b"
STUDENT_A, STUDENT_B = Actor("student-a", Role.STUDENT), Actor("student-b", Role.STUDENT)
TEACHER, OTHER_TEACHER = Actor("teacher-a", Role.TEACHER), Actor("teacher-b", Role.TEACHER)
CONCEPT = "cj.pattern-match.exhaustiveness"
MISCONCEPTION = "cj.misconception.match-non-exhaustive"
NOW = datetime(2026, 10, 7, 1, tzinfo=UTC)
PRIVATE_B = "PRIVATE_B_MEMORY_SENTINEL_4c98"
PRIVATE_OTHER_COURSE = "PRIVATE_OTHER_COURSE_SENTINEL_12fa"
PROTECTED_ANSWER = "REFERENCE_ANSWER_SENTINEL_55dd"
SOURCE = "enum Choice { A | B }\nmain() {\n  match (Choice.A) { case A => 1 }\n}"


def model_output(**overrides):
    result = {
        "category": "conceptual", "locations": [{"file": "main.cj", "start_line": 3, "end_line": 3}],
        "concept_ids": [CONCEPT], "root_cause": "Synthetic diagnosis: a possible branch is omitted.",
        "evidence": [{"kind": "compiler_diagnostic", "summary": "untrusted model summary", "diagnostic_index": 0},
                     {"kind": "rule_match", "summary": "untrusted model summary", "misconception_id": MISCONCEPTION}],
        "confidence": 0.92, "recommended_hint_level": 1,
    }
    result.update(overrides)
    return result


def knowledge_for(repo, course, *, explanation="A match must cover all possible cases.", concept=CONCEPT):
    source = {"kind": "course_material", "references": [f"fixture:{course}:match"],
              "toolchain_version": "synthetic fixture for cjc 1.2.0", "verification_status": "unverified"}
    repo.load_course(course, [Concept.model_validate({"id": concept, "topic": "enum_match", "title": "Synthetic exhaustiveness",
        "summary": explanation, "review_status": "approved", "source": source})], [], [MisconceptionPattern.model_validate({
        "id": MISCONCEPTION, "topic": "enum_match", "title": "Synthetic match evidence", "root_concept_id": concept,
        "trigger_evidence": [{"kind": "compiler_diagnostic", "pattern": "non-exhaustive patterns", "strength": "strong"}],
        "explanation": explanation, "hint_ladder": [{"level": i, "outline": f"Reflect on case coverage, step {i}."} for i in range(1, 5)],
        "review_status": "approved", "source": source,
        "verification": {"method": "knowledge_base_summary", "toolchain_version": "1.2.0", "note": "Synthetic test fixture; no real teacher annotation."},
    })])


class SyntheticRunner:
    def __init__(self, *, stdout="", stderr="non-exhaustive patterns"):
        self.stdout, self.stderr = stdout, stderr
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return RunnerResult.model_validate({
            "submission_id": request.submission_id, "status": "compile_failed", "phase": "compile", "retryable": False,
            "exit_code": 1, "signal": None, "stdout": self.stdout, "stderr": self.stderr,
            "diagnostics": [{"severity": "error", "message": "non-exhaustive patterns", "code": None, "file": "main.cj",
                             "start_line": 3, "start_column": 1, "end_line": 3, "end_column": 10}],
            "command_summary": {"source_count": 1, "entrypoint": "main.cj"}, "limits": {"timeout_ms": 5000},
            "toolchain": {"cjc": "1.2.0", "cjpm": "not-executed"},
        })


@dataclass
class Harness:
    app: object
    users: UserRepository
    courses: CourseRepository
    enrollments: EnrollmentRepository
    provider: DeterministicMockProvider
    runner: SyntheticRunner
    memories: dict
    proposals: dict
    tokens: dict = field(repr=False)

    @property
    def state(self): return self.app.state

    def request(self, method, path, *, actor=STUDENT_A, body=None, request_id="security-request", key="security-key"):
        async def perform():
            headers = {"X-Request-ID": request_id, "Idempotency-Key": key}
            if actor is not None: headers["Authorization"] = f"Bearer {self.tokens[actor.user_id]}"
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://local-test") as client:
                return await client.request(method, path, headers=headers, json=body)
        return anyio.run(perform)

    def revoke_enrollment(self, actor, course):
        # The in-memory repository has no public revoke operation. Alter the
        # authoritative fixture store, never the policy or request result.
        self.enrollments._enrollments.pop((course, actor.user_id))


def build_harness(*, provider=None, runner=None, knowledge_explanation="A match must cover all possible cases.", empty_knowledge=False, pending_other_course=False):
    users = UserRepository([User.with_password(a.user_id, a.user_id, "synthetic-password", a.role)
                            for a in (STUDENT_A, STUDENT_B, TEACHER, OTHER_TEACHER)])
    courses = CourseRepository([Course(COURSE_A, "仓颉语言设计", TEACHER.user_id), Course(COURSE_B, "Synthetic isolation course", OTHER_TEACHER.user_id)],
                               [Exercise("exercise-a", COURSE_A, "Synthetic match", True), Exercise("exercise-b", COURSE_B, "Synthetic match", True)])
    enrollments = EnrollmentRepository([Enrollment(c, a.user_id, a.role) for c, a in
                                       [(COURSE_A, STUDENT_A), (COURSE_A, STUDENT_B), (COURSE_B, STUDENT_A)]])
    course_service = CourseService(users, courses, enrollments, AuthorizationPolicy())
    authenticator = Authenticator(users, TokenCodec("synthetic-task10-secret-at-least-16-bytes"))
    submissions, diagnostics, knowledge = InMemorySubmissionRepository(), InMemoryDiagnosticRepository(), InMemoryKnowledgeRepository()
    if empty_knowledge: knowledge.load_course(COURSE_A, [], [], [])
    else: knowledge_for(knowledge, COURSE_A, explanation=knowledge_explanation)
    knowledge_for(knowledge, COURSE_B, explanation=PRIVATE_OTHER_COURSE)
    courses.set_protected_answer(COURSE_A, "exercise-a", PROTECTED_ANSWER)
    provider = provider or DeterministicMockProvider()
    runner = runner or SyntheticRunner()
    access = CourseSubmissionAccess(course_service, is_published=lambda e: e.is_published)
    diagnosis_service = DiagnosisService(submissions=submissions, knowledge=knowledge, repository=diagnostics, provider=provider, access=access, confidence_threshold=0.75)
    submission_service = SubmissionService(repository=submissions, access=access, runner=runner, knowledge=knowledge,
        execution_completed=lambda sid, rid: diagnosis_service.diagnose(sid, request_id=rid))
    repository, index, audit = InMemoryMemoryRepository(), InMemoryRetrievalIndex(), AuditService()
    memory_source = DiagnosticMemorySource(diagnostics=diagnostics, submissions=submissions, confidence_threshold=0.75)
    app = create_app(authenticator=authenticator, course_service=course_service, knowledge_repository=knowledge,
        submission_repository=submissions, diagnostic_repository=diagnostics, protected_answer_lookup=courses,
        model_provider=provider, diagnosis_service=diagnosis_service, submission_service=submission_service,
        memory_repository=repository, memory_source=memory_source, memory_index=index, memory_audit=audit)
    harness = Harness(app, users, courses, enrollments, provider, runner, {}, {},
        {a.user_id: authenticator.login(a.user_id, "synthetic-password")[0] for a in (STUDENT_A, STUDENT_B, TEACHER, OTHER_TEACHER)})
    for label, actor, course, content, accept in [
        ("a", STUDENT_A, COURSE_A, "PRIVATE_A_MEMORY_SENTINEL_c387", True),
        ("b", STUDENT_B, COURSE_A, PRIVATE_B, True),
        ("a-other", STUDENT_A, COURSE_B, PRIVATE_OTHER_COURSE, not pending_other_course),
        ("pending", STUDENT_A, COURSE_A, "PRIVATE_PENDING_SENTINEL", False),
    ]:
        sid, did, eid = f"submission-{label}", f"diagnosis-{label}", f"check-{label}"
        submissions.create(submission_id=sid, course_id=course, exercise_id="exercise-a" if course == COURSE_A else "exercise-b",
            owner_user_id=actor.user_id, source_files=[{"path": "main.cj", "content": SOURCE}], entrypoint="main.cj", is_formal=False, request_id=f"seed-{label}")
        submissions.transition(sid, SubmissionStatus.executing, request_id="seed", reason="synthetic evidence")
        result = runner.execute(RunnerRequest(submission_id=sid, source_files=[{"path": "main.cj", "content": SOURCE}], entrypoint="main.cj", timeout_ms=5000))
        from app.diagnostics.rules import match_rules
        execution = ExecutionResult.from_runner(course_id=course, result=result, request_id="seed")
        submissions.complete_execution(execution, match_rules(course_id=course, diagnostics=execution.diagnostics, knowledge=knowledge), request_id="seed", reason="synthetic evidence")
        submissions.transition(sid, SubmissionStatus.diagnosing, request_id="seed", reason="synthetic evidence")
        submissions.transition(sid, SubmissionStatus.diagnosed, request_id="seed", reason="synthetic evidence")
        diagnostics.save_diagnosis(Diagnosis(diagnosis_id=did, submission_id=sid, course_id=course, owner_user_id=actor.user_id,
            category=DiagnosisCategory.conceptual, locations=(DiagnosisLocation(file="main.cj", start_line=3, end_line=3),),
            concept_ids=(CONCEPT,), root_cause=content,
            evidence=(CompilerDiagnosticEvidence(kind="compiler_diagnostic", summary="non-exhaustive patterns", diagnostic_index=0),),
            confidence=0.92, recommended_hint_level=1, requires_teacher_review=False, created_at=NOW, request_id="seed"))
        diagnostics.add_explanation(ExplanationCheck(explanation_check_id=eid, diagnosis_id=did, understands=True,
            concept_ids=(CONCEPT,), evidence_summary="synthetic fixture", confidence=0.91, feedback="synthetic fixture",
            memory_proposal_eligible=True, created_at=NOW, request_id="seed"))
        proposal = app.state.memory_service.create_proposal(actor, eid, request_id="seed")
        harness.proposals[label] = proposal
        if accept: harness.memories[label] = app.state.memory_service.accept_proposal(actor, proposal.proposal_id, request_id="seed", idempotency_key=f"seed-{label}")
    runner.requests.clear()
    return harness


def public_denial(response):
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "RESOURCE_NOT_AVAILABLE"
    assert body["message"] == "Resource is not available."
    assert isinstance(body["request_id"], str) and body["request_id"]
    return {k: v for k, v in body.items() if k != "request_id"}
