from __future__ import annotations

import pytest

from app.auth.models import Actor, Role
from app.diagnostics.hints import HintLadderService, HintLevelExhausted
from app.diagnostics.leakage import contains_answer_leakage
from app.diagnostics.repository import InMemoryDiagnosticRepository
from app.diagnostics.service import DiagnosisService
from app.model_gateway.mock import DeterministicMockProvider

from conftest import StudentSubmissionAccess, diagnosis_output, seed_executed_submission


def setup_services(submissions, knowledge, hints, *, max_regenerations=1):
    access = StudentSubmissionAccess()
    provider = DeterministicMockProvider(diagnoses=[diagnosis_output()], hints=hints)
    repository = InMemoryDiagnosticRepository()
    diagnosis_service = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=access,
        confidence_threshold=0.75,
        id_factory=lambda: "diag-1",
    )
    diagnosis = diagnosis_service.diagnose("sub-1", request_id="req-diag").diagnosis
    hints_service = HintLadderService(
        repository=repository,
        knowledge=knowledge,
        provider=provider,
        submissions=submissions,
        access=access,
        max_regenerations=max_regenerations,
        min_attempts_for_level_four=2,
    )
    return diagnosis, hints_service, repository, provider


def hint(level, content):
    return {"level": level, "content": content}


def test_hint_levels_advance_one_at_a_time_and_record_server_attempts(submissions, knowledge):
    diagnosis, service, repository, _ = setup_services(
        submissions,
        knowledge,
        [hint(1, "What values can reach this match?"), hint(2, "Review exhaustiveness."), hint(3, "List every enum case first."), hint(4, "A complete explanation.")],
    )
    actor = Actor("student-1", Role.STUDENT)

    first = service.next_hint(actor, diagnosis.diagnosis_id, reason="student requested help", request_id="req-h1")
    repository.record_attempt(diagnosis.diagnosis_id)
    second = service.next_hint(actor, diagnosis.diagnosis_id, reason="still blocked", request_id="req-h2")
    repository.record_attempt(diagnosis.diagnosis_id)
    third = service.next_hint(actor, diagnosis.diagnosis_id, reason="tried again", request_id="req-h3")
    fourth = service.next_hint(actor, diagnosis.diagnosis_id, reason="enough attempts", request_id="req-h4")

    assert [
        first.current_level,
        second.current_level,
        third.current_level,
        fourth.current_level,
    ] == [1, 2, 3, 4]
    events = repository.hint_events(diagnosis.diagnosis_id)
    assert [(e.previous_level, e.current_level) for e in events] == [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert [e.previous_attempt_count for e in events] == [0, 1, 2, 2]
    assert [e.reason for e in events] == ["student requested help", "still blocked", "tried again", "enough attempts"]
    assert all(e.request_id.startswith("req-h") for e in events)


def test_level_one_complete_program_is_regenerated_with_lower_information(submissions, knowledge):
    diagnosis, service, _, provider = setup_services(
        submissions,
        knowledge,
        [hint(1, "```cangjie\nmain() { println(\"answer\") }\n```"), hint(1, "Which enum value is not handled?")],
    )
    event = service.next_hint(
        Actor("student-1", Role.STUDENT), diagnosis.diagnosis_id, reason="help", request_id="req-hint"
    )

    assert event.content == "Which enum value is not handled?"
    assert [request.low_information for request in provider.hint_requests] == [False, True]


def test_repeated_unsafe_level_two_output_uses_fixed_safe_hint(submissions, knowledge):
    unsafe = "```cangjie\nmain() { println(\"complete answer\") }\n```"
    diagnosis, service, _, _ = setup_services(
        submissions, knowledge, [hint(1, "Observe the error."), hint(2, unsafe), hint(2, unsafe)], max_regenerations=1
    )
    actor = Actor("student-1", Role.STUDENT)
    service.next_hint(actor, diagnosis.diagnosis_id, reason="first", request_id="req-1")
    event = service.next_hint(actor, diagnosis.diagnosis_id, reason="second", request_id="req-2")

    assert event.used_safe_fallback is True
    assert "完整" not in event.content
    assert "main()" not in event.content


def test_level_three_does_not_return_complete_replacement_program(submissions, knowledge):
    unsafe = "main() {\n  println(\"complete replacement\")\n}"
    diagnosis, service, repository, _ = setup_services(
        submissions,
        knowledge,
        [hint(1, "Observe."), hint(2, "Recall the concept."), hint(3, unsafe)],
    )
    actor = Actor("student-1", Role.STUDENT)
    service.next_hint(actor, diagnosis.diagnosis_id, reason="one", request_id="req-1")
    repository.record_attempt(diagnosis.diagnosis_id)
    service.next_hint(actor, diagnosis.diagnosis_id, reason="two", request_id="req-2")
    repository.record_attempt(diagnosis.diagnosis_id)
    event = service.next_hint(actor, diagnosis.diagnosis_id, reason="three", request_id="req-3")
    assert "main()" not in event.content
    assert event.used_safe_fallback is True


def test_level_four_requires_enough_server_recorded_attempts(submissions, knowledge):
    diagnosis, service, repository, provider = setup_services(
        submissions,
        knowledge,
        [hint(1, "one"), hint(2, "two"), hint(3, "three"), hint(4, "four")],
    )
    actor = Actor("student-1", Role.STUDENT)
    service.next_hint(actor, diagnosis.diagnosis_id, reason="one", request_id="req-1")
    service.next_hint(actor, diagnosis.diagnosis_id, reason="two", request_id="req-2")
    service.next_hint(actor, diagnosis.diagnosis_id, reason="three", request_id="req-3")

    with pytest.raises(HintLevelExhausted, match="attempt"):
        service.next_hint(actor, diagnosis.diagnosis_id, reason="skip", request_id="req-4")
    assert len(provider.hint_requests) == 3

    repository.record_attempt(diagnosis.diagnosis_id)
    repository.record_attempt(diagnosis.diagnosis_id)
    assert (
        service.next_hint(
            actor, diagnosis.diagnosis_id, reason="ready", request_id="req-5"
        ).current_level
        == 4
    )


def test_no_hint_is_generated_after_level_four(submissions, knowledge):
    diagnosis, service, repository, provider = setup_services(
        submissions,
        knowledge,
        [hint(1, "one"), hint(2, "two"), hint(3, "three"), hint(4, "four")],
    )
    actor = Actor("student-1", Role.STUDENT)
    for level in (1, 2, 3):
        repository.record_attempt(diagnosis.diagnosis_id)
        service.next_hint(actor, diagnosis.diagnosis_id, reason=str(level), request_id=f"req-{level}")
    service.next_hint(actor, diagnosis.diagnosis_id, reason="four", request_id="req-4")
    calls = len(provider.hint_requests)

    with pytest.raises(HintLevelExhausted, match="maximum"):
        service.next_hint(actor, diagnosis.diagnosis_id, reason="again", request_id="req-5")
    assert len(provider.hint_requests) == calls


def test_foreign_student_cannot_request_hint(submissions, knowledge):
    diagnosis, service, _, _ = setup_services(submissions, knowledge, [hint(1, "one")])
    from app.courses.service import ResourceNotAvailable

    with pytest.raises(ResourceNotAvailable):
        service.next_hint(
            Actor("student-2", Role.STUDENT), diagnosis.diagnosis_id, reason="peek", request_id="req"
        )


@pytest.mark.parametrize(
    "content",
    [
        "func solve(): Int64 { 42 }",
        "class Answer { func solve(): Int64 { 42 } }",
        "Replace lines 1, 2, and 3 with the following final code.",
        "```cangjie\nfunc solve(): Int64 { 42 }\n```",
    ],
)
def test_short_or_unfenced_complete_replacement_code_is_leakage(content):
    assert contains_answer_leakage(content, level=1)


def test_protected_reference_answer_similarity_is_leakage():
    answer = "func solve(value: Int64): Int64 { return value + 42 }"
    output = "func solve(value: Int64): Int64 {\n return value + 42\n}"
    assert contains_answer_leakage(
        output, level=1, protected_answers=(answer,)
    )


def test_low_confidence_diagnosis_cannot_generate_model_hint(submissions, knowledge):
    access = StudentSubmissionAccess()
    provider = DeterministicMockProvider(
        diagnoses=[diagnosis_output(confidence=0.2)], hints=[hint(1, "unsafe")]
    )
    repository = InMemoryDiagnosticRepository()
    diagnosis = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=access,
        confidence_threshold=0.75,
        id_factory=iter(["diag-low", "review-low"]).__next__,
    ).diagnose("sub-1", request_id="req-low").diagnosis
    service = HintLadderService(
        repository=repository,
        knowledge=knowledge,
        provider=provider,
        submissions=submissions,
        access=access,
    )

    with pytest.raises(HintLevelExhausted, match="review"):
        service.next_hint(
            Actor("student-1", Role.STUDENT),
            diagnosis.diagnosis_id,
            reason="help",
            request_id="req-hint",
        )
    assert provider.hint_requests == []


def test_attempts_are_registered_from_authorized_task5_resubmissions(
    submissions, knowledge
):
    diagnosis, service, repository, _ = setup_services(
        submissions, knowledge, [hint(1, "one")]
    )
    seed_executed_submission(submissions, submission_id="sub-retry-1")
    actor = Actor("student-1", Role.STUDENT)

    assert service.record_submission_attempt(
        actor, diagnosis.diagnosis_id, "sub-retry-1"
    ) == 1
    assert service.record_submission_attempt(
        actor, diagnosis.diagnosis_id, "sub-retry-1"
    ) == 1
    assert repository.attempt_count(diagnosis.diagnosis_id) == 1


def test_concurrent_hint_requests_reserve_distinct_levels(submissions, knowledge):
    from concurrent.futures import ThreadPoolExecutor
    import time

    class SlowProvider(DeterministicMockProvider):
        def generate_hint(self, request):
            time.sleep(0.05)
            return super().generate_hint(request)

    access = StudentSubmissionAccess()
    provider = SlowProvider(
        diagnoses=[diagnosis_output()], hints=[hint(1, "one"), hint(2, "two")]
    )
    repository = InMemoryDiagnosticRepository()
    diagnosis = DiagnosisService(
        submissions=submissions,
        knowledge=knowledge,
        repository=repository,
        provider=provider,
        access=access,
        confidence_threshold=0.75,
        id_factory=lambda: "diag-concurrent",
    ).diagnose("sub-1", request_id="req-diag").diagnosis
    service = HintLadderService(
        repository=repository,
        knowledge=knowledge,
        provider=provider,
        submissions=submissions,
        access=access,
    )
    actor = Actor("student-1", Role.STUDENT)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                service.next_hint,
                actor,
                diagnosis.diagnosis_id,
                reason="help",
                request_id=f"req-{index}",
            )
            for index in (1, 2)
        ]
    assert sorted(item.result().current_level for item in futures) == [1, 2]
