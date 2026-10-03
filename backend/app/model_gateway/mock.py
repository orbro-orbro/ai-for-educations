from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from app.model_gateway.base import (
    DiagnosisModelOutput,
    DiagnosisRequest,
    ExplanationCheckRequest,
    ExplanationModelOutput,
    HintModelOutput,
    HintRequest,
    ProviderFailure,
)


class DeterministicMockProvider:
    """Fixture-driven provider used by tests; it performs no I/O or logging."""

    def __init__(
        self,
        *,
        diagnoses: Iterable[object] = (),
        hints: Iterable[object] = (),
        explanations: Iterable[object] = (),
    ) -> None:
        self._diagnoses = deque(diagnoses)
        self._hints = deque(hints)
        self._explanations = deque(explanations)
        self.diagnosis_requests: list[DiagnosisRequest] = []
        self.hint_requests: list[HintRequest] = []
        self.explanation_requests: list[ExplanationCheckRequest] = []

    @staticmethod
    def _next(queue: deque[object], model):
        if not queue:
            raise ProviderFailure("mock fixture exhausted")
        value = queue.popleft()
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, model):
            return value
        if isinstance(value, dict):
            return model.model_validate(value)
        return value

    def generate_diagnosis(self, request: DiagnosisRequest) -> DiagnosisModelOutput:
        self.diagnosis_requests.append(request)
        return self._next(self._diagnoses, DiagnosisModelOutput)

    def generate_hint(self, request: HintRequest) -> HintModelOutput:
        self.hint_requests.append(request)
        return self._next(self._hints, HintModelOutput)

    def check_explanation(
        self, request: ExplanationCheckRequest
    ) -> ExplanationModelOutput:
        self.explanation_requests.append(request)
        return self._next(self._explanations, ExplanationModelOutput)
