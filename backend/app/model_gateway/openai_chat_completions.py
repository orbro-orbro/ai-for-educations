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


class OpenAIChatCompletionsProvider:
    """OpenAI-compatible Chat Completions in JSON mode (DeepSeek, Qwen, ...).

    JSON mode guarantees valid JSON only, so the schema is given in the prompt
    and every response is strictly validated; failures are never masked.
    """

    def __init__(self, *, api_key: str, model: str, base_url: str, timeout_seconds: float = 30.0, client: httpx.Client | None = None) -> None:
        if not api_key or not model or not base_url:
            raise ValueError("api_key, model and base_url are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._model = model
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def generate_diagnosis(self, request: DiagnosisRequest) -> DiagnosisModelOutput:
        return self._generate(request, DiagnosisModelOutput)

    def generate_hint(self, request: HintRequest) -> HintModelOutput:
        return self._generate(request, HintModelOutput)

    def check_explanation(self, request: ExplanationCheckRequest) -> ExplanationModelOutput:
        return self._generate(request, ExplanationModelOutput)

    def _generate(self, request: BaseModel, output_type: type[_Output]) -> _Output:
        started = monotonic()
        provider_request_id = "unavailable"
        schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
        payload = {
            "model": self._model,
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only one JSON object that matches this JSON schema exactly, with no extra keys: "
                        + schema
                        + " Use only authorized evidence in the user JSON and never invent compiler output or course facts."
                    ),
                },
                {"role": "user", "content": json.dumps(request.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))},
            ],
        }
        try:
            response = self._client.post(self._endpoint, headers=self._headers, json=payload)
            provider_request_id = response.headers.get("x-request-id", provider_request_id)
            if response.status_code >= 400:
                self._log_failure(f"http_{response.status_code}", provider_request_id, started)
                raise ProviderFailure("model provider request failed")
            body = response.json()
            provider_request_id = str(body.get("id") or provider_request_id)
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("response did not contain text")
            return output_type.model_validate_json(content)
        except httpx.TimeoutException as exc:
            self._log_failure("timeout", provider_request_id, started)
            raise ProviderTimeout("model provider timed out") from exc
        except ProviderFailure:
            raise
        except (httpx.RequestError, ValueError, TypeError, KeyError, IndexError, AttributeError, ValidationError) as exc:
            self._log_failure("invalid_or_transport", provider_request_id, started)
            raise ProviderFailure("model provider request failed") from exc

    def _log_failure(self, category: str, request_id: str, started: float) -> None:
        key = self._headers["Authorization"].removeprefix("Bearer ")
        safe_request_id = request_id if _SAFE_REQUEST_ID.fullmatch(request_id) and key not in request_id else "unavailable"
        _LOG.warning("model provider failure category=%s request_id=%s elapsed_ms=%d", category, safe_request_id, int((monotonic() - started) * 1000))
