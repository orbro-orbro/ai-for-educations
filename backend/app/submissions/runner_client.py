from __future__ import annotations

import httpx
from pydantic import ValidationError

from app.submissions.runner_contract import RunnerRequest, RunnerResult, RunnerStatus


class RunnerUnavailable(RuntimeError):
    """Safe infrastructure failure; messages never include submitted source."""


class RunnerClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=timeout_seconds,
        )

    def execute(self, request: RunnerRequest) -> RunnerResult:
        try:
            response = self._client.post(
                "/v2/execute",
                json=request.model_dump(mode="json"),
            )
        except httpx.TimeoutException as exc:
            raise RunnerUnavailable("runner response timed out") from exc
        except httpx.RequestError as exc:
            raise RunnerUnavailable("runner connection failed") from exc
        try:
            result = RunnerResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise RunnerUnavailable("runner returned an invalid v2 response") from exc
        if result.submission_id != request.submission_id:
            raise RunnerUnavailable("runner response submission mismatch")
        if response.status_code == 503 and not (
            result.status is RunnerStatus.runner_unavailable and result.retryable
        ):
            raise RunnerUnavailable("runner returned invalid 503 response")
        if response.status_code not in {200, 503}:
            raise RunnerUnavailable(f"runner returned HTTP {response.status_code}")
        return result
