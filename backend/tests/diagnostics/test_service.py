from __future__ import annotations

from pathlib import Path

import anyio
import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import Authenticator, TokenCodec
from app.api.diagnostics import create_diagnostics_router
from app.api.errors import install_error_handling
from app.auth.models import Actor, Role, User, UserRepository
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.diagnostics.service import (
    DiagnosisService,
    ExecutionEvidenceUnavailable,
)
from app.model_gateway.base import ProviderFailure, ProviderTimeout
from app.model_gateway.mock import DeterministicMockProvider
from app.submissions.models import SubmissionStatus
from app.submissions.repository import InMemorySubmissionRepository

from conftest import (
    COURSE_ID,
    CONCEPT_ID,
    StudentSubmissionAccess,
    diagnosis_output,
    seed_executed_submission,
)


ROOT = Path(__file__).resolve().parents[3]


def make_service(
    submissions, knowledge, outputs, *, threshold=0.75, retries=1, access=None
):
    provider = DeterministicMockProvider(diagnoses=outputs)
    repository = InMemoryDiagnosticRepository()
    service = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=access or StudentSubmissionAccess(),
        confidence_threshold=threshold,
        max_provider_retries=retries,
        id_factory=iter(["diag-1", "diag-2", "diag-3"]).__next__,
    )
    return service, repository, provider


def test_high_confidence_diagnosis_uses_only_current_course_approved_knowledge(
    submissions, knowledge
):
    service, repository, provider = make_service(
        submissions, knowledge, [diagnosis_output()]
    )
    result = service.diagnose("sub-1", request_id="req-diag")

    assert result.diagnosis.requires_teacher_review is False
    assert submissions.get("sub-1").status is SubmissionStatus.diagnosed
    assert repository.get_for_submission("sub-1") == result.diagnosis
    request = provider.diagnosis_requests[0]
    assert {item.root_concept_id for item in request.knowledge} == {CONCEPT_ID}
    serialized = request.model_dump_json()
    for secret in ("student-1", "course-2", "Bearer", "api_key", "password"):
        assert secret not in serialized
    assert "owner_user_id" not in serialized
    assert "course_id" not in serialized
    transitions = submissions.transitions("sub-1")[-2:]
    assert [item.to_status for item in transitions] == [
        SubmissionStatus.diagnosing,
        SubmissionStatus.diagnosed,
    ]
    assert all(item.request_id == "req-diag" for item in transitions)
    assert all(item.changed_at.utcoffset().total_seconds() == 0 for item in transitions)


def test_low_confidence_enters_review_and_is_not_memory_eligible(submissions, knowledge):
    service, repository, _ = make_service(
        submissions, knowledge, [diagnosis_output(confidence=0.4)]
    )
    result = service.diagnose("sub-1", request_id="req-low")

    assert result.diagnosis.requires_teacher_review is True
    assert submissions.get("sub-1").status is SubmissionStatus.needs_review
    assert repository.review_events()[0].reason == "low_confidence"
    check = service.check_explanation(
        Actor("student-1", Role.STUDENT),
        result.diagnosis.diagnosis_id,
        "A match needs all cases.",
        request_id="req-explain",
    )
    assert check.memory_proposal_eligible is False


def test_missing_execution_result_never_calls_provider(knowledge):
    submissions = InMemorySubmissionRepository()
    submissions.create(
        submission_id="sub-missing",
        course_id=COURSE_ID,
        exercise_id="exercise-1",
        owner_user_id="student-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-create",
    )
    service, repository, provider = make_service(submissions, knowledge, [])

    with pytest.raises(ExecutionEvidenceUnavailable):
        service.diagnose("sub-missing", request_id="req-diag")

    assert provider.diagnosis_requests == []
    assert repository.review_events()[0].reason == "execution_evidence_unavailable"

    with pytest.raises(ExecutionEvidenceUnavailable):
        service.diagnose("sub-missing", request_id="req-diag")
    assert len(repository.review_events()) == 1


def test_execution_unavailable_is_not_disguised_as_compiler_error(knowledge):
    submissions = InMemorySubmissionRepository()
    submissions.create(
        submission_id="sub-unavailable",
        course_id=COURSE_ID,
        exercise_id="exercise-1",
        owner_user_id="student-1",
        source_files=[{"path": "main.cj", "content": "main() {}"}],
        entrypoint="main.cj",
        is_formal=True,
        request_id="req-create",
    )
    submissions.transition(
        "sub-unavailable", SubmissionStatus.executing, request_id="req-run", reason="run"
    )
    submissions.transition(
        "sub-unavailable",
        SubmissionStatus.execution_unavailable,
        request_id="req-run",
        reason="runner unavailable",
    )
    service, _, provider = make_service(submissions, knowledge, [])

    with pytest.raises(ExecutionEvidenceUnavailable):
        service.diagnose("sub-unavailable", request_id="req-diag")
    assert provider.diagnosis_requests == []


def test_no_approved_knowledge_safely_enters_review_without_provider(submissions):
    class NoApprovedKnowledge:
        def approved_evidence(self, *_args, **_kwargs):
            return []

    service, repository, provider = make_service(
        submissions, NoApprovedKnowledge(), [diagnosis_output()]
    )
    result = service.diagnose("sub-1", request_id="req-none")

    assert result.diagnosis is None
    assert submissions.get("sub-1").status is SubmissionStatus.needs_review
    assert repository.review_events()[0].reason == "no_approved_evidence"
    assert provider.diagnosis_requests == []


@pytest.mark.parametrize(
    "outputs, reason",
    [
        ([ProviderTimeout("slow"), ProviderTimeout("slow")], "provider_timeout"),
        ([ProviderFailure("vendor detail"), ProviderFailure("vendor detail")], "provider_failure"),
        (["not-json", "still-not-json"], "invalid_provider_response"),
        ([{"category": "conceptual"}] * 2, "invalid_provider_response"),
        ([diagnosis_output(concept_ids=["cj.fake.concept"])] * 2, "invalid_provider_response"),
    ],
)
def test_provider_and_structure_failures_safely_enter_review(
    outputs, reason, submissions, knowledge
):
    service, repository, _ = make_service(submissions, knowledge, outputs, retries=1)
    result = service.diagnose("sub-1", request_id="req-fail")

    assert result.diagnosis is None
    assert submissions.get("sub-1").status is SubmissionStatus.needs_review
    event = repository.review_events()[0]
    assert event.reason == reason
    assert "vendor detail" not in event.summary
    assert "main.cj" not in event.summary


def test_same_request_retry_is_idempotent(submissions, knowledge):
    service, repository, provider = make_service(
        submissions, knowledge, [diagnosis_output(), diagnosis_output(root_cause="conflict")]
    )
    first = service.diagnose("sub-1", request_id="req-idempotent")
    second = service.diagnose("sub-1", request_id="req-idempotent")

    assert second == first
    assert len(provider.diagnosis_requests) == 1
    assert len(repository.diagnoses()) == 1


def test_student_can_read_only_own_diagnosis_and_teacher_is_denied(submissions, knowledge):
    service, _, _ = make_service(submissions, knowledge, [diagnosis_output()])
    diagnosis = service.diagnose("sub-1", request_id="req-diag").diagnosis

    assert service.get_diagnosis(Actor("student-1", Role.STUDENT), "sub-1") == diagnosis
    from app.courses.service import ResourceNotAvailable

    for actor in (
        Actor("student-2", Role.STUDENT),
        Actor("teacher-1", Role.TEACHER),
    ):
        with pytest.raises(ResourceNotAvailable):
            service.get_diagnosis(actor, "sub-1")
    with pytest.raises(ResourceNotAvailable):
        service.get_diagnosis(Actor("student-1", Role.STUDENT), "missing")


def test_explanation_check_requires_reasoning_not_keyword_repetition(submissions, knowledge):
    provider = DeterministicMockProvider(
        diagnoses=[diagnosis_output()],
        explanations=[
            {
                "understands": True,
                "concept_ids": [CONCEPT_ID],
                "evidence_summary": "Explains why all enum cases are required.",
                "confidence": 0.92,
                "feedback": "You connected the missing branch to exhaustiveness.",
            },
            {
                "understands": False,
                "concept_ids": [],
                "evidence_summary": "Only repeats the compiler message.",
                "confidence": 0.94,
                "feedback": "Explain why a branch is required.",
            },
        ],
    )
    repository = InMemoryDiagnosticRepository()
    service = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=StudentSubmissionAccess(),
        confidence_threshold=0.75,
        id_factory=lambda: "diag-1",
    )
    diagnosis = service.diagnose("sub-1", request_id="req-diag").diagnosis
    actor = Actor("student-1", Role.STUDENT)

    correct = service.check_explanation(
        actor,
        diagnosis.diagnosis_id,
        "Because Choice has A and B, every possible value needs a branch.",
        request_id="req-correct",
    )
    repeated = service.check_explanation(
        actor,
        diagnosis.diagnosis_id,
        "non-exhaustive patterns non-exhaustive patterns",
        request_id="req-repeat",
    )

    assert correct.understands is True
    assert correct.memory_proposal_eligible is True
    assert repeated.understands is False
    assert repeated.memory_proposal_eligible is False
    assert not hasattr(repository, "memories")
    recorded = provider.explanation_requests[0].model_dump_json()
    assert "student-1" not in recorded and "course-1" not in recorded


def test_explanation_rejects_wrong_or_cross_course_concepts(submissions, knowledge):
    provider = DeterministicMockProvider(
        diagnoses=[diagnosis_output()],
        explanations=[
            {
                "understands": True,
                "concept_ids": ["cj.pattern-match.other-course"],
                "evidence_summary": "wrong course",
                "confidence": 0.9,
                "feedback": "wrong",
            }
        ],
    )
    repository = InMemoryDiagnosticRepository()
    service = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=StudentSubmissionAccess(),
        confidence_threshold=0.75,
        id_factory=lambda: "diag-1",
    )
    diagnosis = service.diagnose("sub-1", request_id="req-diag").diagnosis

    checked = service.check_explanation(
        Actor("student-1", Role.STUDENT),
        diagnosis.diagnosis_id,
        "wrong explanation",
        request_id="req-check",
    )
    assert checked.understands is False
    assert checked.memory_proposal_eligible is False


def test_revoked_course_access_and_inconsistent_diagnosis_are_hidden(
    submissions, knowledge
):
    access = StudentSubmissionAccess()
    service, repository, _ = make_service(
        submissions, knowledge, [diagnosis_output()], access=access
    )
    diagnosis = service.diagnose("sub-1", request_id="req-diag").diagnosis
    access.allowed = False
    from app.courses.service import ResourceNotAvailable

    with pytest.raises(ResourceNotAvailable):
        service.get_diagnosis(Actor("student-1", Role.STUDENT), "sub-1")
    access.allowed = True
    repository._diagnoses_by_id[diagnosis.diagnosis_id] = diagnosis.model_copy(
        update={"course_id": "course-2"}
    )
    with pytest.raises(ResourceNotAvailable):
        service.check_explanation(
            Actor("student-1", Role.STUDENT),
            diagnosis.diagnosis_id,
            "explanation",
            request_id="req-check",
        )


def test_explanation_replay_does_not_call_provider_twice(submissions, knowledge):
    provider = DeterministicMockProvider(
        diagnoses=[diagnosis_output()],
        explanations=[
            {
                "understands": True,
                "concept_ids": [CONCEPT_ID],
                "evidence_summary": "reasoning",
                "confidence": 0.9,
                "feedback": "good",
            }
        ],
    )
    repository = InMemoryDiagnosticRepository()
    service = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=StudentSubmissionAccess(),
        confidence_threshold=0.75,
        id_factory=iter(["diag-replay", "check-replay"]).__next__,
    )
    diagnosis = service.diagnose("sub-1", request_id="req-diag").diagnosis
    actor = Actor("student-1", Role.STUDENT)
    first = service.check_explanation(
        actor, diagnosis.diagnosis_id, "reasoning", request_id="req-check"
    )
    second = service.check_explanation(
        actor, diagnosis.diagnosis_id, "reasoning", request_id="req-check"
    )
    assert second == first
    assert len(provider.explanation_requests) == 1


def test_concurrent_diagnosis_deliveries_create_one_final_result(
    submissions, knowledge
):
    from concurrent.futures import ThreadPoolExecutor
    import time

    class SlowProvider(DeterministicMockProvider):
        def generate_diagnosis(self, request):
            time.sleep(0.05)
            return super().generate_diagnosis(request)

    provider = SlowProvider(
        diagnoses=[diagnosis_output(), diagnosis_output(root_cause="conflict")]
    )
    repository = InMemoryDiagnosticRepository()
    service = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=StudentSubmissionAccess(),
        confidence_threshold=0.75,
        id_factory=iter(["diag-a", "diag-b"]).__next__,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(service.diagnose, "sub-1", request_id=f"req-{index}")
            for index in (1, 2)
        ]
    results = [item.result().diagnosis for item in futures]
    assert results[0] == results[1]
    assert len(repository.diagnoses()) == 1
    assert len(provider.diagnosis_requests) == 1


def test_task6_contract_and_runtime_router_are_isolated_and_strict():
    contract = yaml.safe_load(
        (ROOT / "contracts/fragments/task-6-diagnostics.yaml").read_text(encoding="utf-8")
    )
    assert set(contract["paths"]) == {
        "/submissions/{submission_id}/diagnosis",
        "/diagnoses/{diagnosis_id}/hints/next",
        "/diagnoses/{diagnosis_id}/explanation-check",
    }
    operations = [
        operation
        for path in contract["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    ]
    assert len({item["operationId"] for item in operations}) == 3
    assert all(item["security"] == [{"bearerAuth": []}] for item in operations)
    assert all({"401", "404", "409", "422", "503"} <= set(item["responses"]) for item in operations)
    schemas = contract["components"]["schemas"]
    assert {"Role", "ErrorResponse", "CompilerDiagnostic", "RuleMatch"}.isdisjoint(schemas)
    for name in ("NextHintRequest", "ExplanationCheckRequest"):
        assert schemas[name]["additionalProperties"] is False
    for parameter in ("SubmissionId", "DiagnosisId"):
        assert contract["components"]["parameters"][parameter]["schema"]["maxLength"] == 128

    runtime_ids = {
        route.operation_id
        for route in create_diagnostics_router(None, None, None).routes
        if route.operation_id
    }
    assert runtime_ids == {item["operationId"] for item in operations}


def test_api_rejects_client_control_fields_and_hides_foreign_resources(
    submissions, knowledge
):
    service, repository, _ = make_service(submissions, knowledge, [diagnosis_output()])
    diagnosis = service.diagnose("sub-1", request_id="req-diag").diagnosis
    users = UserRepository(
        [
            User.with_password("student-1", "student-1", "password", Role.STUDENT),
            User.with_password("student-2", "student-2", "password", Role.STUDENT),
            User.with_password("teacher-1", "teacher-1", "password", Role.TEACHER),
        ]
    )
    authenticator = Authenticator(users, TokenCodec("diagnostic-api-secret-long"))
    app = FastAPI()
    install_error_handling(app)
    app.include_router(create_diagnostics_router(service, None, authenticator))
    tokens = {name: authenticator.login(name, "password")[0] for name in ("student-1", "student-2", "teacher-1")}

    async def requests():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            foreign = await client.get(
                "/submissions/sub-1/diagnosis",
                headers={"Authorization": f"Bearer {tokens['student-2']}"},
            )
            missing = await client.get(
                "/submissions/missing/diagnosis",
                headers={"Authorization": f"Bearer {tokens['student-2']}"},
            )
            teacher = await client.get(
                "/submissions/sub-1/diagnosis",
                headers={"Authorization": f"Bearer {tokens['teacher-1']}"},
            )
            controlled_explanation = await client.post(
                f"/diagnoses/{diagnosis.diagnosis_id}/explanation-check",
                headers={"Authorization": f"Bearer {tokens['student-1']}"},
                json={
                    "explanation": "text",
                    "course_id": "course-2",
                    "owner_user_id": "student-2",
                    "confidence_threshold": 0,
                    "target_hint_level": 4,
                },
            )
            controlled_hint = await client.post(
                f"/diagnoses/{diagnosis.diagnosis_id}/hints/next",
                headers={"Authorization": f"Bearer {tokens['student-1']}"},
                json={"reason": "help", "target_hint_level": 4},
            )
            return foreign, missing, teacher, controlled_explanation, controlled_hint

    foreign, missing, teacher, controlled_explanation, controlled_hint = anyio.run(requests)
    assert foreign.status_code == missing.status_code == teacher.status_code == 404
    assert foreign.json()["code"] == missing.json()["code"] == teacher.json()["code"] == "RESOURCE_NOT_AVAILABLE"
    assert controlled_explanation.status_code == controlled_hint.status_code == 422
