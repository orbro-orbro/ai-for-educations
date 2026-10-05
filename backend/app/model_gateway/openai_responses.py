from __future__ import annotations

import json
import logging
import re
from time import monotonic
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.model_gateway.base import (
    DiagnosisModelOutput,
    DiagnosisRequest,
    ExplanationCheckRequest,
    ExplanationModelOutput,
    HintModelOutput,
    HintRequest,
    ProviderFailure,
    ProviderTimeout,
)


_LOG = logging.getLogger(__name__)
_Output = TypeVar("_Output", bound=BaseModel)
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class OpenAIResponsesProvider:
    def __init__(self, *, api_key: str, model: str, base_url: str = "https://api.openai.com", timeout_seconds: float = 30.0, client: httpx.Client | None = None) -> None:
        if not api_key or not model:
            raise ValueError("api_key and model are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._model = model
        self._endpoint = f"{base_url.rstrip('/')}/v1/responses"
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def generate_diagnosis(self, request: DiagnosisRequest) -> DiagnosisModelOutput:
        return self._generate(request, DiagnosisModelOutput, "diagnosis")

    def generate_hint(self, request: HintRequest) -> HintModelOutput:
        return self._generate(request, HintModelOutput, "hint")

    def check_explanation(self, request: ExplanationCheckRequest) -> ExplanationModelOutput:
        return self._generate(request, ExplanationModelOutput, "explanation_check")

    def _generate(self, request: BaseModel, output_type: type[_Output], schema_name: str) -> _Output:
        started = monotonic()
        provider_request_id = "unavailable"
        payload = {
            "model": self._model,
            "store": False,
            "instructions": "Return only JSON matching the supplied schema. Use only authorized evidence and never invent compiler output or course facts.",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": json.dumps(request.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))}]}],
            "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": output_type.model_json_schema()}},
        }
        try:
            response = self._client.post(self._endpoint, headers=self._headers, json=payload)
            provider_request_id = response.headers.get("x-request-id", provider_request_id)
            if response.status_code >= 400:
                self._log_failure(f"http_{response.status_code}", provider_request_id, started)
                raise ProviderFailure("model provider request failed")
            body = response.json()
            provider_request_id = str(body.get("id") or provider_request_id)
            return output_type.model_validate_json(_output_text(body))
        except httpx.TimeoutException as exc:
            self._log_failure("timeout", provider_request_id, started)
            raise ProviderTimeout("model provider timed out") from exc
        except ProviderFailure:
            raise
        except (httpx.RequestError, ValueError, TypeError, KeyError, ValidationError) as exc:
            self._log_failure("invalid_or_transport", provider_request_id, started)
            raise ProviderFailure("model provider request failed") from exc

    @staticmethod
    def _log_failure(category: str, request_id: str, started: float) -> None:
        safe_request_id = (
            request_id if _SAFE_REQUEST_ID.fullmatch(request_id) else "unavailable"
        )
        _LOG.warning("model provider failure category=%s request_id=%s elapsed_ms=%d", category, safe_request_id, int((monotonic() - started) * 1000))


def _output_text(body: dict) -> str:
    for item in body.get("output", ()):
        if item.get("type") != "message":
            continue
        for content in item.get("content", ()):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("response did not contain output text")
